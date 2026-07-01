"""Summer House (minor improvement, D #33; Dulcinaria Expansion; players -).

Card text: "During scoring, if you live in a stone house, you get 2 bonus points
for each unused farmyard space orthogonally adjacent to your house. (You still
lose the points for these unused spaces.)"

cost: 3 Wood, 1 Stone.  prereq: "Still in Wooden House".

A pure end-game scoring minor (Category 1) with NO on-play effect — the scoring
term is derived from the farmyard at game end. Two subtleties, both load-bearing:

  * House material is OPPOSITE at the two timings. The prerequisite gates PLAY on
    living in a WOOD house ("Still in Wooden House"), but the +2 bonus only pays
    out at SCORING if you live in a STONE house. So `_in_wooden_house` (the play
    prereq) checks `house_material == WOOD`, while `_score` returns 0 unless
    `house_material == STONE`. The two are intentionally distinct — do not
    conflate them.

  * "Unused farmyard space" matches the base scoring definition exactly
    (scoring.py: the -1-per-unused-space penalty): a cell is unused iff it is
    `CellType.EMPTY` AND not inside any pasture (`enclosed_cells`). A pasture is
    derived from the fence arrays, not a `CellType`, so a fenced-but-empty cell
    keeps `cell_type == EMPTY` yet IS used (it is a pasture). "Orthogonally
    adjacent to your house" = sharing an edge (up/down/left/right) with a ROOM
    cell.

The parenthetical "(You still lose the points for these unused spaces.)" confirms
the base -1-per-unused-space penalty is unaffected — this card adds an INDEPENDENT
+2 per qualifying cell. No offset/cancellation of the base penalty is performed.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import CellType, HouseMaterial
from agricola.helpers import enclosed_cells
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "summer_house"

# 3x5 farmyard; orthogonal neighbours (sharing an edge).
_NEIGHBORS = ((-1, 0), (1, 0), (0, -1), (0, 1))


def _in_wooden_house(state: GameState, idx: int) -> bool:
    """Play prerequisite: 'Still in Wooden House' — you live in a WOOD house."""
    return state.players[idx].house_material == HouseMaterial.WOOD


def _score(state: GameState, idx: int) -> int:
    p = state.players[idx]
    # The bonus only applies if you live in a STONE house at game end.
    if p.house_material != HouseMaterial.STONE:
        return 0

    fy = p.farmyard
    grid = fy.grid
    enclosed = enclosed_cells(fy)

    room_cells = {
        (r, c)
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.ROOM
    }

    qualifying = 0
    for r in range(3):
        for c in range(5):
            # "Unused" = EMPTY and not inside a pasture (base-scoring definition).
            if grid[r][c].cell_type != CellType.EMPTY or (r, c) in enclosed:
                continue
            # Orthogonally adjacent to at least one ROOM cell.
            if any(
                (r + dr, c + dc) in room_cells for dr, dc in _NEIGHBORS
            ):
                qualifying += 1

    return 2 * qualifying


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=3, stone=1)),
    prereq=_in_wooden_house,
)
register_scoring(CARD_ID, _score)
