"""Stonecutter (occupation, A143; Base Revised; players 3+).

Card text: "Every improvement, room, and renovation costs you 1 stone less."

A passive COST-REDUCTION card (COST_MODIFIER_DESIGN.md §1.1), the Bricklayer shape in
stone instead of clay: a flat −1 stone on each affected build kind — "improvement"
(major AND minor), "room" (build_room), and "renovation" (renovate). Reductions are
signed deltas that the chokepoint's `apply_reductions` floors at 0, so a build with
little/no stone in its printed cost is simply unaffected. No on-play effect.

The four clauses each resolve through the `effective_payments` chokepoint with a
`CostCtx` carrying the matching `action_kind`. This is a [3+] occupation — not dealt in
the 2-player game, but valid to implement and unit-test now.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_reduction
from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.resources import Resources

CARD_ID = "stonecutter"


def _less_1_stone(state, idx, ctx, cost: Resources) -> Resources:
    return cost - Resources(stone=1)


# "Every improvement, room, and renovation costs 1 stone less."
register_reduction("build_major", CARD_ID, _less_1_stone)   # "improvement" — major
register_reduction("play_minor", CARD_ID, _less_1_stone)    # "improvement" — minor
register_reduction("build_room", CARD_ID, _less_1_stone)    # "room"
register_reduction("renovate", CARD_ID, _less_1_stone)      # "renovation"

register_occupation(CARD_ID, _noop_on_play)   # no on-play effect (passive cost card)
