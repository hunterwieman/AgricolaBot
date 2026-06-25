"""Stable Architect (occupation, A98; Base Revised; players 1+).

Card text: "During scoring, you get 1 bonus point for each unfenced stable in
your farmyard." A pure end-game scoring term — no on-play effect (it is still
played via Lessons; its on-play is a no-op).

Category 1 (end-game scoring). No stored state — derived from the farmyard.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.constants import CellType
from agricola.scoring import register_scoring
from agricola.state import Farmyard, GameState

CARD_ID = "stable_architect"


def count_unfenced_stables(farmyard: Farmyard) -> int:
    """Stables NOT inside any pasture (a stable inside a pasture is 'fenced')."""
    enclosed = {cell for past in farmyard.pastures for cell in past.cells}
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if farmyard.grid[r][c].cell_type == CellType.STABLE and (r, c) not in enclosed
    )


def _score(state: GameState, idx: int) -> int:
    return count_unfenced_stables(state.players[idx].farmyard)


# Pure scoring occupation: played via Lessons, but its on-play effect is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)
register_scoring(CARD_ID, _score)
