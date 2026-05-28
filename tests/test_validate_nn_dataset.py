"""Tests for the validation script (`scripts/validate_nn_dataset.py`).

Covers two things:
1. Validation of a clean dataset passes (no failures).
2. Each kind of corruption produces the appropriate check failure.

Corrupted datasets are constructed in-test by writing modified
GameRecords to pickle files. The tests verify the validation script's
*detection* behavior, not its real-world performance.
"""

from __future__ import annotations

import pickle
import sys
from dataclasses import replace
from pathlib import Path

import pytest

# Make scripts/ importable for the test.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from agricola.actions import Action, PlaceWorker
from agricola.agents.base import RandomAgent
from agricola.agents.nn import DecisionSnapshot, GameRecord, play_recording_game
from agricola.legality import legal_actions
from agricola.setup import setup
from validate_nn_dataset import check_record, validate_run


def _record_one_random_game(seed: int = 42) -> GameRecord:
    """Produce a single clean GameRecord via the recording driver."""
    initial = setup(seed=seed)
    return play_recording_game(
        initial,
        RandomAgent(seed=seed),
        RandomAgent(seed=seed + 1),
        game_idx=0,
        seed=seed,
        p0_config_path="random",
        p1_config_path="random",
        p0_temperature=0.0,
        p1_temperature=0.0,
        legal_actions_fn=legal_actions,
    )


def _make_run_dir(tmp_path: Path, records: list[GameRecord]) -> Path:
    """Write `records` to a worker pickle under tmp_path/games/ so
    `validate_run` can discover it."""
    run_dir = tmp_path / "fixture_run"
    games_dir = run_dir / "games"
    games_dir.mkdir(parents=True)
    with (games_dir / "worker_00.pkl").open("wb") as f:
        pickle.dump(records, f)
    return run_dir


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_clean_record_has_no_failures():
    """A freshly recorded game record passes all check_record invariants."""
    rec = _record_one_random_game()
    failures = check_record(rec)
    assert failures == [], f"Expected no failures, got: {[str(f) for f in failures]}"


def test_validate_run_on_clean_run_passes(tmp_path: Path):
    """End-to-end: full validate_run() on a clean run dir returns no failures."""
    rec = _record_one_random_game()
    run_dir = _make_run_dir(tmp_path, [rec])
    failures = validate_run(run_dir, verbose=False)
    assert failures == []


# ---------------------------------------------------------------------------
# Corruption detection
# ---------------------------------------------------------------------------


def test_detects_scoring_drift_p0():
    """If the stored p0_final_score doesn't match score(terminal_state, 0),
    the scoring_drift_p0 check fires. Simulates 'engine changed
    after recording'."""
    rec = _record_one_random_game()
    bad = replace(rec, p0_final_score=rec.p0_final_score + 999)
    failures = check_record(bad)
    assert any(f.check == "scoring_drift_p0" for f in failures), \
        f"Expected scoring_drift_p0 failure; got: {[f.check for f in failures]}"


def test_detects_scoring_drift_p1():
    """Same but for P1."""
    rec = _record_one_random_game()
    bad = replace(rec, p1_final_score=rec.p1_final_score - 50)
    failures = check_record(bad)
    assert any(f.check == "scoring_drift_p1" for f in failures)


def test_detects_empty_decisions():
    """An empty `decisions` tuple should be flagged."""
    rec = _record_one_random_game()
    bad = replace(rec, decisions=())
    failures = check_record(bad)
    assert any(f.check == "non_empty_decisions" for f in failures)


def test_detects_wrong_decider_idx():
    """A snapshot whose stored decider_idx disagrees with
    decider_of(state) should be flagged."""
    rec = _record_one_random_game()
    # Flip the first snapshot's decider_idx to the wrong value.
    first = rec.decisions[0]
    bad_snap = replace(first, decider_idx=1 - first.decider_idx)
    bad = replace(rec, decisions=(bad_snap,) + rec.decisions[1:])
    failures = check_record(bad)
    assert any(f.check == "decider_idx_mismatch" for f in failures)


def test_detects_illegal_chosen_action():
    """A snapshot whose chosen_action isn't in legal_actions(state)
    should be flagged. We swap in an arbitrary other action."""
    rec = _record_one_random_game()
    # Pick an arbitrary action that's UNLIKELY to be in the first
    # snapshot's legal actions. PlaceWorker("urgent_wish_for_children")
    # is only available from Stage 5 onward; at round 1 it's illegal.
    first = rec.decisions[0]
    impossible = PlaceWorker(space="urgent_wish_for_children")
    actions_at_first = legal_actions(first.state)
    # Verify our assumption holds — if this changes, swap to a different
    # impossible action.
    assert impossible not in actions_at_first, \
        "Test assumption broken: urgent_wish_for_children IS legal at round 1"

    bad_snap = replace(first, chosen_action=impossible)
    bad = replace(rec, decisions=(bad_snap,) + rec.decisions[1:])
    failures = check_record(bad)
    assert any(f.check == "chosen_action_illegal" for f in failures), \
        f"Expected chosen_action_illegal; got: {[f.check for f in failures]}"


def test_validate_run_aggregates_failures(tmp_path: Path):
    """End-to-end: a run dir with one corrupted record produces failures
    from validate_run()."""
    rec = _record_one_random_game()
    bad = replace(rec, p0_final_score=rec.p0_final_score + 999)
    run_dir = _make_run_dir(tmp_path, [bad])
    failures = validate_run(run_dir, verbose=False)
    assert len(failures) > 0
    assert any(f.check == "scoring_drift_p0" for f in failures)


def test_validate_run_missing_games_dir_raises(tmp_path: Path):
    """Pointing validate_run at a directory without games/ raises
    FileNotFoundError."""
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        validate_run(empty, verbose=False)


def test_validate_run_sample_size_works(tmp_path: Path):
    """Sample-size limits the number of records checked."""
    # Make 5 clean records.
    records = [
        replace(_record_one_random_game(seed=s), game_idx=s)
        for s in range(5)
    ]
    run_dir = _make_run_dir(tmp_path, records)

    # All 5 pass.
    full = validate_run(run_dir, verbose=False)
    assert full == []

    # Sampling 2 also passes (clean data).
    sampled = validate_run(run_dir, sample_size=2, verbose=False)
    assert sampled == []
