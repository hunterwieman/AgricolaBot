"""Tests for Farmers Market (minor improvement, E8; Ephipparius; traveling).

Card text: "You immediately get 1 vegetable. (Effectively, you are buying 1
vegetable for 2 food.)" Cost 2 Food; no prereq; no VPs; passing.

Coverage: registration (cost 2 food, passing, no vps/prereq); the on-play +1 veg
directly; and the real play flow via a PendingPlayMinor — pays 2 food, gains 1
veg, and CIRCULATES to the opponent (traveling, not kept).
"""
import agricola.cards.farmers_market  # noqa: F401  (registers the card)

from agricola.cards.specs import MINORS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor

CARD_ID = "farmers_market"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(food=2))
    assert spec.passing_left is True
    assert spec.vps == 0
    assert spec.prereq is None


def test_on_play_grants_one_veg():
    s, _env = setup_env(0)
    veg0 = s.players[0].resources.veg
    out = MINORS[CARD_ID].on_play(s, 0)
    assert out.players[0].resources.veg == veg0 + 1
    # opponent untouched
    assert out.players[1].resources.veg == s.players[1].resources.veg


def test_real_flow_pays_two_food_gains_veg_and_passes():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    opp = 1 - cp
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({CARD_ID}),
                     resources=Resources(food=3))
    opp_p = fast_replace(cs.players[opp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp_p for i in range(2)))
    veg0 = cs.players[cp].resources.veg
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))

    assert legal_actions(cs) == [sole_play_minor(cs, CARD_ID)]
    cs = step(cs, sole_play_minor(cs, CARD_ID))

    p = cs.players[cp]
    assert p.resources.veg == veg0 + 1        # +1 veg
    assert p.resources.food == 1              # paid 2 of 3 food
    assert CARD_ID not in p.minor_improvements  # traveling -> not kept
    assert CARD_ID not in p.hand_minors         # left my hand
    assert CARD_ID in cs.players[opp].hand_minors  # circulated to opponent


def test_not_playable_without_two_food():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({CARD_ID}),
                     resources=Resources(food=1))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    assert sole_play_minor is not None
    commits = [a for a in legal_actions(cs)
               if getattr(a, "card_id", None) == CARD_ID]
    assert commits == []   # 1 food < 2 -> unaffordable
