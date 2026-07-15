"""Tests for Moral Crusader (occupation, B106).

Card text: "Immediately before the start of each round, if there are goods on
the remaining round space that are promised to you, you get 1 food."

User ruling 2026-07-15: "immediately before the start of each round" names the
SAME instant as the preparation ladder's `before_round` window (Small Animal
Breeder / Civic Facade's rung); no distinct earlier instant. A mandatory,
choice-free `register_auto("before_round", ...)`: at that window
`round_number` still names the just-completed round, so the entering round's
schedule slot index is `round_number` itself. Eligibility = the OWNER's
`future_resources[round_number]` non-empty OR the entering slot's
`future_rewards` ANIMALS non-empty (animals are goods; a scheduled EFFECT id
alone is not goods). Payout: +1 food.

Exercised by driving `_complete_preparation` (the compat seam that walks the
whole ladder: fires before_round, increments at `__round_setup__`, collects
the round-space goods at `__collect__`, refills), mirroring
tests/test_card_small_animal_breeder.py. Because `__collect__` CLEARS the
consumed `future_resources` slot, the card paying out at all is itself the
ordering witness that the check ran BEFORE collection — an after-collection
read would find the slot already empty.
"""
from __future__ import annotations

import agricola.cards.moral_crusader  # noqa: F401

from agricola.cards.schedules import (
    schedule_animals,
    schedule_effect,
    schedule_resources,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import Phase
from agricola.engine import _complete_preparation
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.setup import setup

CARD_ID = "moral_crusader"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _hand_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, hand_occupations=p.hand_occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _prep(state, round_number):
    """A PREPARATION state about to ENTER `round_number` (so
    _complete_preparation fires before_round pre-increment, then increments
    to it and collects that round's scheduled goods)."""
    return fast_replace(state, phase=Phase.PREPARATION, round_number=round_number - 1)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_occupation_with_no_cost_or_vps():
    assert CARD_ID in OCCUPATIONS
    spec = OCCUPATIONS[CARD_ID]
    # Occupation: no cost / prereq / passing / printed VPs.
    assert getattr(spec, "vps", 0) == 0


def test_registered_as_before_round_auto():
    # "IMMEDIATELY BEFORE the start of each round" -> the before_round window
    # (user ruling 2026-07-15: the same instant as "before the start of each
    # round" — no distinct earlier instant).
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("before_round", ())}
    assert CARD_ID in auto_ids
    assert CARD_ID not in {e.card_id for e in AUTO_EFFECTS.get("start_of_round", ())}
    # Mandatory + choice-free: an auto, never surfaced as a FireTrigger.
    from agricola.cards.triggers import TRIGGERS
    trigger_ids = {e.card_id for e in TRIGGERS.get("before_round", ())}
    assert CARD_ID not in trigger_ids


def test_on_play_is_a_noop():
    s = setup(0)
    before = s.players[0].resources
    s2 = OCCUPATIONS[CARD_ID].on_play(s, 0)
    assert s2.players[0].resources == before


# ---------------------------------------------------------------------------
# Real-flow effect via _complete_preparation
# ---------------------------------------------------------------------------

def test_income_when_goods_scheduled_on_entering_round():
    # 1 food promised on the entering round's space -> +1 card food at
    # before_round, and the scheduled food itself lands at __collect__: +2
    # total by the time WORK begins. The card paying at all pins the
    # before-collection read: __collect__ clears the slot, so an
    # after-collection check would have found it empty.
    s = _own_occ(setup(0), 0, CARD_ID)
    s = schedule_resources(s, 0, [4], Resources(food=1))
    s = _prep(s, 4)
    before = s.players[0].resources.food
    after = _complete_preparation(s)
    assert after.round_number == 4
    assert after.players[0].resources.food == before + 2  # 1 card + 1 scheduled
    # The consumed slot cleared; a choice-free auto pushes no frame.
    assert after.players[0].future_resources[3] == Resources()
    assert after.pending_stack == ()
    assert after.phase is Phase.WORK


def test_non_food_goods_also_qualify():
    # "Goods" is any good, not just food: 1 wood promised on the entering
    # round -> +1 food from the card (plus the wood itself).
    s = _own_occ(setup(0), 0, CARD_ID)
    s = schedule_resources(s, 0, [5], Resources(wood=1))
    s = _prep(s, 5)
    before = s.players[0].resources
    after = _complete_preparation(s)
    assert after.players[0].resources.food == before.food + 1
    assert after.players[0].resources.wood == before.wood + 1


def test_no_income_when_goods_scheduled_only_on_later_round():
    # Goods promised on round 6 only; entering round 4 -> nothing this round.
    s = _own_occ(setup(0), 0, CARD_ID)
    s = schedule_resources(s, 0, [6], Resources(food=1))
    s = _prep(s, 4)
    before = s.players[0].resources.food
    after = _complete_preparation(s)
    assert after.players[0].resources.food == before
    # The round-6 promise is untouched (still waiting).
    assert after.players[0].future_resources[5] == Resources(food=1)


def test_scheduled_animals_are_goods():
    # ANIMALS promised on the entering round's space are goods too: +1 food,
    # and the sheep itself is granted at collection.
    s = _own_occ(setup(0), 0, CARD_ID)
    s = schedule_animals(s, 0, [4], Animals(sheep=1))
    s = _prep(s, 4)
    before_food = s.players[0].resources.food
    before_sheep = s.players[0].animals.sheep
    after = _complete_preparation(s)
    assert after.players[0].resources.food == before_food + 1
    assert after.players[0].animals.sheep == before_sheep + 1


def test_effect_only_schedule_is_not_goods():
    # A scheduled EFFECT id alone (e.g. Handplow's deferred plow) is not
    # goods -> no income.
    s = _own_occ(setup(0), 0, CARD_ID)
    s = schedule_effect(s, 0, [4], "some_effect_card")
    s = _prep(s, 4)
    before = s.players[0].resources.food
    after = _complete_preparation(s)
    assert after.players[0].resources.food == before


def test_no_income_when_nothing_scheduled():
    s = _own_occ(setup(0), 0, CARD_ID)
    s = _prep(s, 4)
    before = s.players[0].resources.food
    after = _complete_preparation(s)
    assert after.players[0].resources.food == before


# ---------------------------------------------------------------------------
# Scoping — "promised to YOU", owner only, each qualifying round
# ---------------------------------------------------------------------------

def test_opponent_schedule_pays_owner_nothing():
    # Player 0 owns the card; the promise is on player 1's schedule ("promised
    # to you" reads the OWNER's schedule only). No card food for anyone: p0
    # has no promise, p1 has no card.
    s = _own_occ(setup(0), 0, CARD_ID)
    s = schedule_resources(s, 1, [4], Resources(food=1))
    s = _prep(s, 4)
    f0 = s.players[0].resources.food
    f1 = s.players[1].resources.food
    after = _complete_preparation(s)
    assert after.players[0].resources.food == f0            # owner: nothing
    assert after.players[1].resources.food == f1 + 1        # scheduled food only


def test_fires_each_qualifying_round():
    # Promises on rounds 3 AND 4 -> the card pays on both round entries.
    s = _own_occ(setup(0), 0, CARD_ID)
    s = schedule_resources(s, 0, [3, 4], Resources(wood=1))
    s = _prep(s, 3)
    f0 = s.players[0].resources.food
    after3 = _complete_preparation(s)
    assert after3.players[0].resources.food == f0 + 1
    # Enter round 4 next: fires again off the round-4 promise.
    after4 = _complete_preparation(fast_replace(after3, phase=Phase.PREPARATION))
    assert after4.round_number == 4
    assert after4.players[0].resources.food == f0 + 2


def test_hand_only_is_inert():
    # In hand but not played: no income (only the scheduled good lands).
    s = _hand_occ(setup(0), 0, CARD_ID)
    s = schedule_resources(s, 0, [4], Resources(food=1))
    s = _prep(s, 4)
    before = s.players[0].resources.food
    after = _complete_preparation(s)
    assert after.players[0].resources.food == before + 1  # scheduled food only
