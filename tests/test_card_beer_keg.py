import agricola.cards.beer_keg  # noqa: F401
# Tests for Beer Keg (minor improvement, A62; Artifex Expansion).
#
# Card text: "In the feeding phase of each harvest, you can use this card to
# exchange 1/2/3 grain for 0/1/2 bonus points and exactly 3 food."
# Cost 1 wood. Prereq: 2 grain in your supply. VPs: 0.
#
# Three HarvestConversionSpec entries (beer_keg_1/2/3) — each spends 1/2/3 grain
# for exactly 3 food, banking 0/1/2 bonus points. Used at most once per harvest
# (a CHOICE of grain amount, not three independent fires). Bonus points are
# banked in the CardStore and read by the scoring term at end-game.
#
# Mirrors tests/test_harvest_feed.py's craft-firing flow.

import dataclasses

import agricola.cards.wood_expert  # noqa: F401  (the food-for-wood conversion, for the
#                                     prereq-reservation tests)
from agricola.actions import (
    CommitConvert,
    CommitFoodPayment,
    CommitHarvestConversion,
    CommitPlayMinor,
)
from agricola.cards.beer_keg import CARD_ID
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import Phase
from agricola.engine import _initiate_harvest_feed, step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingFoodPayment, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import SCORING_TERMS
from agricola.state import GameState
from agricola.setup import setup

from tests.factories import (
    with_minors,
    with_pending_stack,
    with_phase,
    with_resources,
)


# --- Helpers ----------------------------------------------------------------

def _feed_state(*, grain=0, food=0, beer_keg=True) -> GameState:
    """A HARVEST_FEED state with player 0 owning Beer Keg, given grain/food,
    player 1 well-fed so only player 0's feed frame is interesting."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    if beer_keg:
        state = with_minors(state, 0, frozenset({CARD_ID}))
    state = with_resources(state, 0, food=food, grain=grain)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    return _initiate_harvest_feed(state)


def _beer_keg_actions(state):
    return sorted(
        (a.conversion_id for a in legal_actions(state)
         if isinstance(a, CommitHarvestConversion) and a.conversion_id.startswith(CARD_ID))
    )


def _score_fn():
    """The registered scoring callable for Beer Keg (SCORING_TERMS is a list of
    (card_id, fn) tuples, not a dict)."""
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(wood=1)
    assert spec.vps == 0
    # Three conversion entries.
    for grain in (1, 2, 3):
        assert f"{CARD_ID}_{grain}" in HARVEST_CONVERSIONS
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


def test_conversion_outputs_and_points_match_text():
    """Each entry: spend `grain` grain, produce exactly 3 food."""
    for grain in (1, 2, 3):
        spec = HARVEST_CONVERSIONS[f"{CARD_ID}_{grain}"]
        assert spec.input_cost == Resources(grain=grain)
        assert spec.food_out == 3


# --- Prerequisite -----------------------------------------------------------

def test_prereq_requires_two_grain():
    state = setup(seed=0)
    spec = MINORS[CARD_ID]
    state = with_resources(state, 0, grain=1)
    assert prereq_met(spec, state, 0) is False
    state = with_resources(state, 0, grain=2)
    assert prereq_met(spec, state, 0) is True
    state = with_resources(state, 0, grain=5)
    assert prereq_met(spec, state, 0) is True


# --- Prerequisite reservation (user ruling 2026-07-27) ----------------------
# The spec declares `prereq_reserved = 2 grain`: a food-raising liquidation on the
# play (Wood Expert converts the 1-wood cost to 1 food) may neither count the 2
# prerequisite grain as fuel at the affordability gate nor cook them at the
# PendingFoodPayment frame — conversions notionally precede the play
# (CARD_AUTHORING_GUIDE.md §0.5), so the post-raise state must still satisfy the
# prerequisite the gate checked.

def _play_state(**res):
    """A state at a PendingPlayMinor with Beer Keg in player 0's hand, Wood Expert
    played (the wood->food cost conversion active), and the given resources."""
    state = setup(seed=0)
    p = fast_replace(state.players[0],
                     hand_minors=frozenset({CARD_ID}),
                     occupations=frozenset({"wood_expert"}),
                     resources=Resources(**res))
    state = fast_replace(state, players=(p, state.players[1]), current_player=0)
    return with_pending_stack(state, (PendingPlayMinor(
        player_idx=0, initiated_by_id="space:meeting_place_cards"),))


def test_prereq_reserved_on_spec():
    assert MINORS[CARD_ID].prereq_reserved == Cost(resources=Resources(grain=2))


def test_food_route_not_playable_when_only_fuel_is_prereq_grain():
    # 0 wood / 0 food / exactly 2 grain: the prerequisite passes, but the only
    # payment Wood Expert offers (1 food) could be raised only by cooking the
    # prerequisite grain — reserved, so NOT playable.
    state = _play_state(grain=2)
    assert prereq_met(MINORS[CARD_ID], state, 0)
    assert CARD_ID not in playable_minors(state, 0)


def test_food_route_plays_off_free_grain_and_prereq_grain_survives():
    # With a 3rd (free) grain the food route is playable: the bundle may cook only
    # the free grain, and the 2 prerequisite grain survive the play.
    state = _play_state(grain=3)
    assert CARD_ID in playable_minors(state, 0)
    commits = [a for a in legal_actions(state)
               if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]
    assert [c.payment for c in commits] == [Resources(food=1)]   # no wood on hand
    state = step(state, commits[0])

    top = state.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 1
    assert top.reserved == Cost(resources=Resources(grain=2))    # the prereq grain
    bundles = legal_actions(state)
    assert bundles == [CommitFoodPayment(grain=1, veg=0, sheep=0, boar=0, cattle=0)]
    state = step(state, bundles[0])                              # only the free grain

    p = state.players[0]
    assert CARD_ID in p.minor_improvements
    assert p.resources.grain == 2      # the prerequisite grain survived the raise
    assert p.resources.food == 0       # raised 1, debited 1


def test_ordinary_wood_payment_unaffected_by_reservation():
    # With the printed wood on hand the wood payment plays as before; the food
    # route is (correctly) not offered — its raise could only cook prereq grain.
    state = _play_state(wood=1, grain=2)
    assert CARD_ID in playable_minors(state, 0)
    commits = [a for a in legal_actions(state)
               if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]
    assert [c.payment for c in commits] == [Resources(wood=1)]
    state = step(state, commits[0])
    p = state.players[0]
    assert CARD_ID in p.minor_improvements
    assert p.resources.wood == 0
    assert p.resources.grain == 2      # untouched


# --- Eligibility / offering -------------------------------------------------

def test_offered_only_when_owned():
    """All three variants offered iff the player owns Beer Keg."""
    owned = _feed_state(grain=3, food=0, beer_keg=True)
    assert _beer_keg_actions(owned) == ["beer_keg_1", "beer_keg_2", "beer_keg_3"]

    unowned = _feed_state(grain=3, food=0, beer_keg=False)
    assert _beer_keg_actions(unowned) == []


def test_offered_variants_gated_by_affordable_grain():
    """Only variants whose grain cost is affordable are offered."""
    # 1 grain -> only beer_keg_1.
    assert _beer_keg_actions(_feed_state(grain=1)) == ["beer_keg_1"]
    # 2 grain -> beer_keg_1, beer_keg_2.
    assert _beer_keg_actions(_feed_state(grain=2)) == ["beer_keg_1", "beer_keg_2"]
    # 0 grain -> none affordable.
    assert _beer_keg_actions(_feed_state(grain=0)) == []


# --- Real-flow effect -------------------------------------------------------

def test_fire_variant_spends_grain_adds_three_food_banks_points():
    """Fire beer_keg_2: spend 2 grain, gain 3 food, bank 1 bonus point."""
    state = _feed_state(grain=3, food=0)
    state = step(state, CommitHarvestConversion(conversion_id="beer_keg_2"))

    p = state.players[0]
    assert p.resources.grain == 1          # 3 - 2 spent
    assert p.resources.food == 3           # +3 food
    assert p.card_state.get(CARD_ID, 0) == 1  # 1 banked point
    assert "beer_keg_2" in p.harvest_conversions_used


def test_fire_one_grain_variant_banks_zero_points():
    state = _feed_state(grain=1, food=0)
    state = step(state, CommitHarvestConversion(conversion_id="beer_keg_1"))
    p = state.players[0]
    assert p.resources.grain == 0
    assert p.resources.food == 3
    assert p.card_state.get(CARD_ID, 0) == 0  # 0 points for the 1-grain variant


def test_fire_three_grain_variant_banks_two_points():
    state = _feed_state(grain=3, food=0)
    state = step(state, CommitHarvestConversion(conversion_id="beer_keg_3"))
    p = state.players[0]
    assert p.resources.grain == 0
    assert p.resources.food == 3
    assert p.card_state.get(CARD_ID, 0) == 2


# --- Once-per-harvest: choosing ONE variant suppresses the others -----------

def test_once_per_harvest_choice():
    """After firing one variant, no beer_keg variant is offered again this harvest
    (a single use, choosing the grain amount — not three independent fires)."""
    state = _feed_state(grain=5, food=0)
    assert _beer_keg_actions(state) == ["beer_keg_1", "beer_keg_2", "beer_keg_3"]

    state = step(state, CommitHarvestConversion(conversion_id="beer_keg_1"))
    # Even though 4 grain remains, the card is spent for this harvest.
    assert _beer_keg_actions(state) == []


# --- Optionality: declining (commit feed without firing) --------------------

def test_optional_decline_via_commit():
    """The conversion is optional — committing feed without firing it leaves
    grain/food/points untouched."""
    state = _feed_state(grain=3, food=10)  # plenty of food, need not fire
    # CommitConvert with no consumption ends the feed without firing the keg.
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    p = state.players[0]
    assert p.resources.grain == 3
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
