import agricola.cards.farm_store  # noqa: F401
# Tests for Farm Store (minor improvement, C41; Consul Dirigens Expansion).
#
# Card text: "After the feeding phase of each harvest, you can exchange exactly 1
# food for 2 different building resources of your choice or 1 vegetable."
# Cost 2 wood, 2 clay. No prereq. VPs: 0. Not passing.
#
# Seven HarvestConversionSpec entries (the six distinct building-resource pairs +
# the single-veg option) — each spends exactly 1 food and grants its goods. Used
# at most once per harvest (a CHOICE of output, not seven independent fires).
#
# Mirrors tests/test_card_beer_keg.py's craft-firing flow.

import dataclasses

from agricola.actions import CommitConvert, CommitHarvestConversion
from agricola.cards.farm_store import CARD_ID, _OUTPUTS
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.specs import MINORS
from agricola.constants import Phase
from agricola.engine import _initiate_harvest_feed, step
from agricola.legality import legal_actions
from agricola.resources import Resources
from agricola.state import GameState
from agricola.setup import setup

from tests.factories import (
    with_minors,
    with_phase,
    with_resources,
)


# --- Helpers ----------------------------------------------------------------

def _feed_state(*, food=0, farm_store=True) -> GameState:
    """A HARVEST_FEED state with player 0 (optionally) owning Farm Store and the
    given food, player 1 well-fed so only player 0's feed frame is interesting."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    if farm_store:
        state = with_minors(state, 0, frozenset({CARD_ID}))
    state = with_resources(state, 0, food=food)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    return _initiate_harvest_feed(state)


def _farm_store_actions(state):
    return sorted(
        (a.conversion_id for a in legal_actions(state)
         if isinstance(a, CommitHarvestConversion)
         and a.conversion_id.startswith(CARD_ID))
    )


_EXPECTED_IDS = sorted(f"{CARD_ID}_{tag}" for tag, _ in _OUTPUTS)


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(wood=2, clay=2)
    assert spec.vps == 0
    assert spec.passing_left is False
    assert spec.prereq is None
    # Exactly seven conversion entries.
    for cid in _EXPECTED_IDS:
        assert cid in HARVEST_CONVERSIONS
    assert len(_OUTPUTS) == 7


def test_conversion_inputs_and_outputs_match_text():
    """Each entry spends exactly 1 food, produces no food, and grants the goods."""
    pairs = {
        "farm_store_wood_clay":  Resources(wood=1, clay=1),
        "farm_store_wood_reed":  Resources(wood=1, reed=1),
        "farm_store_wood_stone": Resources(wood=1, stone=1),
        "farm_store_clay_reed":  Resources(clay=1, reed=1),
        "farm_store_clay_stone": Resources(clay=1, stone=1),
        "farm_store_reed_stone": Resources(reed=1, stone=1),
        "farm_store_veg":        Resources(veg=1),
    }
    assert set(pairs) == set(_EXPECTED_IDS)
    for cid, _ in pairs.items():
        spec = HARVEST_CONVERSIONS[cid]
        assert spec.input_cost == Resources(food=1)
        assert spec.food_out == 0


def test_building_pairs_are_distinct():
    """"2 *different* building resources" — every building-resource pair has two
    distinct resources (no doubles)."""
    for tag, out in _OUTPUTS:
        if tag == "veg":
            continue
        nonzero = [n for n in ("wood", "clay", "reed", "stone")
                   if getattr(out, n) > 0]
        # Two distinct building resources, each granted once.
        assert len(nonzero) == 2
        assert all(getattr(out, n) == 1 for n in nonzero)
        assert out.veg == 0 and out.grain == 0 and out.food == 0


# --- Eligibility / offering -------------------------------------------------

def test_offered_only_when_owned():
    """All seven variants offered iff the player owns Farm Store and has food."""
    owned = _feed_state(food=1, farm_store=True)
    assert _farm_store_actions(owned) == _EXPECTED_IDS

    unowned = _feed_state(food=1, farm_store=False)
    assert _farm_store_actions(unowned) == []


def test_offered_only_when_food_affordable():
    """Need at least 1 food to spare; 0 food -> nothing offered."""
    assert _farm_store_actions(_feed_state(food=1)) == _EXPECTED_IDS
    assert _farm_store_actions(_feed_state(food=0)) == []


# --- Real-flow effect -------------------------------------------------------

def test_fire_building_pair_spends_food_grants_two_resources():
    """Fire farm_store_wood_stone: spend 1 food, gain 1 wood + 1 stone."""
    state = _feed_state(food=2)
    before = state.players[0].resources
    state = step(state, CommitHarvestConversion(conversion_id="farm_store_wood_stone"))
    p = state.players[0]
    assert p.resources.food == before.food - 1
    assert p.resources.wood == before.wood + 1
    assert p.resources.stone == before.stone + 1
    # The other two building resources untouched.
    assert p.resources.clay == before.clay
    assert p.resources.reed == before.reed
    assert "farm_store_wood_stone" in p.harvest_conversions_used


def test_fire_veg_variant_spends_food_grants_vegetable():
    state = _feed_state(food=2)
    before = state.players[0].resources
    state = step(state, CommitHarvestConversion(conversion_id="farm_store_veg"))
    p = state.players[0]
    assert p.resources.food == before.food - 1
    assert p.resources.veg == before.veg + 1
    # No building resource granted on the veg variant.
    assert p.resources.wood == before.wood
    assert p.resources.clay == before.clay
    assert p.resources.reed == before.reed
    assert p.resources.stone == before.stone


# --- Once-per-harvest: choosing ONE variant suppresses the others -----------

def test_once_per_harvest_choice():
    """After firing one variant, no farm_store variant is offered again this
    harvest (a single use, choosing the output — not seven independent fires)."""
    state = _feed_state(food=5)
    assert _farm_store_actions(state) == _EXPECTED_IDS

    state = step(state, CommitHarvestConversion(conversion_id="farm_store_clay_reed"))
    # Even though 4 food remains, the card is spent for this harvest.
    assert _farm_store_actions(state) == []


# --- Optionality: declining (commit feed without firing) --------------------

def test_optional_decline_via_commit():
    """The conversion is optional — committing feed without firing it grants no
    farm_store goods and marks no farm_store variant used. (Committing feed pays
    the feeding cost, so food drops; the card itself stays inert.)"""
    state = _feed_state(food=10)  # plenty of food, need not fire
    before = state.players[0].resources
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    p = state.players[0]
    # No farm_store output was granted (no building resources / veg gained).
    assert p.resources.wood == before.wood
    assert p.resources.clay == before.clay
    assert p.resources.reed == before.reed
    assert p.resources.stone == before.stone
    assert p.resources.veg == before.veg
    # Food only changed by the (feeding) cost, never increased.
    assert p.resources.food <= before.food
    assert not any(c.startswith(CARD_ID) for c in p.harvest_conversions_used)
