"""Lord of the Manor (occupation, D100; Dulcinaria Expansion; players 1+).

Card text: "During scoring, you get 1 bonus point for each scoring category in
which you score the maximum 4 points. (The bonus point is also awarded for 4
fenced stables.)"

A pure end-game scoring term — no on-play effect (it is still played via Lessons;
its on-play is a no-op).

The eight scoring categories whose value table maxes at exactly 4 points are:
field tiles, pastures, grain, vegetables, sheep, wild boar, cattle, and fenced
stables. (Rooms — clay ×1 / stone ×2 — people ×3, major improvements, unused
spaces and begging are NOT counted: their values are not capped at 4, so the
rule "you score the maximum 4 points" never applies to them. The parenthetical
in the card text confirms fenced stables — capped at 4 — is one of the eight.)

This recomputes those eight per-category point values *inline from raw state*,
mirroring agricola/scoring.py's own counting (and reusing its `_score_*` look-up
helpers). It must NOT call `scoring.score()`: `score()` iterates `SCORING_TERMS`
and would re-invoke this very term — infinite recursion.

Category 1 (end-game scoring). No stored state — derived from the farmyard.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.constants import CellType
from agricola.scoring import (
    _score_boar,
    _score_cattle,
    _score_field_tiles,
    _score_grain,
    _score_pastures,
    _score_sheep,
    _score_veg,
    register_scoring,
)
from agricola.state import GameState

CARD_ID = "lord_of_the_manor"


def _category_point_values(state: GameState, idx: int) -> list[int]:
    """The eight max-4-capped categories' point values, mirroring scoring.score().

    Returned in the same order as scoring.py computes them: field tiles, pastures,
    grain, vegetables, sheep, boar, cattle, fenced stables.
    """
    ps = state.players[idx]
    grid = ps.farmyard.grid
    pastures = ps.farmyard.pastures

    # Field tiles
    num_fields = sum(
        1
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
    )

    # Grain / vegetables: supply + all on field cells (exactly as scoring.score()).
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

    # Fenced stables: stables inside any pasture, capped at 4 (matches scoring.py).
    fenced_stables = sum(
        1
        for p in pastures
        for (r, c) in p.cells
        if grid[r][c].cell_type == CellType.STABLE
    )

    return [
        _score_field_tiles(num_fields),
        _score_pastures(len(pastures)),
        _score_grain(total_grain),
        _score_veg(total_veg),
        _score_sheep(ps.animals.sheep),
        _score_boar(ps.animals.boar),
        _score_cattle(ps.animals.cattle),
        min(fenced_stables, 4),
    ]


def _score(state: GameState, idx: int) -> int:
    """+1 bonus point per max-4 scoring category in which the player scores 4."""
    return sum(1 for value in _category_point_values(state, idx) if value == 4)


# Pure scoring occupation: played via Lessons, but its on-play effect is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)
register_scoring(CARD_ID, _score)
