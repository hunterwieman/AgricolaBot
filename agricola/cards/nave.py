"""Nave (minor improvement, E32; Ephipparius Expansion; cost 2 Stone + 1 Reed).

Card text: "During scoring, you get 1 bonus point for each of the 5 columns of your
farmyard board containing at least one room."

Category 1 (end-game scoring term). The farmyard is a 3-row x 5-column grid
(`farmyard.grid[r][c]`, row 0 = top, col 0 = left). A column scores if any of its 3
cells is a room, so the value is the count of the 5 columns holding >= 1
`CellType.ROOM`. Rooms carry a real `CellType` (unlike pastures), so a plain
`cell_type == ROOM` scan is correct here. No stored state — derived from the farmyard.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "nave"


def _score(state: GameState, idx: int) -> int:
    grid = state.players[idx].farmyard.grid
    return sum(
        any(grid[r][c].cell_type == CellType.ROOM for r in range(3))
        for c in range(5)
    )


register_minor(CARD_ID, cost=Cost(resources=Resources(stone=2, reed=1)))
register_scoring(CARD_ID, _score)
