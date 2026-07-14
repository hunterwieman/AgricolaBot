"""Tests for Small Animal Breeder (occupation, C111).

Card text: "Before the start of each round, if you have food equal to or higher
than the current round number (e.g., 8+ food in round 8), you get 1 food."

A Category-7 start-of-round automatic effect (the preparation ladder's
start_of_round window, ruling 54, 2026-07-14): fired frame-lessly for the owner —
if their (post-distribution) food >= the round being entered, +1 food. Mandatory
and choice-free (register_auto), and re-checked each round so the income turns
on/off as food rises/falls relative to the advancing round number.

Exercised by driving `_complete_preparation` (the compat seam that walks the whole
ladder: distributes the round's resources at `__collect__`, increments
round_number at `__round_setup__`, then fires the start_of_round window's autos),
mirroring tests/test_cards_category7.py's Scullery / Small-scale Farmer.
"""
from __future__ import annotations

import agricola.cards.small_animal_breeder  # noqa: F401

from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import Phase
from agricola.engine import _complete_preparation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup

CARD_ID = "small_animal_breeder"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_food(state, idx, food):
    p = state.players[idx]
    p = fast_replace(p, resources=fast_replace(p.resources, food=food))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _prep(state, round_number):
    """A PREPARATION state about to ENTER `round_number` (so _complete_preparation
    increments to it and then fires the start_of_round autos)."""
    return fast_replace(state, phase=Phase.PREPARATION, round_number=round_number - 1)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_occupation_with_no_cost_or_vps():
    assert CARD_ID in OCCUPATIONS
    spec = OCCUPATIONS[CARD_ID]
    # Occupation: no cost / prereq / passing / printed VPs.
    assert getattr(spec, "vps", 0) == 0


def test_registered_as_start_of_round_auto():
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("start_of_round", ())}
    assert CARD_ID in auto_ids
    # Auto effect is choice-free (not surfaced as a FireTrigger / mandatory tag);
    # it fires mechanically at the window with no frame, so there is no separate
    # hosting registration to assert.
    from agricola.cards.triggers import TRIGGERS
    trigger_ids = {e.card_id for e in TRIGGERS.get("start_of_round", ())}
    assert CARD_ID not in trigger_ids


def test_on_play_is_a_noop():
    s = setup(0)
    before = s.players[0].resources
    s2 = OCCUPATIONS[CARD_ID].on_play(s, 0)
    assert s2.players[0].resources == before


# ---------------------------------------------------------------------------
# Real-flow effect via _complete_preparation
# ---------------------------------------------------------------------------

def test_income_when_food_equals_round_number():
    # Food == round number → +1 food (boundary: "equal to or higher").
    s = _own_occ(setup(0), 0, CARD_ID)
    s = _prep(s, 3)
    s = _set_food(s, 0, 3)
    before = s.players[0].resources.food
    after = _complete_preparation(s)
    assert after.round_number == 3
    assert after.players[0].resources.food == before + 1
    # A choice-free auto pushes no frame: the ladder completed, straight to WORK.
    assert after.pending_stack == ()
    assert after.phase is Phase.WORK


def test_income_when_food_above_round_number():
    s = _own_occ(setup(0), 0, CARD_ID)
    s = _prep(s, 5)
    s = _set_food(s, 0, 9)
    before = s.players[0].resources.food
    after = _complete_preparation(s)
    assert after.players[0].resources.food == before + 1


def test_no_income_when_food_below_round_number():
    # Food == round - 1 → ineligible, no income (boundary on the other side).
    s = _own_occ(setup(0), 0, CARD_ID)
    s = _prep(s, 5)
    s = _set_food(s, 0, 4)
    before = s.players[0].resources.food
    after = _complete_preparation(s)
    assert after.players[0].resources.food == before


# ---------------------------------------------------------------------------
# Scoping — owner only, and re-checked each round
# ---------------------------------------------------------------------------

def test_only_owner_gets_income():
    # Player 0 owns the card; player 1 does not, even though both have plenty of food.
    s = _own_occ(setup(0), 0, CARD_ID)
    s = _prep(s, 4)
    s = _set_food(s, 0, 10)
    s = _set_food(s, 1, 10)
    f0, f1 = s.players[0].resources.food, s.players[1].resources.food
    after = _complete_preparation(s)
    assert after.players[0].resources.food == f0 + 1
    assert after.players[1].resources.food == f1   # non-owner unaffected


def test_condition_rechecked_each_round_off_then_on():
    s = _own_occ(setup(0), 0, CARD_ID)
    # Entering round 8 with 7 food: below threshold → no income.
    s_lo = _set_food(_prep(s, 8), 0, 7)
    f_lo = s_lo.players[0].resources.food
    assert _complete_preparation(s_lo).players[0].resources.food == f_lo
    # Entering round 8 with 8 food: at threshold → income (same round, re-checked).
    s_hi = _set_food(_prep(s, 8), 0, 8)
    f_hi = s_hi.players[0].resources.food
    assert _complete_preparation(s_hi).players[0].resources.food == f_hi + 1


def test_uses_post_distribution_food_total():
    # The auto fires AFTER the round's future_resources are added, so a player who
    # is below threshold pre-distribution but reaches it via the round's grant gets
    # the income. Schedule +2 food into the round-4 slot (index 3) and start at 2.
    s = _own_occ(setup(0), 0, CARD_ID)
    s = _prep(s, 4)            # entering round 4 → threshold 4
    s = _set_food(s, 0, 2)     # only 2 food pre-distribution (below 4)
    p = s.players[0]
    fr = list(p.future_resources)
    fr[3] = fr[3] + Resources(food=2)   # round-4 slot grants +2 food
    p = fast_replace(p, future_resources=tuple(fr))
    s = fast_replace(s, players=(p, s.players[1]))
    after = _complete_preparation(s)
    # 2 + 2 (distribution) = 4 == threshold → eligible → +1.
    assert after.players[0].resources.food == 5
