"""Tests for Bunk Beds (minor improvement, C11).

Card text (verbatim): "Once you have 4 rooms, your house can hold 5 people."
Cost 1 wood; prerequisite 2 built major improvements.

A +1 PEOPLE-capacity bonus (housing-capacity registry) once the house has >= 4
rooms (raising capacity to 5), inert below 4 rooms and adding nothing at 5+ rooms.
Verified as the raw bonus, as the prereq/cost, and end-to-end as the
family-growth-with-room legality flip.

Default setup geometry (seed 0): rooms at (1,0),(2,0).
"""
import agricola.cards.bunk_beds  # noqa: F401  (registers the card)

from agricola.cards.bunk_beds import _capacity_bonus, _prereq
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import CellType
from agricola.legality import _housing_capacity, _legal_basic_wish_for_children
from agricola.resources import Cost, Resources
from agricola.setup import setup
from agricola.state import Cell
from tests.factories import (
    with_current_player,
    with_grid,
    with_majors,
    with_minors,
    with_people,
    with_space,
)

CARD_ID = "bunk_beds"


def _rooms(state, idx, n):
    """Force exactly `n` ROOM cells (default 2 at (1,0),(2,0); add along row 0)."""
    assert 2 <= n <= 6
    overrides = {(0, c): Cell(cell_type=CellType.ROOM) for c in range(n - 2)}
    return with_grid(state, idx, overrides)


def _own(state, idx):
    return with_minors(state, idx, state.players[idx].minor_improvements | {CARD_ID})


# --- Registration / cost / prereq -------------------------------------------

def test_registration_cost_and_noop_on_play():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))
    s = setup(seed=0)
    assert spec.on_play(s, 0) is s


def test_prereq_needs_two_majors():
    s = setup(seed=0)
    assert _prereq(s, 0) is False                     # no majors
    s1 = with_majors(s, owner_by_idx={0: 0})          # one major
    assert _prereq(s1, 0) is False
    s2 = with_majors(s, owner_by_idx={0: 0, 1: 0})    # two majors -> ok
    assert _prereq(s2, 0) is True
    assert prereq_met(MINORS[CARD_ID], s2, 0) is True


# --- The capacity bonus (raw) -----------------------------------------------

def test_no_bonus_below_four_rooms():
    s = _own(setup(seed=0), 0)                         # 2 rooms
    assert _capacity_bonus(s, 0) == 0
    assert _capacity_bonus(_rooms(s, 0, 3), 0) == 0


def test_plus_one_at_four_rooms():
    s = _rooms(_own(setup(seed=0), 0), 0, 4)
    assert _capacity_bonus(s, 0) == 1                  # capacity 4 -> 5


def test_no_extra_at_five_or_more_rooms():
    """The rooms already provide >= 5; 'hold 5' adds nothing (and 5-person cap)."""
    assert _capacity_bonus(_rooms(_own(setup(seed=0), 0), 0, 5), 0) == 0
    assert _capacity_bonus(_rooms(_own(setup(seed=0), 0), 0, 6), 0) == 0


# --- End-to-end: the family-growth-with-room gate flips ----------------------

def test_gate_flips_at_four_rooms():
    """4 rooms, 4 people: no spare capacity -> Basic Wish illegal. Bunk Beds' +1
    makes capacity 5 > 4 -> legal."""
    base = with_space(with_current_player(setup(seed=0), 0),
                      "basic_wish_for_children", revealed=True)
    base = with_people(_rooms(base, 0, 4), 0, total=4)

    without = base
    assert _housing_capacity(without, 0) == 4
    assert _legal_basic_wish_for_children(without) is False

    withcard = _own(base, 0)
    assert _housing_capacity(withcard, 0) == 5
    assert _legal_basic_wish_for_children(withcard) is True
