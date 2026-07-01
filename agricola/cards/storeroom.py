"""Storeroom (minor improvement, D31; Dulcinaria Expansion; players -).

Card text: "During scoring, you get 1/2 bonus point for each pair of grain plus
vegetable you have (considering all crops in your supply and fields), rounded up."
Cost: 1 Wood, 2 Stone. Printed VPs: 1.

Category 1 (pure end-game scoring term) with no on-play effect, no prerequisite,
no passing. The 1 printed VP is scored automatically from the spec's `vps`
(scoring.py); `register_scoring` adds only the bonus-point term below.

The "/" in "1/2 bonus point" is the FRACTION one-half (half a point per pair), not
an OR/play-variant alternative — there is no choice to make.

Counting and rounding. "All crops in your supply and fields" pools grain and
vegetables together: total = (supply grain + grain on field cells) + (supply veg +
veg on field cells), counting crops on `CellType.FIELD` cells exactly as
scoring.score() does (supply + the per-field-cell amounts). A "pair" is two pooled
crops, so pairs = total // 2 (an odd leftover crop forms no pair). You then get
half a point per pair, ROUNDED UP: points = ceil(pairs / 2).

Worked examples: 5 grain + 4 veg = 9 crops -> 4 pairs -> ceil(4/2) = 2 points;
3 crops -> 1 pair -> ceil(1/2) = 1 point; 1 crop -> 0 pairs -> 0 points.
"""
from __future__ import annotations

import math

from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "storeroom"


def _pooled_crops(state: GameState, idx: int) -> int:
    """Total grain + vegetables across supply and all field cells.

    Mirrors scoring.score(): supply grain/veg plus the per-field-cell grain/veg
    on cells whose `cell_type is CellType.FIELD` (crops sitting on pasture/other
    cells are not counted)."""
    ps = state.players[idx]
    grid = ps.farmyard.grid
    total_grain = ps.resources.grain + sum(
        grid[r][c].grain
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
    )
    total_veg = ps.resources.veg + sum(
        grid[r][c].veg
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
    )
    return total_grain + total_veg


def _score(state: GameState, idx: int) -> int:
    """1/2 bonus point per pair of pooled grain+veg crops, rounded up."""
    pairs = _pooled_crops(state, idx) // 2
    return math.ceil(pairs / 2)


register_minor(CARD_ID, cost=Cost(Resources(wood=1, stone=2)), vps=1)
register_scoring(CARD_ID, _score)
