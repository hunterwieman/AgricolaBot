"""Petting Zoo (minor improvement, E11; Ephipparius Expansion; players -).

Card text (verbatim): "As long as you have a pasture orthogonally adjacent to
your house, you can keep animals of any type on this card, up to the number of
rooms in your house."

Cost 1 Wood; no prerequisite; no printed VP.

A STANDING capacity effect: while the condition holds, the card holds up to
`num_rooms` animals, "of any type" — ruled MIXED-type (user ruling 2026-07-20):
the animals on the card may be of different types and mix freely, exactly the
Feedyard "even different types" / Animal Tamer house-slot shape, NOT a single
Stockyard-style same-type bin. The engine's "flexible slot" abstraction already
captures any-type-per-slot, capacity-1, mixable across slots (each flexible slot
holds one animal of any type; `can_accommodate` sums overflow across types into a
flat slot count), so the card contributes `num_rooms` FLEXIBLE slots — registered
via the flexible-slot registry (capacity_mods). No new accommodation structure.

The condition — "a pasture orthogonally adjacent to your house" — is: some
pasture cell shares an EDGE (orthogonal adjacency, RULES.md "Board Geography")
with some ROOM cell. A pasture is not its own `CellType` (an empty fenced cell
reads `EMPTY`), so pasture cells come from the fence-derived decomposition
(`enclosed_cells`, reading `farmyard.pastures`), never from the grid. When the
condition fails the card grants 0 slots. `num_rooms` is the count of ROOM cells.

The condition is monotone in practice (rooms and pastures are permanent, rooms
only added, so capacity never drops once live) — no eviction path is needed — but
`_slots` is still written as a pure function of the current state.
"""
from __future__ import annotations

from agricola.cards.capacity_mods import register_flexible_slots
from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.helpers import enclosed_cells
from agricola.resources import Cost, Resources
from agricola.state import PlayerState

CARD_ID = "petting_zoo"

_ORTHO = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _room_cells(p: PlayerState) -> list[tuple[int, int]]:
    grid = p.farmyard.grid
    return [
        (r, c)
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.ROOM
    ]


def _slots(p: PlayerState) -> int:
    """Flexible slots the card grants: `num_rooms` if some pasture cell is
    orthogonally adjacent to some room cell, else 0."""
    rooms = _room_cells(p)
    if not rooms:
        return 0
    room_set = set(rooms)
    for (pr, pc) in enclosed_cells(p.farmyard):
        for (dr, dc) in _ORTHO:
            if (pr + dr, pc + dc) in room_set:
                return len(rooms)
    return 0


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register_flexible_slots(CARD_ID, _slots)
