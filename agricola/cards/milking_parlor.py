"""Milking Parlor (minor improvement, A57; Artifex Expansion).

Card text: "When you play this card, if you have at least 1/3/4 sheep, you
immediately get 2/3/4 food. The same applies if you have at least 1/2/3 cattle."
Cost 2 wood, prerequisite "At Least 4 Unused Farmyard Spaces", 1 printed VP.

Category 2 (on-play one-shot). The two clauses are INDEPENDENT and ADDITIVE
("the same applies" = a second, separate bonus), and the two ladders DIFFER:

  sheep : >=1 -> 2 food, >=3 -> 3 food, >=4 -> 4 food
  cattle: >=1 -> 2 food, >=2 -> 3 food, >=3 -> 4 food

Each ladder is BANDED / single-tier (the reward is the highest band met, not a
sum across bands); the two ladder amounts are then SUMMED. Pure food grant — no
animal accommodation concern (the animals are read, not gained).

Prerequisite — "At Least 4 Unused Farmyard Spaces": a farmyard cell is UNUSED iff
its `cell_type` is EMPTY *and* it is not part of a fenced pasture. A pasture is not
its own `CellType` — it is derived from the fence arrays — so a fenced-but-empty
pasture cell keeps `cell_type == EMPTY` yet is a USED space. The check therefore
uses `enclosed_cells`, not `cell_type` alone (the inverse of Big Country's
all-spaces-used predicate; the same documented trap).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.helpers import enclosed_cells
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "milking_parlor"


def _at_least_4_unused(state: GameState, idx: int) -> bool:
    """Prerequisite: at least 4 farmyard cells are unused (EMPTY and not enclosed
    by fences). A fenced-but-empty pasture cell reads `cell_type == EMPTY` but is a
    USED space, so it must NOT be counted as unused."""
    fy = state.players[idx].farmyard
    grid = fy.grid
    enclosed = enclosed_cells(fy)
    unused = sum(
        1
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type is CellType.EMPTY and (r, c) not in enclosed
    )
    return unused >= 4


def _sheep_food(n: int) -> int:
    # Banded single-tier: >=4 -> 4, >=3 -> 3, >=1 -> 2, else 0.
    if n >= 4:
        return 4
    if n >= 3:
        return 3
    if n >= 1:
        return 2
    return 0


def _cattle_food(n: int) -> int:
    # Banded single-tier: >=3 -> 4, >=2 -> 3, >=1 -> 2, else 0.
    if n >= 3:
        return 4
    if n >= 2:
        return 3
    if n >= 1:
        return 2
    return 0


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    food = _sheep_food(p.animals.sheep) + _cattle_food(p.animals.cattle)
    p = fast_replace(p, resources=p.resources + Resources(food=food))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=2)),
    prereq=_at_least_4_unused,
    vps=1,
    on_play=_on_play,
)
