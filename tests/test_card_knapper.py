import agricola.cards.knapper  # noqa: F401  (registers the card)

"""Tests for Knapper (occupation, Artifex A124).

Card text: "Each time before you use an action space card on round spaces 5 to 7,
you get 1 stone."

A ``before_action_space`` automatic effect firing when the used space's
``revealed_round`` is in {5, 6, 7}; +1 stone. Western Quarry is the one atomic
round-5–7 space, hosted via ``register_action_space_hook``. Covers the round
filter across 5/6/7, the out-of-range boundary, the hook scope, and the not-owned
no-op.
"""
import pytest

from agricola.actions import PlaceWorker
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import (
    AUTO_EFFECTS,
    OWN_ACTION_HOOK_CARDS,
    should_host_space,
)
from agricola.engine import step
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_current_player, with_space

_POOL = CardPool(
    occupations=("knapper",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return with_current_player(s, 0)


def _own(state, idx=0):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | {"knapper"})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _quarry(state, round_number):
    """Reveal Western Quarry as the given round space, stocked with 1 stone."""
    return with_space(state, "western_quarry", revealed=True,
                      revealed_round=round_number, accumulated=Resources(stone=1))


# ---------------------------------------------------------------------------
# Registration + hook scope
# ---------------------------------------------------------------------------

def test_registration_and_hook():
    assert "knapper" in OCCUPATIONS
    autos = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", [])}
    assert "knapper" in autos
    # Hooks Western Quarry only (the atomic round-5–7 space); the other two are
    # already-hosted spaces that need no hook.
    assert "knapper" in OWN_ACTION_HOOK_CARDS.get("western_quarry", set())
    for atomic in ("forest", "clay_pit", "reed_bank", "eastern_quarry"):
        assert "knapper" not in OWN_ACTION_HOOK_CARDS.get(atomic, set())


def test_hosts_western_quarry_when_owned():
    s = _own(_quarry(_state(), 6))
    assert should_host_space(s, "western_quarry", 0)


# ---------------------------------------------------------------------------
# Fires on round spaces 5/6/7 -> +1 stone (via a real Western Quarry placement)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("round_number", [5, 6, 7])
def test_grants_one_stone_on_rounds_5_6_7(round_number):
    s = _own(_quarry(_state(), round_number))
    before = s.players[0].resources.stone
    s = step(s, PlaceWorker(space="western_quarry"))
    # Hosted (before-phase); the auto fired at the push. The accumulated quarry
    # stone is not on the player yet (that comes at Proceed), so this +1 is Knapper.
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert s.players[0].resources.stone == before + 1


def test_no_stone_outside_rounds_5_to_7():
    # Western Quarry is still hooked (hosted) at round 8, but the round filter
    # rejects it -> no Knapper stone in the before-phase.
    s = _own(_quarry(_state(), 8))
    before = s.players[0].resources.stone
    s = step(s, PlaceWorker(space="western_quarry"))
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert s.players[0].resources.stone == before


def test_not_owned_stays_atomic():
    # Nobody owns Knapper -> Western Quarry is not hosted; it resolves atomically,
    # yielding only its accumulated stone (no Knapper grant).
    s = _quarry(_state(), 6)
    before = s.players[0].resources.stone
    s = step(s, PlaceWorker(space="western_quarry"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
    assert s.players[0].resources.stone == before + 1   # accumulated only
