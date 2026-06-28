"""Bricklayer (occupation, C122; Building Resource Provider).

Card text: "Each improvement and each renovation cost you 1 clay less. Each room
costs you 2 clay less."

A passive COST-REDUCTION card (COST_MODIFIER_DESIGN.md §1.1): no on-play effect — it
registers a clay reduction on each affected build kind. Reductions are signed deltas
that `apply_reductions` floors at 0.

Prototype-slice status (COST_MODIFIER_DESIGN.md §8): only the `renovate` clause is
exercised today — renovate is the first action wired through `effective_payments`. The
`build_room` / `build_major` / `play_minor` clauses are registered for completeness but
stay inert until those paths route through the chokepoint. The card is live (dealable)
— `register_occupation` is below and `cards/__init__` imports it — with a no-op on-play
(its only effect is passive cost reduction).
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_reduction
from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.resources import Resources

CARD_ID = "bricklayer"


def _less_1_clay(state, idx, ctx, cost: Resources) -> Resources:
    return cost - Resources(clay=1)


def _less_2_clay(state, idx, ctx, cost: Resources) -> Resources:
    return cost - Resources(clay=2)


# "Each improvement and each renovation cost 1 clay less; each room 2 clay less."
register_reduction("renovate", CARD_ID, _less_1_clay)
register_reduction("build_major", CARD_ID, _less_1_clay)   # "improvement" — major
register_reduction("play_minor", CARD_ID, _less_1_clay)    # "improvement" — minor
register_reduction("build_room", CARD_ID, _less_2_clay)

register_occupation(CARD_ID, _noop_on_play)   # no on-play effect (passive cost card)
