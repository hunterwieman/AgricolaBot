"""Strawberry Patch (minor improvement, B45; Base Revised).

Card text: "Place 1 food on each of the next 3 round spaces. At the start of these
rounds, you get the food."
Cost: 1 Wood. Prerequisite: 2 Vegetable Fields. VPs: 2. Not passing.

Category 8 (deferred goods). Identical schedule to Pond Hut (1 food on the next 3
round spaces, R+1..R+3) but a different cost/prereq/VP. "2 Vegetable Fields" is a
prerequisite: at least 2 fields currently holding vegetables — FIELD cells on the
farmyard grid (veg > 0) plus vegetable-holding card-fields
(`crop_card_field_count(p, "veg")`). Ruling 45 (2026-07-12), verbatim: '"field
TILES" means the plowed fields on the farmyard grid; "field" is the BROADER
category and includes card-fields. So a card-field counts for field-count readers —
the Fields scoring category and any "you need N fields" requirement — while
per-TILE readers still exclude it (ruling 32 unchanged).'
"""
from __future__ import annotations

from agricola.constants import CellType
from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "strawberry_patch"


def _two_vegetable_fields(state: GameState, idx: int) -> bool:
    """Prereq: 2 Vegetable Fields — grid FIELD cells holding veg, plus
    veg-holding card-fields (ruling 45, 2026-07-12: "field" includes
    card-fields; ruling 47: each card counts exactly once)."""
    from agricola.cards.card_fields import crop_card_field_count  # local: load-order safe
    p = state.players[idx]
    grid = p.farmyard.grid
    n_veg_fields = sum(
        1
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type is CellType.FIELD and grid[r][c].veg > 0
    ) + crop_card_field_count(p, "veg")
    return n_veg_fields >= 2


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    return schedule_resources(state, idx, range(R + 1, R + 4), Resources(food=1))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1)),
    prereq=_two_vegetable_fields,
    vps=2,
    on_play=_on_play,
)
