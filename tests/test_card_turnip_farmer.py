"""Tests for Turnip Farmer (occupation, A141; Artifex Expansion).

Card text: "At the start of the returning home phase of each round, if both the
'Day Laborer' and 'Grain Seeds' action spaces are occupied, you get 1 vegetable."

A choice-free automatic effect on the round-end ladder's start_of_returning_home
window (ruling 49), which fires PRE-reset — so eligibility reads the still-placed
board (both day_laborer and grain_seeds holding a worker). The tests drive the
REAL round-end walk (_advance_until_decision from a drained WORK state, the
Swimming Class idiom).
"""
from __future__ import annotations

import agricola.cards.turnip_farmer  # noqa: F401  (registers the card)

from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision
from agricola.replace import fast_replace
from agricola.setup import setup
from tests.factories import with_space

CARD_ID = "turnip_farmer"


def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_occ(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {CARD_ID})


def _drained_work_state(*, occupied=("day_laborer", "grain_seeds"), seed=0):
    """A round-1 WORK state with every person placed (people_home=0) and a worker
    recorded on each named space (pre-reset occupancy visible at the window)."""
    state = setup(seed)
    state = fast_replace(state, phase=Phase.WORK, round_number=1)
    for sid in occupied:
        state = with_space(state, sid, workers=(1, 0))
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    return state


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    assert getattr(OCCUPATIONS[CARD_ID], "vps", 0) == 0
    assert any(e.card_id == CARD_ID
               for e in AUTO_EFFECTS.get("start_of_returning_home", ()))


# --- The fire, through the real round-end walk ------------------------------

def test_veg_when_both_spaces_occupied():
    state = _own_occ(_drained_work_state(), 0)
    before = state.players[0].resources.veg
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION       # round 1: no harvest
    assert state.players[0].resources.veg == before + 1


def test_no_veg_when_only_one_space_occupied():
    state = _own_occ(_drained_work_state(occupied=("day_laborer",)), 0)
    before = state.players[0].resources.veg
    state = _advance_until_decision(state)
    assert state.players[0].resources.veg == before


def test_no_veg_when_neither_space_occupied():
    state = _own_occ(_drained_work_state(occupied=()), 0)
    before = state.players[0].resources.veg
    state = _advance_until_decision(state)
    assert state.players[0].resources.veg == before


def test_opponent_worker_counts_as_occupancy():
    """A space is occupied by EITHER player's worker: put both spaces' workers on
    the OPPONENT and the owner still scores the vegetable."""
    state = setup(0)
    state = fast_replace(state, phase=Phase.WORK, round_number=1)
    for sid in ("day_laborer", "grain_seeds"):
        state = with_space(state, sid, workers=(0, 1))   # opponent occupies
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    state = _own_occ(state, 0)
    before = state.players[0].resources.veg
    state = _advance_until_decision(state)
    assert state.players[0].resources.veg == before + 1


def test_unowned_does_not_fire():
    state = _drained_work_state()                 # no ownership
    before = state.players[0].resources.veg
    state = _advance_until_decision(state)
    assert state.players[0].resources.veg == before
