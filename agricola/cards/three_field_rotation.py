"""Three-Field Rotation (minor improvement, B61; Base Revised; free, 3-occupation prereq).

Card text: "At the start of the field phase of each harvest, if you have at least
1 grain field, 1 vegetable field, and 1 empty field, you get 3 food." No cost, no
printed VPs. Prerequisite: 3 occupations.

Category 6 (harvest-field hook). A MANDATORY, choice-free income → an automatic
effect (register_auto on the `harvest_field` event), fired by
`_resolve_harvest_field` BEFORE the mechanical crop take — so the eligibility
read sees the fields still sown (matching the card's "at the start of the field
phase" timing). A FIELD cell counts as a grain field if it holds grain, a
vegetable field if it holds veg, and an empty field if it holds neither. See
CARD_IMPLEMENTATION_PLAN.md Category 6.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto, register_harvest_field_hook
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "three_field_rotation"


def _eligible(state: GameState, idx: int) -> bool:
    has_grain = has_veg = has_empty = False
    for row in state.players[idx].farmyard.grid:
        for cell in row:
            if cell.cell_type != CellType.FIELD:
                continue
            if cell.grain > 0:
                has_grain = True
            elif cell.veg > 0:
                has_veg = True
            else:
                has_empty = True
    return has_grain and has_veg and has_empty


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=3))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, min_occupations=3)
register_auto("harvest_field", CARD_ID, _eligible, _apply)
register_harvest_field_hook(CARD_ID)
