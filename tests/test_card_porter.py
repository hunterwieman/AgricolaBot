"""Tests for Porter (occupation, D146).

Card text: "Each time you take at least 4 of the same building resource from an
accumulation space, you get 1 additional building resource of the accumulating type and
1 food."

A Category-3 automatic-income hook on every building-resource accumulation space (forest,
clay_pit, reed_bank, western_quarry, eastern_quarry): an after_action_space auto — when ≥4
of that space's resource was taken (the host frame's `taken`), grant +1 of that resource
and +1 food. Driven end-to-end through the hosted-atomic lifecycle. Threshold is inclusive
at 4; below 4 grants nothing.
"""
import pytest

import agricola.cards.porter  # noqa: F401  (registers the card)

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
    occupations=("porter",) + tuple(f"o{i}" for i in range(20)),
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


def _state_with(space, field, amount, *, own=True):
    s = fast_replace(_card_state(), current_player=0)
    if own:
        s = _own(s, 0, "porter")
    # Quarries are Stage 2/4 spaces (not revealed at round 1); reveal them.
    s = with_space(s, space, accumulated=Resources(**{field: amount}),
                   revealed=True, workers=(0, 0))
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
    assert "porter" in OCCUPATIONS
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("after_action_space", ())}
    assert "porter" in auto_ids
    for space in ("forest", "clay_pit", "reed_bank", "western_quarry", "eastern_quarry"):
        assert "porter" in OWN_ACTION_HOOK_CARDS[space]


@pytest.mark.parametrize("space,field,amount", [
    ("forest", "wood", 4),
    ("clay_pit", "clay", 4),
    ("reed_bank", "reed", 5),
    ("western_quarry", "stone", 4),
    ("eastern_quarry", "stone", 6),
])
def test_bonus_at_or_above_four(space, field, amount):
    s = _state_with(space, field, amount)
    before_good = getattr(s.players[0].resources, field)
    before_food = s.players[0].resources.food
    out = _play_hosted_space(s, space)
    # take (all `amount`) + 1 of the accumulating type, plus 1 food.
    assert getattr(out.players[0].resources, field) == before_good + amount + 1
    assert out.players[0].resources.food == before_food + 1


def test_no_bonus_below_four():
    s = _state_with("forest", "wood", 3)
    before_wood = s.players[0].resources.wood
    before_food = s.players[0].resources.food
    out = _play_hosted_space(s, "forest")
    assert out.players[0].resources.wood == before_wood + 3   # just the take
    assert out.players[0].resources.food == before_food       # no bonus food


def test_not_owned_is_atomic_no_bonus():
    s = _state_with("forest", "wood", 4, own=False)
    before_wood = s.players[0].resources.wood
    before_food = s.players[0].resources.food
    out = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.wood == before_wood + 4
    assert out.players[0].resources.food == before_food
