"""Tests for FutureReward (CARD_IMPLEMENTATION_PLAN.md II.5) — the card-only sibling
of `future_resources` that carries animals + round-start effect hooks, distributed
at round start by `engine._collect_future_rewards`.

Goods/food schedules still ride on the Family-reachable `future_resources` (the
Well's structure, untouched here); FutureReward adds only what a Resources slot
cannot — animals (collected + accommodated) and effect-card hooks (a card id whose
round-start effect fires). Card-only and default-empty, so the Family game is
byte-identical and the C++ Family engine is untouched (no canonical churn).

These tests drive `_complete_preparation` directly across a round boundary
(mirroring tests/test_cards_preparation_hook.py) and check the FutureReward
dataclass algebra in isolation.
"""
from __future__ import annotations

from agricola.canonical import dumps, loads
from agricola.cards.triggers import register_round_start_effect, ROUND_START_EFFECTS
from agricola.constants import Phase
from agricola.engine import _collect_future_rewards, _complete_preparation
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.setup import setup
from agricola.state import FutureReward, GameState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_future_rewards(state, idx, rewards):
    p = fast_replace(state.players[idx], future_rewards=rewards)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _prep_state(round_number=1):
    """A PREPARATION-phase state poised for `_complete_preparation`: increments to
    `round_number+1` and distributes that round's slot. We move the game's
    round-card count past `round_number` by setting round_number directly; the
    refill/transition machinery doesn't depend on the count for this test."""
    state = setup(0)
    return fast_replace(state, round_number=round_number, phase=Phase.PREPARATION)


# ---------------------------------------------------------------------------
# FutureReward dataclass algebra
# ---------------------------------------------------------------------------

def test_future_reward_default_is_falsy():
    assert not FutureReward()
    assert bool(FutureReward(animals=Animals(boar=1)))
    assert bool(FutureReward(effect_card_ids=frozenset({"x"})))


def test_future_reward_add_is_additive():
    a = FutureReward(animals=Animals(sheep=1), effect_card_ids=frozenset({"p"}))
    b = FutureReward(animals=Animals(sheep=2, boar=1), effect_card_ids=frozenset({"q"}))
    s = a + b
    assert s.animals == Animals(sheep=3, boar=1)
    assert s.effect_card_ids == frozenset({"p", "q"})


def test_future_rewards_default_length_14():
    state = setup(0)
    assert len(state.players[0].future_rewards) == 14
    assert all(not r for r in state.players[0].future_rewards)


# ---------------------------------------------------------------------------
# Family byte-identity — future_rewards is default-skipped in canonical JSON
# ---------------------------------------------------------------------------

def test_family_canonical_omits_future_rewards():
    state = setup(0)
    j = dumps(state)
    assert "future_rewards" not in j         # card-only field, default → omitted
    assert "future_resources" in j           # Family-reachable, always present
    assert loads(j) == state                 # round-trips


def test_family_preparation_byte_identical():
    # With no future_rewards populated, _collect_future_rewards is a no-op and
    # returns the SAME object (the Family fast path).
    state = _prep_state(round_number=2)
    out = _collect_future_rewards(state, slot=2)
    assert out is state


# ---------------------------------------------------------------------------
# Animals distribution + accommodation at round start
# ---------------------------------------------------------------------------

def test_collect_future_rewards_animals_accommodated():
    # Promise 2 sheep into the slot for the round being entered; they fit the house
    # pet + a default farm, so all are kept.
    state = _prep_state(round_number=3)
    slot = 3   # entering round 4 → slot index 3
    rewards = list(state.players[0].future_rewards)
    rewards[slot] = FutureReward(animals=Animals(sheep=1))
    state = _set_future_rewards(state, 0, tuple(rewards))
    sheep0 = state.players[0].animals.sheep
    out = _collect_future_rewards(state, slot)
    assert out.players[0].animals.sheep == sheep0 + 1
    # The consumed slot is cleared.
    assert not out.players[0].future_rewards[slot]


def test_collect_future_rewards_animals_overflow_trimmed():
    # Promise more animals than the farm can hold → keep the best accommodatable
    # configuration (no decision; preparation is decision-free). A default farm has
    # only the house pet (1 flexible slot), so a flood of sheep is trimmed to fit.
    state = _prep_state(round_number=1)
    slot = 1
    rewards = list(state.players[0].future_rewards)
    rewards[slot] = FutureReward(animals=Animals(sheep=20))
    state = _set_future_rewards(state, 0, tuple(rewards))
    out = _collect_future_rewards(state, slot)
    a = out.players[0].animals
    total = a.sheep + a.boar + a.cattle
    # At least one kept (house pet), and not the impossible 20.
    assert 1 <= total < 20


# ---------------------------------------------------------------------------
# Effect-card round-start hooks fire
# ---------------------------------------------------------------------------

def test_collect_future_rewards_fires_effect_hook():
    # Register a throwaway round-start effect, schedule it, and confirm it runs.
    fired = []
    register_round_start_effect("_test_effect", lambda s, i: (fired.append(i) or s))
    try:
        state = _prep_state(round_number=2)
        slot = 2
        rewards = list(state.players[0].future_rewards)
        rewards[slot] = FutureReward(effect_card_ids=frozenset({"_test_effect"}))
        state = _set_future_rewards(state, 0, tuple(rewards))
        _collect_future_rewards(state, slot)
        assert fired == [0]
    finally:
        ROUND_START_EFFECTS.pop("_test_effect", None)


def test_complete_preparation_distributes_future_rewards():
    # End-to-end through _complete_preparation: an effect scheduled into the round
    # being entered fires when preparation completes.
    fired = []
    register_round_start_effect("_test_prep_effect", lambda s, i: (fired.append(i) or s))
    try:
        state = _prep_state(round_number=4)   # _complete_preparation → round 5, slot 4
        rewards = list(state.players[1].future_rewards)
        rewards[4] = FutureReward(effect_card_ids=frozenset({"_test_prep_effect"}))
        state = _set_future_rewards(state, 1, tuple(rewards))
        out = _complete_preparation(state)
        assert out.round_number == 5
        assert fired == [1]
        assert not out.players[1].future_rewards[4]   # slot cleared
    finally:
        ROUND_START_EFFECTS.pop("_test_prep_effect", None)
