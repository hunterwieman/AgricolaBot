import agricola.cards.schnapps_distillery  # noqa: F401
# Tests for Schnapps Distillery (minor improvement, C59; Consul Dirigens
# Expansion; Food Provider).
#
# Card text: "In each feeding phase, you can use this card to turn exactly 1
# vegetable into 5 food. During scoring, you get 1 bonus point each for your
# 5th and 6th vegetable."
# Cost: 2 Stone, 1 Vegetable. VPs: 2. Not passing.
#
# Two effects, both off existing machinery:
#   1. ONE HarvestConversionSpec (veg=1 -> 5 food), offered once per feeding
#      phase via the engine's harvest_conversions_used accounting (mirrors the
#      built-in crafts joinery/pottery/basketmaker and Beer Keg, but with no
#      choice of amount, so a single registry entry).
#   2. A scoring term: +1 point each for the player's 5th and 6th vegetable,
#      counting vegetables the SAME way scoring.py does (supply veg + veg on
#      unharvested FIELD cells + veg planted on card-fields — ruling 45,
#      2026-07-12: crops planted on card-fields are crops "in your fields";
#      stone on Rock Garden is not a vegetable and never counts). The printed
#      2 VP is awarded separately by the engine, so the term must NOT re-add it.
#
# Mirrors tests/test_card_beer_keg.py's craft-firing flow.

import agricola.cards.beanfield  # noqa: F401  (registers the card-fields used below)
import agricola.cards.rock_garden  # noqa: F401

import dataclasses

from agricola.cards.card_fields import stacks_to_store

from agricola.actions import CommitConvert, CommitHarvestConversion
from agricola.cards.schnapps_distillery import CARD_ID
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.specs import MINORS
from agricola.constants import Phase
from agricola.engine import _initiate_harvest_feed, step
from agricola.legality import legal_actions
from agricola.resources import Animals, Resources
from agricola.scoring import SCORING_TERMS
from agricola.state import GameState
from agricola.setup import setup

from tests.factories import (
    with_minors,
    with_phase,
    with_resources,
    with_sown_fields,
)


# --- Helpers ----------------------------------------------------------------

def _feed_state(*, veg=0, food=0, owned=True) -> GameState:
    """A HARVEST_FEED state with player 0 owning Schnapps Distillery, given
    veg/food in supply, player 1 well-fed so only player 0's feed frame is
    interesting."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    if owned:
        state = with_minors(state, 0, frozenset({CARD_ID}))
    state = with_resources(state, 0, food=food, veg=veg)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    return _initiate_harvest_feed(state)


def _schnapps_actions(state):
    return sorted(
        a.conversion_id for a in legal_actions(state)
        if isinstance(a, CommitHarvestConversion) and a.conversion_id == CARD_ID
    )


def _score_fn():
    """The registered scoring callable (SCORING_TERMS is a list of (card_id, fn)
    tuples, not a dict)."""
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


def _own_card(state, idx, card_id):
    """Give player idx an arbitrary minor improvement (a card-field card)."""
    p = state.players[idx]
    return dataclasses.replace(state, players=tuple(
        dataclasses.replace(p, minor_improvements=p.minor_improvements | {card_id})
        if i == idx else state.players[i] for i in range(2)))


def _set_stacks(state, idx, cid, stacks):
    """Write a card-field's per-stack (grain, veg, wood, stone) contents."""
    p = state.players[idx]
    p = dataclasses.replace(p, card_state=stacks_to_store(p.card_state, cid, stacks))
    return dataclasses.replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(stone=2, veg=1)
    assert spec.cost.animals == Animals()
    assert spec.vps == 2
    assert spec.passing_left is False
    assert CARD_ID in HARVEST_CONVERSIONS
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


def test_conversion_matches_text():
    """One entry: spend exactly 1 vegetable, produce exactly 5 food, no side
    effect."""
    spec = HARVEST_CONVERSIONS[CARD_ID]
    assert spec.input_cost == Resources(veg=1)
    assert spec.food_out == 5
    assert spec.side_effect_fn is None


# --- Eligibility / offering -------------------------------------------------

def test_offered_only_when_owned():
    """The conversion is offered iff the player owns Schnapps Distillery."""
    assert _schnapps_actions(_feed_state(veg=1, owned=True)) == [CARD_ID]
    assert _schnapps_actions(_feed_state(veg=1, owned=False)) == []


def test_offered_only_when_veg_affordable():
    """No veg in supply -> the conversion is not affordable, so not offered."""
    assert _schnapps_actions(_feed_state(veg=0)) == []
    assert _schnapps_actions(_feed_state(veg=1)) == [CARD_ID]
    assert _schnapps_actions(_feed_state(veg=3)) == [CARD_ID]


# --- Real-flow effect -------------------------------------------------------

def test_fire_spends_one_veg_adds_five_food():
    """Fire the conversion: spend exactly 1 veg, gain 5 food."""
    state = _feed_state(veg=2, food=0)
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))

    p = state.players[0]
    assert p.resources.veg == 1     # 2 - 1 spent
    assert p.resources.food == 5    # +5 food
    assert CARD_ID in p.harvest_conversions_used


# --- Once-per-feeding-phase: a single use ----------------------------------

def test_once_per_feeding_phase():
    """After firing the conversion, it is not offered again this harvest even
    though more veg remains in supply."""
    state = _feed_state(veg=5, food=0)
    assert _schnapps_actions(state) == [CARD_ID]

    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))
    # 4 veg remain, but the card is spent for this feeding phase.
    assert _schnapps_actions(state) == []
    assert state.players[0].resources.veg == 4


# --- Optionality: declining (commit feed without firing) --------------------

def test_optional_decline_via_commit():
    """The conversion is optional — committing feed without firing it leaves
    veg/food untouched."""
    state = _feed_state(veg=3, food=10)  # plenty of food, need not fire
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    p = state.players[0]
    assert p.resources.veg == 3
    assert CARD_ID not in p.harvest_conversions_used


# --- Scoring: 5th and 6th vegetable -----------------------------------------

def test_scoring_thresholds_supply_veg():
    """+1 at the 5th vegetable, +1 more at the 6th, counting supply veg."""
    score_fn = _score_fn()
    base = setup(seed=0)

    def points(veg):
        s = with_resources(base, 0, veg=veg)
        return score_fn(s, 0)

    assert points(0) == 0
    assert points(4) == 0
    assert points(5) == 1   # 5th vegetable
    assert points(6) == 2   # + 6th vegetable
    assert points(10) == 2  # capped at 2 (no 7th-veg bonus)


def test_scoring_counts_veg_on_fields():
    """Vegetables sitting on unharvested FIELD cells count toward the 5th/6th
    bonus, exactly as scoring.py's printed-veg track does — not just supply."""
    score_fn = _score_fn()
    state = setup(seed=0)
    # 1 veg in supply + 4 veg on fields (2 veg-fields * 2 veg each) = 5 total.
    state = with_resources(state, 0, veg=1)
    state = with_sown_fields(state, 0, veg_fields=[(0, 0), (0, 1)])
    assert score_fn(state, 0) == 1  # 5th vegetable counted across supply+fields


def test_scoring_counts_veg_on_card_fields():
    """Ruling 45 (2026-07-12): veg planted on a card-field is a vegetable "in
    your fields" — the 5th-veg threshold is reached ONLY by counting Beanfield's
    2 planted veg (grid-only counting saw 3 -> 0 points)."""
    score_fn = _score_fn()
    state = setup(seed=0)
    state = with_resources(state, 0, veg=3)
    state = _own_card(state, 0, "beanfield")
    state = _set_stacks(state, 0, "beanfield", [(0, 2, 0, 0)])
    assert score_fn(state, 0) == 1  # 3 supply + 2 on Beanfield = 5th veg
    # One more supply veg makes 6 -> both bonus points.
    state6 = with_resources(state, 0, veg=4)
    assert score_fn(state6, 0) == 2


def test_stone_on_rock_garden_is_not_a_vegetable():
    """Rock Garden sows stone "as you would vegetables", but stone is NOT a
    vegetable — 6 planted stone add nothing to the 5th/6th-veg count."""
    score_fn = _score_fn()
    state = setup(seed=0)
    state = with_resources(state, 0, veg=4)
    state = _own_card(state, 0, "rock_garden")
    state = _set_stacks(state, 0, "rock_garden",
                        [(0, 0, 0, 2), (0, 0, 0, 2), (0, 0, 0, 2)])
    assert score_fn(state, 0) == 0  # still 4 vegetables


def test_opponent_without_card_unaffected():
    """The scoring term is keyed to the owner; only called for owners by the
    engine, but the fn itself returns 0 when no veg is held."""
    score_fn = _score_fn()
    state = setup(seed=0)
    assert score_fn(state, 1) == 0
