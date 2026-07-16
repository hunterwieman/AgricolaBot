"""Tests for Stork's Nest (minor improvement, D10; Consul Dirigens Expansion).

Card text (verbatim): "In the returning home phase of each round, if you have
more rooms than people, you can pay 1 food to take a "Family Growth" action."
Clarification (verbatim): "To clarify, this can only be used once per round."

Cost 1 Reed, prereq "5 Occupations", no VPs. An optional trigger on the
round-end ladder's ``returning_home`` window (ruling 49), gated on a free room
(more rooms than people) + the family cap + the 1 food being payable: pays 1
food (the shared food-payment path) and pushes the card-granted
``PendingFamilyGrowth(place_on_space=False)``. Tests drive the real round-end
walk (the Autumn Mother / Master Renovator idioms).
"""
from __future__ import annotations

import agricola.cards.storks_nest  # noqa: F401  (registers the card)

import pytest

from agricola.actions import (
    CommitFamilyGrowth, CommitFoodPayment, FireTrigger, Proceed, Stop,
)
from agricola.cards.specs import FOOD_PAYMENT_RESUMES, MINORS
from agricola.cards.triggers import CARDS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingFamilyGrowth, PendingFoodPayment, PendingHarvestWindow,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_grid, with_resources

CARD_ID = "storks_nest"
WINDOW_ID = "returning_home"


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    return _edit_player(state, idx, minor_improvements=p.minor_improvements | {card_id})


def _drained_work_state(round_number=1):
    state = setup(seed=0)
    state = fast_replace(
        state, phase=Phase.WORK, round_number=round_number, starting_player=0)
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    return state


def _sn_state(*, owned=True, extra_rooms=1, people_total=None, **res):
    """A drained WORK state; P0 optionally owns Stork's Nest. Setup gives 2
    people in 2 rooms (people == rooms, so the gate FAILS by default);
    ``extra_rooms`` adds ROOM cells at (0,0)/(0,1) to create free rooms."""
    state = _drained_work_state()
    if owned:
        state = _own_minor(state, 0, CARD_ID)
    if extra_rooms:
        state = with_grid(state, 0, {
            (0, c): Cell(cell_type=CellType.ROOM) for c in range(extra_rooms)})
    if people_total is not None:
        state = _edit_player(state, 0, people_total=people_total,
                             workers_in_supply=5 - people_total)   # keep the 5-meeple invariant
    state = with_resources(state, 0, **res)
    return state


def _walk_to_window(state):
    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow), (
        f"no {WINDOW_ID} window (top={top!r}, phase={state.phase})")
    assert top.window_id == WINDOW_ID and top.player_idx == 0
    return state


def _no_window(state):
    state = _advance_until_decision(state)
    assert not any(
        isinstance(f, PendingHarvestWindow) and f.window_id == WINDOW_ID
        for f in state.pending_stack)
    return state


# --- Registration -----------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(reed=1))
    assert spec.min_occupations == 5
    entry = CARDS[CARD_ID]
    assert entry.event == WINDOW_ID
    assert entry.mandatory is False
    assert CARD_ID in FOOD_PAYMENT_RESUMES


# --- The fire: pay 1 food, family growth (food on hand) ---------------------

def test_pays_one_food_and_grows_without_occupying_a_space():
    state = _walk_to_window(_sn_state(extra_rooms=1, food=3))
    before_workers = tuple(sp.workers for sp in state.board.action_spaces)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)
    assert Proceed() in legal_actions(state)

    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.players[0].resources.food == 2        # 1 food debited
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFamilyGrowth)
    assert top.place_on_space is False
    assert top.initiated_by_id == f"card:{CARD_ID}"

    assert legal_actions(state) == [CommitFamilyGrowth()]
    state = step(state, CommitFamilyGrowth())
    assert state.players[0].people_total == 3
    assert state.players[0].newborns == 1
    # The newborn occupies NO action space.
    assert tuple(sp.workers for sp in state.board.action_spaces) == before_workers

    # Once per round: back at the window, only Proceed remains.
    state = step(state, Stop())
    assert isinstance(state.pending_stack[-1], PendingHarvestWindow)
    assert legal_actions(state) == [Proceed()]


# --- The food-raise path (food short, grain liquidatable) -------------------

def test_food_raise_path_via_pending_food_payment():
    state = _walk_to_window(_sn_state(extra_rooms=1, food=0, grain=1))
    state = step(state, FireTrigger(card_id=CARD_ID))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 1 and top.resume_kind == CARD_ID

    state = step(state, CommitFoodPayment(grain=1, veg=0, sheep=0, boar=0, cattle=0))
    assert state.players[0].resources.food == 0
    assert state.players[0].resources.grain == 0
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFamilyGrowth) and top.place_on_space is False
    state = step(state, CommitFamilyGrowth())
    assert state.players[0].people_total == 3
    assert state.players[0].newborns == 1


# --- Eligibility boundaries --------------------------------------------------

def test_not_offered_without_a_free_room():
    """2 people in 2 rooms (people == rooms): "more rooms than people" fails."""
    state = _sn_state(extra_rooms=0, food=3)
    _no_window(state)
    assert state.players[0].people_total == 2


def test_not_offered_at_the_family_cap():
    """5 people with free rooms: the 5-cap is a rule the card doesn't waive."""
    state = _sn_state(extra_rooms=4, people_total=5, food=3)   # 6 rooms, 5 people
    _no_window(state)


def test_not_offered_when_one_food_unpayable():
    state = _sn_state(extra_rooms=1, food=0)                   # room, but no food
    _no_window(state)


def test_declinable_costs_nothing():
    state = _walk_to_window(_sn_state(extra_rooms=1, food=3))
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.players[0].people_total == 2                 # no growth
    assert state.players[0].resources.food == 3               # no debit


def test_unowned_never_hosts():
    state = _sn_state(owned=False, extra_rooms=1, food=3)
    _no_window(state)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
