"""Tests for Animal Tamer's Apprentice (occupation, E168; Ephipparius Expansion).

Card text: "At the start of each round, you get 1 sheep/wild boar/cattle for each
unoccupied wood/clay/stone room in your house."

A choice-free automatic effect on the preparation ladder's start_of_round window
(the Scullery / Plow Driver rung): the animal type follows the house material
(wood→sheep, clay→boar, stone→cattle) and the count is the number of unoccupied
rooms (num_rooms − people_total). Animals are handed over via grant_animals, so an
over-capacity grant reconciles through the accommodation barrier. Exercised by
driving _complete_preparation (the start_of_round window's autos), plus a full
_advance_until_decision for the overflow → PendingAccommodate path.
"""
from __future__ import annotations

import agricola.cards.animal_tamers_apprentice  # noqa: F401  (registers the card)

from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import CellType, HouseMaterial, Phase
from agricola.engine import _advance_until_decision, _complete_preparation
from agricola.pending import PendingAccommodate
from agricola.replace import fast_replace
from agricola.setup import setup
from agricola.state import Cell
from tests.factories import with_grid, with_house

CARD_ID = "animal_tamers_apprentice"

# Starting Family rooms are (1,0) and (2,0); these top-row cells are empty.
_EXTRA_ROOM_CELLS = [(0, 0), (0, 1), (0, 2), (0, 3)]


def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_occ(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {CARD_ID})


def _state(*, extra_rooms=0, material=HouseMaterial.WOOD, owned=True):
    """A PREPARATION state entering round 2 (so _complete_preparation fires the
    start_of_round autos); P0 has `extra_rooms` rooms beyond the two starting
    ones (→ extra_rooms unoccupied, since people_total stays 2)."""
    s = setup(0)
    if extra_rooms:
        s = with_grid(s, 0, {rc: Cell(cell_type=CellType.ROOM)
                             for rc in _EXTRA_ROOM_CELLS[:extra_rooms]})
    s = with_house(s, 0, material)
    if owned:
        s = _own_occ(s, 0)
    return fast_replace(s, phase=Phase.PREPARATION, round_number=1)


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    assert any(e.card_id == CARD_ID
               for e in AUTO_EFFECTS.get("start_of_round", ()))


# --- Type follows house material; count = unoccupied rooms ------------------

def test_wood_house_grants_sheep_one_per_unoccupied_room():
    after = _complete_preparation(_state(extra_rooms=1, material=HouseMaterial.WOOD))
    p = after.players[0]
    assert p.animals.sheep == 1 and p.animals.boar == 0 and p.animals.cattle == 0


def test_clay_house_grants_boar():
    after = _complete_preparation(_state(extra_rooms=1, material=HouseMaterial.CLAY))
    assert after.players[0].animals.boar == 1


def test_stone_house_grants_cattle():
    after = _complete_preparation(_state(extra_rooms=1, material=HouseMaterial.STONE))
    assert after.players[0].animals.cattle == 1


def test_count_scales_with_unoccupied_rooms():
    # 2 starting + 3 extra = 5 rooms, 2 people → 3 unoccupied → 3 sheep (fits:
    # a pasture would be needed; without one the barrier resolves it, but the
    # grant itself is 3).
    after = _complete_preparation(_state(extra_rooms=3, material=HouseMaterial.WOOD))
    assert after.players[0].animals.sheep == 3


def test_no_grant_when_house_fully_occupied():
    # 2 rooms, 2 people → 0 unoccupied → nothing.
    after = _complete_preparation(_state(extra_rooms=0))
    assert after.players[0].animals.sheep == 0


# --- Accommodation barrier on overflow --------------------------------------

def test_overflow_surfaces_accommodation():
    """2 unoccupied wood rooms → 2 sheep, but a fresh farm houses only 1 (the
    house pet): the grant lands over capacity and the barrier surfaces a
    PendingAccommodate at the round's first decision."""
    granted = _complete_preparation(_state(extra_rooms=2, material=HouseMaterial.WOOD))
    assert granted.players[0].animals.sheep == 2
    assert granted.players[0].animals_need_accommodation
    settled = _advance_until_decision(granted)
    assert isinstance(settled.pending_stack[-1], PendingAccommodate)


# --- Ownership --------------------------------------------------------------

def test_unowned_does_not_fire():
    after = _complete_preparation(_state(extra_rooms=2, owned=False))
    assert after.players[0].animals.sheep == 0
