"""Tests for Homekeeper (occupation, A85).

Card text (verbatim): "Exactly one clay or stone room in your house can hold an
additional person if the room is adjacent to both a field and a pasture."

A +1 PEOPLE-capacity bonus (housing-capacity registry) gated on: clay/stone house
AND some ROOM cell orthogonally adjacent to BOTH a FIELD cell AND a pasture cell.
"Exactly one" -> capped at +1. Verified both as the raw bonus and end-to-end as the
family-growth-with-room legality flip (people_total < _housing_capacity).

Default setup geometry (seed 0): rooms at (1,0),(2,0); house WOOD; 2 people; no
pastures. Tests set house material, a field, and a pasture to build the adjacency.
"""
import agricola.cards.homekeeper  # noqa: F401  (registers the card)

from agricola.cards.homekeeper import _capacity_bonus
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import CellType, HouseMaterial
from agricola.legality import _housing_capacity, _legal_basic_wish_for_children
from agricola.pasture import Pasture
from agricola.replace import fast_replace
from agricola.setup import setup
from tests.factories import (
    with_current_player,
    with_fields,
    with_house,
    with_people,
    with_space,
)

CARD_ID = "homekeeper"


def _own(state, idx):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {CARD_ID}) if i == idx
        else state.players[i] for i in range(2)))


def _with_pasture(state, idx, cells):
    fy = state.players[idx].farmyard
    past = Pasture(cells=frozenset(cells), num_stables=0, capacity=2 * len(cells))
    return fast_replace(state, players=tuple(
        fast_replace(state.players[idx], farmyard=fast_replace(fy, pastures=(past,)))
        if i == idx else state.players[i] for i in range(2)))


def _adjacent_geometry(state, idx, material=HouseMaterial.CLAY):
    """Room (1,0) touches a FIELD at (0,0) and a pasture cell at (1,1)."""
    state = with_house(state, idx, material)
    state = with_fields(state, idx, [(0, 0)])
    state = _with_pasture(state, idx, [(1, 1)])
    return state


# --- Registration -----------------------------------------------------------

def test_registration_and_noop_on_play():
    assert CARD_ID in OCCUPATIONS
    s = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) is s


# --- The capacity bonus (raw) -----------------------------------------------

def test_bonus_when_clay_room_touches_field_and_pasture():
    s = _adjacent_geometry(_own(setup(seed=0), 0), 0)
    assert _capacity_bonus(s, 0) == 1


def test_bonus_stone_house_also_qualifies():
    s = _adjacent_geometry(_own(setup(seed=0), 0), 0, material=HouseMaterial.STONE)
    assert _capacity_bonus(s, 0) == 1


def test_no_bonus_in_wooden_house():
    """Only a clay or stone room qualifies."""
    s = _adjacent_geometry(_own(setup(seed=0), 0), 0, material=HouseMaterial.WOOD)
    assert _capacity_bonus(s, 0) == 0


def test_no_bonus_without_a_pasture():
    s = with_fields(with_house(_own(setup(seed=0), 0), 0, HouseMaterial.CLAY), 0, [(0, 0)])
    assert _capacity_bonus(s, 0) == 0                 # field-adjacent but no pasture


def test_no_bonus_when_field_not_adjacent_to_a_room():
    """Field at (0,4) touches no room; rooms are (1,0),(2,0)."""
    s = with_house(_own(setup(seed=0), 0), 0, HouseMaterial.CLAY)
    s = with_fields(s, 0, [(0, 4)])
    s = _with_pasture(s, 0, [(1, 1)])                 # pasture-adjacent to (1,0), but no adjacent field
    assert _capacity_bonus(s, 0) == 0


def test_no_bonus_when_pasture_not_adjacent_to_a_room():
    """Pasture cell (2,4) touches no room."""
    s = with_house(_own(setup(seed=0), 0), 0, HouseMaterial.CLAY)
    s = with_fields(s, 0, [(0, 0)])                   # field-adjacent to (1,0)
    s = _with_pasture(s, 0, [(2, 4)])
    assert _capacity_bonus(s, 0) == 0


def test_only_owner_gets_the_bonus():
    """P1 does not own it — the geometry on P0 does nothing for P1 (and P0 owns it)."""
    s = _adjacent_geometry(setup(seed=0), 0)          # geometry but no card
    assert _housing_capacity(s, 0) == 2               # no owner -> pure room count


# --- End-to-end: the family-growth-with-room gate flips ----------------------

def test_gate_flips_with_homekeeper():
    """2 rooms, 2 people: no spare capacity -> Basic Wish illegal. Homekeeper's +1
    (clay room touching field+pasture) makes capacity 3 > 2 -> legal."""
    base = with_space(with_current_player(setup(seed=0), 0),
                      "basic_wish_for_children", revealed=True)
    base = with_people(base, 0, total=2)              # == 2 rooms

    without = base                                    # no card, no geometry
    assert _housing_capacity(without, 0) == 2
    assert _legal_basic_wish_for_children(without) is False

    withcard = _adjacent_geometry(_own(base, 0), 0)
    assert _housing_capacity(withcard, 0) == 3
    assert _legal_basic_wish_for_children(withcard) is True
