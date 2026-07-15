"""Fodder Beets (minor improvement, E44; Ephipparius Expansion).

Card text: "Place 1 food on each remaining odd-numbered round space. At the start of
these rounds, you get the food."
Cost: none (free). Prerequisite: 3 Field Tiles. VPs: 1. Not passing.

Category 8 (deferred goods), the Pond Hut shape. On play, +1 food is scheduled onto
each remaining ODD-numbered round space — the odd rounds strictly after the current
round (from rounds 1, 3, 5, 7, 9, 11, 13, only those > R). Food rides on
`future_resources`, collected at each round's start by `engine._complete_preparation`.
The "3 Field Tiles" prerequisite counts plowed FIELD cells on the farmyard grid only —
a per-TILE reader (ruling 32), so card-fields do NOT count.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "fodder_beets"


def _field_tiles(state: GameState, idx: int) -> int:
    grid = state.players[idx].farmyard.grid
    return sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type is CellType.FIELD
    )


def _prereq(state: GameState, idx: int) -> bool:
    return _field_tiles(state, idx) >= 3


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    rounds = [r for r in range(R + 1, 15) if r % 2 == 1]
    return schedule_resources(state, idx, rounds, Resources(food=1))


register_minor(
    CARD_ID,
    prereq=_prereq,
    vps=1,
    on_play=_on_play,
)
