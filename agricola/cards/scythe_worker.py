"""Scythe Worker (occupation, A112; Base Revised; players 1+).

Card text: "When you play this card, you immediately get 1 grain. In the field
phase of each harvest, you can harvest 1 additional grain from each of your grain
fields."

Category 2 on-play (+1 grain) + Category 6 (harvest-field hook). The field-phase
clause harvests one ADDITIONAL grain from each grain field — taken FROM the field,
so the field is depleted by 2 this harvest (1 here + 1 in the mechanical take),
not 1. The additional grain only comes from fields with >= 2 grain: a 1-grain
field gives its single grain to the normal take with none to spare. Implemented as
an automatic effect (register_auto on `harvest_field`), fired by
`_resolve_harvest_field` BEFORE the mechanical crop take — firing first matters so
the additional grain is removed while the fields are still fully sown.

DELIBERATELY DEFERRED — the choice. The card reads "you CAN harvest 1 additional
grain from each of your grain fields": it is OPTIONAL because taking the extra
grain depletes the field (trading future-harvest yield for grain now). With the
*current* card set, taking it on every eligible field is strictly optimal, so we
model it as mandatory-take-the-maximum and skip the choice machinery (YAGNI). When
a later card makes partial use meaningful, surface the choice by following the
PLANNED design — do NOT invent harvest-flow structure:
  - Realize `PendingHarvestField` as a per-relevant-player SURFACED host, pushed
    at field-phase entry, mirroring the feed/breed pendings (CARD_SYSTEM_DESIGN.md
    §"Harvest-field hook"; CARD_IMPLEMENTATION_PLAN.md §II.6 / Category 6). The
    current single transient frame is the automatic-only simplification of that.
  - Represent Scythe as a WIDE trigger on that host: present every count option
    (use on 1 … N fields) at once as the trigger's choices, plus Proceed to decline
    — analogous to the play-variant pattern (roof_ballaster / Cooking Hearth), not a
    fire-then-sub-decision.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto, register_harvest_field_hook
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "scythe_worker"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(grain=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible(state: GameState, idx: int) -> bool:
    # Only a field with >= 2 grain can spare an ADDITIONAL grain beyond the
    # mechanical 1-per-field take this harvest.
    return any(
        cell.cell_type == CellType.FIELD and cell.grain >= 2
        for row in state.players[idx].farmyard.grid
        for cell in row
    )


def _apply(state: GameState, idx: int) -> GameState:
    """Take 1 additional grain FROM each grain field with >= 2 grain: decrement the
    field and credit supply. Fires before the mechanical take, which then removes
    the remaining 1 per field — so a >=2-grain field is depleted by 2 total."""
    p = state.players[idx]
    new_grid = []
    additional = 0
    for row in p.farmyard.grid:
        new_row = []
        for cell in row:
            if cell.cell_type == CellType.FIELD and cell.grain >= 2:
                additional += 1
                new_row.append(fast_replace(cell, grain=cell.grain - 1))
            else:
                new_row.append(cell)
        new_grid.append(tuple(new_row))
    if additional == 0:
        return state
    # Fields never lie inside pastures, so the pasture cache rides along on the
    # grid fast_replace (mirrors _resolve_harvest_field's mechanical take).
    new_fy = fast_replace(p.farmyard, grid=tuple(new_grid))
    p = fast_replace(p, farmyard=new_fy, resources=p.resources + Resources(grain=additional))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, _on_play)
register_auto("harvest_field", CARD_ID, _eligible, _apply)
register_harvest_field_hook(CARD_ID)
