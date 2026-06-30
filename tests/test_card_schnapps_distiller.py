"""Tests for Schnapps Distiller (occupation, C109).

Card text: "In the feeding phase of each harvest, you can use this card to turn
exactly 1 vegetable into 5 food."

The conversion is surfaced as an optional once-per-harvest CommitHarvestConversion
during HARVEST_FEED (input_cost=1 veg, food_out=5). These tests drive a REAL
HARVEST_FEED resolution (via _initiate_harvest_feed + step), not a poked frame.
"""
from __future__ import annotations

import agricola.cards.schnapps_distiller  # noqa: F401  (register the card)

import dataclasses

from agricola.actions import CommitConvert, CommitHarvestConversion, Stop
from agricola.constants import Phase
from agricola.engine import _initiate_harvest_feed, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestFeed
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.specs import OCCUPATIONS
from agricola.setup import setup

from tests.factories import with_resources, with_phase

CARD_ID = "schnapps_distiller"


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


def _convert_actions(state):
    return [
        a for a in legal_actions(state)
        if isinstance(a, CommitHarvestConversion) and a.conversion_id == CARD_ID
    ]


def _owner_state(*, owner_food=10, owner_veg=1, give_occ=True):
    """P0 owns Schnapps Distiller and has `owner_veg` vegetables.

    P1 is given ample food so its feed frame resolves trivially. P0's people
    default (2 adults -> need 4 food); owner_food governs whether feeding leaves
    P0 able to decline / fire the conversion.
    """
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    if give_occ:
        state = _give_occupation(state, 0)
    state = with_resources(state, 0, food=owner_food, veg=owner_veg)
    state = with_resources(state, 1, food=99)
    return state


# --- Registration -----------------------------------------------------------

def test_registered_as_conversion_and_occupation():
    assert CARD_ID in HARVEST_CONVERSIONS
    spec = HARVEST_CONVERSIONS[CARD_ID]
    # Spend exactly 1 vegetable, produce 5 food, no points / side effect.
    assert spec.input_cost.veg == 1
    assert spec.food_out == 5
    assert spec.side_effect_fn is None
    # Registered as a (no-op on-play) occupation, played via Lessons.
    assert CARD_ID in OCCUPATIONS


def test_on_play_is_noop():
    state = _owner_state()
    spec = OCCUPATIONS[CARD_ID]
    assert spec.on_play(state, 0) is state


# --- The conversion fires ---------------------------------------------------

def test_convert_spends_one_veg_and_makes_five_food():
    state = _enter_feed(_owner_state(owner_food=10, owner_veg=2))
    assert _convert_actions(state) == [CommitHarvestConversion(conversion_id=CARD_ID)]

    food0 = state.players[0].resources.food
    veg0 = state.players[0].resources.veg
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))

    # 1 veg spent, 5 food produced.
    assert state.players[0].resources.veg == veg0 - 1
    assert state.players[0].resources.food == food0 + 5
    assert CARD_ID in state.players[0].harvest_conversions_used


def test_convert_is_once_per_harvest():
    state = _enter_feed(_owner_state(owner_food=10, owner_veg=3))
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))
    # After one use this harvest, it is no longer offered (even with veg left).
    assert _convert_actions(state) == []
    assert state.players[0].resources.veg == 2  # only one veg consumed


def test_convert_is_optional_declinable():
    """Declining is implicit: commit the feed without firing the conversion."""
    state = _enter_feed(_owner_state(owner_food=10, owner_veg=1))
    # P0 has 10 food, need 4 -> food_owed 0. CommitConvert resolves the feed
    # without ever firing the conversion; the veg stays.
    assert any(isinstance(a, CommitConvert) for a in legal_actions(state))
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    assert state.players[0].resources.veg == 1
    assert CARD_ID not in state.players[0].harvest_conversions_used


# --- Eligibility boundaries -------------------------------------------------

def test_not_offered_without_occupation():
    state = _enter_feed(_owner_state(owner_food=10, owner_veg=1, give_occ=False))
    assert _convert_actions(state) == []


def test_not_offered_without_vegetable():
    state = _enter_feed(_owner_state(owner_food=10, owner_veg=0))
    assert _convert_actions(state) == []


def test_not_offered_to_non_owner():
    """The conversion is global; the non-owner must NOT be offered it.

    P0 owns the occupation, P1 does not (but has a vegetable). Drive both feed
    frames and assert only P0's frame offers the conversion.
    """
    state = _owner_state(owner_food=10, owner_veg=1)
    state = with_resources(state, 1, food=10, veg=1)  # P1 has veg but no occ
    state = _enter_feed(state)

    saw_p0 = False
    saw_p1 = False
    while state.pending_stack and isinstance(
        state.pending_stack[-1], PendingHarvestFeed
    ):
        top = state.pending_stack[-1]
        convs = [
            a for a in legal_actions(state)
            if isinstance(a, CommitHarvestConversion) and a.conversion_id == CARD_ID
        ]
        if top.player_idx == 0 and convs:
            saw_p0 = True
        if top.player_idx == 1 and convs:
            saw_p1 = True
        actions = legal_actions(state)
        nxt = next(
            (a for a in actions if isinstance(a, CommitConvert)),
            next((a for a in actions if isinstance(a, Stop)), None),
        )
        assert nxt is not None
        state = step(state, nxt)

    assert saw_p0       # the owner IS offered the conversion
    assert not saw_p1   # the non-owner is NOT
