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

    A sequence element may be a **thunk** ``(state) -> action`` instead of a
    concrete action; it is called with the current state to produce the action
    at apply time. This lets a scripted walk name an action whose exact value
    depends on the running state — e.g. ``sole_renovate`` (below), whose
    ``CommitRenovate.payment`` is the renovate frontier point at that moment.
    Action instances are never callable, so the two cases are unambiguous.
    """
    for element in actions:
        action = element(state) if callable(element) else element
        legal = legal_actions(state)
        assert action in legal, (
            f"Action {action!r} not in legal_actions: {legal!r}"
        )
        state = step(state, action)
    return state


def sole_renovate(state):
    """The unique legal ``CommitRenovate`` at a before-phase ``PendingRenovate``.

    Renovate carries an explicit ``payment`` since the cost-modifier refactor
    (COST_MODIFIER_DESIGN.md §3.2); in the Family game the frontier is a singleton
    (the printed cost), so this returns that one commit. Use it as a ``run_actions``
    thunk (bare ``sole_renovate``) or directly (``step(s, sole_renovate(s))``) in
    place of the old parameter-free ``CommitRenovate()``.
    """
    from agricola.actions import CommitRenovate
    opts = [a for a in legal_actions(state) if isinstance(a, CommitRenovate)]
    assert len(opts) == 1, f"expected exactly one CommitRenovate, got {opts!r}"
    return opts[0]


def sole_play_minor(state, card_id):
    """The unique legal ``CommitPlayMinor`` for ``card_id`` at a PendingPlayMinor.

    Play-minor is a *wide* commit carrying an explicit ``payment`` (the cost-modifier
    frontier point — COST_MODIFIER_DESIGN.md §3.4); with no conversion/formula minor in
    the catalog the frontier is a singleton, so exactly one commit exists per card. Use
    directly (``step(s, sole_play_minor(s, "x"))``) or via the ``play_minor`` thunk in a
    ``run_actions`` list, in place of the old ``CommitPlayMinor(card_id="x")``."""
    from agricola.actions import CommitPlayMinor
    opts = [a for a in legal_actions(state)
            if isinstance(a, CommitPlayMinor) and a.card_id == card_id]
    assert len(opts) == 1, f"expected one CommitPlayMinor for {card_id!r}, got {opts!r}"
    return opts[0]


def play_minor(card_id):
    """A ``run_actions`` thunk for `sole_play_minor` — `play_minor("x")` resolves to the
    legal ``CommitPlayMinor`` for "x" at apply time."""
    return lambda state: sole_play_minor(state, card_id)


def sole_build_major(state, major_idx, fireplace=None):
    """The legal ``CommitBuildMajor`` for `(major_idx, route)` at a PendingBuildMajor.

    `fireplace=None` selects the standard resource payment; `fireplace=fp` selects the
    Cooking-Hearth `ReturnImprovement(fp)` route. CommitBuildMajor is a *wide* commit
    carrying the chosen `payment` explicitly (COST_MODIFIER_DESIGN.md §3.4), so this
    pulls the matching one from `legal_actions` rather than hand-building the payment."""
    from agricola.actions import CommitBuildMajor
    from agricola.cost import ReturnImprovement
    for a in legal_actions(state):
        if not (isinstance(a, CommitBuildMajor) and a.major_idx == major_idx):
            continue
        is_route = isinstance(a.payment, ReturnImprovement)
        if fireplace is None and not is_route:
            return a
        if fireplace is not None and is_route and a.payment.improvement_idx == fireplace:
            return a
    raise AssertionError(
        f"no legal CommitBuildMajor(major_idx={major_idx}, fireplace={fireplace})")


def build_major(major_idx, fireplace=None):
    """A ``run_actions`` thunk for `sole_build_major`."""
    return lambda state: sole_build_major(state, major_idx, fireplace)


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
