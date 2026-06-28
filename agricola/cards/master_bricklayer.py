"""Master Bricklayer (occupation, B95; Base Revised; players 1+).

Card text: "Each time you build a major improvement, reduce the stone cost by the number
of rooms you have built onto you initial house."

A passive cost-REDUCTION card (COST_MODIFIER_DESIGN.md §1.1) on `build_major` only, with a
STATE-DEPENDENT delta: the stone cost drops by the number of rooms the player has added
beyond the two rooms the house starts with. (Reductions are signed deltas; the chokepoint's
`apply_reductions` floors every component at 0, so a major with little/no stone, or a player
with no extra rooms, is simply unaffected.) No on-play effect.

"Rooms built onto your initial house" = (total rooms now) − 2 (the two starting rooms). Room
count is derived from the farmyard grid (cells of type ROOM), per the engine's
derived-data-not-cached convention.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_reduction
from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.constants import CellType
from agricola.resources import Resources

CARD_ID = "master_bricklayer"

_INITIAL_ROOMS = 2


def _rooms_added(state, idx) -> int:
    """Rooms built beyond the two the house starts with (never negative)."""
    grid = state.players[idx].farmyard.grid
    total = sum(
        1 for row in grid for cell in row if cell.cell_type == CellType.ROOM
    )
    return max(0, total - _INITIAL_ROOMS)


def _less_n_stone(state, idx, ctx, cost: Resources) -> Resources:
    return cost - Resources(stone=_rooms_added(state, idx))


register_reduction("build_major", CARD_ID, _less_n_stone)
register_occupation(CARD_ID, _noop_on_play)   # passive cost card, no on-play
