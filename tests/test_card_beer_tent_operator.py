"""Tests for Beer Tent Operator (occupation, D133; Dulcinaria Expansion).

Card text: "In the feeding phase of each harvest, you can use this card to turn 1
wood plus 1 grain into 1 bonus point and 2 food."

One `HarvestConversionSpec` entry: spend 1 wood + 1 grain -> 2 food + 1 banked
bonus point, once per harvest. Points ride the CardStore and are read by the
end-game scoring term. Mirrors tests/test_card_beer_keg.py's craft-firing flow.
"""
from __future__ import annotations

import dataclasses

import agricola.cards.beer_tent_operator  # noqa: F401  (registers the card)

import pytest

from agricola.actions import CommitConvert, CommitHarvestConversion
from agricola.cards.beer_tent_operator import CARD_ID
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import Phase
from agricola.engine import _initiate_harvest_feed, step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import SCORING_TERMS
from agricola.setup import setup

from tests.factories import with_phase, with_resources


def _own_occ(state, idx):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {CARD_ID}) if i == idx
        else state.players[i] for i in range(2)))


def _feed_state(*, wood=0, grain=0, food=0, owned=True):
    state = dataclasses.replace(setup(seed=0), starting_player=0)
    if owned:
        state = _own_occ(state, 0)
    state = with_resources(state, 0, wood=wood, grain=grain, food=food)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    return _initiate_harvest_feed(state)


def _offered(state):
    return [a.conversion_id for a in legal_actions(state)
            if isinstance(a, CommitHarvestConversion) and a.conversion_id == CARD_ID]


def _score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


# --- Registration -----------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in HARVEST_CONVERSIONS
    spec = HARVEST_CONVERSIONS[CARD_ID]
    assert spec.input_cost == Resources(wood=1, grain=1)
    assert spec.food_out == 2
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


# --- Offering / eligibility -------------------------------------------------

def test_offered_when_owned_and_affordable():
    assert _offered(_feed_state(wood=1, grain=1)) == [CARD_ID]


def test_not_offered_when_unowned():
    assert _offered(_feed_state(wood=1, grain=1, owned=False)) == []


def test_not_offered_without_both_inputs():
    assert _offered(_feed_state(wood=1, grain=0)) == []   # no grain
    assert _offered(_feed_state(wood=0, grain=1)) == []   # no wood


# --- Real-flow effect -------------------------------------------------------

def test_fire_spends_inputs_adds_food_banks_point():
    state = _feed_state(wood=1, grain=1, food=0)
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))
    p = state.players[0]
    assert p.resources.wood == 0
    assert p.resources.grain == 0
    assert p.resources.food == 2                 # +2 food
    assert p.card_state.get(CARD_ID, 0) == 1     # 1 banked bonus point
    assert CARD_ID in p.harvest_conversions_used


def test_once_per_harvest():
    state = _feed_state(wood=2, grain=2, food=0)
    assert _offered(state) == [CARD_ID]
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))
    # A second use is not offered even though wood+grain remain.
    assert _offered(state) == []


def test_optional_decline_via_commit():
    state = _feed_state(wood=1, grain=1, food=10)   # plenty of food, need not fire
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    p = state.players[0]
    assert p.resources.wood == 1 and p.resources.grain == 1
    assert p.card_state.get(CARD_ID, 0) == 0
    assert CARD_ID not in p.harvest_conversions_used


# --- Scoring ----------------------------------------------------------------

def test_scoring_reads_bank():
    score_fn = _score_fn()
    state = setup(seed=0)
    assert score_fn(state, 0) == 0
    p = dataclasses.replace(state.players[0],
                            card_state=state.players[0].card_state.set(CARD_ID, 3))
    state = dataclasses.replace(
        state, players=tuple(p if i == 0 else state.players[i] for i in range(2)))
    assert score_fn(state, 0) == 3
    assert score_fn(state, 1) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
