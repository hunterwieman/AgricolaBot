"""Fellow Grazer (occupation, A99; Artifex Expansion; players 1+).

Card text: "During scoring, you get 2 bonus points for each pasture you have
covering at least 3 farmyard spaces." A pure end-game scoring term — no on-play
effect (it is still played via Lessons; its on-play is a no-op).

"Covering at least 3 farmyard spaces" = the pasture spans at least 3 cells,
measured as the count of enclosed cells (len(p.cells) >= 3) — NOT capacity, and
NOT a stable/edge count. Stables inside a pasture raise its capacity, not its
cell count, so they do not affect whether it qualifies. Iterate
farmyard.pastures (the BFS-derived enclosed connected components); never read
CellType, since a pasture is not a CellType and an empty fenced cell reads EMPTY.

Category 1 (end-game scoring). No stored state — derived from the farmyard.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "fellow_grazer"


def _score(state: GameState, idx: int) -> int:
    """2 VP per pasture covering at least 3 farmyard cells."""
    pastures = state.players[idx].farmyard.pastures
    return 2 * sum(1 for p in pastures if len(p.cells) >= 3)


# Pure scoring occupation: played via Lessons, but its on-play effect is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)
register_scoring(CARD_ID, _score)
