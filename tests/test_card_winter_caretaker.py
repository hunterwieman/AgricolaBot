"""Tests for Winter Caretaker (occupation, C113).

Card text (verbatim): "When you play this card, you immediately get 1 grain. At
the end of each harvest, you can buy exactly 1 vegetable for 2 food."

Two effects:
1. On play: immediately +1 grain.
2. A recurring, optional, once-per-harvest buy surfaced as an optional TRIGGER on
   harvest window #16 ``end_of_harvest`` (the last in-harvest moment, after
   breeding; ruling 2026-07-03). Firing it spends 2 food and grants 1 vegetable;
   declining is the window frame's ``Proceed``. The vegetable is a normal good, so
   there is NO scoring term.

Mis-timing history: the buy previously rode the ``HARVEST_CONVERSIONS`` seam,
surfacing during the FEED sub-phase. It has been migrated to window #16 per the
printed "at the end of each harvest" and the 2026-07-03 post-breeding-timeline
ruling. These tests drive the REAL harvest walk (``_advance_harvest`` via
``_advance_until_decision`` + step) and assert the buy surfaces at the
``end_of_harvest`` window (after breeding), never during feeding.
"""
from __future__ import annotations

import dataclasses

import agricola.cards.winter_caretaker  # noqa: F401  (register the card)

from agricola.actions import FireTrigger, Proceed
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestFeed, PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.scoring import SCORING_TERMS
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.triggers import TRIGGERS
from agricola.cards.specs import OCCUPATIONS
from agricola.setup import setup

from tests.factories import with_phase, with_resources

CARD_ID = "winter_caretaker"


# --- Helpers ----------------------------------------------------------------

def _give_occupation(state, player_idx):
    p = state.players[player_idx]
    p = dataclasses.replace(p, occupations=p.occupations | {CARD_ID})
    return dataclasses.replace(
        state,
        players=tuple(p if i == player_idx else state.players[i] for i in range(2)),
    )


def _harvest_state(*, owner_food=10, give_occ=True):
    """A HARVEST_FIELD-phase state. P0 owns Winter Caretaker (unless give_occ is
    False) and holds owner_food food; P1 is food-rich so its feeding is trivial.
    P0 needs 4 food (2 adults) — owner_food governs whether the buy is affordable
    on top of feeding."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    if give_occ:
        state = _give_occupation(state, 0)
    state = with_resources(state, 0, food=owner_food)
    state = with_resources(state, 1, food=99)
    return state


def _walk_to_end_of_harvest(state):
    """Drive the harvest walk until P0's end_of_harvest window frame is on top,
    stepping the first legal action at every other decision. Returns
    (state, feeding_ever_offered_the_buy)."""
    saw_buy_in_feeding = False
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestFeed):
            if any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(state)):
                saw_buy_in_feeding = True
        if (isinstance(top, PendingHarvestWindow)
                and top.window_id == "end_of_harvest"
                and top.player_idx == 0):
            return state, saw_buy_in_feeding
        state = step(state, legal_actions(state)[0])
    return state, saw_buy_in_feeding


# --- Registration -----------------------------------------------------------

def test_registered_as_occupation_and_window_trigger():
    assert CARD_ID in OCCUPATIONS
    # Migrated off HARVEST_CONVERSIONS onto the end_of_harvest window.
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("end_of_harvest", set())
    assert any(e.card_id == CARD_ID for e in TRIGGERS.get("end_of_harvest", ()))


def test_no_longer_on_harvest_conversions():
    from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
    assert CARD_ID not in HARVEST_CONVERSIONS


def test_no_scoring_term():
    """The vegetable is a normal good — no banked points, no scoring term."""
    assert not any(card_id == CARD_ID for card_id, _ in SCORING_TERMS)


# --- On-play: +1 grain ------------------------------------------------------

def test_on_play_grants_one_grain():
    state = setup(seed=0)
    grain0 = state.players[0].resources.grain

    on_play = OCCUPATIONS[CARD_ID].on_play
    new_state = on_play(state, 0)

    assert new_state.players[0].resources.grain == grain0 + 1
    # No other resource moved, opponent untouched.
    assert new_state.players[1].resources == state.players[1].resources
    assert (
        dataclasses.replace(new_state.players[0].resources, grain=grain0)
        == state.players[0].resources
    )


# --- The buy surfaces at end_of_harvest (not feeding) -----------------------

def test_buy_surfaces_at_end_of_harvest_not_feeding():
    """The buy is a FireTrigger at the end_of_harvest window (after breeding),
    and never appears during feeding."""
    state, saw_buy_in_feeding = _walk_to_end_of_harvest(_harvest_state(owner_food=10))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "end_of_harvest"
    assert top.player_idx == 0
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)
    assert Proceed() in legal_actions(state)
    assert not saw_buy_in_feeding


def test_buy_spends_two_food_and_grants_one_vegetable():
    state, _ = _walk_to_end_of_harvest(_harvest_state(owner_food=10))
    food0 = state.players[0].resources.food
    veg0 = state.players[0].resources.veg
    state = step(state, FireTrigger(card_id=CARD_ID))

    # 2 food spent, no food produced; one vegetable gained.
    assert state.players[0].resources.food == food0 - 2
    assert state.players[0].resources.veg == veg0 + 1


def test_buy_is_once_per_harvest():
    """Once-per-window: after firing, only Proceed remains for this window."""
    state, _ = _walk_to_end_of_harvest(_harvest_state(owner_food=10))
    veg0 = state.players[0].resources.veg
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert legal_actions(state) == [Proceed()]
    assert state.players[0].resources.veg == veg0 + 1


def test_buy_is_optional_declinable():
    """Declining is the window frame's Proceed; nothing is spent or gained."""
    state, _ = _walk_to_end_of_harvest(_harvest_state(owner_food=10))
    veg0 = state.players[0].resources.veg
    food0 = state.players[0].resources.food
    assert Proceed() in legal_actions(state)
    state = step(state, Proceed())
    assert state.players[0].resources.veg == veg0
    assert state.players[0].resources.food == food0


# --- Eligibility boundaries -------------------------------------------------

def test_not_offered_to_non_owner_seat():
    """The trigger is global; only the occupation owner is offered the buy.

    Drive the whole harvest and assert P0's end_of_harvest frame offers the buy
    while P1 never gets an end_of_harvest frame at all (owner-gated)."""
    state = _harvest_state(owner_food=10)
    state = with_resources(state, 1, food=10)  # P1 food-rich too

    saw_p0_buy = False
    saw_p1_window = False
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestWindow) and top.window_id == "end_of_harvest":
            buys = [a for a in legal_actions(state)
                    if isinstance(a, FireTrigger) and a.card_id == CARD_ID]
            if top.player_idx == 0 and buys:
                saw_p0_buy = True
            if top.player_idx == 1:
                saw_p1_window = True
        state = step(state, legal_actions(state)[0])

    assert saw_p0_buy         # the owner IS offered the buy
    assert not saw_p1_window  # the non-owner gets no end_of_harvest frame


def test_not_offered_when_unowned():
    """No seat owns Winter Caretaker → no end_of_harvest frame ever appears."""
    state = _harvest_state(owner_food=10, give_occ=False)
    saw_window = False
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestWindow) and top.window_id == "end_of_harvest":
            saw_window = True
        state = step(state, legal_actions(state)[0])
    assert not saw_window


def test_not_offered_when_food_short():
    """Needs 2 food to buy; with 1 food (and feeding need 4) it's unaffordable,
    so eligibility fails and no end_of_harvest frame is pushed for P0."""
    state = _harvest_state(owner_food=1)
    saw_window = False
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestWindow) and top.window_id == "end_of_harvest":
            saw_window = True
        state = step(state, legal_actions(state)[0])
    assert not saw_window


# --- Eligibility unit check -------------------------------------------------

def test_eligibility_gates_on_ownership_and_food():
    from agricola.cards.winter_caretaker import _eligible
    state = _harvest_state(owner_food=10)
    assert _eligible(state, 0, frozenset()) is True
    # Non-owner seat.
    assert _eligible(state, 1, frozenset()) is False
    # Owner with only 1 food cannot afford it.
    state1 = with_resources(state, 0, food=1)
    assert _eligible(state1, 0, frozenset()) is False
