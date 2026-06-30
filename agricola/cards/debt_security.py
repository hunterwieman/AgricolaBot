"""Debt Security (minor improvement, A31; Artifex; players -).

Card text: "During scoring, you get 1 bonus point for each major improvement you
have, up to the number of your unused farmyard spaces."

Cost 2 Food, no prerequisite, no printed VPs, not passing.

Category 1 (end-game scoring). No stored state — both quantities are derived at
scoring time: the count of major improvements owned, capped by the number of
unused farmyard spaces. The bonus is `min(n_majors, unused)`.

Two precise points:
  (1) Major improvements are NOT a `PlayerState` field — ownership lives on
      `state.board.major_improvement_owners` (a length-10 tuple, None=on supply
      else the owner's player index). Count the entries equal to `idx`.
  (2) "Unused farmyard spaces" uses the engine's exact end-game rule
      (scoring.py): a cell is unused iff `cell_type == EMPTY` AND it is not
      enclosed by fences. A fenced-but-empty pasture cell reads EMPTY but is a
      used space (it is a pasture), so `enclosed_cells` must be subtracted —
      `cell_type` alone would overcount.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.helpers import enclosed_cells
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "debt_security"


def _score(state: GameState, idx: int) -> int:
    n_majors = sum(1 for o in state.board.major_improvement_owners if o == idx)

    fy = state.players[idx].farmyard
    enclosed = enclosed_cells(fy)
    unused = sum(
        1
        for r in range(3)
        for c in range(5)
        if fy.grid[r][c].cell_type is CellType.EMPTY and (r, c) not in enclosed
    )

    return min(n_majors, unused)


register_minor(CARD_ID, cost=Cost(resources=Resources(food=2)))
register_scoring(CARD_ID, _score)
