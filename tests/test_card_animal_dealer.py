"""Tests for Animal Dealer (A147) — an occupation: each time you use the Sheep/Pig/
Cattle Market, you CAN buy 1 additional animal of that type for 1 food.

An optional `before_action_space` FireTrigger on the market host. Firing pays 1 food
(directly, or by liquidating convertible goods) and bumps the market frame's `gained`
by 1 (the Cowherd idiom), so the extra animal flows through the SAME accommodation
frontier as the market's own. Owner-gated; once per use; declinable (the market's
CommitAccommodate is the decline). Not offered when the 1 food is unpayable.
"""
import agricola.cards.animal_dealer  # noqa: F401  (registers the card)

from agricola.actions import (
    CommitAccommodate,
    CommitFoodPayment,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pasture import Pasture
from agricola.pending import PendingFoodPayment, PendingSheepMarket
from agricola.replace import fast_replace
from agricola.setup import setup
from tests.factories import with_current_player, with_resources, with_space

CARD_ID = "animal_dealer"
_FT = FireTrigger(card_id=CARD_ID)


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


def _sheep_market_state(*, accumulated, owner=0, **res):
    s = setup(seed=0)
    s = with_current_player(s, owner)
    s = with_space(s, "sheep_market", revealed=True, accumulated_amount=accumulated)
    s = with_resources(s, owner, **res)
    s = _give(s, owner)
    s = _give_capacity(s, owner, [(0, 0), (0, 1)])   # capacity 4 → keep everything
    return s


def _keep_all(state):
    keep = max((a for a in legal_actions(state) if isinstance(a, CommitAccommodate)),
               key=lambda a: a.sheep)
    state = step(state, keep)
    if state.pending_stack and isinstance(state.pending_stack[-1], PendingSheepMarket):
        assert legal_actions(state) == [Stop()]
        state = step(state, Stop())
    return state


def test_registration():
    assert CARD_ID in OCCUPATIONS
    s = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) is s


def test_fire_buys_extra_sheep_food_on_hand():
    s = _sheep_market_state(accumulated=1, food=1)
    s = step(s, PlaceWorker(space="sheep_market"))
    assert s.pending_stack[-1].gained == 1          # market's own sheep only
    assert _FT in legal_actions(s)                  # the optional buy is offered

    s = step(s, _FT)
    assert s.players[0].resources.food == 0         # 1 food paid
    assert s.pending_stack[-1].gained == 2          # bumped: extra sheep staged
    assert _FT not in legal_actions(s)              # once per use

    s = _keep_all(s)
    assert s.players[0].animals.sheep == 2          # 1 market + 1 bought, both kept


def test_can_decline():
    """Declining (accommodating without firing) keeps the market's animals only and
    pays no food."""
    s = _sheep_market_state(accumulated=1, food=1)
    s = step(s, PlaceWorker(space="sheep_market"))
    assert _FT in legal_actions(s)
    s = _keep_all(s)                                # decline: accommodate directly
    assert s.players[0].animals.sheep == 1
    assert s.players[0].resources.food == 1         # untouched


def test_not_offered_without_payable_food():
    """0 food and nothing convertible → the buy is not offered."""
    s = _sheep_market_state(accumulated=1, food=0)   # no food, no grain/veg/animals
    s = step(s, PlaceWorker(space="sheep_market"))
    assert _FT not in legal_actions(s)


def test_liquidation_path():
    """0 food but 1 grain → payable by liquidation; firing raises the food via a
    PendingFoodPayment, whose resume debits it and bumps `gained`."""
    s = _sheep_market_state(accumulated=1, food=0, grain=1)
    s = step(s, PlaceWorker(space="sheep_market"))
    assert _FT in legal_actions(s)

    s = step(s, _FT)
    assert isinstance(s.pending_stack[-1], PendingFoodPayment)   # food not on hand

    pays = [a for a in legal_actions(s) if isinstance(a, CommitFoodPayment)]
    assert len(pays) == 1                            # convert the 1 grain
    s = step(s, pays[0])
    assert s.pending_stack[-1].gained == 2           # bumped after payment
    assert s.players[0].resources.food == 0          # raised then spent on the animal
    assert s.players[0].resources.grain == 0         # the grain was liquidated

    s = _keep_all(s)
    assert s.players[0].animals.sheep == 2


def test_only_owner_is_offered():
    """P1 owns Animal Dealer; P0 (active, no card) uses Sheep Market → no buy offered."""
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = with_space(s, "sheep_market", revealed=True, accumulated_amount=1)
    s = with_resources(s, 0, food=5)
    s = _give(s, 1)                                   # P1 owns it, not the actor
    s = step(s, PlaceWorker(space="sheep_market"))
    assert _FT not in legal_actions(s)
    assert s.pending_stack[-1].gained == 1
