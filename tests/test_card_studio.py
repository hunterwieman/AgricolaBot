import agricola.cards.studio  # noqa: F401
# Tests for Studio (minor improvement, C55; Corbarius Expansion).
#
# Card text: "In the feeding phase of each harvest, you can use this card to turn
# exactly 1 wood/clay/stone into 2/2/3 food."
# Cost 1 clay + 1 reed. VPs: 1. No prereq.
#
# Three HarvestConversionSpec entries (studio_wood/clay/stone) — each turns 1 of
# that resource into 2/2/3 food. Used at most once per harvest (a CHOICE of which
# resource, not three independent fires). No banked points; the 1 vp is printed.
#
# Mirrors tests/test_card_beer_keg.py / test_harvest_feed.py's craft-firing flow.

import dataclasses

from agricola.actions import CommitConvert, CommitHarvestConversion
from agricola.cards.studio import CARD_ID
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.specs import MINORS, prereq_met
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

def _feed_state(*, wood=0, clay=0, reed=0, stone=0, food=0, studio=True) -> GameState:
    """A HARVEST_FEED state with player 0 owning Studio, given resources, and
    player 1 well-fed so only player 0's feed frame is interesting."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    if studio:
        state = with_minors(state, 0, frozenset({CARD_ID}))
    state = with_resources(state, 0, wood=wood, clay=clay, reed=reed, stone=stone, food=food)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    return _initiate_harvest_feed(state)


def _studio_actions(state):
    return sorted(
        (a.conversion_id for a in legal_actions(state)
         if isinstance(a, CommitHarvestConversion) and a.conversion_id.startswith(CARD_ID))
    )


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(clay=1, reed=1)
    assert spec.vps == 1
    assert spec.passing_left is False
    assert spec.prereq is None
    # Three conversion entries.
    for name in ("wood", "clay", "stone"):
        assert f"{CARD_ID}_{name}" in HARVEST_CONVERSIONS


def test_no_prereq():
    """Studio has no prerequisite — playable at any state (occupation-count
    bounds default to 0/None and no custom predicate)."""
    spec = MINORS[CARD_ID]
    state = setup(seed=0)
    assert prereq_met(spec, state, 0) is True


def test_conversion_outputs_match_text():
    """Each entry: spend exactly 1 of its resource, produce 2/2/3 food."""
    assert HARVEST_CONVERSIONS[f"{CARD_ID}_wood"].input_cost == Resources(wood=1)
    assert HARVEST_CONVERSIONS[f"{CARD_ID}_wood"].food_out == 2
    assert HARVEST_CONVERSIONS[f"{CARD_ID}_clay"].input_cost == Resources(clay=1)
    assert HARVEST_CONVERSIONS[f"{CARD_ID}_clay"].food_out == 2
    assert HARVEST_CONVERSIONS[f"{CARD_ID}_stone"].input_cost == Resources(stone=1)
    assert HARVEST_CONVERSIONS[f"{CARD_ID}_stone"].food_out == 3
    # No banked-point side effect.
    for name in ("wood", "clay", "stone"):
        assert HARVEST_CONVERSIONS[f"{CARD_ID}_{name}"].side_effect_fn is None


# --- Eligibility / offering -------------------------------------------------

def test_offered_only_when_owned():
    """Variants offered iff the player owns Studio."""
    owned = _feed_state(wood=1, clay=1, stone=1, studio=True)
    assert _studio_actions(owned) == ["studio_clay", "studio_stone", "studio_wood"]

    unowned = _feed_state(wood=1, clay=1, stone=1, studio=False)
    assert _studio_actions(unowned) == []


def test_offered_variants_gated_by_affordable_resource():
    """Only variants whose single-resource cost is affordable are offered."""
    # Only wood -> only studio_wood.
    assert _studio_actions(_feed_state(wood=1)) == ["studio_wood"]
    # Only stone -> only studio_stone.
    assert _studio_actions(_feed_state(stone=1)) == ["studio_stone"]
    # No building resources -> none affordable.
    assert _studio_actions(_feed_state()) == []
    # wood + clay -> studio_wood, studio_clay (not stone).
    assert _studio_actions(_feed_state(wood=1, clay=1)) == ["studio_clay", "studio_wood"]


# --- Real-flow effect -------------------------------------------------------

def test_fire_wood_variant_spends_wood_adds_two_food():
    state = _feed_state(wood=2, food=0)
    state = step(state, CommitHarvestConversion(conversion_id="studio_wood"))
    p = state.players[0]
    assert p.resources.wood == 1   # 2 - 1 spent
    assert p.resources.food == 2   # +2 food
    assert "studio_wood" in p.harvest_conversions_used


def test_fire_clay_variant_spends_clay_adds_two_food():
    state = _feed_state(clay=2, food=0)
    state = step(state, CommitHarvestConversion(conversion_id="studio_clay"))
    p = state.players[0]
    assert p.resources.clay == 1
    assert p.resources.food == 2
    assert "studio_clay" in p.harvest_conversions_used


def test_fire_stone_variant_spends_stone_adds_three_food():
    state = _feed_state(stone=2, food=0)
    state = step(state, CommitHarvestConversion(conversion_id="studio_stone"))
    p = state.players[0]
    assert p.resources.stone == 1
    assert p.resources.food == 3   # stone yields 3, not 2
    assert "studio_stone" in p.harvest_conversions_used


# --- Once-per-harvest: choosing ONE variant suppresses the others -----------

def test_once_per_harvest_choice():
    """After firing one variant, no studio variant is offered again this harvest
    (a single use, choosing which resource — not three independent fires)."""
    state = _feed_state(wood=5, clay=5, stone=5, food=0)
    assert _studio_actions(state) == ["studio_clay", "studio_stone", "studio_wood"]

    state = step(state, CommitHarvestConversion(conversion_id="studio_wood"))
    # Even though plenty of wood/clay/stone remains, the card is spent this harvest.
    assert _studio_actions(state) == []


# --- Optionality: declining (commit feed without firing) --------------------

def test_optional_decline_via_commit():
    """The conversion is optional — committing feed without firing it leaves
    resources untouched."""
    state = _feed_state(wood=1, clay=1, stone=1, food=10)  # plenty of food
    # CommitConvert with no consumption ends the feed without firing the studio.
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    p = state.players[0]
    assert p.resources.wood == 1
    assert p.resources.clay == 1
    assert p.resources.stone == 1
    assert not any(c.startswith(CARD_ID) for c in p.harvest_conversions_used)
