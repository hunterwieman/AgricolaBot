"""Tests for Winter Caretaker (occupation, C113).

Card text: "When you play this card, you immediately get 1 grain. At the end of
each harvest, you can buy exactly 1 vegetable for 2 food."

Two effects:
1. On play: immediately +1 grain.
2. A recurring, optional, once-per-harvest buy surfaced as a
   CommitHarvestConversion during HARVEST_FEED (input_cost = 2 food,
   food_out=0); firing it grants 1 vegetable via the side_effect_fn. The
   vegetable is a normal good, so there is NO scoring term.

These tests drive a REAL HARVEST_FEED resolution (via _initiate_harvest_feed +
step), not a poked frame, and verify the on-play grain grant directly.
"""
from __future__ import annotations

import dataclasses

import agricola.cards.winter_caretaker  # noqa: F401  (register the card)

from agricola.actions import CommitConvert, CommitHarvestConversion, Stop
from agricola.constants import Phase
from agricola.engine import _initiate_harvest_feed, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestFeed
from agricola.scoring import SCORING_TERMS
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.specs import OCCUPATIONS
from agricola.setup import setup

from tests.factories import with_resources, with_phase

CARD_ID = "winter_caretaker"


# --- Helpers ----------------------------------------------------------------

def _give_occupation(state, player_idx):
    p = state.players[player_idx]
    p = dataclasses.replace(p, occupations=p.occupations | {CARD_ID})
    return dataclasses.replace(
        state,
        players=tuple(p if i == player_idx else state.players[i] for i in range(2)),
    )


def _enter_feed(state):
    """Put `state` into HARVEST_FEED and push the per-player feed frames."""
    state = with_phase(state, Phase.HARVEST_FEED)
    return _initiate_harvest_feed(state)


def _buy_actions(state):
    return [
        a for a in legal_actions(state)
        if isinstance(a, CommitHarvestConversion) and a.conversion_id == CARD_ID
    ]


def _owner_state(*, owner_food=10, give_occ=True):
    """P0 owns Winter Caretaker (unless give_occ=False).

    P1 is given ample food so its feed frame resolves trivially. P0's people
    default (2 adults → need 4 food); owner_food governs whether the buy is
    affordable on top of feeding.
    """
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    if give_occ:
        state = _give_occupation(state, 0)
    state = with_resources(state, 0, food=owner_food)
    state = with_resources(state, 1, food=99)
    return state


# --- Registration -----------------------------------------------------------

def test_registered_as_occupation_and_conversion():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in HARVEST_CONVERSIONS
    spec = HARVEST_CONVERSIONS[CARD_ID]
    # The buy is a food-to-good: spend 2 food, produce none; the side effect
    # grants the vegetable.
    assert spec.input_cost.food == 2
    assert spec.food_out == 0
    assert spec.side_effect_fn is not None


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


# --- The buy fires and grants a vegetable -----------------------------------

def test_buy_spends_two_food_and_grants_one_vegetable():
    state = _enter_feed(_owner_state(owner_food=10))
    assert _buy_actions(state) == [CommitHarvestConversion(conversion_id=CARD_ID)]

    food0 = state.players[0].resources.food
    veg0 = state.players[0].resources.veg
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))

    # 2 food spent, no food produced; one vegetable gained.
    assert state.players[0].resources.food == food0 - 2
    assert state.players[0].resources.veg == veg0 + 1
    assert CARD_ID in state.players[0].harvest_conversions_used


def test_buy_is_once_per_harvest():
    state = _enter_feed(_owner_state(owner_food=10))
    veg0 = state.players[0].resources.veg
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))
    # After one buy this harvest, it is no longer offered ("buy EXACTLY 1").
    assert _buy_actions(state) == []
    assert state.players[0].resources.veg == veg0 + 1


def test_buy_is_optional_declinable():
    """Declining is implicit: commit the feed without firing the buy."""
    state = _enter_feed(_owner_state(owner_food=10))
    veg0 = state.players[0].resources.veg
    # P0 has 10 food, need 4 → food_owed 0. CommitConvert resolves the feed
    # without ever firing the buy.
    assert any(isinstance(a, CommitConvert) for a in legal_actions(state))
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    assert state.players[0].resources.veg == veg0


# --- Eligibility boundaries -------------------------------------------------

def test_not_offered_to_non_owner_seat():
    """The conversion is global; only the occupation owner is offered the buy.

    P0 owns the occupation; P1 does not. Drive the whole two-player feed and
    assert P0's frame offers the buy while P1's never does (owner-gated by
    is_owned_fn, not global).
    """
    state = _owner_state(owner_food=10)
    state = with_resources(state, 1, food=10)  # P1 food-rich too
    state = _enter_feed(state)

    saw_p0_buy = False
    saw_p1_buy = False
    while state.pending_stack and isinstance(
        state.pending_stack[-1], PendingHarvestFeed
    ):
        top = state.pending_stack[-1]
        buys = [
            a for a in legal_actions(state)
            if isinstance(a, CommitHarvestConversion) and a.conversion_id == CARD_ID
        ]
        if top.player_idx == 0 and buys:
            saw_p0_buy = True
        if top.player_idx == 1 and buys:
            saw_p1_buy = True
        actions = legal_actions(state)
        nxt = next(
            (a for a in actions if isinstance(a, CommitConvert)),
            next((a for a in actions if isinstance(a, Stop)), None),
        )
        assert nxt is not None
        state = step(state, nxt)

    assert saw_p0_buy       # the owner IS offered the buy
    assert not saw_p1_buy   # the non-owner is NOT


def test_not_offered_when_unowned():
    """No seat owns Winter Caretaker → the buy is never offered."""
    state = _enter_feed(_owner_state(owner_food=10, give_occ=False))
    assert _buy_actions(state) == []


def test_not_offered_when_food_short():
    """Needs 2 food to buy; with 1 food (and feeding need 4) it's unaffordable."""
    state = _enter_feed(_owner_state(owner_food=1))
    assert _buy_actions(state) == []


# --- Scoping across harvests ------------------------------------------------

def test_buy_available_again_next_harvest():
    """harvest_conversions_used resets each harvest, so a fresh buy is offered."""
    state = _enter_feed(_owner_state(owner_food=10))
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))
    assert _buy_actions(state) == []

    # Simulate the next harvest: harvest_conversions_used reset to empty.
    p = state.players[0]
    p = dataclasses.replace(p, harvest_conversions_used=frozenset())
    state = dataclasses.replace(state, players=(p, state.players[1]))
    # Re-enter a fresh feed (P0 still food-rich enough for the buy).
    state = with_resources(state, 0, food=10)
    state = _enter_feed(state)
    assert _buy_actions(state) == [CommitHarvestConversion(conversion_id=CARD_ID)]
