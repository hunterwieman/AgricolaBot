"""Artisan District (minor improvement, D30; Dulcinaria Expansion; Points Provider).

Card text (verbatim): "During scoring, you get 2/5/8 bonus points for having
3/4/5 major improvements from the bottom row of the supply board."

Cost: 1 Stone. Prerequisite: 3 Occupations. Printed VPs: 1.

The "3 Occupations" line is a PREREQUISITE (a have-check on the number of
occupations the player has played), not a cost — modeled via the built-in
`min_occupations=3`. The 1-Stone is the cost actually paid on play.

"The bottom row of the supply board" is physical supply-board geometry, not a
field the engine stores. The 10 base major improvements are laid out in two
rows: the TOP row is the two Fireplaces (indices 0, 1), the two Cooking Hearths
(2, 3), and the Well (4); the BOTTOM row is the five work-station crafts — Clay
Oven (5), Stone Oven (6), Joinery (7), Pottery (8), and Basketmaker's Workshop
(9). So the bonus counts ONLY indices 5-9 owned by THIS player. Exactly five
bottom-row majors exist, so the count caps at 5.

The bonus is a step function on that count `n`: n<3 → 0, n==3 → 2, n==4 → 5,
n==5 → 8 (so n in {0,1,2} score nothing). This is an end-game scoring term
(`register_scoring`) on top of the printed +1 VP (scored automatically from the
spec's `vps`). No stored state — the count is derived from board ownership at
scoring time.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "artisan_district"

# Indices of the bottom-row major improvements in the ownership tuple
# (constants.py): Clay Oven, Stone Oven, Joinery, Pottery, Basketmaker's
# Workshop. The top row (Fireplaces, Cooking Hearths, Well) is indices 0-4.
_BOTTOM_ROW_MAJOR_IDXS = (5, 6, 7, 8, 9)

# Bonus points by count of bottom-row majors owned. Below 3 scores nothing.
_BONUS_BY_COUNT = {3: 2, 4: 5, 5: 8}


def _bottom_row_count(state: GameState, idx: int) -> int:
    """Number of bottom-row major improvements owned by player `idx`."""
    owners = state.board.major_improvement_owners
    return sum(1 for m in _BOTTOM_ROW_MAJOR_IDXS if owners[m] == idx)


def _bonus(state: GameState, idx: int) -> int:
    """+2 / +5 / +8 for owning 3 / 4 / 5 bottom-row majors; 0 below 3."""
    return _BONUS_BY_COUNT.get(_bottom_row_count(state, idx), 0)


register_minor(CARD_ID, cost=Cost(resources=Resources(stone=1)), min_occupations=3, vps=1)
register_scoring(CARD_ID, _bonus)
