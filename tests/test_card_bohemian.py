"""Tests for Bohemian (occupation, A157; Artifex Expansion).

Card text: "At the start of each returning home phase, if at least one 'Lessons'
action space is unoccupied, you get 1 food."

A choice-free automatic effect on the round-end ladder's start_of_returning_home
window (ruling 49), fired PRE-reset so the live Lessons occupancy is the event
data. The 2-player board has one Lessons space, so "at least one unoccupied" is
that space empty. Tests drive the REAL round-end walk.
"""
from __future__ import annotations

import agricola.cards.bohemian  # noqa: F401  (registers the card)

from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision
from agricola.replace import fast_replace
from agricola.setup import setup
from tests.factories import with_space

CARD_ID = "bohemian"


def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_occ(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {CARD_ID})


def _drained_work_state(*, lessons_workers=(0, 0), seed=0):
    state = setup(seed)
    state = fast_replace(state, phase=Phase.WORK, round_number=1)
    state = with_space(state, "lessons", workers=lessons_workers)
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    return state


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    assert any(e.card_id == CARD_ID
               for e in AUTO_EFFECTS.get("start_of_returning_home", ()))


# --- The fire, through the real round-end walk ------------------------------

def test_food_when_lessons_unoccupied():
    state = _own_occ(_drained_work_state(lessons_workers=(0, 0)), 0)
    before = state.players[0].resources.food
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION
    assert state.players[0].resources.food == before + 1


def test_no_food_when_owner_occupies_lessons():
    state = _own_occ(_drained_work_state(lessons_workers=(1, 0)), 0)
    before = state.players[0].resources.food
    state = _advance_until_decision(state)
    assert state.players[0].resources.food == before


def test_no_food_when_opponent_occupies_lessons():
    """"Unoccupied" means empty of EITHER player: an opponent worker on Lessons
    also suppresses the food."""
    state = _own_occ(_drained_work_state(lessons_workers=(0, 1)), 0)
    before = state.players[0].resources.food
    state = _advance_until_decision(state)
    assert state.players[0].resources.food == before


def test_unowned_does_not_fire():
    state = _drained_work_state(lessons_workers=(0, 0))    # no ownership
    before = state.players[0].resources.food
    state = _advance_until_decision(state)
    assert state.players[0].resources.food == before
