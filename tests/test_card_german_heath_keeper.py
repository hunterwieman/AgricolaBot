"""Tests for German Heath Keeper (C164) — an occupation: each time ANY player
(including you) uses Pig Market, the OWNER gets 1 sheep from the general supply.

An `any_player` `before_action_space` automatic effect on the non-atomic Pig Market
(no hook). The sheep is granted via helpers.grant_animals, so it routes through the
accommodation barrier on overflow. The owner is given pasture capacity here so the
grant is kept (not cooked). Fires for the owner on the owner's OWN use and on the
opponent's use.
"""
import agricola.cards.german_heath_keeper  # noqa: F401  (registers the card)

from agricola.actions import PlaceWorker
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.pasture import Pasture
from agricola.replace import fast_replace
from agricola.setup import setup
from tests.factories import with_current_player, with_space

CARD_ID = "german_heath_keeper"


def _give(state, idx, cid=CARD_ID):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {cid}) if i == idx
        else state.players[i] for i in range(2)))


def _give_capacity(state, idx, cells):
    fy = state.players[idx].farmyard
    pasture = Pasture(cells=frozenset(cells), num_stables=0, capacity=2 * len(cells))
    fy = fast_replace(fy, pastures=(pasture,))
    p = fast_replace(state.players[idx], farmyard=fy)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _pig_market_state(*, owner, actor):
    s = setup(seed=0)
    s = with_current_player(s, actor)
    s = with_space(s, "pig_market", revealed=True, accumulated_amount=1)
    s = _give(s, owner)
    s = _give_capacity(s, owner, [(0, 0)])   # capacity 2 → keep the sheep
    return s


def test_registration():
    assert CARD_ID in OCCUPATIONS
    s = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) is s


def test_owner_uses_pig_market():
    s = _pig_market_state(owner=0, actor=0)
    sheep0 = s.players[0].animals.sheep
    s = step(s, PlaceWorker(space="pig_market"))
    assert s.players[0].animals.sheep == sheep0 + 1


def test_opponent_uses_pig_market():
    """P1 acts; the OWNER (P0) gets the sheep, not the actor."""
    s = _pig_market_state(owner=0, actor=1)
    sheep_owner0 = s.players[0].animals.sheep
    s = step(s, PlaceWorker(space="pig_market"))
    assert s.players[0].animals.sheep == sheep_owner0 + 1   # owner
    assert s.players[1].animals.sheep == 0                  # actor got no sheep


def test_no_fire_on_other_market():
    """Sheep Market (not Pig Market) does not trigger the card."""
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = with_space(s, "sheep_market", revealed=True, accumulated_amount=1)
    s = _give(s, 0)
    s = _give_capacity(s, 0, [(0, 0)])
    s = step(s, PlaceWorker(space="sheep_market"))
    # No card sheep granted; the market's own 1 sheep is still staged (gained), not
    # on the player yet.
    assert s.players[0].animals.sheep == 0
