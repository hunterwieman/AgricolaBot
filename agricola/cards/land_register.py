"""Land Register (minor improvement, E34; Ephipparius Expansion; cost 1 Wood).

Card text: "During scoring, if your farm has no unused spaces, you get 2 bonus points."

Category 1 (end-game scoring term). "No unused spaces" means every one of the 15
farmyard cells is used — a room, field, stable, or a fenced pasture cell. A pasture is
NOT its own `CellType` (an empty fenced cell reads `EMPTY`), so the check must consult
the fences, not `cell_type` alone: a cell is used iff `cell_type != EMPTY` OR it is in
`enclosed_cells(farmyard)`. This mirrors Big Country's `_all_farmyard_spaces_used`
prerequisite exactly (the reference for this check; CARD_ENGINE_IMPLEMENTATION.md §6).
Scores a flat +2 when the whole farm is used, else 0. No stored state.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.helpers import enclosed_cells
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "land_register"


def _all_farmyard_spaces_used(state: GameState, idx: int) -> bool:
    fy = state.players[idx].farmyard
    grid = fy.grid
    enclosed = enclosed_cells(fy)
    return all(
        grid[r][c].cell_type is not CellType.EMPTY or (r, c) in enclosed
        for r in range(3)
        for c in range(5)
    )


def _score(state: GameState, idx: int) -> int:
    return 2 if _all_farmyard_spaces_used(state, idx) else 0


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register_scoring(CARD_ID, _score)
