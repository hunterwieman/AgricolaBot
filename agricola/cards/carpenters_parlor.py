"""Carpenter's Parlor (minor improvement, B13; Base Revised; cost 1 wood + 1 stone).

Card text: "Wooden rooms only cost you 2 wood and 2 reed each."

A passive cost-FORMULA card (COST_MODIFIER_DESIGN.md §1.1 / §4.2), conditional on the
house material: when the player lives in a WOOD house, building a room costs the fixed
alternative 2 wood + 2 reed (replacing the printed 5 wood + 2 reed). In a clay or stone
house the clause does not apply — "wooden rooms" — so the `applies` predicate gates it on
`house_material == WOOD`, mirroring Clay Plasterer's per-material formula. Formulas are
mutually exclusive (the player uses at most one); the chokepoint surfaces this alternative
beside the printed base, lets reductions stack on each, and Pareto-min keeps the cheaper.

It is a MINOR (cost 1 wood + 1 stone, no prereq, no printed VPs) whose ONLY effect is the
passive room-cost formula — no on-play effect.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_formula
from agricola.cards.specs import register_minor
from agricola.constants import HouseMaterial
from agricola.resources import Cost, Resources

CARD_ID = "carpenters_parlor"


def _in_wood_house(state, idx, ctx) -> bool:
    return state.players[idx].house_material == HouseMaterial.WOOD


def _wood_room_formula(state, idx, ctx) -> Resources:
    return Resources(wood=2, reed=2)


register_formula("build_room", CARD_ID, _in_wood_house, _wood_room_formula)
register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1, stone=1)))
