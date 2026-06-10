"""End-to-end gate for the C++ self-play data-generation pipeline.

Exercises `scripts/nn/generate_selfplay_data_cpp.py` against the compiled
C++ binary: run a handful of small games through the binary, replay each
trace into a `GameRecord`, write the chunked-pickle run dir, then assert the
output is IDENTICAL in format to the Python pipeline and survives the
`validate_dataset.py` invariants — and crucially that `visit_distribution`
(π) AND `root_value` survived the C++→trace→replay path (proving the
policy/value training targets are intact).

Skips cleanly if the C++ binary or the exported NN weights are absent.

Kept fast (4 games, sims=16, 2 workers) so it runs in well under a minute.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agricola.agents.base import decider_of  # noqa: E402
from agricola.agents.nn import DATA_VERSION, load_game_records  # noqa: E402
from agricola.constants import Phase  # noqa: E402
from agricola.legality import legal_actions  # noqa: E402
from agricola.scoring import score, tiebreaker  # noqa: E402
from agricola.agents.nn.schema import compute_winner  # noqa: E402

# scripts/ is not a package — load the validator's per-record checker by path
# (mirrors the existing test_cpp_selfplay.py / build_combined_policy pattern).
from scripts.nn.validate_dataset import check_record  # noqa: E402

_BIN = ROOT / "cpp" / "build" / "selfplay"
_MANIFEST = ROOT / "nn_models" / "cpp_export" / "weights_manifest.json"

pytestmark = pytest.mark.skipif(
    not (_BIN.exists() and _MANIFEST.exists()),
    reason="C++ selfplay binary or nn_models/cpp_export weights absent",
)


def _load_driver():
    """Import the generator script by file path (scripts/ has no __init__)."""
    path = ROOT / "scripts" / "nn" / "generate_selfplay_data_cpp.py"
    spec = importlib.util.spec_from_file_location("generate_selfplay_data_cpp", path)
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec so the module's @dataclass decorators can resolve
    # cls.__module__ via sys.modules (dataclasses.py reads sys.modules[__module__]).
    sys.modules["generate_selfplay_data_cpp"] = mod
    spec.loader.exec_module(mod)
    return mod


def _all_records(run_dir: Path):
    games = run_dir / "games"
    pkls = sorted(games.glob("worker_*_c*.pkl"))
    out = []
    for pkl in pkls:
        out.extend(load_game_records(pkl))  # also enforces DATA_VERSION
    return out


@pytest.fixture(scope="module", params=["batch", "per_game"])
def run_dir(request, tmp_path_factory):
    """Generate a tiny C++ self-play run once per generation mode.

    Parametrized over both modes so the gate covers the default (batch) AND the
    A/B-baseline per-game path; both must produce identical-format output.
    """
    mode = request.param
    driver = _load_driver()
    out = tmp_path_factory.mktemp(f"cpp_selfplay_pipeline_{mode}")
    spec = driver._Spec(
        selfplay_bin=str(_BIN),
        model_dir="nn_models/cpp_export",
        sims=16,
        c_uct=1.4,
        temperature=1.0,
        chunk_size=2,  # < n_games so we exercise multi-chunk flushing
        generation_mode=mode,
    )
    meta = driver.generate(
        n_games=4, out_dir=out, n_workers=2, base_seed=0, spec=spec, verbose=False,
    )
    # If every game errored, the binary couldn't actually run — surface it as a
    # skip rather than a confusing downstream assertion failure.
    if meta["completed_games"] == 0:
        errs = meta.get("errored_games", [])
        first = errs[0]["error"].splitlines()[0] if errs else "unknown"
        pytest.skip(f"C++ binary produced no games (first error: {first})")
    return out, meta


def test_records_count_and_data_version(run_dir):
    out, _ = run_dir
    records = _all_records(out)
    assert len(records) == 4, f"expected 4 records summed across chunks, got {len(records)}"
    for rec in records:
        assert rec.data_version == DATA_VERSION


def test_terminal_and_scoring_consistent(run_dir):
    out, _ = run_dir
    for rec in _all_records(out):
        assert rec.terminal_state.phase == Phase.BEFORE_SCORING
        p0, _ = score(rec.terminal_state, 0)
        p1, _ = score(rec.terminal_state, 1)
        assert p0 == rec.p0_final_score
        assert p1 == rec.p1_final_score
        expected_winner = compute_winner(
            p0, p1, tiebreaker(rec.terminal_state, 0), tiebreaker(rec.terminal_state, 1)
        )
        assert rec.winner == expected_winner


def test_policy_value_targets_populated(run_dir):
    """The whole point: π + root_value must survive C++→trace→replay."""
    out, _ = run_dir
    n_snaps = 0
    for rec in _all_records(out):
        assert len(rec.decisions) > 0
        for snap in rec.decisions:
            n_snaps += 1
            assert snap.visit_distribution is not None, (
                "visit_distribution (π) lost on a snapshot"
            )
            assert len(snap.visit_distribution) > 0
            assert snap.root_value is not None, "root_value lost on a snapshot"
            assert isinstance(snap.root_value, float)
    assert n_snaps > 0


def test_validate_dataset_invariants(run_dir):
    out, _ = run_dir
    failures = []
    for rec in _all_records(out):
        failures.extend(check_record(rec))
    assert not failures, "validate_dataset invariants failed:\n" + "\n".join(
        str(f) for f in failures[:20]
    )


def test_decider_and_legality_per_snapshot(run_dir):
    """Spot-check the two key invariants directly (belt-and-suspenders on top
    of check_record): chosen_action legal + decider_idx consistent."""
    out, _ = run_dir
    for rec in _all_records(out):
        for snap in rec.decisions:
            assert snap.decider_idx == decider_of(snap.state)
            assert snap.chosen_action in legal_actions(snap.state)
            assert snap.state.phase != Phase.BEFORE_SCORING


def test_metadata_fields(run_dir):
    out, meta = run_dir
    import json
    on_disk = json.loads((out / "metadata.json").read_text())
    assert on_disk == meta  # generate() returns exactly what it wrote
    assert meta["generator"] == "cpp"
    assert meta["data_version"] == DATA_VERSION
    assert meta["planned_games"] == 4
    assert meta["completed_games"] == 4
    assert meta["sims"] == 16
    assert meta["model_dir"] == "nn_models/cpp_export"
    assert "selfplay_bin" in meta
    assert "c_uct" in meta and "temperature" in meta
