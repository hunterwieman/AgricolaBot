"""Wood Slide Hammer (minor improvement, C13; Corbarius Expansion; players -).

Card text: "On your first renovation, if you have at least 5 wood rooms, you can
renovate to stone directly and you get a discount of 2 stone on the renovation
cost."

Cost 1 Wood; no prerequisite; no printed VPs; kept (not traveling). No on-play
effect — two standing renovate modifiers, both gated identically.

THE GATE. "On your first renovation" means the house is still WOOD: renovation
only ever moves up (WOOD -> CLAY -> STONE), never back, so `house_material ==
WOOD` holds exactly when no renovation has happened yet — the next one is the
first. "at least 5 wood rooms" = >= 5 ROOM cells while the house is wood (all
rooms share the house material, so wood rooms are just the rooms when the material
is wood). The combined gate is therefore `house == WOOD and num_rooms >= 5`.

TWO effects on that gate:

  1. RENOVATE-TARGET EXTENSION — make WOOD -> STONE a legal renovate target,
     skipping the clay tier (the Conservator shape via
     `register_renovate_target_extension`). The cost of that target then flows
     from the cost-modifier chokepoint as the stone tier (1 stone per room + 1
     reed). Self-gated on ownership + the gate.

  2. COST REDUCTION — a discount of 2 stone on that renovation
     (`register_reduction("renovate", ...)`, the Bricklayer signed-delta shape;
     the fold floors at 0). Gated additionally on `ctx.to_material is STONE` so it
     only touches the stone renovation (a wood->clay first renovation has no stone
     in its cost anyway, but scoping to the stone target keeps it exact and means
     the discount cannot leak to a later clay->stone renovation, where `house ==
     WOOD` is already false). Ownership is checked by the reduction fold.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_reduction
from agricola.cards.specs import _noop_on_play, register_minor
from agricola.constants import CellType, HouseMaterial
from agricola.legality import register_renovate_target_extension
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "wood_slide_hammer"


def _num_rooms(p) -> int:
    grid = p.farmyard.grid
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.ROOM
    )


def _gate(state: GameState, idx: int) -> bool:
    """The card's condition: first renovation (house still WOOD) with >= 5 wood rooms."""
    p = state.players[idx]
    return p.house_material is HouseMaterial.WOOD and _num_rooms(p) >= 5


def _wood_to_stone(state: GameState, idx: int, current_material) -> list:
    """Add STONE as a legal renovate target for a wood house, on the gate."""
    if CARD_ID in state.players[idx].minor_improvements and _gate(state, idx):
        return [HouseMaterial.STONE]
    return []


def _discount_2_stone(state: GameState, idx: int, ctx, cost: Resources) -> Resources:
    """-2 stone on the wood->stone first renovation (ownership checked by the fold)."""
    if ctx.to_material is HouseMaterial.STONE and _gate(state, idx):
        return cost - Resources(stone=2)
    return cost


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), on_play=_noop_on_play)
register_renovate_target_extension(_wood_to_stone)
register_reduction("renovate", CARD_ID, _discount_2_stone)
