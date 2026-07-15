import agricola.cards.mattock  # noqa: F401  (registers the card)

"""Tests for Mattock (minor improvement, Ephipparius E77).

Card text: "Each time you get reed and/or stone from an action space, you get 1
additional clay."

A ``before_action_space`` automatic effect on the reed / stone accumulation spaces
(Reed Bank, Western Quarry, Eastern Quarry) — the only reed/stone yields in the
2-player action-space set — granting +1 clay. Covers each of the three spaces, that
a non-reed/stone space (Forest) does not fire it, and the not-owned no-op.
"""
import pytest

from agricola.actions import PlaceWorker
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS, should_host_space
from agricola.engine import step
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_current_player, with_space

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("mattock",) + tuple(f"m{i}" for i in range(20)),
)

# (space, the accumulated Resources kwarg that stocks it)
_YIELDING = {
    "reed_bank": Resources(reed=1),
    "western_quarry": Resources(stone=1),
    "eastern_quarry": Resources(stone=1),
}


def _state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return with_current_player(s, 0)


def _own(state, idx=0):
    p = fast_replace(state.players[idx],
                     minor_improvements=state.players[idx].minor_improvements | {"mattock"})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _stock(state, space_id):
    return with_space(state, space_id, revealed=True, accumulated=_YIELDING[space_id])


# ---------------------------------------------------------------------------
# Registration + hook scope
# ---------------------------------------------------------------------------

def test_registration_and_hook():
    assert "mattock" in MINORS
    assert MINORS["mattock"].cost == Cost(resources=Resources(wood=1))
    autos = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", [])}
    assert "mattock" in autos
    for space in _YIELDING:
        assert "mattock" in OWN_ACTION_HOOK_CARDS.get(space, set())
    # Not the wood / clay / grain spaces.
    for other in ("forest", "clay_pit", "grain_seeds"):
        assert "mattock" not in OWN_ACTION_HOOK_CARDS.get(other, set())


# ---------------------------------------------------------------------------
# +1 clay on each reed/stone accumulation space
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("space", list(_YIELDING))
def test_grants_one_clay_on_reed_stone_spaces(space):
    s = _own(_stock(_state(), space))
    assert should_host_space(s, space, 0)
    before = s.players[0].resources.clay
    s = step(s, PlaceWorker(space=space))
    # Hosted before-phase: the auto fired at the push. +1 clay (the accumulated
    # reed/stone lands later at Proceed, so it can't confound clay).
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert s.players[0].resources.clay == before + 1


# ---------------------------------------------------------------------------
# Does not fire on a non-reed/stone space
# ---------------------------------------------------------------------------

def test_no_fire_on_forest():
    # Forest yields wood, not reed/stone; Mattock doesn't hook it -> atomic, no clay.
    s = _own(_state())
    before = s.players[0].resources.clay
    s = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
    assert s.players[0].resources.clay == before


def test_not_owned_no_clay():
    # Nobody owns Mattock -> the quarry stays atomic, no bonus clay.
    s = _stock(_state(), "western_quarry")
    before = s.players[0].resources.clay
    s = step(s, PlaceWorker(space="western_quarry"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
    assert s.players[0].resources.clay == before
