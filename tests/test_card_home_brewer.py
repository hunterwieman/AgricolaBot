import agricola.cards.home_brewer  # noqa: F401
# Tests for Home Brewer (occupation, C #110; Consul Dirigens Expansion).
#
# Card text: "After the field phase of each harvest, you can use this card to
# turn exactly 1 grain into your choice of 3 food or 1 bonus point."
# Occupation. No cost / prereq. VPs: 0. Not passing.
#
# Two HarvestConversionSpec entries (home_brewer_food / home_brewer_vp) — each
# spends exactly 1 grain. The food variant yields 3 food; the VP variant yields
# 0 food and banks 1 bonus point. Used at most once per harvest (a CHOICE of
# output, not two independent fires). Bonus points are banked in the CardStore
# and read by the scoring term at end-game.
#
# Mirrors tests/test_card_beer_keg.py's harvest-feed craft-firing flow.

import dataclasses

from agricola.actions import CommitConvert, CommitHarvestConversion
from agricola.cards.home_brewer import CARD_ID
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import Phase
from agricola.engine import _initiate_harvest_feed, step
from agricola.legality import legal_actions
from agricola.resources import Resources
from agricola.scoring import SCORING_TERMS
from agricola.state import GameState
from agricola.setup import setup

from tests.factories import with_phase, with_resources


# --- Helpers ----------------------------------------------------------------

def _with_occupations(state, player_idx, card_ids: frozenset):
    p = state.players[player_idx]
    p = dataclasses.replace(p, occupations=card_ids)
    return dataclasses.replace(
        state,
        players=tuple(p if i == player_idx else state.players[i] for i in range(2)),
    )


def _feed_state(*, grain=0, food=0, owned=True) -> GameState:
    """A HARVEST_FEED state with player 0 (optionally) owning Home Brewer, given
    grain/food, player 1 well-fed so only player 0's feed frame is interesting."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    if owned:
        state = _with_occupations(state, 0, frozenset({CARD_ID}))
    state = with_resources(state, 0, food=food, grain=grain)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    return _initiate_harvest_feed(state)


def _brewer_actions(state):
    return sorted(
        a.conversion_id for a in legal_actions(state)
        if isinstance(a, CommitHarvestConversion) and a.conversion_id.startswith(CARD_ID)
    )


def _score_fn():
    """The registered scoring callable for Home Brewer (SCORING_TERMS is a list of
    (card_id, fn) tuples, not a dict)."""
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    # Two conversion entries (food / VP).
    assert f"{CARD_ID}_food" in HARVEST_CONVERSIONS
    assert f"{CARD_ID}_vp" in HARVEST_CONVERSIONS
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


def test_conversion_specs_match_text():
    """Each entry spends exactly 1 grain; food variant -> 3 food, VP variant ->
    0 food (the point is banked via the side effect)."""
    food = HARVEST_CONVERSIONS[f"{CARD_ID}_food"]
    assert food.input_cost == Resources(grain=1)
    assert food.food_out == 3
    assert food.side_effect_fn is None

    vp = HARVEST_CONVERSIONS[f"{CARD_ID}_vp"]
    assert vp.input_cost == Resources(grain=1)
    assert vp.food_out == 0
    assert vp.side_effect_fn is not None


def test_on_play_is_noop():
    """The occupation's on-play does nothing (effect is the recurring conversion)."""
    state = setup(seed=0)
    out = OCCUPATIONS[CARD_ID].on_play(state, 0)
    assert out is state


# --- Eligibility / offering -------------------------------------------------

def test_offered_only_when_owned():
    """Both variants offered iff the player owns Home Brewer."""
    owned = _feed_state(grain=1, food=0, owned=True)
    assert _brewer_actions(owned) == ["home_brewer_food", "home_brewer_vp"]

    unowned = _feed_state(grain=1, food=0, owned=False)
    assert _brewer_actions(unowned) == []


def test_offered_only_when_grain_affordable():
    """Both variants need 1 grain; with 0 grain neither is offered."""
    assert _brewer_actions(_feed_state(grain=1)) == ["home_brewer_food", "home_brewer_vp"]
    assert _brewer_actions(_feed_state(grain=0)) == []


# --- Real-flow effect -------------------------------------------------------

def test_fire_food_variant_spends_grain_adds_three_food():
    """Fire home_brewer_food: spend 1 grain, gain 3 food, bank 0 points."""
    state = _feed_state(grain=2, food=0)
    state = step(state, CommitHarvestConversion(conversion_id=f"{CARD_ID}_food"))

    p = state.players[0]
    assert p.resources.grain == 1            # 2 - 1 spent
    assert p.resources.food == 3             # +3 food
    assert p.card_state.get(CARD_ID, 0) == 0  # no banked point
    assert f"{CARD_ID}_food" in p.harvest_conversions_used


def test_fire_vp_variant_spends_grain_banks_one_point_no_food():
    """Fire home_brewer_vp: spend 1 grain, gain 0 food, bank 1 bonus point."""
    state = _feed_state(grain=2, food=0)
    state = step(state, CommitHarvestConversion(conversion_id=f"{CARD_ID}_vp"))

    p = state.players[0]
    assert p.resources.grain == 1            # 2 - 1 spent
    assert p.resources.food == 0             # VP variant gives no food
    assert p.card_state.get(CARD_ID, 0) == 1  # 1 banked point
    assert f"{CARD_ID}_vp" in p.harvest_conversions_used


# --- Once-per-harvest: choosing ONE output suppresses the other -------------

def test_once_per_harvest_choice():
    """After firing one variant, no home_brewer variant is offered again this
    harvest (a single use, choosing the output — not two independent fires)."""
    state = _feed_state(grain=5, food=0)
    assert _brewer_actions(state) == ["home_brewer_food", "home_brewer_vp"]

    state = step(state, CommitHarvestConversion(conversion_id=f"{CARD_ID}_food"))
    # Even though 4 grain remains, the card is spent for this harvest.
    assert _brewer_actions(state) == []


def test_vp_variant_also_suppresses_food_variant():
    """Firing the VP output likewise spends the once-per-harvest use."""
    state = _feed_state(grain=5, food=0)
    state = step(state, CommitHarvestConversion(conversion_id=f"{CARD_ID}_vp"))
    assert _brewer_actions(state) == []


# --- Scoping: a fresh harvest re-enables the card ---------------------------

def test_fresh_harvest_reenables_card():
    """harvest_conversions_used is reset each harvest, so a new feed frame offers
    the card again — and the bank carries forward."""
    state = _feed_state(grain=2, food=0)
    state = step(state, CommitHarvestConversion(conversion_id=f"{CARD_ID}_vp"))
    assert state.players[0].card_state.get(CARD_ID, 0) == 1

    # Simulate the next harvest's fresh FEED frame: clear used-set, re-init feed.
    p = state.players[0]
    p = dataclasses.replace(p, harvest_conversions_used=frozenset())
    state = dataclasses.replace(
        state, players=tuple(p if i == 0 else state.players[i] for i in range(2)),
    )
    state = with_resources(state, 0, grain=2, food=0)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    assert _brewer_actions(state) == ["home_brewer_food", "home_brewer_vp"]
    # Bank carries forward across harvests.
    assert state.players[0].card_state.get(CARD_ID, 0) == 1


# --- Optionality: declining (commit feed without firing) --------------------

def test_optional_decline_via_commit():
    """The conversion is optional — committing feed without firing it leaves
    grain/food/points untouched."""
    state = _feed_state(grain=2, food=10)  # plenty of food, need not fire
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    p = state.players[0]
    assert p.resources.grain == 2
    assert p.card_state.get(CARD_ID, 0) == 0
    assert not any(c.startswith(CARD_ID) for c in p.harvest_conversions_used)


# --- Scoring ----------------------------------------------------------------

def test_scoring_reads_bank():
    score_fn = _score_fn()
    state = setup(seed=0)
    # No bank -> 0.
    assert score_fn(state, 0) == 0
    # Bank 3 points across harvests.
    p = state.players[0]
    p = dataclasses.replace(p, card_state=p.card_state.set(CARD_ID, 3))
    state = dataclasses.replace(
        state, players=tuple(p if i == 0 else state.players[i] for i in range(2))
    )
    assert score_fn(state, 0) == 3
    # Opponent (no bank) scores 0.
    assert score_fn(state, 1) == 0
