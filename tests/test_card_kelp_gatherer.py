"""Tests for Kelp Gatherer (E160) — an occupation: each time ANOTHER player uses
Fishing, that player gets 1 additional food and the OWNER gets 1 vegetable.

An `any_player` `before_action_space` automatic effect on Fishing (ATOMIC → hooked
with any_player=True so it hosts on either player's turn). Eligibility requires
actor != owner (the owner's own use grants nothing). Both rewards are flat.
"""
import agricola.cards.kelp_gatherer  # noqa: F401  (registers the card)

from agricola.actions import PlaceWorker, Proceed
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.setup import setup
from tests.factories import with_current_player, with_space

CARD_ID = "kelp_gatherer"


def _give(state, idx, cid=CARD_ID):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {cid}) if i == idx
        else state.players[i] for i in range(2)))


def test_registration():
    assert CARD_ID in OCCUPATIONS
    s = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) is s


def test_opponent_uses_fishing():
    """P1 acts; P1 gets +1 food (plus the space's food at Proceed), P0 gets +1 veg."""
    s = setup(seed=0)
    s = with_current_player(s, 1)
    s = with_space(s, "fishing", revealed=True, accumulated_amount=2)
    s = _give(s, 0)                       # owner P0, actor P1
    food_actor0 = s.players[1].resources.food
    veg_owner0 = s.players[0].resources.veg

    s = step(s, PlaceWorker(space="fishing"))
    assert isinstance(s.pending_stack[-1], PendingActionSpace)   # atomic space hosted
    assert s.players[1].resources.food == food_actor0 + 1        # actor's bonus food
    assert s.players[0].resources.veg == veg_owner0 + 1          # owner's veg

    s = step(s, Proceed())                                       # take the 2 fishing food
    assert s.players[1].resources.food == food_actor0 + 1 + 2


def test_owner_uses_fishing_no_bonus():
    """The owner's OWN Fishing use grants nothing (text is 'another player')."""
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = with_space(s, "fishing", revealed=True, accumulated_amount=2)
    s = _give(s, 0)
    veg0 = s.players[0].resources.veg
    food0 = s.players[0].resources.food

    s = step(s, PlaceWorker(space="fishing"))
    assert s.players[0].resources.veg == veg0        # no veg
    assert s.players[0].resources.food == food0      # no bonus food

    s = step(s, Proceed())
    assert s.players[0].resources.food == food0 + 2  # only the space's own food
