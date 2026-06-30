"""Slurry Spreader (occupation, A106; Artifex Expansion; players 1+).

Card text: "In the field phase of each harvest, each time you take the last
grain/vegetable from a field, you also get 2 food/1 food."

Category 6 (harvest-field hook), automatic income. A mandatory, choice-free
reward → an automatic effect (register_auto on `harvest_field`), not a
FireTrigger.

"The last grain/vegetable from a field" means a field whose remaining crop count
is exactly 1: the mechanical field-phase take removes exactly one crop per planted
field this harvest, emptying any 1-count field. The `harvest_field` hook fires
BEFORE that mechanical take (see `_resolve_harvest_field` / `_fire_harvest_field_hook`
in engine.py), so at fire time the fields are still fully sown and a field reading
grain==1 / veg==1 is exactly the one whose *last* crop is about to be taken. A
field with grain>=2 keeps a grain after the take, so its last grain is NOT taken
this harvest and it earns nothing.

A field is sown with a single crop type (grain XOR veg — `_execute_sow` fills
grain=3 OR veg=2), so grain==1 and veg==1 are mutually exclusive per cell. The
reward is +2 food per last-grain field and +1 food per last-veg field, summed.

Slurry only READS the grid (no mutation): the mechanical take in
`_resolve_harvest_field` performs the actual crop removal. Reading the live grid at
Slurry's own fire time (not a pre-snapshot) keeps it correct under interaction with
other harvest-field cards (e.g. Scythe Worker, which fires first per registration
order and can reduce a 2-grain field to 1 grain — Slurry then correctly counts that
field as grain==1).

Played via Lessons; its on-play is a no-op. See CARD_BATCH_TRIAGE.md (A106).
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto, register_harvest_field_hook
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "slurry_spreader"


def _eligible(state: GameState, idx: int) -> bool:
    # Some field is about to have its LAST crop taken this harvest: a field whose
    # remaining grain or veg is exactly 1.
    return any(
        cell.cell_type == CellType.FIELD and (cell.grain == 1 or cell.veg == 1)
        for row in state.players[idx].farmyard.grid
        for cell in row
    )


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    food = 0
    for row in p.farmyard.grid:
        for cell in row:
            if cell.cell_type != CellType.FIELD:
                continue
            if cell.grain == 1:
                food += 2
            elif cell.veg == 1:
                food += 1
    if food == 0:
        return state
    p = fast_replace(p, resources=p.resources + Resources(food=food))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("harvest_field", CARD_ID, _eligible, _apply)
register_harvest_field_hook(CARD_ID)
