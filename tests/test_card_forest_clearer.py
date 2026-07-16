"""Tests for Forest Clearer (occupation, B162).

Card text: "Each time you obtain exactly 2/3/4 wood from a wood accumulation space, you
get 1 additional wood and 1/0/1 food."

A Category-3 automatic-income hook on Forest (the only wood accumulation space in the
2-player game): an after_action_space auto banded by the wood taken (the host frame's
`taken`) — 2→+1 wood +1 food, 3→+1 wood, 4→+1 wood +1 food; nothing outside {2,3,4}.
Driven end-to-end through the hosted-atomic lifecycle.
"""
import pytest

import agricola.cards.forest_clearer  # noqa: F401  (registers the card)

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_space

_POOL = CardPool(
    occupations=("forest_clearer",) + tuple(f"o{i}" for i in range(20)),
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


def _state_with_forest(wood, *, own=True):
    s = fast_replace(_card_state(), current_player=0)
    if own:
        s = _own(s, 0, "forest_clearer")
    s = with_space(s, "forest", accumulated=Resources(wood=wood), workers=(0, 0))
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
    assert "forest_clearer" in OCCUPATIONS
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("after_action_space", ())}
    assert "forest_clearer" in auto_ids
    assert "forest_clearer" in OWN_ACTION_HOOK_CARDS["forest"]


@pytest.mark.parametrize("wood,food_bonus", [(2, 1), (3, 0), (4, 1)])
def test_bonus_by_band(wood, food_bonus):
    s = _state_with_forest(wood)
    before_wood = s.players[0].resources.wood
    before_food = s.players[0].resources.food
    out = _play_hosted_space(s, "forest")
    # take (all `wood`) + 1 additional wood from Forest Clearer.
    assert out.players[0].resources.wood == before_wood + wood + 1
    assert out.players[0].resources.food == before_food + food_bonus


@pytest.mark.parametrize("wood", [1, 5])
def test_no_bonus_outside_band(wood):
    s = _state_with_forest(wood)
    before_wood = s.players[0].resources.wood
    before_food = s.players[0].resources.food
    out = _play_hosted_space(s, "forest")
    assert out.players[0].resources.wood == before_wood + wood    # just the take
    assert out.players[0].resources.food == before_food           # no bonus food


def test_not_owned_is_atomic_no_bonus():
    s = _state_with_forest(2, own=False)
    before_wood = s.players[0].resources.wood
    before_food = s.players[0].resources.food
    out = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.wood == before_wood + 2
    assert out.players[0].resources.food == before_food
