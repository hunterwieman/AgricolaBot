"""Bunk Beds (minor improvement, C10; Corbarius).

Card text (verbatim): "Once you have 4 rooms, your house can hold 5 people."
Cost: 1 wood.  Prerequisite: 2 built major improvements.

A passive PEOPLE-capacity bonus (registered via the housing-capacity registry,
capacity_mods): once the house has at least 4 ROOM cells, it can hold 5 people
instead of the usual one-per-room. Modeled as a bonus that raises capacity TO 5
while rooms >= 4 (`max(0, 5 - rooms)`): at 4 rooms it is +1 (capacity 5); at 5+
rooms it is 0 (the rooms already provide >= 5, and the card's "hold 5" adds
nothing). Below 4 rooms the card is inert. The 5-person family cap makes any
capacity beyond 5 moot regardless.

The prerequisite (2 major improvements) is a HAVE-check on the number of built
majors this player owns, spent by nothing. No on-play effect.
"""
from __future__ import annotations

from agricola.cards.capacity_mods import register_housing_capacity
from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.resources import Cost, Resources
from agricola.state import GameState, PlayerState

CARD_ID = "bunk_beds"


def _num_rooms(p: PlayerState) -> int:
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if p.farmyard.grid[r][c].cell_type == CellType.ROOM
    )


def _capacity_bonus(state: GameState, idx: int) -> int:
    rooms = _num_rooms(state.players[idx])
    if rooms < 4:
        return 0
    return max(0, 5 - rooms)


def _prereq(state: GameState, idx: int) -> bool:
    """2 built major improvements owned by this player."""
    owners = state.board.major_improvement_owners
    return sum(1 for o in owners if o == idx) >= 2


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), prereq=_prereq)
register_housing_capacity(CARD_ID, _capacity_bonus)
