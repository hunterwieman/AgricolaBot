"""Tests for Storehouse Steward (occupation, A146).

Card text: "Each time you take exactly 2/3/4/5 food from a food accumulation space, you
also get 1 stone/reed/clay/wood. (If you take 6 or more food, you do not get a bonus
good)."

A Category-3 automatic-income hook on Fishing (the only food accumulation space in the
2-player card game): the bonus good is banded by the pre-take food count (2→stone,
3→reed, 4→clay, 5→wood; nothing at 6+). Driven end-to-end through the hosted-atomic
lifecycle.
"""
import pytest

import agricola.cards.storehouse_steward  # noqa: F401  (registers the card)

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from tests.factories import with_space

_POOL = CardPool(
    occupations=("storehouse_steward",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


def _own(state, idx, *occupations):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | set(occupations))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _state_with_fishing(amount, *, own=True):
    s = fast_replace(_card_state(), current_player=0)
    if own:
        s = _own(s, 0, "storehouse_steward")
    s = with_space(s, "fishing", accumulated_amount=amount, workers=(0, 0))
    return s


def _play_hosted_space(state, space_id):
    state = step(state, PlaceWorker(space=space_id))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert Proceed() in legal_actions(state)
    state = step(state, Proceed())
    state = step(state, Stop())
    assert not state.pending_stack
    return state


def test_registration():
    assert "storehouse_steward" in OCCUPATIONS
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert "storehouse_steward" in auto_ids
    assert "storehouse_steward" in OWN_ACTION_HOOK_CARDS["fishing"]


@pytest.mark.parametrize("amount,field", [(2, "stone"), (3, "reed"), (4, "clay"), (5, "wood")])
def test_bonus_good_by_band(amount, field):
    s = _state_with_fishing(amount)
    before_good = getattr(s.players[0].resources, field)
    before_food = s.players[0].resources.food
    out = _play_hosted_space(s, "fishing")
    assert getattr(out.players[0].resources, field) == before_good + 1   # the bonus good
    assert out.players[0].resources.food == before_food + amount         # the food take


def test_six_or_more_food_no_bonus():
    s = _state_with_fishing(6)
    r0 = s.players[0].resources
    out = _play_hosted_space(s, "fishing")
    r1 = out.players[0].resources
    assert r1.food == r0.food + 6
    # No building-resource bonus at all.
    assert (r1.stone, r1.reed, r1.clay, r1.wood) == (r0.stone, r0.reed, r0.clay, r0.wood)


def test_one_food_no_bonus():
    s = _state_with_fishing(1)
    r0 = s.players[0].resources
    out = _play_hosted_space(s, "fishing")
    r1 = out.players[0].resources
    assert r1.food == r0.food + 1
    assert (r1.stone, r1.reed, r1.clay, r1.wood) == (r0.stone, r0.reed, r0.clay, r0.wood)


def test_not_owned_is_atomic_no_bonus():
    s = _state_with_fishing(2, own=False)
    r0 = s.players[0].resources
    out = step(s, PlaceWorker(space="fishing"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    r1 = out.players[0].resources
    assert r1.food == r0.food + 2
    assert r1.stone == r0.stone
