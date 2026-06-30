"""Tests for Case Builder (occupation, B105).

Card text: "When you play this card, you immediately get 1 good of each of the
following types, If you have at least 2 of that good in your supply already:
food, grain, vegetable, reed, wood."

Drives the real engine play-occupation flow (Lessons -> play_occupation ->
CommitPlayOccupation) and checks the >=2 thresholds per good type.
"""
import agricola.cards.case_builder  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.legality import legal_actions, legal_placements
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env

_POOL = CardPool(
    occupations=("case_builder",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _state_with_resources(resources, *, seed=5):
    """A card-mode round-1 state with the current player holding Case Builder in
    hand and the given supply set deterministically."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(
        cs.players[cp],
        hand_occupations=frozenset({"case_builder"}),
        resources=resources,
    )
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


def _play_case_builder(cs):
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))  # singleton: push PendingPlayOccupation
    cs = step(cs, CommitPlayOccupation(card_id="case_builder"))
    return cs


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_case_builder_registered():
    assert "case_builder" in OCCUPATIONS


# ---------------------------------------------------------------------------
# Effect via the real play-occupation flow
# ---------------------------------------------------------------------------

def test_all_five_goods_at_threshold_gain_one_each():
    # >=2 of each named good -> +1 of each.  (food must stay >=2 so Lessons is
    # affordable -- but this is the first occupation, so it is free anyway.)
    res = Resources(food=2, grain=2, veg=2, reed=2, wood=2, clay=5, stone=5)
    cs, cp = _state_with_resources(res)
    # confirm Lessons surfaces a playable occupation
    assert "lessons" in {a.space for a in legal_placements(cs)}

    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    assert legal_actions(cs) == [CommitPlayOccupation(card_id="case_builder")]
    cs = step(cs, CommitPlayOccupation(card_id="case_builder"))

    after = cs.players[cp].resources
    assert (after.food, after.grain, after.veg, after.reed, after.wood) == (3, 3, 3, 3, 3)
    # untracked goods (clay, stone) are unchanged
    assert (after.clay, after.stone) == (5, 5)
    assert "case_builder" in cs.players[cp].occupations
    assert "case_builder" not in cs.players[cp].hand_occupations


def test_below_threshold_goods_gain_nothing():
    # grain=1 and reed=0 are below the >=2 threshold; food/veg/wood at >=2.
    res = Resources(food=3, grain=1, veg=2, reed=0, wood=2)
    cs, cp = _state_with_resources(res)
    cs = _play_case_builder(cs)

    after = cs.players[cp].resources
    assert after.grain == 1   # below threshold -> no gain
    assert after.reed == 0    # below threshold -> no gain
    assert after.food == 4    # 3 -> +1
    assert after.veg == 3     # 2 -> +1
    assert after.wood == 3    # 2 -> +1


def test_exactly_two_is_inclusive():
    # The threshold is "at least 2" (>=2): exactly 2 qualifies.
    res = Resources(food=2, grain=2)
    cs, cp = _state_with_resources(res)
    cs = _play_case_builder(cs)

    after = cs.players[cp].resources
    assert after.food == 3
    assert after.grain == 3


def test_no_qualifying_goods_grants_nothing_but_is_still_played():
    # All named goods below threshold -> no gain, but the card still enters play.
    # (food=1 is below 2; first occupation is free so Lessons is still affordable.)
    res = Resources(food=1, grain=1, veg=0, reed=1, wood=1)
    cs, cp = _state_with_resources(res)
    before = cs.players[cp].resources
    cs = _play_case_builder(cs)

    after = cs.players[cp].resources
    assert after == before                          # nothing crossed the threshold
    assert "case_builder" in cs.players[cp].occupations


def test_three_or_more_still_grants_exactly_one():
    # "at least 2" -> a single +1, regardless of how far above the threshold.
    res = Resources(food=5, wood=9)
    cs, cp = _state_with_resources(res)
    cs = _play_case_builder(cs)

    after = cs.players[cp].resources
    assert after.food == 6
    assert after.wood == 10


def test_play_completes_and_pops_the_stack():
    res = Resources(food=2, grain=2)
    cs, cp = _state_with_resources(res)
    cs = _play_case_builder(cs)
    cs = step(cs, Stop())   # pop PendingPlayOccupation's after-phase
    cs = step(cs, Stop())   # pop the Lessons host
    assert cs.pending_stack == ()
