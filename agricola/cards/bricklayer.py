"""Bricklayer (occupation, C122; Building Resource Provider).

Card text: "Each improvement and each renovation cost you 1 clay less. Each room
costs you 2 clay less."

A passive COST-REDUCTION card (COST_MODIFIER_DESIGN.md §1.1): no on-play effect — it
registers a clay reduction on each affected build kind. Reductions are signed deltas
that `apply_reductions` floors at 0.

All four clauses are live: renovate, build_room, build_major, and play_minor each
resolve through the `effective_payments` chokepoint with a `CostCtx` carrying the
matching `action_kind` (the prototype-slice era, when only renovate was wired, is over
— room coverage in tests/test_cost_modifiers.py::
test_bricklayer_room_reduction_singleton_inline_debit; the major/minor chokepoints are
exercised end-to-end by the sibling reductions in tests/test_cards_cost_cards.py). The
card is dealable — `register_occupation` is below and `cards/__init__` imports it —
with a no-op on-play (its only effect is passive cost reduction).
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
