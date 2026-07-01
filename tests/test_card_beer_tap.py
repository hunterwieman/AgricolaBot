import agricola.cards.beer_tap  # noqa: F401
# Tests for Beer Tap (minor improvement, D62; Dulcinaria Expansion).
#
# Card text: "When you play this card, you immediately get 2 food. In the
# feeding phase of each harvest, you can turn 2/3/4 grain into 3/6/9 food."
# Cost 1 wood. No prereq. VPs: 0.
#
# Effects:
#   - ON PLAY: +2 food.
#   - Three HarvestConversionSpec entries (beer_tap_2/3/4) — each spends 2/3/4
#     grain for 3/6/9 food. Used at most once per harvest (a CHOICE of grain
#     amount, not three independent fires). No banked points, no CardStore.
#
# Mirrors tests/test_card_beer_keg.py and tests/test_harvest_feed.py's craft flow.

import dataclasses

from agricola.actions import CommitConvert, CommitHarvestConversion
from agricola.cards.beer_tap import CARD_ID
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

def _feed_state(*, grain=0, food=0, beer_tap=True) -> GameState:
    """A HARVEST_FEED state with player 0 owning Beer Tap, given grain/food,
    player 1 well-fed so only player 0's feed frame is interesting."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    if beer_tap:
        state = with_minors(state, 0, frozenset({CARD_ID}))
    state = with_resources(state, 0, food=food, grain=grain)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    return _initiate_harvest_feed(state)


def _beer_tap_actions(state):
    return sorted(
        (a.conversion_id for a in legal_actions(state)
         if isinstance(a, CommitHarvestConversion) and a.conversion_id.startswith(CARD_ID))
    )


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(wood=1)
    assert spec.vps == 0
    assert spec.passing_left is False
    assert spec.prereq is None
    # Three conversion entries.
    for grain in (2, 3, 4):
        assert f"{CARD_ID}_{grain}" in HARVEST_CONVERSIONS


def test_conversion_outputs_match_text():
    """Each entry: spend 2/3/4 grain, produce 3/6/9 food."""
    expected = {2: 3, 3: 6, 4: 9}
    for grain, food in expected.items():
        spec = HARVEST_CONVERSIONS[f"{CARD_ID}_{grain}"]
        assert spec.input_cost == Resources(grain=grain)
        assert spec.food_out == food
        assert spec.side_effect_fn is None


# --- On-play effect ---------------------------------------------------------

def test_on_play_grants_two_food():
    """Playing the card immediately grants the owner 2 food (and nothing else)."""
    state = setup(seed=0)
    state = with_resources(state, 0, food=5, grain=4)
    spec = MINORS[CARD_ID]
    out = spec.on_play(state, 0)
    p = out.players[0]
    assert p.resources.food == 7          # 5 + 2
    assert p.resources.grain == 4         # grain untouched
    # Opponent untouched.
    assert out.players[1].resources == state.players[1].resources


# --- Eligibility / offering -------------------------------------------------

def test_offered_only_when_owned():
    """All three variants offered iff the player owns Beer Tap."""
    owned = _feed_state(grain=4, food=0, beer_tap=True)
    assert _beer_tap_actions(owned) == ["beer_tap_2", "beer_tap_3", "beer_tap_4"]

    unowned = _feed_state(grain=4, food=0, beer_tap=False)
    assert _beer_tap_actions(unowned) == []


def test_offered_variants_gated_by_affordable_grain():
    """Only variants whose grain cost is affordable are offered."""
    # 2 grain -> only beer_tap_2.
    assert _beer_tap_actions(_feed_state(grain=2)) == ["beer_tap_2"]
    # 3 grain -> beer_tap_2, beer_tap_3.
    assert _beer_tap_actions(_feed_state(grain=3)) == ["beer_tap_2", "beer_tap_3"]
    # 1 grain -> none affordable (cheapest tier needs 2).
    assert _beer_tap_actions(_feed_state(grain=1)) == []
    # 0 grain -> none affordable.
    assert _beer_tap_actions(_feed_state(grain=0)) == []


# --- Real-flow effect -------------------------------------------------------

def test_fire_two_grain_variant_spends_grain_adds_three_food():
    """Fire beer_tap_2: spend 2 grain, gain 3 food."""
    state = _feed_state(grain=4, food=0)
    state = step(state, CommitHarvestConversion(conversion_id="beer_tap_2"))
    p = state.players[0]
    assert p.resources.grain == 2          # 4 - 2 spent
    assert p.resources.food == 3           # +3 food


def test_fire_three_grain_variant():
    state = _feed_state(grain=4, food=0)
    state = step(state, CommitHarvestConversion(conversion_id="beer_tap_3"))
    p = state.players[0]
    assert p.resources.grain == 1          # 4 - 3
    assert p.resources.food == 6           # +6 food


def test_fire_four_grain_variant():
    state = _feed_state(grain=4, food=0)
    state = step(state, CommitHarvestConversion(conversion_id="beer_tap_4"))
    p = state.players[0]
    assert p.resources.grain == 0          # 4 - 4
    assert p.resources.food == 9           # +9 food


# --- Once-per-harvest: choosing ONE variant suppresses the others -----------

def test_once_per_harvest_choice():
    """After firing one variant, no beer_tap variant is offered again this harvest
    (a single use, choosing the grain amount — not three independent fires)."""
    state = _feed_state(grain=9, food=0)
    assert _beer_tap_actions(state) == ["beer_tap_2", "beer_tap_3", "beer_tap_4"]

    state = step(state, CommitHarvestConversion(conversion_id="beer_tap_2"))
    # Even though plenty of grain remains, the card is spent for this harvest.
    assert _beer_tap_actions(state) == []
    p = state.players[0]
    assert "beer_tap_2" in p.harvest_conversions_used
    # Grain only spent once (9 - 2), not 2+3+4.
    assert p.resources.grain == 7
    assert p.resources.food == 3


# --- Optionality: declining (commit feed without firing) --------------------

def test_optional_decline_via_commit():
    """The conversion is optional — committing feed without firing it leaves
    grain/food untouched."""
    state = _feed_state(grain=4, food=10)  # plenty of food, need not fire
    # CommitConvert with no consumption ends the feed without firing the tap.
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    p = state.players[0]
    assert p.resources.grain == 4
    assert not any(c.startswith(CARD_ID) for c in p.harvest_conversions_used)
