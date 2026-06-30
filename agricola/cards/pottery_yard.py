"""Pottery Yard (minor improvement, B31; Bubulcus Expansion; Points Provider).

Card text (verbatim): "During the scoring, if there are at least 2 orthogonally
adjacent unused spaces in your farm, you get 2 bonus points. (You still get the
negative points for those unused spaces.)"

Prerequisite: Pottery (or an Upgrade Thereof). Printed VPs: 1. No cost.

An "unused space" is a farmyard cell that scores the unused-space penalty: an
EMPTY cell not enclosed in any pasture — exactly the definition used in
`scoring.py`. The +2 bonus is awarded iff some pair of such unused cells is
orthogonally adjacent (sharing an edge, |dr|+|dc| == 1). The engine still
applies its own −1-per-unused-space penalty (the parenthetical) — that is
untouched here; this card only adds the +2 when the adjacency condition holds.

Prerequisite note — "or an Upgrade Thereof": the implemented major-improvement
set is the 10-major base set, in which Pottery (index 8) has no upgraded
variant; the upgrade clause refers to expansion majors that are not part of this
set. So the prerequisite reduces to "owns Pottery" (`major_improvement_owners[8]
== idx`).

Category: end-game scoring (the +2 bonus via register_scoring) plus a printed VP
(scored automatically from the spec's vps). No stored state — both the prereq
and the bonus are derived from the board / farmyard. Inline adjacency, no
geometry API needed (mirrors stable_architect's inline cell scan).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "pottery_yard"

# Index of Pottery in the major-improvement ownership tuple (constants.py).
_POTTERY_MAJOR_IDX = 8


def _owns_pottery(state: GameState, idx: int) -> bool:
    """Prerequisite: player `idx` owns Pottery."""
    return state.board.major_improvement_owners[_POTTERY_MAJOR_IDX] == idx


def _bonus(state: GameState, idx: int) -> int:
    """+2 iff there exist two orthogonally adjacent UNUSED spaces.

    An unused space is an EMPTY cell not inside any pasture — the same set the
    engine's unused-space penalty is computed over (scoring.py).
    """
    farmyard = state.players[idx].farmyard
    grid = farmyard.grid
    enclosed = {cell for past in farmyard.pastures for cell in past.cells}
    unused = {
        (r, c)
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.EMPTY and (r, c) not in enclosed
    }
    for (r, c) in unused:
        # Only need to check the right and down neighbors to cover every
        # adjacent pair exactly once.
        if (r, c + 1) in unused or (r + 1, c) in unused:
            return 2
    return 0


register_minor(CARD_ID, prereq=_owns_pottery, vps=1)
register_scoring(CARD_ID, _bonus)
