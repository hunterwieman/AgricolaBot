"""Tests for Autumn Mother (occupation, C92).

Card text (verbatim): "Immediately before each harvest, if you have room in your
house, you can take a "Family Growth" action for 3 food."

An optional trigger on harvest window #1 ``immediately_before_harvest``: firing
pays 3 food — directly when on hand, else via a raise-only ``PendingFoodPayment``
(the Ox Goad pattern; the anytime conversions raise the shortfall) — and pushes
the card-granted family-growth primitive
(``PendingFamilyGrowth(place_on_space=False)``, Group A1 ruling 2026-07-03: the
newborn occupies NO action space). Eligibility gates on the printed room
condition (people_total < 5 and a free room) AND the 3 food being payable with
liquidation, so a fired trigger is never a dead end. Declining is the window
frame's ``Proceed``.

These tests drive REAL harvests through the walk (``_advance_until_decision`` +
``step``), per the harvest-window test convention.
"""
from __future__ import annotations

import dataclasses

import agricola.cards.autumn_mother  # noqa: F401  (register the card)

from agricola.actions import (
    CommitFamilyGrowth,
    CommitFoodPayment,
    FireTrigger,
    Proceed,
    Stop,
)
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import FOOD_PAYMENT_RESUMES, OCCUPATIONS
from agricola.cards.triggers import TRIGGERS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingFamilyGrowth,
    PendingFoodPayment,
    PendingHarvestFeed,
    PendingHarvestWindow,
)
from agricola.replace import fast_replace
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_grid, with_phase, with_resources

CARD_ID = "autumn_mother"
WINDOW_ID = "immediately_before_harvest"


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {CARD_ID})


def _harvest_state(*, owner=0, food=10, extra_room=True, give_occ=True):
    """A HARVEST_FIELD-phase state, P0 the starting player. Setup gives each
    player 2 people in 2 rooms — the room gate FAILS by default — so
    ``extra_room`` adds a third ROOM at (0, 0). Both players get ``food`` so
    feeding is painless (the owner's growth changes their own bill only)."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = fast_replace(state, starting_player=0)
    if give_occ:
        state = _own(state, owner)
    if extra_room:
        state = with_grid(state, owner, {(0, 0): Cell(cell_type=CellType.ROOM)})
    for idx in (0, 1):
        state = with_resources(state, idx, food=food)
    return state


def _walk_to_window(state, window_id=WINDOW_ID, player_idx=0):
    """Advance until the given player's window frame is on top, stepping the
    first legal action everywhere else. Returns (state, frame_seen,
    fire_seen_during_feeding); frame_seen is False if the harvest completed
    without the frame ever surfacing."""
    fire_in_feeding = False
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestFeed):
            if any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(state)):
                fire_in_feeding = True
        if (isinstance(top, PendingHarvestWindow)
                and top.window_id == window_id and top.player_idx == player_idx):
            return state, True, fire_in_feeding
        acts = legal_actions(state)
        # Never let the generic walker fire OUR trigger by accident.
        picked = next((a for a in acts
                       if not (isinstance(a, FireTrigger) and a.card_id == CARD_ID)),
                      acts[0])
        state = step(state, picked)
    return state, False, fire_in_feeding


def _finish_harvest(state):
    """Drive the rest of the harvest, declining any further Autumn Mother offers."""
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        acts = legal_actions(state)
        picked = next((a for a in acts
                       if not (isinstance(a, FireTrigger) and a.card_id == CARD_ID)),
                      acts[0])
        state = step(state, picked)
    return state


# --- Registration -----------------------------------------------------------

def test_registered_as_occupation_window_trigger_and_food_resume():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in HARVEST_WINDOW_CARDS.get(WINDOW_ID, set())
    assert any(e.card_id == CARD_ID for e in TRIGGERS.get(WINDOW_ID, ()))
    # The 3-food cost's shortfall continuation (the Ox Goad pattern).
    assert CARD_ID in FOOD_PAYMENT_RESUMES


def test_on_play_is_a_noop():
    """No on-play clause — the effect is purely the recurring window trigger."""
    state = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(state, 0) == state


# --- The growth, end to end (food on hand) ----------------------------------

def test_growth_fires_immediately_before_harvest():
    state = _harvest_state(food=10)
    before_workers = tuple(sp.workers for sp in state.board.action_spaces)

    state, seen, _ = _walk_to_window(state)
    assert seen
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == WINDOW_ID and top.player_idx == 0
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) in acts and Proceed() in acts

    # Fire: 3 food debited immediately (food on hand), the growth frame pushed.
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.players[0].resources.food == 7
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFamilyGrowth)
    assert top.place_on_space is False
    assert top.initiated_by_id == f"card:{CARD_ID}"
    assert top.player_idx == 0

    # The growth is the only action; the newborn lands on NO action space.
    assert legal_actions(state) == [CommitFamilyGrowth()]
    state = step(state, CommitFamilyGrowth())
    assert state.players[0].people_total == 3
    assert state.players[0].newborns == 1
    assert tuple(sp.workers for sp in state.board.action_spaces) == before_workers

    # After-phase Stop pops back to the window host; once per window: only
    # Proceed remains.
    state = step(state, Stop())
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow) and top.window_id == WINDOW_ID
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())

    # The harvest completes; the newborn was fed at THIS harvest's FEED:
    # 10 - 3 (cost) - 5 (2 adults x2 + newborn x1) = 2. The opponent is untouched.
    state = _finish_harvest(state)
    assert state.phase == Phase.PREPARATION
    assert state.players[0].resources.food == 2
    assert state.players[0].people_total == 3
    assert state.players[1].people_total == 2
    assert state.players[1].resources.food == 6      # 10 - 4, no newborn


# --- The food-raise path (food short, crops liquidatable) --------------------

def test_food_raise_path_via_pending_food_payment():
    state = _harvest_state(food=0)
    state = with_resources(state, 0, food=0, grain=3)

    state, seen, _ = _walk_to_window(state)
    assert seen                                       # liquidatable -> offered
    state = step(state, FireTrigger(card_id=CARD_ID))

    # Short on food: the raise-only frame is out, resume wired to this card.
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 3 and top.resume_kind == CARD_ID

    # The only full-payment bundle is 3 grain (1:1).
    acts = legal_actions(state)
    assert acts == [CommitFoodPayment(grain=3, veg=0, sheep=0, boar=0, cattle=0)]
    state = step(state, acts[0])

    # Raised 3, debited 3, growth granted.
    assert state.players[0].resources.food == 0
    assert state.players[0].resources.grain == 0
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFamilyGrowth) and top.place_on_space is False
    state = step(state, CommitFamilyGrowth())
    assert state.players[0].people_total == 3
    assert state.players[0].newborns == 1


# --- Eligibility boundaries --------------------------------------------------

def test_not_offered_without_a_free_room():
    """Setup's 2 people in 2 rooms: 'room in your house' fails -> never offered."""
    state = _harvest_state(food=10, extra_room=False)
    state, seen, _ = _walk_to_window(state)
    assert not seen
    assert state.players[0].people_total == 2


def test_not_offered_at_the_family_cap():
    """5 people with free rooms: the 5-cap is a game rule the card doesn't waive."""
    state = _harvest_state(food=20)
    state = with_grid(state, 0, {(0, c): Cell(cell_type=CellType.ROOM)
                                 for c in range(5)})   # 7 rooms total
    state = _edit_player(state, 0, people_total=5)
    state, seen, _ = _walk_to_window(state)
    assert not seen


def test_not_offered_when_three_food_unpayable():
    """2 food, nothing liquidatable: the cost gate (never a dead-end offer)."""
    state = _harvest_state(food=0)
    state = with_resources(state, 0, food=2)
    state, seen, _ = _walk_to_window(state)
    assert not seen


def test_not_offered_to_a_non_owner():
    state = _harvest_state(food=10, give_occ=False)
    state, seen, _ = _walk_to_window(state)
    assert not seen


# --- Decline + wrong-window negatives ----------------------------------------

def test_decline_via_proceed_costs_nothing_and_never_surfaces_in_feeding():
    state = _harvest_state(food=10)
    state, seen, _ = _walk_to_window(state)
    assert seen
    state = step(state, Proceed())                    # decline

    fire_in_feeding = False
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestFeed):
            if any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(state)):
                fire_in_feeding = True
        state = step(state, legal_actions(state)[0])

    assert not fire_in_feeding
    assert state.players[0].people_total == 2         # no growth
    assert state.players[0].resources.food == 6       # 10 - 4, no 3-food debit
