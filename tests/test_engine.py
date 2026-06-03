"""Tests for the engine module — step, _advance_until_decision, and the
round-transition machinery.

Split between (a) gameplay-reachable scenarios that exercise the engine
end-to-end via random-agent play, and (b) prefabricated-state unit tests
that target specific behaviors of step and _advance_until_decision.
"""
from __future__ import annotations

import dataclasses

import pytest

from agricola.actions import PlaceWorker
from agricola.constants import Phase
from agricola.engine import (
    _advance_current_player,
    _advance_until_decision,
    _complete_preparation,
    _resolve_return_home,
    step,
)
from agricola.legality import legal_actions, legal_actions_cache
from agricola.setup import setup
from agricola.state import get_space

from tests.factories import (
    with_current_player,
    with_people,
    with_phase,
    with_resources,
    with_round,
    with_space,
)
from tests.test_utils import filter_implemented, random_agent_play


# ---------------------------------------------------------------------------
# Step on atomic placements
# ---------------------------------------------------------------------------

def test_step_day_laborer_basic():
    """Atomic placement: +2 food, people_home -= 1, workers updated, stack empty."""
    state = setup(seed=0)
    ap = state.current_player
    pre = state.players[ap]
    pre_food = pre.resources.food
    pre_home = pre.people_home

    new_state = step(state, PlaceWorker(space="day_laborer"))

    assert new_state.players[ap].resources.food == pre_food + 2
    assert new_state.players[ap].people_home == pre_home - 1
    assert get_space(new_state.board, "day_laborer").workers != (0, 0)
    assert new_state.pending_stack == ()
    # current_player alternated.
    assert new_state.current_player != ap


def test_step_atomic_then_atomic_alternates():
    """Two consecutive atomic placements alternate correctly."""
    state = setup(seed=0)
    ap = state.current_player
    state = step(state, PlaceWorker(space="day_laborer"))
    assert state.current_player == 1 - ap
    state = step(state, PlaceWorker(space="forest"))
    assert state.current_player == ap


# ---------------------------------------------------------------------------
# Stack invariants
# ---------------------------------------------------------------------------

def test_step_on_atomic_leaves_empty_stack():
    state = setup(seed=0)
    new_state = step(state, PlaceWorker(space="day_laborer"))
    assert new_state.pending_stack == ()


def test_advance_until_decision_idempotent():
    """A state returned by step is stable under _advance_until_decision."""
    state = setup(seed=0)
    state = step(state, PlaceWorker(space="day_laborer"))
    assert _advance_until_decision(state) == state


# ---------------------------------------------------------------------------
# _advance_current_player
# ---------------------------------------------------------------------------

def test_advance_current_player_alternates():
    state = setup(seed=0)
    ap = state.current_player
    new_state = _advance_current_player(state)
    assert new_state.current_player == 1 - ap


def test_advance_current_player_stays_when_other_has_no_workers():
    state = setup(seed=0)
    ap = state.current_player
    state = with_people(state, 1 - ap, home=0)
    # Other player has 0 workers — alternation should leave current_player.
    new_state = _advance_current_player(state)
    assert new_state.current_player == ap


# ---------------------------------------------------------------------------
# Round transitions
# ---------------------------------------------------------------------------

def test_work_phase_ends_when_both_players_zero_workers():
    """When both players have placed all workers, the round ends: RETURN_HOME →
    PREPARATION → (nature reveal) → next round's WORK."""
    state = setup(seed=0)
    # Force both players to people_home=0.
    state = with_people(state, 0, home=0)
    state = with_people(state, 1, home=0)

    # _advance_until_decision now parks at the round-2 reveal nature node — it
    # cannot cross a round boundary without the reveal being resolved.
    reveal_node = _advance_until_decision(state)
    assert reveal_node.phase == Phase.PREPARATION and reveal_node.pending_stack
    # Resolve the reveal (any candidate) → round-2 WORK.
    new_state = step(reveal_node, legal_actions(reveal_node)[0])

    # Should now be at round 2, WORK phase, both players replenished.
    assert new_state.phase == Phase.WORK
    assert new_state.round_number == 2
    assert new_state.players[0].people_home == new_state.players[0].people_total
    assert new_state.players[1].people_home == new_state.players[1].people_total
    # current_player reset to starting_player.
    assert new_state.current_player == new_state.starting_player
    # All action-space workers reset.
    for space_state in new_state.board.action_spaces:
        assert space_state.workers == (0, 0)


def test_return_home_resets_workers():
    """_resolve_return_home zeroes every action space's workers tuple."""
    state = setup(seed=0)
    # Place a worker somewhere.
    state = with_space(state, "forest", workers=(1, 0))
    state = with_phase(state, Phase.RETURN_HOME)

    new_state = _resolve_return_home(state)
    for space_state in new_state.board.action_spaces:
        assert space_state.workers == (0, 0)


def test_return_home_returns_people_home():
    """_resolve_return_home sets people_home back to people_total."""
    state = setup(seed=0)
    state = with_people(state, 0, home=0)
    state = with_people(state, 1, home=1)  # mid-placement
    state = with_phase(state, Phase.RETURN_HOME)

    new_state = _resolve_return_home(state)
    for p in new_state.players:
        assert p.people_home == p.people_total


def test_return_home_does_not_clear_newborns():
    """Newborns must survive RETURN_HOME for the harvest-feed discount."""
    state = setup(seed=0)
    state = with_people(state, 0, total=3, home=2, newborns=1)
    state = with_phase(state, Phase.RETURN_HOME)

    new_state = _resolve_return_home(state)
    assert new_state.players[0].newborns == 1


def test_preparation_clears_newborns():
    """_complete_preparation is where newborns are cleared (after any harvest)."""
    state = setup(seed=0)
    state = with_people(state, 0, total=3, home=3, newborns=1)
    state = with_phase(state, Phase.PREPARATION)

    new_state = _complete_preparation(state)
    assert new_state.players[0].newborns == 0


def test_preparation_refills_accumulation_spaces():
    """PREP adds per-round rates to every revealed accumulation space."""
    state = setup(seed=0)
    state = with_phase(state, Phase.PREPARATION)
    # Pre-PREP forest accumulation is some round-1 value. After PREP for
    # round 2, it gains 3 more wood.
    pre_forest = get_space(state.board, "forest").accumulated
    pre_clay_pit = get_space(state.board, "clay_pit").accumulated

    new_state = _complete_preparation(state)

    new_forest = get_space(new_state.board, "forest").accumulated
    new_clay_pit = get_space(new_state.board, "clay_pit").accumulated
    assert new_forest.wood == pre_forest.wood + 3
    assert new_clay_pit.clay == pre_clay_pit.clay + 1


def test_preparation_increments_round_number():
    state = setup(seed=0)
    state = with_phase(state, Phase.PREPARATION)
    new_state = _complete_preparation(state)
    assert new_state.round_number == state.round_number + 1


def test_preparation_resets_current_player_to_starting_player():
    state = setup(seed=0)
    state = with_current_player(state, 1 - state.starting_player)
    state = with_phase(state, Phase.PREPARATION)
    new_state = _complete_preparation(state)
    assert new_state.current_player == new_state.starting_player


def test_harvest_round_return_home_transitions_to_harvest_field():
    """After RETURN_HOME on a HARVEST_ROUND (e.g. 4), the next phase is
    HARVEST_FIELD — the harvest sub-phases drive the round forward, not
    PREPARATION (Task 7). Round 14's HARVEST_BREED exit lands in
    BEFORE_SCORING, but that transition lives in _advance_until_decision,
    not here."""
    state = setup(seed=0)
    state = with_round(state, 4)
    state = with_phase(state, Phase.RETURN_HOME)
    new_state = _resolve_return_home(state)
    assert new_state.phase == Phase.HARVEST_FIELD
    assert new_state.round_number == 4   # not advanced — that happens in PREPARATION


def test_non_harvest_round_return_home_transitions_to_preparation():
    """RETURN_HOME on a non-harvest round goes to PREPARATION."""
    state = setup(seed=0)
    state = with_round(state, 3)   # not in HARVEST_ROUNDS
    state = with_phase(state, Phase.RETURN_HOME)
    new_state = _resolve_return_home(state)
    assert new_state.phase == Phase.PREPARATION
    assert new_state.round_number == 3


# ---------------------------------------------------------------------------
# Error behaviors
# ---------------------------------------------------------------------------

def test_step_raises_on_before_scoring():
    """step() raises if called on a terminal-phase state."""
    state = setup(seed=0)
    state = with_phase(state, Phase.BEFORE_SCORING)
    with pytest.raises(RuntimeError):
        step(state, PlaceWorker(space="day_laborer"))


def test_step_raises_on_unknown_space():
    """Calling step on a PlaceWorker with an unknown space-id raises.

    After TASK_6, every non-atomic space surfaced by legal_placements has a
    registered handler. The defensive guard in `_apply_place_worker` covers
    the remaining never-registered IDs (only `lessons`, which is permanently
    illegal in the Family game and never surfaces via legal_placements).
    """
    state = setup(seed=0)
    with pytest.raises(NotImplementedError):
        step(state, PlaceWorker(space="lessons"))


# ---------------------------------------------------------------------------
# End-to-end random agent
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", list(range(10)))
def test_random_agent_plays_full_game(seed):
    """A random agent picking only implemented actions plays all 14 rounds
    to BEFORE_SCORING. Post-Task-7 (harvest + rounds 5–14)."""
    state, trace = random_agent_play(setup(seed=seed), seed=seed)

    assert state.phase == Phase.BEFORE_SCORING
    assert state.round_number == 14
    assert state.pending_stack == ()
    # After RETURN_HOME, both players have full people_home.
    for p in state.players:
        assert p.people_home == p.people_total
    # All action-space workers reset.
    for space_state in state.board.action_spaces:
        assert space_state.workers == (0, 0)
    # Trace contains at least some actions.
    assert len(trace) > 0


# ---------------------------------------------------------------------------
# legal_actions_cache (PROFILING.md R1)
# ---------------------------------------------------------------------------

def test_legal_actions_uncached_by_default():
    """Outside the context manager, two calls each go through full enumeration
    and return DIFFERENT list objects (no cache hit)."""
    state = setup(seed=0)
    a1 = legal_actions(state)
    a2 = legal_actions(state)
    assert a1 == a2          # same content
    assert a1 is not a2      # different list objects (uncached)


def test_legal_actions_cached_inside_context_manager():
    """Inside `with legal_actions_cache():`, the same state returns the SAME
    list object on repeat calls."""
    state = setup(seed=0)
    with legal_actions_cache():
        a1 = legal_actions(state)
        a2 = legal_actions(state)
        assert a1 is a2      # cached by reference


def test_legal_actions_cache_distinguishes_states():
    """Different states get different cache entries."""
    state_a = setup(seed=0)
    state_b = setup(seed=1)
    with legal_actions_cache():
        a = legal_actions(state_a)
        b = legal_actions(state_b)
        # Two distinct states -> two distinct cached lists (regardless of
        # whether the lists' contents happen to coincide).
        assert legal_actions(state_a) is a
        assert legal_actions(state_b) is b


def test_legal_actions_cache_size_grows_with_unique_states():
    """The cache dict yielded by the context manager grows as new states are
    queried; repeat queries on the same state do not."""
    state = setup(seed=0)
    with legal_actions_cache() as cache:
        assert len(cache) == 0
        legal_actions(state)
        assert len(cache) == 1
        legal_actions(state)
        assert len(cache) == 1   # no new entry on repeat
        # Step once to produce a different state, query that too.
        actions = legal_actions(state)
        state2 = step(state, actions[0])
        legal_actions(state2)
        assert len(cache) == 2


def test_legal_actions_cache_cleared_on_exit():
    """After exiting the context manager, the next call is uncached again."""
    state = setup(seed=0)
    with legal_actions_cache():
        a_inside = legal_actions(state)
        assert legal_actions(state) is a_inside
    a_outside = legal_actions(state)
    assert a_outside is not a_inside   # different object, fresh enumeration


def test_legal_actions_cache_nests():
    """Nested context managers have independent caches; inner exit does not
    drop outer's entries."""
    state = setup(seed=0)
    with legal_actions_cache() as outer:
        a_outer = legal_actions(state)
        assert len(outer) == 1
        with legal_actions_cache() as inner:
            assert len(inner) == 0          # fresh inner cache
            a_inner = legal_actions(state)
            assert a_inner is not a_outer   # different object — inner cache miss-then-fill
            assert len(inner) == 1
        # After inner exit, outer cache still has its entry
        assert len(outer) == 1
        assert legal_actions(state) is a_outer


def test_legal_actions_cache_step_state_evolution():
    """Walk a few steps of a game inside the cache; verify each new state is
    a new entry and repeat queries are reused."""
    state = setup(seed=0)
    with legal_actions_cache() as cache:
        for _ in range(5):
            actions = legal_actions(state)
            # Repeat query is cached
            assert legal_actions(state) is actions
            state = step(state, actions[0])
        # We've seen at least 5 distinct states (likely all of them unique).
        assert len(cache) >= 5


# ---------------------------------------------------------------------------
# Non-negative safety net (PROFILING.md R2)
# ---------------------------------------------------------------------------

def test_nonnegative_assertion_active_under_debug():
    """The R2 gate is `if __debug__:`. Under unoptimized Python (test runner
    default), __debug__ is True and the assertion remains live."""
    assert __debug__, "Tests should run with __debug__ == True"
    # Sanity: a normal step doesn't trip the assertion.
    state = setup(seed=0)
    state = step(state, legal_actions(state)[0])
    # If the assertion fired, step would have raised before returning.
    assert state is not None


def test_nonnegative_assertion_fires_on_corrupted_state():
    """When the assertion path runs, a state with negative resources trips it.

    Builds a state with negative grain, then calls _assert_nonnegative_state
    directly (so the test doesn't depend on a step() path that happens to
    produce negative values).
    """
    from agricola.actions import Stop
    from agricola.engine import _assert_nonnegative_state
    from agricola.resources import Resources
    from tests.factories import with_resources

    state = setup(seed=0)
    state = with_resources(state, 0, grain=-1)
    with pytest.raises(AssertionError):
        _assert_nonnegative_state(state, Stop())


def test_random_agent_invariants():
    """Meta-test: across random plays, the decider rule holds at every state.

    'Decider' rule: when stack is non-empty, the decision-maker is
    pending_stack[-1].player_idx; when empty, it's state.current_player.
    During WORK, the worker-placement path keeps current_player aligned with
    the top pending. During HARVEST_FEED / HARVEST_BREED, the pending stack
    alone identifies the decider — no worker is placed, and current_player
    is not updated to track each pending swap (per TASK_7 Part 2.1: the
    stack is authoritative). So the alignment invariant holds only during
    WORK.
    """
    for seed in range(5):
        state = setup(seed=seed)
        while state.phase != Phase.BEFORE_SCORING:
            actions = filter_implemented(legal_actions(state))
            if not actions:
                break
            # During WORK with a non-empty stack, the alignment holds.
            # (Harvest phases are excluded — the stack is authoritative there.)
            if state.pending_stack and state.phase == Phase.WORK:
                assert state.pending_stack[-1].player_idx == state.current_player
            action = actions[0]   # deterministic pick for invariant testing
            state = step(state, action)
