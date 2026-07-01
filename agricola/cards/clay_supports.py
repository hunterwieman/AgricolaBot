"""Clay Supports (minor improvement, D15; Consul Dirigens; cost 2 wood).

Card text: "Each time you build a clay room, you can pay 2 clay, 1 wood, and 1 reed
instead of 5 clay and 2 reed."

A passive cost-FORMULA card (COST_MODIFIER_DESIGN.md §1.1 / §4.2), conditional on the
house material. A "clay room" is a room built while living in a CLAY house — its printed
cost is `ROOM_COSTS[CLAY] = 5 clay + 2 reed`, exactly the card's "instead of 5 clay and 2
reed". When the player lives in a clay house, building a room may instead cost the fixed
alternative 2 clay + 1 wood + 1 reed. The `applies` predicate therefore gates on
`house_material == CLAY`, mirroring Clay Plasterer's clay-room formula clause exactly.

Formulas are mutually exclusive (the player uses at most one); the `effective_payments`
chokepoint surfaces this alternative beside the printed base and lets reductions stack on
each. The two payments are Pareto-INCOMPARABLE over goods spent — the formula uses less
clay + reed but 1 more wood — so both survive the frontier rather than one dominating. That
is exactly the card's "you can pay ... instead": a genuine choice (cheaper unless the player
is wood-poor), surfaced to the agent as a two-way cost decision, with nothing extra
hand-coded.

It is a MINOR (cost 2 wood, no prereq, no printed VPs) whose ONLY effect is the passive
clay-room-cost formula — no on-play effect.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_formula
from agricola.cards.specs import register_minor
from agricola.constants import HouseMaterial
from agricola.resources import Cost, Resources

CARD_ID = "clay_supports"


def _in_clay_house(state, idx, ctx) -> bool:
    return state.players[idx].house_material == HouseMaterial.CLAY


def _clay_room_formula(state, idx, ctx) -> Resources:
    return Resources(clay=2, wood=1, reed=1)


register_formula("build_room", CARD_ID, _in_clay_house, _clay_room_formula)
register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2)))
