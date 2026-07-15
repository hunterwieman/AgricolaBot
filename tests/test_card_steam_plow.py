"""Tests for Steam Plow (minor improvement, D18; Dulcinaria Expansion).

Card text (verbatim): "Immediately after each returning home phase, you can pay
2 wood and 1 food to use the "Farmland" action space without placing a person."

Cost 1 Wood + 1 Food, 1 VP. An optional trigger on the round-end ladder's
``after_returning_home`` rung (ruling 49): pay 2 wood + 1 food (the food via the
shared food-payment path — the Ox Goad pattern) to plow 1 field (Farmland's
effect). Tests drive the real round-end walk.
"""
from __future__ import annotations

import agricola.cards.steam_plow  # noqa: F401  (registers the card)

import pytest

from agricola.actions import CommitFoodPayment, CommitPlow, FireTrigger, Proceed, Stop
from agricola.cards.specs import FOOD_PAYMENT_RESUMES, MINORS
from agricola.cards.triggers import CARDS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingFoodPayment, PendingHarvestWindow, PendingPlow,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_grid, with_resources

CARD_ID = "steam_plow"
WINDOW_ID = "after_returning_home"


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    return _edit_player(state, idx, minor_improvements=p.minor_improvements | {card_id})


def _count_fields(state, idx):
    grid = state.players[idx].farmyard.grid
    return sum(1 for row in grid for cell in row if cell.cell_type == CellType.FIELD)


def _drained_work_state(round_number=1):
    state = setup(seed=0)
    state = fast_replace(
        state, phase=Phase.WORK, round_number=round_number, starting_player=0)
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    return state


def _sp_state(*, owned=True, plowable=True, **res):
    state = _drained_work_state()
    if owned:
        state = _own_minor(state, 0, CARD_ID)
    state = with_resources(state, 0, **res)
    if not plowable:
        state = with_grid(state, 0, {
            (r, c): Cell(cell_type=CellType.STABLE)
            for r in range(3) for c in range(5)
            if state.players[0].farmyard.grid[r][c].cell_type == CellType.EMPTY})
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
    assert spec.cost == Cost(resources=Resources(wood=1, food=1))
    assert spec.vps == 1
    entry = CARDS[CARD_ID]
    assert entry.event == WINDOW_ID
    assert entry.mandatory is False
    assert CARD_ID in FOOD_PAYMENT_RESUMES


# --- The fire: pay 2 wood + 1 food, plow (food on hand) ---------------------

def test_pays_two_wood_one_food_and_plows():
    state = _walk_to_window(_sp_state(wood=2, food=1))
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)
    assert Proceed() in legal_actions(state)

    before = _count_fields(state, 0)
    state = step(state, FireTrigger(card_id=CARD_ID))
    # Food on hand: 2 wood + 1 food debited, plow frame pushed directly.
    assert state.players[0].resources.wood == 0
    assert state.players[0].resources.food == 0
    top = state.pending_stack[-1]
    assert isinstance(top, PendingPlow)
    assert top.initiated_by_id == f"card:{CARD_ID}"

    plows = [a for a in legal_actions(state) if isinstance(a, CommitPlow)]
    assert plows
    state = step(state, plows[0])
    assert _count_fields(state, 0) == before + 1

    state = step(state, Stop())
    assert isinstance(state.pending_stack[-1], PendingHarvestWindow)
    assert legal_actions(state) == [Proceed()]


# --- The food-raise path (food short, grain liquidatable) -------------------

def test_food_raise_path_via_pending_food_payment():
    state = _walk_to_window(_sp_state(wood=2, food=0, grain=1))
    state = step(state, FireTrigger(card_id=CARD_ID))

    # 2 wood already debited; short on food -> raise-only frame wired to us.
    assert state.players[0].resources.wood == 0
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 1 and top.resume_kind == CARD_ID

    pays = [a for a in legal_actions(state) if isinstance(a, CommitFoodPayment)]
    assert CommitFoodPayment(grain=1, veg=0, sheep=0, boar=0, cattle=0) in pays
    state = step(state, CommitFoodPayment(grain=1, veg=0, sheep=0, boar=0, cattle=0))

    # Raised 1, debited 1; the plow is now granted.
    assert state.players[0].resources.food == 0
    assert state.players[0].resources.grain == 0
    top = state.pending_stack[-1]
    assert isinstance(top, PendingPlow)
    before = _count_fields(state, 0)
    plows = [a for a in legal_actions(state) if isinstance(a, CommitPlow)]
    state = step(state, plows[0])
    assert _count_fields(state, 0) == before + 1


# --- Eligibility boundaries --------------------------------------------------

def test_not_offered_without_two_wood():
    state = _sp_state(wood=1, food=5)
    _no_window(state)


def test_not_offered_when_food_unpayable():
    """2 wood but 0 food and nothing liquidatable -> never a dead-end offer."""
    state = _sp_state(wood=2, food=0)
    _no_window(state)


def test_not_offered_without_a_plowable_cell():
    state = _sp_state(wood=2, food=1, plowable=False)
    _no_window(state)


def test_declinable_costs_nothing():
    state = _walk_to_window(_sp_state(wood=2, food=1))
    before = _count_fields(state, 0)
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.players[0].resources.wood == 2
    assert state.players[0].resources.food == 1
    assert _count_fields(state, 0) == before


def test_unowned_never_hosts():
    state = _sp_state(owned=False, wood=2, food=1)
    _no_window(state)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
