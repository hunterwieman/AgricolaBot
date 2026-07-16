"""Tests for Pet Lover (D138) — an occupation: each time you use an accumulation
space providing exactly 1 animal, you CAN leave it on the space and get one from the
general supply instead, as well as 3 food and 1 grain.

An optional `before_action_space` FireTrigger on the animal-market host, eligible only
when the space provides exactly 1 animal (`gained == 1`). Firing has two INDEPENDENT
halves: (1) suppress the market's own take — leave the animal on the space
(`accumulated_amount` restored) and zero `gained`; (2) grant a same-type supply animal
(via the accommodation barrier) + 3 food + 1 grain. Owner-gated; once per use;
declinable (the market's CommitAccommodate is the decline, taking the animal normally).
"""
import agricola.cards.pet_lover  # noqa: F401  (registers the card)

import pytest

from agricola.actions import CommitAccommodate, FireTrigger, PlaceWorker, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pasture import Pasture
from agricola.replace import fast_replace
from agricola.setup import setup
from agricola.state import get_space
from tests.factories import with_current_player, with_space

CARD_ID = "pet_lover"
_FT = FireTrigger(card_id=CARD_ID)

_MARKETS = [
    ("sheep_market", "sheep"),
    ("pig_market", "boar"),
    ("cattle_market", "cattle"),
]


def _give(state, idx, cid=CARD_ID):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {cid}) if i == idx
        else state.players[i] for i in range(2)))


def _give_capacity(state, idx, cells):
    fy = state.players[idx].farmyard
    pasture = Pasture(cells=frozenset(cells), num_stables=0, capacity=2 * len(cells))
    p = fast_replace(state.players[idx], farmyard=fast_replace(fy, pastures=(pasture,)))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _market_state(space="sheep_market", *, accumulated=1, owner=0):
    s = setup(seed=0)
    s = with_current_player(s, owner)
    s = with_space(s, space, revealed=True, accumulated_amount=accumulated)
    s = _give(s, owner)
    s = _give_capacity(s, owner, [(0, 0), (0, 1)])   # capacity 4 (one type) → keep the animal
    return s


def _finish_market(state):
    """Accommodate (keep everything), then Stop to pop the market host."""
    keep = max((a for a in legal_actions(state) if isinstance(a, CommitAccommodate)),
               key=lambda a: a.sheep + a.boar + a.cattle)
    state = step(state, keep)
    if state.pending_stack and state.pending_stack[-1].phase == "after":
        assert legal_actions(state) == [Stop()]
        state = step(state, Stop())
    return state


def test_registration():
    assert CARD_ID in OCCUPATIONS
    s = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) is s   # no on-play effect


@pytest.mark.parametrize("space,attr", _MARKETS)
def test_fire_leaves_animal_and_grants_supply(space, attr):
    s = _market_state(space, accumulated=1)
    food0 = s.players[0].resources.food
    grain0 = s.players[0].resources.grain
    n0 = getattr(s.players[0].animals, attr)

    s = step(s, PlaceWorker(space=space))
    assert s.pending_stack[-1].gained == 1          # "providing exactly 1 animal"
    assert _FT in legal_actions(s)

    s = step(s, _FT)
    # (1) Suppression: the 1 animal is LEFT on the space; the take channel is zeroed.
    assert get_space(s.board, space).accumulated_amount == 1
    assert s.pending_stack[-1].gained == 0
    # (2) Pet Lover's own reward: 1 same-type supply animal (housed) + 3 food + 1 grain.
    assert getattr(s.players[0].animals, attr) == n0 + 1
    assert s.players[0].resources.food == food0 + 3
    assert s.players[0].resources.grain == grain0 + 1
    assert _FT not in legal_actions(s)              # once per use

    s = _finish_market(s)
    assert getattr(s.players[0].animals, attr) == n0 + 1          # kept
    assert get_space(s.board, space).accumulated_amount == 1      # still on the space


def test_decline_takes_animal_normally():
    """Declining (accommodating without firing) sweeps the space's own animal and
    grants no food/grain — the base 'you cannot leave animals on the space' rule."""
    s = _market_state("sheep_market", accumulated=1)
    food0 = s.players[0].resources.food
    grain0 = s.players[0].resources.grain
    s = step(s, PlaceWorker(space="sheep_market"))
    assert _FT in legal_actions(s)

    s = _finish_market(s)                            # decline: accommodate directly
    assert s.players[0].animals.sheep == 1                       # took the space's sheep
    assert get_space(s.board, "sheep_market").accumulated_amount == 0   # swept off
    assert s.players[0].resources.food == food0                 # no bonus
    assert s.players[0].resources.grain == grain0


def test_not_offered_when_more_than_one():
    s = _market_state("sheep_market", accumulated=2)
    s = step(s, PlaceWorker(space="sheep_market"))
    assert s.pending_stack[-1].gained == 2
    assert _FT not in legal_actions(s)              # not "exactly 1"


def test_not_offered_when_empty():
    s = _market_state("sheep_market", accumulated=0)
    s = step(s, PlaceWorker(space="sheep_market"))
    assert s.pending_stack[-1].gained == 0
    assert _FT not in legal_actions(s)


def test_only_owner_is_offered():
    """P1 owns Pet Lover; P0 (active, no card) uses Sheep Market → not offered."""
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = with_space(s, "sheep_market", revealed=True, accumulated_amount=1)
    s = _give(s, 1)                                  # P1 owns it, not the actor
    s = step(s, PlaceWorker(space="sheep_market"))
    assert _FT not in legal_actions(s)
