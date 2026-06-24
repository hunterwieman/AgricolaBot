"""Stage 5 gate (CPP_ENGINE_PLAN.md §8): native NN inference matches Python.

Three sub-gates over a random-play decision corpus:

- **Encoder (exact):** ``agricola_cpp.encode(dumps(state), p)`` == Python
  ``encode_state(state, p)`` within ≤1e-5 (ideally float-identical), both
  perspectives. Needs NO .ts — runs even on a no-torch build.
- **Value (≤1e-4):** ``agricola_cpp.nn_value(dump, dir)`` ≈ Python
  ``nn_evaluator(state, 0, value_model)`` (== predict_margin from perspective 0;
  terminal = exact margin).
- **Policy (≤1e-4 per action):** the C++ ``nn_policy`` prior dict == Python
  ``build("unweighted")(state, legal_actions(state))`` per action.

The value/policy gates skip unless torch bindings are present AND
``nn_models/cpp_export/`` has been written (run
``scripts/nn/export_torchscript.py`` first). The encoder gate always runs (given
the cpp module).
"""

from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import pytest

from agricola.agents.base import decider_of
from agricola.agents.nn.encoder import encode_state
from agricola.agents.nn.trace_replay import action_to_params
from agricola.canonical import dumps
from agricola.constants import Phase
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.setup import setup_env
from tests.test_utils import filter_implemented

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_BUILD_DIR = _ROOT / "cpp" / "build"
if str(_BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(_BUILD_DIR))

agricola_cpp = pytest.importorskip(
    "agricola_cpp",
    reason="cpp module not built — see cpp/README.md",
)

_EXPORT_DIR = _ROOT / "nn_models" / "cpp_export"
# HAS_TORCH is the historical name for "the NN bindings are present"; the backend
# is now a hand-rolled MLP (no libtorch), but the attr name + meaning are kept so
# this guard is unchanged. The export is now a raw-weight blob set described by
# weights_manifest.json (scripts/nn/export_weights.py), not the old .ts manifest.
_HAS_NN = getattr(agricola_cpp, "HAS_TORCH", False)
_HAS_EXPORT = (_EXPORT_DIR / "weights_manifest.json").exists()
_torch_gate = pytest.mark.skipif(
    not (_HAS_NN and _HAS_EXPORT),
    reason="NN bindings not built or nn_models/cpp_export not exported "
    "(run scripts/nn/export_weights.py)",
)


def _norm_action(a) -> str:
    """Normalized {type, params} JSON for a Python Action (key for matching)."""
    return json.dumps(
        {"type": type(a).__name__, "params": action_to_params(a)}, sort_keys=True
    )


def _norm_json(s: str) -> str:
    return json.dumps(json.loads(s), sort_keys=True)


# ---------------------------------------------------------------------------
# Corpus: every *decision* state from random play (both perspectives for the
# encoder; the policy gate restricts to the decision states a head owns).
# ---------------------------------------------------------------------------


def _collect_states(seed: int, max_states: int = 4000) -> list:
    state, env = setup_env(seed)
    rng = np.random.default_rng(70_000 + seed)
    states = [state]
    while state.phase != Phase.BEFORE_SCORING and len(states) < max_states:
        d = decider_of(state)
        if d is None:
            action = env.resolve(state)
        else:
            legal = filter_implemented(legal_actions(state))
            action = legal[int(rng.integers(len(legal)))]
        state = step(state, action)
        states.append(state)
    return states


def _corpus(n_games: int = 25) -> list:
    out: list = []
    for seed in range(n_games):
        out.extend(_collect_states(seed))
    return out


_CORPUS = _corpus()


def test_corpus_is_non_vacuous():
    assert len(_CORPUS) > 3000
    top_types = {
        type(s.pending_stack[-1]).__name__ for s in _CORPUS if s.pending_stack
    }
    # The decision types the policy heads own must be present.
    assert any(not s.pending_stack and s.phase != Phase.BEFORE_SCORING for s in _CORPUS)
    assert "PendingHarvestFeed" in top_types
    assert "PendingHarvestBreed" in top_types
    assert "PendingSow" in top_types
    assert top_types & {"PendingSheepMarket", "PendingPigMarket", "PendingCattleMarket"}
    assert any(s.phase == Phase.BEFORE_SCORING for s in _CORPUS)


# ---------------------------------------------------------------------------
# Encoder (exact) — no torch needed.
# ---------------------------------------------------------------------------


def test_cpp_encode_matches_python():
    worst = 0.0
    worst_info = None
    for state in _CORPUS:
        d = dumps(state)
        for p in (0, 1):
            py = encode_state(state, p).astype(np.float64)
            cpp = np.asarray(agricola_cpp.encode(d, p), dtype=np.float64)
            assert cpp.shape == py.shape == (170,)
            diff = np.abs(cpp - py)
            m = float(diff.max())
            if m > worst:
                worst = m
                idx = int(diff.argmax())
                worst_info = (
                    state.round_number,
                    state.phase.name,
                    p,
                    idx,
                    float(py[idx]),
                    float(cpp[idx]),
                )
    assert worst <= 1e-5, (
        f"max |Δ|={worst:.3e} at {worst_info} "
        f"(round, phase, perspective, feat_idx, py, cpp)"
    )


# ---------------------------------------------------------------------------
# Value (≤1e-4).
# ---------------------------------------------------------------------------


@_torch_gate
def test_cpp_value_matches_python():
    from agricola.agents.nn.model import load_value_evaluator
    from agricola.agents.nn.shared_policy import make_joint_fns

    # model_kind-aware: `best` is now a joint SharedTrunkModel; its value head
    # satisfies the same predict_margin/value_scale contract. Compare against
    # the matching joint C++ export (cpp_export_best), not the stale separate-net
    # cpp_export. The joint value is read through make_joint_fns' value_fn (the
    # MCTS adapter) rather than nn_evaluator, which assumes a separate-net model
    # with a `.net` attribute that SharedTrunkModel lacks.
    model = load_value_evaluator(str(_ROOT / "nn_models" / "best"))
    model.eval()
    value_fn, _ = make_joint_fns(model)
    model_dir = str(_ROOT / "nn_models" / "cpp_export_best")

    worst = 0.0
    worst_info = None
    for state in _CORPUS:
        py = value_fn(state, 0)
        cpp = agricola_cpp.nn_value(dumps(state), model_dir)
        d = abs(py - cpp)
        if d > worst:
            worst = d
            worst_info = (state.round_number, state.phase.name, py, cpp)
    assert worst <= 1e-4, f"max |Δ|={worst:.3e} at {worst_info}"


# ---------------------------------------------------------------------------
# Policy (≤1e-4 per action).
# ---------------------------------------------------------------------------


@_torch_gate
def test_cpp_policy_matches_python():
    from scripts.nn.build_combined_policy import build

    policy_fn = build("unweighted")
    model_dir = str(_EXPORT_DIR)

    mismatches = []
    covered_types: set = set()
    for state in _CORPUS:
        if state.phase == Phase.BEFORE_SCORING:
            continue
        if decider_of(state) is None:
            continue
        legal = filter_implemented(legal_actions(state))
        if len(legal) <= 1:
            continue  # singleton — search skips; policy still defined but not gated

        py = policy_fn(state, list(legal_actions(state)))
        py_dict = {_norm_action(a): float(v) for a, v in py.items()}

        cpp_pairs = agricola_cpp.nn_policy(dumps(state), model_dir)
        cpp_dict = {_norm_json(s): float(v) for s, v in cpp_pairs}

        top = (
            type(state.pending_stack[-1]).__name__
            if state.pending_stack
            else "<placement>"
        )
        covered_types.add(top)

        keys = set(py_dict) | set(cpp_dict)
        for k in keys:
            pv = py_dict.get(k, 0.0)
            cv = cpp_dict.get(k, 0.0)
            if abs(pv - cv) > 1e-4:
                mismatches.append((top, k, pv, cv))
        if len(mismatches) >= 20:
            break

    if mismatches:
        lines = ["C++/Python policy prior mismatch (per action):"]
        for top, k, pv, cv in mismatches:
            lines.append(f"  [{top}] {k}: py={pv:.6f} cpp={cv:.6f}")
        pytest.fail("\n".join(lines))

    # Sanity: the gate actually exercised the head-owned decision types.
    assert "<placement>" in covered_types
    assert "PendingSow" in covered_types


# ---------------------------------------------------------------------------
# Joint shared-trunk inference (≤1e-4) — SHARED_TRUNK.md. Self-contained: a
# random SharedTrunkModel is exported via the real export_weights CLI to the
# shared_trunk_v1 format, loaded by the C++ joint NNInference, and compared to
# the Python make_joint_fns value + policy. No trained checkpoint needed, so it
# is a permanent gate on the C++ joint math.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_NN, reason="NN bindings not built")
def test_cpp_joint_matches_python(tmp_path):
    import subprocess

    from agricola.agents.nn.dataset import NormStats
    from agricola.agents.nn.encoder import ENCODED_DIM, ENCODING_VERSION
    from agricola.agents.nn.policy_heads import HEADS, POINTER_HEADS
    from agricola.agents.nn.shared_model import SharedTrunkModel
    from agricola.agents.nn.shared_policy import make_joint_fns

    rng = np.random.default_rng(0)
    stats = NormStats(
        input_mean=rng.standard_normal(ENCODED_DIM).astype(np.float32),
        input_std=(1.0 + np.abs(rng.standard_normal(ENCODED_DIM))).astype(np.float32),
        target_std=7.0, encoding_version=ENCODING_VERSION)
    model = SharedTrunkModel(
        fixed_head_specs={n: h.num_classes for n, h in HEADS.items()},
        pointer_head_specs={n: h.candidate_dim for n, h in POINTER_HEADS.items()},
        norm_stats=stats, trunk_hidden_dims=[32, 32], embedding_dim=16,
        pointer_head_dims=[8])
    model.value_scale = 4.0
    for n, h in POINTER_HEADS.items():  # non-identity candidate norms
        model.set_pointer_cand_norm(
            n, rng.standard_normal(h.candidate_dim).astype(np.float32),
            (1.0 + np.abs(rng.standard_normal(h.candidate_dim))).astype(np.float32))

    ckpt = tmp_path / "joint"
    model.save(ckpt)
    export_dir = tmp_path / "export"
    subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "nn" / "export_weights.py"),
         "--value-ckpt", str(ckpt), "--out-dir", str(export_dir)],
        check=True, cwd=str(_ROOT), capture_output=True)
    assert (export_dir / "weights_manifest.json").exists()

    vf, pf = make_joint_fns(model)
    worst_v = worst_p = 0.0
    md = str(export_dir)
    for state in _CORPUS[::9]:
        worst_v = max(worst_v, abs(agricola_cpp.nn_value(dumps(state), md) - vf(state)))
        if state.phase == Phase.BEFORE_SCORING or decider_of(state) is None:
            continue
        if len(filter_implemented(legal_actions(state))) <= 1:
            continue
        py = {_norm_action(a): float(v)
              for a, v in pf(state, list(legal_actions(state))).items()}
        cpp = {_norm_json(s): float(v) for s, v in agricola_cpp.nn_policy(dumps(state), md)}
        for k in set(py) | set(cpp):
            worst_p = max(worst_p, abs(py.get(k, 0.0) - cpp.get(k, 0.0)))
    assert worst_v <= 1e-4, f"joint value max |Δ|={worst_v:.3e}"
    assert worst_p <= 1e-4, f"joint policy max |Δ|={worst_p:.3e}"


# ---------------------------------------------------------------------------
# Joint with the leaky-ReLU activation (≤1e-4). Mirrors test_cpp_joint_matches_
# python but builds the random SharedTrunkModel with activation="leaky_relu", so
# the exporter writes "activation":"leaky_relu" and the C++ Mlp must dispatch to
# the LeakyReLU(0.01) branch in the trunk + pointer-head hidden blocks. A
# permanent gate that the leaky path stays equivalent to Python.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_NN, reason="NN bindings not built")
def test_cpp_joint_leaky_matches_python(tmp_path):
    import subprocess

    from agricola.agents.nn.dataset import NormStats
    from agricola.agents.nn.encoder import ENCODED_DIM, ENCODING_VERSION
    from agricola.agents.nn.policy_heads import HEADS, POINTER_HEADS
    from agricola.agents.nn.shared_model import SharedTrunkModel
    from agricola.agents.nn.shared_policy import make_joint_fns

    rng = np.random.default_rng(1)
    stats = NormStats(
        input_mean=rng.standard_normal(ENCODED_DIM).astype(np.float32),
        input_std=(1.0 + np.abs(rng.standard_normal(ENCODED_DIM))).astype(np.float32),
        target_std=7.0, encoding_version=ENCODING_VERSION)
    model = SharedTrunkModel(
        fixed_head_specs={n: h.num_classes for n, h in HEADS.items()},
        pointer_head_specs={n: h.candidate_dim for n, h in POINTER_HEADS.items()},
        norm_stats=stats, trunk_hidden_dims=[32, 32], embedding_dim=16,
        pointer_head_dims=[8], activation="leaky_relu")
    model.value_scale = 4.0
    for n, h in POINTER_HEADS.items():  # non-identity candidate norms
        model.set_pointer_cand_norm(
            n, rng.standard_normal(h.candidate_dim).astype(np.float32),
            (1.0 + np.abs(rng.standard_normal(h.candidate_dim))).astype(np.float32))

    ckpt = tmp_path / "joint_leaky"
    model.save(ckpt)
    export_dir = tmp_path / "export_leaky"
    subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "nn" / "export_weights.py"),
         "--value-ckpt", str(ckpt), "--out-dir", str(export_dir)],
        check=True, cwd=str(_ROOT), capture_output=True)
    manifest = json.loads((export_dir / "weights_manifest.json").read_text())
    assert manifest["activation"] == "leaky_relu"

    vf, pf = make_joint_fns(model)
    worst_v = worst_p = 0.0
    md = str(export_dir)
    for state in _CORPUS[::9]:
        worst_v = max(worst_v, abs(agricola_cpp.nn_value(dumps(state), md) - vf(state)))
        if state.phase == Phase.BEFORE_SCORING or decider_of(state) is None:
            continue
        if len(filter_implemented(legal_actions(state))) <= 1:
            continue
        py = {_norm_action(a): float(v)
              for a, v in pf(state, list(legal_actions(state))).items()}
        cpp = {_norm_json(s): float(v) for s, v in agricola_cpp.nn_policy(dumps(state), md)}
        for k in set(py) | set(cpp):
            worst_p = max(worst_p, abs(py.get(k, 0.0) - cpp.get(k, 0.0)))
    assert worst_v <= 1e-4, f"joint leaky value max |Δ|={worst_v:.3e}"
    assert worst_p <= 1e-4, f"joint leaky policy max |Δ|={worst_p:.3e}"


# ---------------------------------------------------------------------------
# Outcome head (≤1e-4) — Phase 2b. The C++ outcome readout (the outcome head off
# the shared trunk, sign-flipped to the P0 frame, with the exact sign(margin) at
# a terminal) must match Python SharedTrunkModel.predict_outcome. Uses a real
# trained checkpoint (joint_outcome_44k) exported fresh via the export_weights
# CLI, so it also gates the exporter's new "outcome" manifest entry.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_NN, reason="NN bindings not built")
def test_cpp_outcome_matches_python(tmp_path):
    import subprocess

    import torch

    from agricola.agents.nn.shared_model import SharedTrunkModel

    ckpt = _ROOT / "nn_models" / "joint_outcome_44k" / "best"
    if not ckpt.with_suffix(".meta.json").exists():
        pytest.skip("joint_outcome_44k checkpoint not present")

    model = SharedTrunkModel.load(str(ckpt))
    model.eval()
    assert model.outcome_head is not None

    export_dir = tmp_path / "export"
    subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "nn" / "export_weights.py"),
         "--value-ckpt", str(ckpt), "--out-dir", str(export_dir)],
        check=True, cwd=str(_ROOT), capture_output=True)
    manifest = json.loads((export_dir / "weights_manifest.json").read_text())
    assert manifest.get("outcome") is not None, "exporter did not write outcome head"

    md = str(export_dir)

    @torch.no_grad()
    def py_outcome(state) -> float:
        # P0-frame outcome, mirroring shared_policy.make_joint_fns' "outcome" leaf.
        if state.phase == Phase.BEFORE_SCORING:
            from agricola.scoring import score
            m = float(score(state, 0)[0] - score(state, 1)[0])
            return 1.0 if m > 0 else (-1.0 if m < 0 else 0.0)
        d = decider_of(state)
        if d is None:
            d = 0
        from agricola.agents.nn.encoder import ENCODER_V2
        x = torch.from_numpy(
            ENCODER_V2.encode_for_inference(state, d)).unsqueeze(0)
        v = float(model.predict_outcome(x)[0])
        return v if d == 0 else -v

    worst = 0.0
    worst_info = None
    for state in _CORPUS[::5]:
        py = py_outcome(state)
        cpp = agricola_cpp.nn_outcome(dumps(state), md)
        d = abs(py - cpp)
        if d > worst:
            worst = d
            worst_info = (state.round_number, state.phase.name, py, cpp)
    assert worst <= 1e-4, f"outcome max |Δ|={worst:.3e} at {worst_info}"


# ---------------------------------------------------------------------------
# Candidate encoder (exact, 178-d) — no torch needed. The forward-compatible
# encoder-registry dispatch: a model's encoder is resolved from its manifest
# `encoder_tag` (here exercised directly via the cpp `encode_candidate` binding).
# ---------------------------------------------------------------------------


def test_cpp_candidate_encode_matches_python():
    from agricola.agents.nn.encoder import encode_state_candidate

    worst = 0.0
    worst_info = None
    for state in _CORPUS:
        d = dumps(state)
        for p in (0, 1):
            py = encode_state_candidate(state, p).astype(np.float64)
            cpp = np.asarray(agricola_cpp.encode_candidate(d, p), dtype=np.float64)
            assert cpp.shape == py.shape == (178,)
            m = float(np.abs(cpp - py).max())
            if m > worst:
                worst = m
                worst_info = (state.round_number, state.phase.name, p)
    assert worst <= 1e-5, f"candidate encoder max |Δ|={worst:.3e} at {worst_info}"


# ---------------------------------------------------------------------------
# Candidate JOINT inference (≤1e-4) — the registry-dispatched 178-d encoder +
# the begging add-back at the value head. Self-contained like the v2 joint gate:
# a random SharedTrunkModel TAGGED `cand_feat178_v1` is exported (encoder_tag in
# the manifest), loaded by C++ (registry -> encode_candidate + begging add-back),
# and compared to Python make_joint_fns. No trained checkpoint needed, so it is a
# permanent gate on the candidate path.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_NN, reason="NN bindings not built")
def test_cpp_joint_candidate_matches_python(tmp_path):
    import subprocess

    from agricola.agents.nn.dataset import NormStats
    from agricola.agents.nn.encoder import (
        CANDIDATE_ENCODING_TAG,
        ENCODED_DIM_CANDIDATE,
        ENCODING_VERSION,
    )
    from agricola.agents.nn.policy_heads import HEADS, POINTER_HEADS
    from agricola.agents.nn.shared_model import SharedTrunkModel
    from agricola.agents.nn.shared_policy import make_joint_fns

    rng = np.random.default_rng(1)
    d = ENCODED_DIM_CANDIDATE
    stats = NormStats(
        input_mean=rng.standard_normal(d).astype(np.float32),
        input_std=(1.0 + np.abs(rng.standard_normal(d))).astype(np.float32),
        target_std=7.0, encoding_version=ENCODING_VERSION,
        encoding_tag=CANDIDATE_ENCODING_TAG)
    model = SharedTrunkModel(
        fixed_head_specs={n: h.num_classes for n, h in HEADS.items()},
        pointer_head_specs={n: h.candidate_dim for n, h in POINTER_HEADS.items()},
        norm_stats=stats, input_dim=d, trunk_hidden_dims=[32, 32], embedding_dim=16,
        pointer_head_dims=[8])
    model.value_scale = 4.0
    for n, h in POINTER_HEADS.items():
        model.set_pointer_cand_norm(
            n, rng.standard_normal(h.candidate_dim).astype(np.float32),
            (1.0 + np.abs(rng.standard_normal(h.candidate_dim))).astype(np.float32))

    ckpt = tmp_path / "joint_cand"
    model.save(ckpt)
    export_dir = tmp_path / "export_cand"
    subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "nn" / "export_weights.py"),
         "--value-ckpt", str(ckpt), "--out-dir", str(export_dir)],
        check=True, cwd=str(_ROOT), capture_output=True)
    manifest = json.loads((export_dir / "weights_manifest.json").read_text())
    assert manifest.get("encoder_tag") == CANDIDATE_ENCODING_TAG

    vf, pf = make_joint_fns(model)
    worst_v = worst_p = 0.0
    md = str(export_dir)
    for state in _CORPUS[::9]:
        worst_v = max(worst_v, abs(agricola_cpp.nn_value(dumps(state), md) - vf(state)))
        if state.phase == Phase.BEFORE_SCORING or decider_of(state) is None:
            continue
        if len(filter_implemented(legal_actions(state))) <= 1:
            continue
        py = {_norm_action(a): float(v)
              for a, v in pf(state, list(legal_actions(state))).items()}
        cpp = {_norm_json(s): float(v) for s, v in agricola_cpp.nn_policy(dumps(state), md)}
        for k in set(py) | set(cpp):
            worst_p = max(worst_p, abs(py.get(k, 0.0) - cpp.get(k, 0.0)))
    assert worst_v <= 1e-4, f"candidate joint value max |Δ|={worst_v:.3e}"
    assert worst_p <= 1e-4, f"candidate joint policy max |Δ|={worst_p:.3e}"
