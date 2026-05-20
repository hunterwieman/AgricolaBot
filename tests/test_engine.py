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
    _resolve_preparation,
    _resolve_return_home,
    step,
)
from agricola.legality import legal_actions
from agricola.setup import setup

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
    assert new_state.board.action_spaces["day_laborer"].workers != (0, 0)
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
    """When both players have placed all workers, phase advances through
    RETURN_HOME → PREPARATION → next round's WORK."""
    state = setup(seed=0)
    # Force both players to people_home=0.
    state = with_people(state, 0, home=0)
    state = with_people(state, 1, home=0)

    new_state = _advance_until_decision(state)

    # Should now be at round 2, WORK phase, both players replenished.
    assert new_state.phase == Phase.WORK
    assert new_state.round_number == 2
    assert new_state.players[0].people_home == new_state.players[0].people_total
    assert new_state.players[1].people_home == new_state.players[1].people_total
    # current_player reset to starting_player.
    assert new_state.current_player == new_state.starting_player
    # All action-space workers reset.
    for space_state in new_state.board.action_spaces.values():
        assert space_state.workers == (0, 0)


def test_return_home_resets_workers():
    """_resolve_return_home zeroes every action space's workers tuple."""
    state = setup(seed=0)
    # Place a worker somewhere.
    state = with_space(state, "forest", workers=(1, 0))
    state = with_phase(state, Phase.RETURN_HOME)

    new_state = _resolve_return_home(state)
    for space_state in new_state.board.action_spaces.values():
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
    """_resolve_preparation is where newborns are cleared (after any harvest)."""
    state = setup(seed=0)
    state = with_people(state, 0, total=3, home=3, newborns=1)
    state = with_phase(state, Phase.PREPARATION)

    new_state = _resolve_preparation(state)
    assert new_state.players[0].newborns == 0


def test_preparation_refills_accumulation_spaces():
    """PREP adds per-round rates to every revealed accumulation space."""
    state = setup(seed=0)
    state = with_phase(state, Phase.PREPARATION)
    # Pre-PREP forest accumulation is some round-1 value. After PREP for
    # round 2, it gains 3 more wood.
    pre_forest = state.board.action_spaces["forest"].accumulated
    pre_clay_pit = state.board.action_spaces["clay_pit"].accumulated

    new_state = _resolve_preparation(state)

    new_forest = new_state.board.action_spaces["forest"].accumulated
    new_clay_pit = new_state.board.action_spaces["clay_pit"].accumulated
    assert new_forest.wood == pre_forest.wood + 3
    assert new_clay_pit.clay == pre_clay_pit.clay + 1


def test_preparation_increments_round_number():
    state = setup(seed=0)
    state = with_phase(state, Phase.PREPARATION)
    new_state = _resolve_preparation(state)
    assert new_state.round_number == state.round_number + 1


def test_preparation_resets_current_player_to_starting_player():
    state = setup(seed=0)
    state = with_current_player(state, 1 - state.starting_player)
    state = with_phase(state, Phase.PREPARATION)
    new_state = _resolve_preparation(state)
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
    for space_state in state.board.action_spaces.values():
        assert space_state.workers == (0, 0)
    # Trace contains at least some actions.
    assert len(trace) > 0


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
