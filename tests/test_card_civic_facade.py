"""Tests for Civic Facade (minor improvement, D48; Dulcinaria Expansion).

Card text: "Before the start of each round, if you have more occupations than
improvements in your hand, you get 1 food."

Cost 1 clay; prerequisite 3 rooms.

A choice-free `start_of_round` automatic effect (Category 7, the start-of-round
phase hook). The income is driven through the real `_complete_preparation`
round-boundary transition, mirroring tests/test_card_pavior.py. "Before the start
of each round" is exactly the start-of-round hook.

The eligibility condition is unusual: it compares the player's UNPLAYED HAND —
strictly more occupations than improvements IN HAND, i.e. `len(hand_occupations) >
len(hand_minors)` — NOT the played `occupations` / `minor_improvements` tableaus.
The inequality is STRICT (a tie grants nothing).
"""
from __future__ import annotations

import pytest

import agricola.cards.civic_facade  # noqa: F401  (registers the card)

from agricola.actions import Proceed
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import AUTO_EFFECTS, START_OF_ROUND_CARDS
from agricola.constants import CellType, NUM_ROUNDS, Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingPreparation
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup, setup_env

CARD_ID = "civic_facade"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _set_hand(state, idx, *, occ: frozenset, minors: frozenset):
    p = state.players[idx]
    p = fast_replace(p, hand_occupations=frozenset(occ), hand_minors=frozenset(minors))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _set_res(state, idx, res: Resources):
    p = state.players[idx]
    p = fast_replace(p, resources=res)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _set_rooms(state, idx, n_rooms):
    """Overwrite the player's grid so exactly `n_rooms` cells are ROOM."""
    p = state.players[idx]
    grid = [list(row) for row in p.farmyard.grid]
    placed = 0
    for r in range(3):
        for c in range(5):
            want_room = placed < n_rooms
            cur = grid[r][c]
            ctype = CellType.ROOM if want_room else CellType.EMPTY
            grid[r][c] = fast_replace(cur, cell_type=ctype)
            if want_room:
                placed += 1
    new_grid = tuple(tuple(row) for row in grid)
    fy = fast_replace(p.farmyard, grid=new_grid)
    p = fast_replace(p, farmyard=fy)
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

def test_registered_as_minor():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(clay=1))


def test_registered_on_start_of_round_hook():
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("start_of_round", ())}
    assert CARD_ID in auto_ids
    assert CARD_ID in START_OF_ROUND_CARDS
    # Choice-free auto (no mandatory FireTrigger): it is in AUTO_EFFECTS, not TRIGGERS.
    from agricola.cards.triggers import TRIGGERS
    trigger_ids = {e.card_id for e in TRIGGERS.get("start_of_round", ())}
    assert CARD_ID not in trigger_ids


# ---------------------------------------------------------------------------
# Prerequisite: 3 rooms (a HAVE-check at play time)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n_rooms,expected", [(0, False), (2, False), (3, True), (4, True)])
def test_prereq_three_rooms(n_rooms, expected):
    s = setup(0)
    s = _set_rooms(s, 0, n_rooms)
    assert prereq_met(MINORS[CARD_ID], s, 0) is expected


# ---------------------------------------------------------------------------
# Income: +1 food when more occupations than improvements in hand
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("from_round", [1, 2, 6, 11, 12, NUM_ROUNDS - 1])
def test_food_income_when_more_occupations_in_hand(from_round):
    s = _own_minor(setup(0), 0)
    s = _set_hand(s, 0, occ={"a", "b"}, minors={"x"})  # 2 > 1
    before = s.players[0].resources
    out = _enter_round(s, 0, from_round=from_round)
    assert out.round_number == from_round + 1
    gained = out.players[0].resources - before
    assert gained == Resources(food=1)
    # The start-of-round host frame is on the stack (owner of a start-of-round card);
    # the auto already applied, so Proceed is the only legal action (singleton).
    assert isinstance(out.pending_stack[-1], PendingPreparation)
    assert legal_actions(out) == [Proceed()]


def test_income_is_flat_one_food_regardless_of_margin():
    # A larger occupation surplus does not scale the income.
    s = _own_minor(setup(0), 0)
    s = _set_hand(s, 0, occ={"a", "b", "c", "d"}, minors=frozenset())  # 4 > 0
    before = s.players[0].resources
    out = _enter_round(s, 0, from_round=3)
    assert out.players[0].resources - before == Resources(food=1)


# ---------------------------------------------------------------------------
# Eligibility boundaries: STRICT >, and hand (not tableau)
# ---------------------------------------------------------------------------

def test_tie_grants_nothing():
    # Equal counts -> strict inequality fails -> no income.
    s = _own_minor(setup(0), 0)
    s = _set_hand(s, 0, occ={"a", "b"}, minors={"x", "y"})  # 2 == 2
    before = s.players[0].resources
    out = _enter_round(s, 0, from_round=4)
    assert out.players[0].resources == before
    assert isinstance(out.pending_stack[-1], PendingPreparation)


def test_fewer_occupations_grants_nothing():
    s = _own_minor(setup(0), 0)
    s = _set_hand(s, 0, occ={"a"}, minors={"x", "y"})  # 1 < 2
    before = s.players[0].resources
    out = _enter_round(s, 0, from_round=4)
    assert out.players[0].resources == before


def test_empty_hand_grants_nothing():
    s = _own_minor(setup(0), 0)
    s = _set_hand(s, 0, occ=frozenset(), minors=frozenset())  # 0 == 0
    before = s.players[0].resources
    out = _enter_round(s, 0, from_round=4)
    assert out.players[0].resources == before


def test_condition_reads_hand_not_played_tableau():
    # Played occupations/minors must NOT count: the played tableau is heavy on
    # occupations, but the hand is tied -> no income.
    s = _own_minor(setup(0), 0)
    p = s.players[0]
    p = fast_replace(p, occupations=frozenset({"occ1", "occ2", "occ3"}))
    s = fast_replace(s, players=tuple(p if i == 0 else s.players[i] for i in range(2)))
    s = _set_hand(s, 0, occ={"h1"}, minors={"m1"})  # hand tied 1==1
    before = s.players[0].resources
    out = _enter_round(s, 0, from_round=4)
    assert out.players[0].resources == before


# ---------------------------------------------------------------------------
# Re-evaluated each round (the grant turns on/off as the hand changes)
# ---------------------------------------------------------------------------

def test_eligibility_rechecked_each_round():
    s = _own_minor(setup(0), 0)
    s = _set_hand(s, 0, occ={"a", "b"}, minors={"x"})  # eligible 2 > 1
    s = _set_res(s, 0, Resources())
    out = _enter_round(s, 0, from_round=5)
    assert out.round_number == 6
    assert out.players[0].resources == Resources(food=1)
    # Now play an occupation out of hand so the hand becomes tied -> ineligible.
    out = _set_hand(out, 0, occ={"a"}, minors={"x"})  # 1 == 1
    out = _enter_round(out, 0, from_round=6)
    assert out.round_number == 7
    assert out.players[0].resources == Resources(food=1)  # no further food


# ---------------------------------------------------------------------------
# Owner-gating: only the owner gets the income
# ---------------------------------------------------------------------------

def test_only_owner_gains():
    # Player 0 owns Civic Facade + an eligible hand; player 1 has the same hand but
    # does NOT own the card.
    s = _own_minor(setup(0), 0)
    s = _set_hand(s, 0, occ={"a", "b"}, minors={"x"})
    s = _set_hand(s, 1, occ={"a", "b"}, minors={"x"})  # eligible-looking hand, no card
    p1_before = s.players[1].resources
    out = _enter_round(s, 0, from_round=2)
    assert out.players[0].resources - s.players[0].resources == Resources(food=1)
    assert out.players[1].resources == p1_before  # P1 unchanged (doesn't own the card)


def test_hand_card_does_not_fire():
    # Holding Civic Facade in hand (unplayed) must NOT grant income.
    s = setup(0)
    p = s.players[0]
    p = fast_replace(p, hand_minors=p.hand_minors | {CARD_ID},
                     hand_occupations=frozenset({"a", "b"}))
    s = fast_replace(s, players=tuple(p if i == 0 else s.players[i] for i in range(2)))
    before = s.players[0].resources
    out = _enter_round(s, 0, from_round=3)
    assert out.players[0].resources == before  # not owned (only in hand) -> no fire


# ---------------------------------------------------------------------------
# Full real-game round boundary (not just _complete_preparation in isolation)
# ---------------------------------------------------------------------------

def test_fires_across_a_real_round_boundary():
    """Drive a real game from round 1 into round 2 via `step` and confirm the income
    lands during the preparation transition. Random play also collects food in round
    1, so isolate the boundary by measuring P0's food on the last round-1 state vs the
    first round-2 state — the delta across that single transition is exactly the +1."""
    import numpy as np

    from agricola.agents.base import decider_of

    s, env = setup_env(0)
    s = _own_minor(s, 0)
    s = _set_hand(s, 0, occ={"a", "b"}, minors={"x"})  # eligible
    rng = np.random.default_rng(0)
    steps = 0
    food_before_boundary = s.players[0].resources.food
    while s.round_number == 1 and s.phase != Phase.BEFORE_SCORING and steps < 4000:
        d = decider_of(s)
        if d is None:
            s = step(s, env.resolve(s))
        else:
            la = legal_actions(s)
            s = step(s, la[int(rng.integers(len(la)))])
        if s.round_number == 1:
            food_before_boundary = s.players[0].resources.food
        steps += 1
    assert s.round_number >= 2
    assert s.players[0].resources.food == food_before_boundary + 1
