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
    from agricola.agents.nn.agent import nn_evaluator
    from agricola.agents.nn.model import NormalizedValueModel

    model = NormalizedValueModel.load(str(_ROOT / "nn_models" / "best"))
    model.eval()
    model_dir = str(_EXPORT_DIR)

    worst = 0.0
    worst_info = None
    for state in _CORPUS:
        py = nn_evaluator(state, 0, model)
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
