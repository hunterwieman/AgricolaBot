import agricola.cards.elephantgrass_plant  # noqa: F401
# Tests for Elephantgrass Plant (minor improvement, C34; Corbarius Expansion).
#
# Card text: "Immediately after each harvest, you can use this card to exchange
# exactly 1 reed for 1 bonus point."
# Cost 2 clay, 1 stone. Prereq: 2 occupations. VPs: 0 (printed).
#
# One HarvestConversionSpec entry (elephantgrass_plant) — spends exactly 1 reed
# for 0 food and banks 1 bonus point. Used at most once per harvest. Bonus points
# are banked in the CardStore and read by the scoring term at end-game.
#
# Mirrors tests/test_card_beer_keg.py's craft-firing flow.

import dataclasses

from agricola.actions import CommitConvert, CommitHarvestConversion
from agricola.cards.elephantgrass_plant import CARD_ID
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import Phase
from agricola.engine import _initiate_harvest_feed, step
from agricola.legality import legal_actions
from agricola.resources import Resources
from agricola.scoring import SCORING_TERMS
from agricola.state import GameState
from agricola.setup import setup

from tests.factories import (
    with_minors,
    with_phase,
    with_resources,
)


# --- Helpers ----------------------------------------------------------------

def _with_occupations(state, player_idx, occupations: frozenset):
    """Give a player a set of (dummy) occupation card ids — only the COUNT is
    read by prereq_met, so the ids need not be registered."""
    p = state.players[player_idx]
    p = dataclasses.replace(p, occupations=occupations)
    return dataclasses.replace(
        state,
        players=tuple(p if i == player_idx else state.players[i] for i in range(2)),
    )


def _feed_state(*, reed=0, food=0, owned=True) -> GameState:
    """A HARVEST_FEED state with player 0 owning Elephantgrass Plant, given
    reed/food, player 1 well-fed so only player 0's feed frame is interesting."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    if owned:
        state = with_minors(state, 0, frozenset({CARD_ID}))
    state = with_resources(state, 0, food=food, reed=reed)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    return _initiate_harvest_feed(state)


def _egp_actions(state):
    return sorted(
        a.conversion_id for a in legal_actions(state)
        if isinstance(a, CommitHarvestConversion) and a.conversion_id == CARD_ID
    )


def _score_fn():
    """The registered scoring callable (SCORING_TERMS is a list of
    (card_id, fn) tuples, not a dict)."""
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(clay=2, stone=1)
    assert spec.min_occupations == 2
    assert spec.vps == 0
    assert CARD_ID in HARVEST_CONVERSIONS
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


def test_conversion_matches_text():
    """Spend exactly 1 reed, produce no food (the only effect is the banked point)."""
    spec = HARVEST_CONVERSIONS[CARD_ID]
    assert spec.input_cost == Resources(reed=1)
    assert spec.food_out == 0


# --- Prerequisite -----------------------------------------------------------

def test_prereq_requires_two_occupations():
    spec = MINORS[CARD_ID]
    state = setup(seed=0)
    state = _with_occupations(state, 0, frozenset())
    assert prereq_met(spec, state, 0) is False
    state = _with_occupations(state, 0, frozenset({"a"}))
    assert prereq_met(spec, state, 0) is False
    state = _with_occupations(state, 0, frozenset({"a", "b"}))
    assert prereq_met(spec, state, 0) is True
    state = _with_occupations(state, 0, frozenset({"a", "b", "c"}))
    assert prereq_met(spec, state, 0) is True


# --- Eligibility / offering -------------------------------------------------

def test_offered_only_when_owned():
    """The swap is offered iff the player owns Elephantgrass Plant."""
    owned = _feed_state(reed=1, food=0, owned=True)
    assert _egp_actions(owned) == [CARD_ID]

    unowned = _feed_state(reed=1, food=0, owned=False)
    assert _egp_actions(unowned) == []


def test_offered_only_when_reed_affordable():
    """Offered only when the player has at least 1 reed to spend."""
    assert _egp_actions(_feed_state(reed=1)) == [CARD_ID]
    assert _egp_actions(_feed_state(reed=0)) == []


# --- Real-flow effect -------------------------------------------------------

def test_fire_spends_one_reed_banks_one_point_no_food():
    """Fire the conversion: spend 1 reed, gain NO food, bank 1 bonus point."""
    state = _feed_state(reed=2, food=0)
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))

    p = state.players[0]
    assert p.resources.reed == 1            # 2 - 1 spent
    assert p.resources.food == 0            # food_out == 0, no food added
    assert p.card_state.get(CARD_ID, 0) == 1  # 1 banked point
    assert CARD_ID in p.harvest_conversions_used


# --- Once-per-harvest: firing suppresses a second use this harvest ----------

def test_once_per_harvest():
    """After firing, the swap is not offered again this harvest (even with reed
    left over)."""
    state = _feed_state(reed=3, food=0)
    assert _egp_actions(state) == [CARD_ID]

    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))
    # 2 reed remains, but the card is spent for this harvest.
    assert _egp_actions(state) == []


# --- Optionality: declining (commit feed without firing) --------------------

def test_optional_decline_via_commit():
    """The conversion is optional — committing feed without firing it leaves
    reed/points untouched."""
    state = _feed_state(reed=2, food=10)  # plenty of food, need not fire
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    p = state.players[0]
    assert p.resources.reed == 2
    assert p.card_state.get(CARD_ID, 0) == 0
    assert CARD_ID not in p.harvest_conversions_used


# --- Scoping: opponent ownership does not offer to the wrong player ----------

def test_not_offered_to_non_owner():
    """Player 1 owning the card must not offer player 0 the swap (is_owned_fn
    gates per-player even though the registration is global)."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_minors(state, 1, frozenset({CARD_ID}))  # opponent owns it
    state = with_resources(state, 0, reed=5, food=0)
    state = with_resources(state, 1, food=99, reed=5)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)
    # Player 0 (the feed decider here) does not own it -> not offered.
    assert _egp_actions(state) == []


# --- Scoring ----------------------------------------------------------------

def test_scoring_reads_bank():
    score_fn = _score_fn()
    state = setup(seed=0)
    # No bank -> 0.
    assert score_fn(state, 0) == 0
    # Bank 4 points across harvests.
    p = state.players[0]
    p = dataclasses.replace(p, card_state=p.card_state.set(CARD_ID, 4))
    state = dataclasses.replace(
        state, players=tuple(p if i == 0 else state.players[i] for i in range(2))
    )
    assert score_fn(state, 0) == 4
    # Opponent (no bank) scores 0.
    assert score_fn(state, 1) == 0
