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

Prerequisite note — "or an Upgrade Thereof" (user ruling 2026-07-02: Large
Pottery is an upgrade of Pottery; no Joinery upgrade currently exists): the
condition is satisfied by owning the Pottery major (`major_improvement_owners[8]
== idx`) OR having played the Large Pottery minor (`large_pottery`, D60, in the
player's `minor_improvements`). The second check is load-bearing, not redundant:
Large Pottery's own cost is "Return the Pottery", so its owner no longer holds
the Pottery major. Large Pottery is not yet implemented, so the membership check
is inert today — but correct the day it lands.

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
# The only current upgrade of Pottery (user ruling 2026-07-02). Not yet an
# implemented card, so this membership check is inert today.
_LARGE_POTTERY_ID = "large_pottery"


def _owns_pottery(state: GameState, idx: int) -> bool:
    """Prerequisite: player `idx` owns the Pottery or an upgrade thereof.

    Satisfied by the Pottery major OR the played Large Pottery minor — whose
    own cost returns the Pottery, so its owner does not hold the major.
    """
    if state.board.major_improvement_owners[_POTTERY_MAJOR_IDX] == idx:
        return True
    return _LARGE_POTTERY_ID in state.players[idx].minor_improvements


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
