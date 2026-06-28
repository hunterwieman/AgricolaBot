"""Lumber Mill (minor improvement, A75; Base Revised; cost 2 stone, <=3 occupations, 2 VP).

Card text: "Every improvement costs you 1 wood less."

A passive cost-REDUCTION card (COST_MODIFIER_DESIGN.md §1.1): a signed −1-wood delta on
the cost, floored at 0 by `apply_reductions`. "Improvement" means a MAJOR or MINOR
improvement only — it does NOT include rooms or renovation. (Contrast Stonecutter, which
says "every improvement, room, AND renovation," and Bricklayer, which spells out room +
renovation clauses separately.) So the reduction registers on exactly `build_major` and
`play_minor`, and nothing else.

It is a MINOR with a structured definition: cost 2 stone, the occupation-count prerequisite
"At Most 3 Occupations" (`max_occupations=3`), and 2 printed victory points. Its only effect
is the passive cost reduction — no on-play effect (the default no-op).
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_reduction
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources

CARD_ID = "lumber_mill"


def _less_1_wood(state, idx, ctx, cost: Resources) -> Resources:
    return cost - Resources(wood=1)


# "Every improvement" = major OR minor improvement (NOT rooms / renovation).
register_reduction("build_major", CARD_ID, _less_1_wood)
register_reduction("play_minor", CARD_ID, _less_1_wood)

register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(stone=2)),
    max_occupations=3,
    vps=2,
)
