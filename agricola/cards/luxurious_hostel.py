"""Luxurious Hostel (minor improvement, D34; Dulcinaria Expansion; players -).

Card text: "During scoring, if you then have more stone rooms than people, you
get 4 bonus points. You can only use one card to get bonus points for your
stone house."

Cost 1 Wood + 2 Clay; no prerequisite; not passing; no flat printed VPs (the 4
points are CONDITIONAL, so they live in the scoring term, not in `vps=`).

A pure end-game scoring term — no on-play effect (its on-play is a no-op). The
condition is a STRICT comparison: stone rooms > people (equal counts score 0).
"Stone rooms" are real only when the house is stone (all rooms share one
material, `ps.house_material`), so a wood/clay house always scores 0 here.
"People" is the total people in play (home + placed) = `ps.people_total`.

Category 1 (end-game scoring). No stored state — derived from the farmyard.

The trailing clause "You can only use one card to get bonus points for your
stone house" is a cross-card de-duplication rule among the Dulcinaria
stone-house bonus cards. No sibling such card is implemented today, so this
clause is inert and a standalone scoring term is faithful; a shared mutual-
exclusion mechanism would be needed if/when a sibling card is added.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import CellType, HouseMaterial
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "luxurious_hostel"


def _stone_rooms(state: GameState, idx: int) -> int:
    """Count rooms only when the house is stone (all rooms share one material)."""
    ps = state.players[idx]
    if ps.house_material != HouseMaterial.STONE:
        return 0
    grid = ps.farmyard.grid
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.ROOM
    )


def _score(state: GameState, idx: int) -> int:
    ps = state.players[idx]
    # STRICT: more stone rooms than people → 4 bonus points; equal/fewer → 0.
    return 4 if _stone_rooms(state, idx) > ps.people_total else 0


# Pure scoring minor: kept (not passing); its on-play effect is a no-op.
register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1, clay=2)),
    on_play=lambda state, idx: state,
)
register_scoring(CARD_ID, _score)
