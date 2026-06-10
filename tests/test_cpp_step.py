"""Stage 3 graduation gate (CPP_ENGINE_PLAN.md §8): the C++ ``step`` produces a
state BYTE-IDENTICAL to the Python oracle at every transition of random games,
and C++ ``score``/``tiebreaker`` equal Python's on terminal states.

Protocol (§3.2 trace-replay): Python plays random games from ``setup_env(seed)``
(nature reveals via ``env.resolve``; player decisions uniform over
``filter_implemented(legal_actions(state))``). At each transition we record
``(state_before, action, state_after)`` and assert

    agricola_cpp.step(dumps(before), action_json) == dumps(after)

where ``action_json = json.dumps({"type": type(a).__name__,
"params": action_to_params(a)})``. On mismatch we print round/phase/pending-top/
action plus a unified diff of the two canonical dumps.

Skips cleanly if the cpp module isn't built (see cpp/README.md).
"""

from __future__ import annotations

import difflib
import json
import pathlib
import sys

import numpy as np
import pytest

import agricola.scoring as scoring
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


def _action_json(action) -> str:
    return json.dumps(
        {"type": type(action).__name__, "params": action_to_params(action)}
    )


def _play_recorded(seed: int, max_steps: int = 6000):
    """Play one full random game; yield (before, action, after) transitions
    and finish with the terminal state."""
    state, env = setup_env(seed)
    transitions = []
    n = 0
    while state.phase != Phase.BEFORE_SCORING and n < max_steps:
        d = decider_of(state)
        if d is None:
            action = env.resolve(state)
        else:
            legal = filter_implemented(legal_actions(state))
            rng = np.random.default_rng(70_000 + seed * 13 + n)
            action = legal[int(rng.integers(len(legal)))]
        after = step(state, action)
        transitions.append((state, action, after))
        state = after
        n += 1
    return transitions, state


# Build the corpus of (before, action, after) transitions + terminal states once.
_N_GAMES = 35
_GAMES = [_play_recorded(seed) for seed in range(_N_GAMES)]
_TRANSITIONS = [t for game, _ in _GAMES for t in game]
_TERMINALS = [terminal for _, terminal in _GAMES]


def test_corpus_is_non_vacuous():
    """The replayed transitions include every hard subsystem the gate stresses."""
    assert len(_TRANSITIONS) > 5000

    action_types = {type(a).__name__ for _, a, _ in _TRANSITIONS}
    after_top_types = {
        type(after.pending_stack[-1]).__name__
        for _, _, after in _TRANSITIONS
        if after.pending_stack
    }

    # Reveals (nature round-card reveal).
    assert "RevealCard" in action_types
    # Harvest sub-phases reached.
    assert any(
        before.phase in _HARVEST_PHASES or after.phase in _HARVEST_PHASES
        for before, _, after in _TRANSITIONS
    )
    assert "PendingHarvestFeed" in after_top_types
    assert "PendingHarvestBreed" in after_top_types
    # Market accommodations.
    assert "CommitAccommodate" in action_types
    # Fencing commits.
    assert "CommitBuildPasture" in action_types
    # Build-major commits.
    assert "CommitBuildMajor" in action_types
    # Terminal scoring states.
    assert any(t.phase == Phase.BEFORE_SCORING for t in _TERMINALS)
    assert len(_TERMINALS) >= 30


def test_cpp_step_matches_python_byte_for_byte():
    """C++ step output == Python step output, byte-identically, at every step."""
    mismatches = []
    for before, action, after in _TRANSITIONS:
        before_dump = dumps(before)
        expected = dumps(after)
        got = agricola_cpp.step(before_dump, _action_json(action))
        if got != expected:
            top = (
                type(before.pending_stack[-1]).__name__
                if before.pending_stack
                else "<empty>"
            )
            diff = "\n".join(
                difflib.unified_diff(
                    json.dumps(json.loads(expected), indent=1, sort_keys=True).splitlines(),
                    json.dumps(json.loads(got), indent=1, sort_keys=True).splitlines(),
                    fromfile="python_after",
                    tofile="cpp_after",
                    lineterm="",
                )
            )
            mismatches.append(
                {
                    "round": before.round_number,
                    "phase": before.phase.name,
                    "pending_top": top,
                    "decider": decider_of(before),
                    "action": _action_json(action),
                    "diff": diff,
                }
            )
            if len(mismatches) >= 8:
                break

    if mismatches:
        lines = ["C++/Python step() byte mismatch:"]
        for m in mismatches:
            lines.append(
                f"  round={m['round']} phase={m['phase']} "
                f"pending_top={m['pending_top']} decider={m['decider']}"
            )
            lines.append(f"    action: {m['action']}")
            lines.append(m["diff"])
        pytest.fail("\n".join(lines))


def test_cpp_scoring_matches_python():
    """C++ score + tiebreaker == Python on every terminal state, both seats."""
    mismatches = []
    for terminal in _TERMINALS:
        if terminal.phase != Phase.BEFORE_SCORING:
            continue
        dump = dumps(terminal)
        for i in (0, 1):
            py_score = scoring.score(terminal, i)[0]
            py_tb = scoring.tiebreaker(terminal, i)
            cpp_score = agricola_cpp.score(dump, i)
            cpp_tb = agricola_cpp.tiebreaker(dump, i)
            if cpp_score != py_score or cpp_tb != py_tb:
                mismatches.append(
                    f"  player {i}: py=({py_score},{py_tb}) "
                    f"cpp=({cpp_score},{cpp_tb})"
                )

    if mismatches:
        pytest.fail("C++/Python scoring mismatch:\n" + "\n".join(mismatches))
