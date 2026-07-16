"""Tests for Material Deliveryman (C163) — an occupation: each time ANY player takes
5/6/7/8+ goods from an accumulation space, the OWNER gets 1 wood/clay/reed/stone.

An `any_player` `after_action_space` automatic effect (Refactor A): the reward is
DETERMINED by the total good count actually TAKEN (positional mapping, not a free
choice): 5→wood, 6→clay, 7→reed, 8+→stone, <5→nothing. Total goods are read from a
building host's `taken` sum, Fishing's `taken.food`, or a market's staged `gained`.
Atomic spaces are hooked any_player; markets are always hosted.

Because the reward may share a type with the take (Forest's wood take vs the 5→wood
tier), the helper drives through the take then subtracts the wood the ACTOR-who-is-
owner swept from Forest, isolating the reward.
"""
import agricola.cards.material_deliveryman  # noqa: F401  (registers the card)

from agricola.actions import CommitAccommodate, PlaceWorker, Proceed
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from tests.factories import with_current_player, with_space

CARD_ID = "material_deliveryman"


def _give(state, idx, cid=CARD_ID):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {cid}) if i == idx
        else state.players[i] for i in range(2)))


def _drive_to_after(state):
    """Drive the hosted lifecycle to the after-window, where the after-auto fires:
    Proceed runs the take for an atomic host; CommitAccommodate flips a market host."""
    if isinstance(state.pending_stack[-1], PendingActionSpace):
        return step(state, Proceed())
    accs = [a for a in legal_actions(state) if isinstance(a, CommitAccommodate)]
    return step(state, accs[0])


def _forest_delta(wood_amt, owner=0, actor=None):
    """Owner owns the card; `actor` (default owner) uses Forest stocked with
    `wood_amt`. Return the owner's (wood, clay, reed, stone) REWARD delta — the after
    the take, minus the wood the take itself gave the owner (only when the owner is
    the one who took it)."""
    if actor is None:
        actor = owner
    s = setup(seed=0)
    s = with_current_player(s, actor)
    s = with_space(s, "forest", revealed=True, accumulated=Resources(wood=wood_amt))
    s = _give(s, owner)
    r0 = s.players[owner].resources
    s = step(s, PlaceWorker(space="forest"))
    s = _drive_to_after(s)                       # the take, then the after-auto reward
    r1 = s.players[owner].resources
    # Forest's take put `wood_amt` wood on the ACTOR; subtract it only when the owner
    # is the actor, so what remains is the reward the card granted the owner.
    took_wood = wood_amt if actor == owner else 0
    return (r1.wood - r0.wood - took_wood, r1.clay - r0.clay,
            r1.reed - r0.reed, r1.stone - r0.stone)


def test_registration():
    assert CARD_ID in OCCUPATIONS
    s = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) is s


def test_tier_below_five_nothing():
    assert _forest_delta(4) == (0, 0, 0, 0)


def test_tier_five_wood():
    assert _forest_delta(5) == (1, 0, 0, 0)


def test_tier_six_clay():
    assert _forest_delta(6) == (0, 1, 0, 0)


def test_tier_seven_reed():
    assert _forest_delta(7) == (0, 0, 1, 0)


def test_tier_eight_plus_stone():
    assert _forest_delta(8) == (0, 0, 0, 1)
    assert _forest_delta(9) == (0, 0, 0, 1)   # 8+ all map to stone


def test_any_player_opponent_use():
    """P1 takes 5 goods; the OWNER (P0) gets the wood."""
    delta = _forest_delta(5, owner=0, actor=1)
    assert delta == (1, 0, 0, 0)


def test_market_goods_counted():
    """Animals are goods too: a market staging 5 animals triggers the 5→wood tier.
    The reward (wood) doesn't collide with the cattle take, so the wood delta is it."""
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = with_space(s, "cattle_market", revealed=True, accumulated_amount=5)
    s = _give(s, 0)
    w0 = s.players[0].resources.wood
    s = step(s, PlaceWorker(space="cattle_market"))   # 5 cattle staged on gained
    s = _drive_to_after(s)                             # accommodate → after-auto: +1 wood
    assert s.players[0].resources.wood == w0 + 1
