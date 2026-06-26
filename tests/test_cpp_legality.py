"""Stage 2 gate (CPP_ENGINE_PLAN.md §8): the C++ ``legal_actions`` produces the
same SET of legal actions as the Python oracle over a large random-play corpus.

Comparison protocol (§3.2 — robust to ordering/format; only the SET must match):

- Python expected set:
    { _norm(json.dumps({"type": type(a).__name__, "params": action_to_params(a)}))
      for a in filter_implemented(legal_actions(state)) }
- C++ set:
    { _norm(s) for s in agricola_cpp.legal_actions(dumps(state)) }
- _norm(s) = json.dumps(json.loads(s), sort_keys=True)  (canonicalize key order)

The corpus is built by random play from setup_env(seed): nature reveals are
routed through env.resolve; player decisions pick uniformly from the
implemented legal set. Covers full games over many seeds, exercising pending
stacks, harvest frames, market frames, fencing frames, and reveals.

Skips cleanly if the cpp module isn't built (see cpp/README.md).
"""

from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import pytest

from agricola.agents.base import decider_of
from agricola.agents.nn.trace_replay import action_to_params
from agricola.canonical import dumps
from agricola.constants import Phase
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.setup import setup_env
from tests.test_utils import filter_implemented

_BUILD_DIR = pathlib.Path(__file__).resolve().parent.parent / "cpp" / "build"
if str(_BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(_BUILD_DIR))

agricola_cpp = pytest.importorskip(
    "agricola_cpp",
    reason="cpp module not built — see cpp/README.md (cmake -S cpp -B cpp/build ...)",
)

_HARVEST_PHASES = {Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED}


def _norm(s: str) -> str:
    """Canonicalize a {type, params} JSON string (key order / formatting)."""
    return json.dumps(json.loads(s), sort_keys=True)


def _py_expected_set(state) -> set:
    return {
        _norm(json.dumps({"type": type(a).__name__, "params": action_to_params(a)}))
        for a in filter_implemented(legal_actions(state))
    }


def _cpp_set(state) -> set:
    return {_norm(s) for s in agricola_cpp.legal_actions(dumps(state))}


def _collect_states(seed: int, max_states: int = 4000) -> list:
    """Play one full random game; return every state visited (incl. pendings)."""
    state, env = setup_env(seed)
    rng = np.random.default_rng(50_000 + seed)
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


def _corpus(n_games: int = 40) -> list:
    out: list = []
    for seed in range(n_games):
        out.extend(_collect_states(seed))
    return out


# Build the corpus once for the whole module.
_CORPUS = _corpus()


def test_corpus_is_non_vacuous():
    """The corpus contains the hard cases the gate is meant to stress."""
    assert len(_CORPUS) > 5000

    def _top_type(s):
        return type(s.pending_stack[-1]).__name__ if s.pending_stack else None

    top_types = {_top_type(s) for s in _CORPUS}
    # Pending-stack states at all.
    assert any(s.pending_stack for s in _CORPUS)
    # Harvest states (FIELD/FEED/BREED phase) and harvest frames.
    assert any(s.phase in _HARVEST_PHASES for s in _CORPUS)
    assert "PendingHarvestFeed" in top_types
    assert "PendingHarvestBreed" in top_types
    # Market frames.
    assert top_types & {"PendingSheepMarket", "PendingPigMarket", "PendingCattleMarket"}
    # Fencing frames (the Fencing space host is now the generic
    # PendingSubActionSpace; the build-fences primitive is PendingBuildFences).
    assert top_types & {"PendingSubActionSpace", "PendingBuildFences"}
    # Reveal (nature) frames.
    assert any(s.pending_stack and decider_of(s) is None for s in _CORPUS)
    # Terminal states.
    assert any(s.phase == Phase.BEFORE_SCORING for s in _CORPUS)


def test_cpp_legal_actions_set_matches_python():
    """C++ legal-action SET == Python's over the whole corpus."""
    mismatches = []
    for state in _CORPUS:
        py = _py_expected_set(state)
        cpp = _cpp_set(state)
        if py != cpp:
            top = (
                type(state.pending_stack[-1]).__name__
                if state.pending_stack
                else "<empty>"
            )
            mismatches.append(
                {
                    "round": state.round_number,
                    "phase": state.phase.name,
                    "pending_top": top,
                    "decider": decider_of(state),
                    "only_in_python": sorted(py - cpp),
                    "only_in_cpp": sorted(cpp - py),
                }
            )
            if len(mismatches) >= 10:
                break

    if mismatches:
        lines = ["C++/Python legal_actions SET mismatch:"]
        for m in mismatches:
            lines.append(
                f"  round={m['round']} phase={m['phase']} "
                f"pending_top={m['pending_top']} decider={m['decider']}"
            )
            for a in m["only_in_python"]:
                lines.append(f"    only in PYTHON: {a}")
            for a in m["only_in_cpp"]:
                lines.append(f"    only in C++:    {a}")
        pytest.fail("\n".join(lines))
