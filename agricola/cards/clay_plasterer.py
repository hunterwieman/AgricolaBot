"""Clay Plasterer (occupation, D31; Consul Dirigens; players 1+).

Card text: "Renovating to clay only costs you exactly 1 clay and 1 reed. Each clay room
only costs you 3 clay and 2 reed to build."

Two passive cost-FORMULA clauses (COST_MODIFIER_DESIGN.md §1.1 / §4.2):
- renovate: when renovating a WOOD house to CLAY, the whole cost becomes 1 clay + 1 reed
  (regardless of room count).
- build_room: when building a room in a CLAY house, the whole cost becomes 3 clay + 2 reed.

Each clause is conditional on the (target / current) material — hence the `applies`
predicate. Formulas are mutually exclusive; cost reductions (e.g. Bricklayer) stack on
top of the chosen formula, and the printed base is also offered, with Pareto-min keeping
the cheaper. This is the §4.2 worked example: Clay Plasterer + Bricklayer on a wood→clay
renovate collapses to a frontier of just `[1 reed]`. No on-play effect.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_formula
from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.constants import HouseMaterial
from agricola.resources import Resources

CARD_ID = "clay_plasterer"


def _renovating_to_clay(state, idx, ctx) -> bool:
    return ctx.to_material == HouseMaterial.CLAY


def _renovate_to_clay_formula(state, idx, ctx) -> Resources:
    return Resources(clay=1, reed=1)


def _in_clay_house(state, idx, ctx) -> bool:
    return state.players[idx].house_material == HouseMaterial.CLAY


def _clay_room_formula(state, idx, ctx) -> Resources:
    return Resources(clay=3, reed=2)


register_formula("renovate", CARD_ID, _renovating_to_clay, _renovate_to_clay_formula)
register_formula("build_room", CARD_ID, _in_clay_house, _clay_room_formula)
register_occupation(CARD_ID, _noop_on_play)   # passive cost card, no on-play
