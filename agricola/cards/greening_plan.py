"""Greening Plan (minor improvement, C #33; Corbarius Expansion; players -).

Card text: "During scoring, if you then have at least 2/4/5/6 unplanted fields,
you get 1/2/3/5 bonus points."

Cost: 3 Food. No prerequisite, no on-play effect, no printed VPs — the bonus is
variable and is scored via `register_scoring`, not the flat `vps` field.

Category 1 (end-game scoring). An "unplanted field" is a grid cell whose
`cell_type is CellType.FIELD` that is sown to nothing (grain == 0 AND veg == 0).
A plowed-but-never-sown field and a field whose crop was fully harvested both
count. Scoring runs after the final harvest (phase BEFORE_SCORING), so by the
time `_score` is called all round-14 crops are already consumed — no special
timing handling is needed; just read the terminal farmyard.

The bonus ladder is a non-uniform threshold ladder (>= 2/4/5/6 fields ->
1/2/3/5 points): note that 3 fields scores the same 1 point as 2 fields (the
2->4 gap), and the jump from 5 to 6 fields is 3->5 points. It is evaluated from
the highest threshold down so each band returns the correct value; a naive
linear formula would be wrong.

Clarifications (from the card text) that do not affect the implementable scope:
Garden Designer (C099) plants FOOD on fields, so a food-planted field would not
count — but Garden Designer is not implemented and food-on-field is not
representable (`Cell` only has grain/veg). Boar held on unplanted field tiles
(Mud Patch A011) do not affect this card's scoring — also not implemented.
Neither edge card exists in the engine, so the plain `grain == 0 and veg == 0`
test is exact here.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import Farmyard, GameState

CARD_ID = "greening_plan"


def count_unplanted_fields(farmyard: Farmyard) -> int:
    """FIELD cells sown to nothing (grain == 0 AND veg == 0)."""
    grid = farmyard.grid
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
        and grid[r][c].grain == 0
        and grid[r][c].veg == 0
    )


def _bonus_for(n: int) -> int:
    """Map an unplanted-field count to bonus points via the >=2/4/5/6 ladder."""
    if n >= 6:
        return 5
    if n >= 5:
        return 3
    if n >= 4:
        return 2
    if n >= 2:
        return 1
    return 0


def _score(state: GameState, idx: int) -> int:
    return _bonus_for(count_unplanted_fields(state.players[idx].farmyard))


# Pure end-game scoring minor: cost 3 food, no prereq/on-play, variable VPs.
register_minor(CARD_ID, cost=Cost(resources=Resources(food=3)))
register_scoring(CARD_ID, _score)
