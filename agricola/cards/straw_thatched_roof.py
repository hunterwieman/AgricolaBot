"""Straw-Thatched Roof (minor improvement, C14; Consul Dirigens Expansion; Farm Planner).

Card text: "You no longer need reed to renovate or build a room."
Cost: free (none printed). Prerequisite: 3 Grain Fields. VPs: 1. Kept (not traveling).

A passive COST-REDUCTION card (COST_MODIFIER_DESIGN.md §1.1): no on-play effect — it
registers a reduction that REMOVES the entire reed component of two build kinds, the
`renovate` and `build_room` costs. Reductions are signed deltas that the fold
(`apply_reductions`) floors at 0 after each card.

The reed is removed ENTIRELY, not by a fixed −1 (the Bricklayer shape). The card says
you "no longer need reed" at all — so a renovate or room that costs 2 reed loses both,
not one. Subtracting the cost's own reed component (`cost - Resources(reed=cost.reed)`)
zeroes it exactly regardless of how much reed the build prints; the floor-at-0 makes it
harmless even on a reed-free cost (a no-op there).

Registered on `renovate` and `build_room` ONLY (the singular cost_mods event names),
NOT `build_major` / `play_minor` — the text names renovation and building a room, no
other improvement. The reductions are inert until a build routes its cost through the
`effective_payments` chokepoint (renovate and build_room both do).

Prerequisite "3 Grain Fields": at least three FIELD cells that currently hold grain
(`cell.cell_type is FIELD and cell.grain > 0`) — the project's settled reading of a
"grain field" (a FIELD carrying grain), matching Sleeping Corner's "2 Grain Fields"
and Gardener's Knife. A prerequisite is a HAVE-check at play time, never spent.

Card-only registries are empty in the Family game (no cards owned), so the Family game
is byte-identical and the C++ differential gates are untouched. See
CARD_AUTHORING_GUIDE.md and COST_MODIFIER_DESIGN.md.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_reduction
from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "straw_thatched_roof"


def _no_reed(state: GameState, idx: int, ctx, cost: Resources) -> Resources:
    """Remove the entire reed component of the cost — "you no longer need reed."
    Subtracting the cost's own reed zeroes it exactly (any printed reed amount); the
    fold floors at 0 afterward, so a reed-free cost is left unchanged."""
    return cost - Resources(reed=cost.reed)


def _three_grain_fields(state: GameState, idx: int) -> bool:
    """Prerequisite: 3 Grain Fields — at least three FIELD cells that currently hold
    grain."""
    grid = state.players[idx].farmyard.grid
    grain_fields = sum(
        1
        for row in grid
        for cell in row
        if cell.cell_type is CellType.FIELD and cell.grain > 0
    )
    return grain_fields >= 3


register_minor(
    CARD_ID,
    cost=Cost(),                 # free — no printed cost
    prereq=_three_grain_fields,
    vps=1,
)
register_reduction("renovate", CARD_ID, _no_reed)
register_reduction("build_room", CARD_ID, _no_reed)
