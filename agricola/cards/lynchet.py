"""Lynchet (minor improvement, D63; Dulcinaria Expansion; Food Provider).

Card text (verbatim): "In the field phase of each harvest, you get 1 food for
each harvested field tile that is orthogonally adjacent to your house."

No cost, no prerequisite, no printed VPs, not a passing card.

Category 6 (harvest-field hook). A MANDATORY, choice-free income → an automatic
effect (`register_auto` on the `harvest_field` event), fired by
`_resolve_harvest_field` BEFORE the mechanical crop take. So `_apply` reads the
grid while the fields are still sown — exactly the moment the card scores.

A "harvested field tile" is a field that actually yields a crop this harvest —
i.e. a FIELD cell still holding grain or vegetables when the field phase begins
(an empty/unsown FIELD yields nothing and does not count). "Your house" is the
set of ROOM cells; "orthogonally adjacent" is plain 3×5-grid edge adjacency
(|dr| + |dc| == 1, in bounds) — not pasture/fence geometry, so no geometry helper
is needed. The bonus is 1 food per such field tile.

`_apply` only READS the fields (it credits food, never mutates the grid) — the
mechanical take that follows still removes 1 crop per sown field as usual.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto, register_harvest_field_hook
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "lynchet"

_ROWS = 3
_COLS = 5


def _room_cells(grid) -> set[tuple[int, int]]:
    """The (row, col) of every ROOM cell — the player's house."""
    return {
        (r, c)
        for r in range(_ROWS)
        for c in range(_COLS)
        if grid[r][c].cell_type == CellType.ROOM
    }


def _adjacent_to_house(r: int, c: int, rooms: set[tuple[int, int]]) -> bool:
    """Is cell (r, c) orthogonally adjacent (edge-sharing) to a ROOM cell?"""
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        if (r + dr, c + dc) in rooms:
            return True
    return False


def _qualifying_count(state: GameState, idx: int) -> int:
    """Number of harvested (sown) field tiles orthogonally adjacent to the house.

    A FIELD cell counts iff it is sown (grain > 0 or veg > 0 — it will yield a
    crop in the mechanical take) AND it borders a ROOM cell.
    """
    grid = state.players[idx].farmyard.grid
    rooms = _room_cells(grid)
    count = 0
    for r in range(_ROWS):
        for c in range(_COLS):
            cell = grid[r][c]
            if cell.cell_type != CellType.FIELD:
                continue
            if cell.grain <= 0 and cell.veg <= 0:
                continue
            if _adjacent_to_house(r, c, rooms):
                count += 1
    return count


def _eligible(state: GameState, idx: int) -> bool:
    return _qualifying_count(state, idx) > 0


def _apply(state: GameState, idx: int) -> GameState:
    count = _qualifying_count(state, idx)
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=count))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID)
register_auto("harvest_field", CARD_ID, _eligible, _apply)
register_harvest_field_hook(CARD_ID)
