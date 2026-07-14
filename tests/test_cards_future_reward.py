"""Tests for FutureReward (CARD_IMPLEMENTATION_PLAN.md II.5) — the card-only sibling
of `future_resources` that carries animals + round-start effect hooks, distributed
by `engine._collect_future_rewards` at the preparation ladder's `__collect__` step
(the new round's first instant, before any window — ruling 54).

Goods/food schedules still ride on the Family-reachable `future_resources` (the
Well's structure, untouched here); FutureReward adds only what a Resources slot
cannot — animals (collected + accommodated) and effect-card hooks (a card id whose
round-start effect fires). Card-only and default-empty, so the Family game is
byte-identical and the C++ Family engine is untouched (no canonical churn).

These tests drive `_collect_future_rewards` directly across a round boundary
(mirroring tests/test_cards_preparation_hook.py) and check the FutureReward
dataclass algebra in isolation.
"""
from __future__ import annotations

from agricola.canonical import dumps, loads
from agricola.cards.triggers import TRIGGERS
from agricola.constants import Phase
from agricola.engine import _collect_future_rewards
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
    """A PREPARATION-phase state poised at a round boundary: the preparation
    ladder's `__collect__` step would distribute the entered round's slot. We set
    round_number directly; the collection machinery doesn't depend on the
    revealed-card count for this test."""
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


def test_collect_future_rewards_animals_overflow_flags_for_barrier():
    # Promise more animals than the farm can hold. _collect_future_rewards no longer
    # trims (the old buggy auto-pick that silently chose for the player); it grants ALL
    # of them — over capacity — via grant_animals and flags the player. The accommodation
    # barrier then reconciles at the next decision. A default farm has only the house pet
    # (1 flexible slot).
    from agricola.engine import _reconcile_accommodation
    from agricola.legality import legal_actions
    from agricola.pending import PendingAccommodate

    state = _prep_state(round_number=1)
    slot = 1
    rewards = list(state.players[0].future_rewards)
    rewards[slot] = FutureReward(animals=Animals(sheep=20))
    state = _set_future_rewards(state, 0, tuple(rewards))

    out = _collect_future_rewards(state, slot)
    # All 20 granted (over capacity), player flagged — NOT trimmed here.
    assert out.players[0].animals == Animals(sheep=20)
    assert out.players[0].animals_need_accommodation
    assert not out.players[0].future_rewards[slot]        # consumed slot cleared

    # The barrier trims to the housable config and surfaces it as a real decision
    # (single-type overflow → exactly one housable config, but still the player's step).
    out, pushed = _reconcile_accommodation(out)
    assert pushed
    assert isinstance(out.pending_stack[-1], PendingAccommodate)
    kept = {(a.sheep, a.boar, a.cattle) for a in legal_actions(out)}
    assert kept == {(1, 0, 0)}


# ---------------------------------------------------------------------------
# Effect-card round-start hooks are NOT force-fired — they are left in the slot for
# an OPTIONAL round_space_collection trigger to consume (a granted sub-action is optional).
# ---------------------------------------------------------------------------

def test_collect_future_rewards_preserves_effect_ids():
    # An effect-only slot is NOT consumed by _collect_future_rewards (which handles
    # animals only): the id survives for the round_space_collection trigger, and since there
    # are no animals the call returns state object-identical.
    state = _prep_state(round_number=2)
    slot = 2
    rewards = list(state.players[0].future_rewards)
    rewards[slot] = FutureReward(effect_card_ids=frozenset({"handplow"}))
    state = _set_future_rewards(state, 0, tuple(rewards))
    out = _collect_future_rewards(state, slot)
    assert out is state                                   # animals-only → no-op here
    assert "handplow" in out.players[0].future_rewards[slot].effect_card_ids


def test_collect_future_rewards_keeps_effect_ids_when_clearing_animals():
    # A slot carrying BOTH animals and an effect id: animals are collected/cleared,
    # the effect id is preserved (it belongs to the trigger, not this collector).
    state = _prep_state(round_number=2)
    slot = 2
    rewards = list(state.players[0].future_rewards)
    rewards[slot] = FutureReward(animals=Animals(sheep=1),
                                 effect_card_ids=frozenset({"handplow"}))
    state = _set_future_rewards(state, 0, tuple(rewards))
    out = _collect_future_rewards(state, slot)
    assert out.players[0].future_rewards[slot].animals == Animals()   # animals cleared
    assert "handplow" in out.players[0].future_rewards[slot].effect_card_ids


def test_scheduled_effect_drives_window_surfacing():
    # A scheduled effect id in the CURRENT round's slot is what makes the card's
    # registered round_space_collection trigger eligible — the schedule, not card ownership
    # per se, gates the window frame (so a played Handplow surfaces only when its
    # plow is due). The eligibility fn reads the slot directly:
    entry = next(e for e in TRIGGERS["round_space_collection"] if e.card_id == "handplow")
    state = setup(0)
    p = fast_replace(state.players[0],
                     minor_improvements=state.players[0].minor_improvements
                     | {"handplow"})
    state = fast_replace(state, players=(p, state.players[1]))
    # Owned but nothing scheduled → not eligible.
    assert not entry.eligibility_fn(state, 0, frozenset())
    rewards = list(state.players[0].future_rewards)
    rewards[state.round_number - 1] = FutureReward(
        effect_card_ids=frozenset({"handplow"}))
    state = _set_future_rewards(state, 0, tuple(rewards))
    # Scheduled for the current round → eligible (this is what drives the
    # PendingHarvestWindow push in the preparation ladder — see
    # tests/test_cards_category8.py for the end-to-end frame drive).
    assert entry.eligibility_fn(state, 0, frozenset())
