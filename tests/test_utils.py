"""Test utilities — multi-step test helpers and the random-agent harness.

Used by test files that need to apply a scripted sequence of actions or
drive a full random game.
"""
from __future__ import annotations

import numpy as np

from agricola.actions import PlaceWorker
from agricola.constants import Phase
from agricola.engine import NONATOMIC_HANDLERS, step
from agricola.legality import legal_actions
from agricola.resolution import ATOMIC_HANDLERS


# ---------------------------------------------------------------------------
# Scripted multi-action helper
# ---------------------------------------------------------------------------

def run_actions(state, actions):
    """Apply a sequence of actions in order; validate each is legal.

    Raises AssertionError if any action in the sequence is illegal at the
    moment it's applied. Useful for scripted tests that walk through a
    specific scenario (e.g., the Grain Utilization sow-then-bake test).
    """
    for action in actions:
        legal = legal_actions(state)
        assert action in legal, (
            f"Action {action!r} not in legal_actions: {legal!r}"
        )
        state = step(state, action)
    return state


# ---------------------------------------------------------------------------
# Implemented-action filter (for random-agent play)
# ---------------------------------------------------------------------------

# Non-atomic spaces whose resolution step() knows how to apply.
# Derived from engine.NONATOMIC_HANDLERS — when a new non-atomic space is
# implemented in engine.py, this filter automatically widens.
IMPLEMENTED_NON_ATOMIC_SPACES = frozenset(NONATOMIC_HANDLERS.keys())


def _is_implemented_action(action):
    """Return True if step() can apply this action under current engine scope.

    For PlaceWorker actions: the target space must be in ATOMIC_HANDLERS or
    in NONATOMIC_HANDLERS. For all other action types (sub-actions, triggers,
    Stop, and the Task-7 harvest commits CommitHarvestConversion / CommitConvert
    / CommitBreed), they're only reachable when the pending stack already has
    an implemented frame, so they're always OK.
    """
    if isinstance(action, PlaceWorker):
        return (
            action.space in ATOMIC_HANDLERS
            or action.space in IMPLEMENTED_NON_ATOMIC_SPACES
        )
    return True


def filter_implemented(actions):
    """Filter a legal_actions output to those step() knows how to apply."""
    return [a for a in actions if _is_implemented_action(a)]


# ---------------------------------------------------------------------------
# Random-agent driver
# ---------------------------------------------------------------------------

def random_agent_play(state, seed: int):
    """Play to BEFORE_SCORING using a random agent that only picks
    implemented actions. Returns (terminal_state, trace).

    Raises RuntimeError if the agent reaches a state with no implemented
    legal actions (would indicate a bug in step or in the filter).
    """
    rng = np.random.default_rng(seed)
    trace = []
    while state.phase != Phase.BEFORE_SCORING:
        actions = filter_implemented(legal_actions(state))
        if not actions:
            raise RuntimeError(
                f"Random agent stuck: no implemented legal actions. "
                f"State: phase={state.phase}, "
                f"current_player={state.current_player}, "
                f"pending_stack={state.pending_stack}"
            )
        action = actions[int(rng.integers(len(actions)))]
        trace.append(action)
        state = step(state, action)
    return state, trace
