"""Tests for Pavior (occupation, B110; Bubulcus Expansion).

Card text: "At the end of each preparation phase, if you have at least 1 stone in
your supply, you get 1 food. In round 14, you get 1 vegetable instead."

A choice-free `start_of_round` automatic effect (Category 7, the start-of-round
phase hook). The income is driven through the real `_complete_preparation`
round-boundary transition, mirroring tests/test_card_interim_storage.py /
tests/test_cards_category7.py (Scullery). "At the end of each preparation phase"
is exactly the start-of-round hook: by the time these autos fire, round_number is
already incremented to the round being entered, so `state.round_number` is the
current round — and round 14 (NUM_ROUNDS, the final round) grants a vegetable.
"""
from __future__ import annotations

import pytest

import agricola.cards.pavior  # noqa: F401  (registers the card)

from agricola.actions import Proceed
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, START_OF_ROUND_CARDS
from agricola.constants import NUM_ROUNDS, Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingPreparation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup, setup_env

CARD_ID = "pavior"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _set_res(state, idx, res: Resources):
    p = state.players[idx]
    p = fast_replace(p, resources=res)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _enter_round(state, idx, *, from_round: int):
    """Set round_number=from_round and run the real `_complete_preparation` to
    enter round from_round+1, firing the player's start_of_round autos."""
    state = fast_replace(state, round_number=from_round, phase=Phase.PREPARATION)
    return _complete_preparation(state)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_occupation():
    assert CARD_ID in OCCUPATIONS
    # No on-play effect: playing it leaves resources untouched.
    s = setup(0)
    before = s.players[0].resources
    s2 = OCCUPATIONS[CARD_ID].on_play(s, 0)
    assert s2.players[0].resources == before


def test_registered_on_start_of_round_hook():
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("start_of_round", ())}
    assert CARD_ID in auto_ids
    assert CARD_ID in START_OF_ROUND_CARDS
    # Choice-free auto (no mandatory FireTrigger): it is in AUTO_EFFECTS, not TRIGGERS.
    from agricola.cards.triggers import TRIGGERS
    trigger_ids = {e.card_id for e in TRIGGERS.get("start_of_round", ())}
    assert CARD_ID not in trigger_ids


# ---------------------------------------------------------------------------
# Income: +1 food with >= 1 stone (non-final rounds)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("from_round", [1, 2, 6, 11, 12])  # entering rounds 2..13 (not 14)
def test_food_income_with_stone(from_round):
    s = _own_occ(setup(0), 0)
    s = _set_res(s, 0, Resources(stone=1))
    before = s.players[0].resources
    out = _enter_round(s, 0, from_round=from_round)
    assert out.round_number == from_round + 1
    gained = out.players[0].resources - before
    assert gained == Resources(food=1)
    # The start-of-round host frame is on the stack (owner of a start-of-round card);
    # the auto already applied, so Proceed is the only legal action (singleton).
    assert isinstance(out.pending_stack[-1], PendingPreparation)
    assert legal_actions(out) == [Proceed()]


def test_more_than_one_stone_still_one_food():
    # "at least 1 stone" — having extra stone does not scale the income.
    s = _own_occ(setup(0), 0)
    s = _set_res(s, 0, Resources(stone=5))
    before = s.players[0].resources
    out = _enter_round(s, 0, from_round=3)
    assert out.players[0].resources - before == Resources(food=1)


# ---------------------------------------------------------------------------
# Eligibility boundary: no stone -> no income
# ---------------------------------------------------------------------------

def test_no_income_without_stone():
    s = _own_occ(setup(0), 0)
    s = _set_res(s, 0, Resources(food=2, wood=3))  # zero stone
    before = s.players[0].resources
    out = _enter_round(s, 0, from_round=4)
    assert out.players[0].resources == before  # nothing gained
    # Host still pushed (owner of a start-of-round card), but the auto did nothing.
    assert isinstance(out.pending_stack[-1], PendingPreparation)


def test_eligibility_rechecked_each_round():
    # Stone in round R+1 -> food; no stone in round R+2 -> no income.
    s = _own_occ(setup(0), 0)
    s = _set_res(s, 0, Resources(stone=1))
    out = _enter_round(s, 0, from_round=5)
    assert out.round_number == 6
    assert out.players[0].resources == Resources(stone=1, food=1)
    # Now spend the stone, advance a round: ineligible -> no income.
    out = _set_res(out, 0, Resources(food=1))  # stone gone
    out = _enter_round(out, 0, from_round=6)
    assert out.round_number == 7
    assert out.players[0].resources == Resources(food=1)


# ---------------------------------------------------------------------------
# Round 14: vegetable instead of food
# ---------------------------------------------------------------------------

def test_round_14_grants_veg_not_food():
    s = _own_occ(setup(0), 0)
    s = _set_res(s, 0, Resources(stone=1))
    before = s.players[0].resources
    out = _enter_round(s, 0, from_round=NUM_ROUNDS - 1)  # 13 -> 14
    assert out.round_number == NUM_ROUNDS
    gained = out.players[0].resources - before
    assert gained == Resources(veg=1)
    assert gained.food == 0


def test_round_14_no_veg_without_stone():
    s = _own_occ(setup(0), 0)
    s = _set_res(s, 0, Resources())  # no stone
    before = s.players[0].resources
    out = _enter_round(s, 0, from_round=NUM_ROUNDS - 1)
    assert out.round_number == NUM_ROUNDS
    assert out.players[0].resources == before  # neither food nor veg


# ---------------------------------------------------------------------------
# Owner-gating: only the owner gets the income
# ---------------------------------------------------------------------------

def test_only_owner_gains():
    # Player 0 owns Pavior + has stone; player 1 owns nothing.
    s = _own_occ(setup(0), 0)
    s = _set_res(s, 0, Resources(stone=1))
    s = _set_res(s, 1, Resources(stone=1))  # P1 has stone but doesn't own the card
    p1_before = s.players[1].resources
    out = _enter_round(s, 0, from_round=2)
    assert out.players[0].resources == Resources(stone=1, food=1)
    assert out.players[1].resources == p1_before  # P1 unchanged


# ---------------------------------------------------------------------------
# Full real-game round boundary (not just _complete_preparation in isolation)
# ---------------------------------------------------------------------------

def test_fires_across_a_real_round_boundary():
    """Drive a real game from round 1 into round 2 via `step` and confirm the
    income lands during the preparation transition (no direct _complete_preparation
    call). Random play also collects food in round 1, so we isolate the boundary by
    measuring P0's food on the last round-1 state vs the first round-2 state — the
    delta across that single transition is exactly the Pavior +1."""
    import numpy as np

    from agricola.agents.base import decider_of

    s, env = setup_env(0)
    s = _own_occ(s, 0)
    s = _set_res(s, 0, Resources(stone=1))
    rng = np.random.default_rng(0)
    steps = 0
    food_before_boundary = s.players[0].resources.food
    while s.round_number == 1 and s.phase != Phase.BEFORE_SCORING and steps < 4000:
        d = decider_of(s)
        if d is None:
            s = step(s, env.resolve(s))
        else:
            la = legal_actions(s)
            # If a Pavior start-of-round host appears, Proceed is the only action.
            s = step(s, la[int(rng.integers(len(la)))])
        # Snapshot the food on the latest state that is still in round 1; the next
        # iteration may cross into round 2 via the preparation transition.
        if s.round_number == 1:
            food_before_boundary = s.players[0].resources.food
        steps += 1
    # We have entered round 2; across the single round-1 -> round-2 boundary the
    # Pavior auto added exactly 1 food (the stone is still held, so still eligible).
    assert s.round_number >= 2
    assert s.players[0].resources.stone == 1  # never spent -> eligible at the boundary
    assert s.players[0].resources.food == food_before_boundary + 1
