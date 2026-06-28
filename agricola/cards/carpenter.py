"""Carpenter (occupation, B69; Base Revised; players 1+).

Card text: "Every new room only costs you 3 of the appropriate building resource and
2 reed (e.g. if you live in a wooden house, 3 wood and 2 reed)."

A passive cost-FORMULA card (COST_MODIFIER_DESIGN.md §1.1): it offers an alternative
*whole* cost for building a room — 3 of the house material + 2 reed — replacing the
printed `ROOM_COSTS` (5 of the material + 2 reed). Formulas are mutually exclusive (the
player uses at most one), so this registers via `register_formula`; the chokepoint
`effective_payments` surfaces the alternative alongside the printed base, lets reductions
(e.g. Bricklayer) stack on top of each, and Pareto-min keeps the cheaper. No on-play
effect — the card's only effect is the passive room-cost formula.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_formula
from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.constants import HouseMaterial
from agricola.resources import Resources

CARD_ID = "carpenter"

_MATERIAL_FIELD = {
    HouseMaterial.WOOD: "wood",
    HouseMaterial.CLAY: "clay",
    HouseMaterial.STONE: "stone",
}


def _applies(state, idx, ctx) -> bool:
    return True   # "every new room"


def _formula(state, idx, ctx) -> Resources:
    """3 of the appropriate (house) building resource + 2 reed."""
    material = state.players[idx].house_material
    return Resources(**{_MATERIAL_FIELD[material]: 3, "reed": 2})


register_formula("build_room", CARD_ID, _applies, _formula)
register_occupation(CARD_ID, _noop_on_play)   # passive cost card, no on-play
