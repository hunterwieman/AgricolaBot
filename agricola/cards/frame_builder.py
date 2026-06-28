"""Frame Builder (occupation, A123; Building Resource Provider).

Card text: "Each time you build a room/renovate, but only once per room/action, you
can replace exactly 2 clay or 2 stone with 1 wood."

A passive optional-CONVERSION card (COST_MODIFIER_DESIGN.md §1.1): no on-play effect —
it registers a conversion on the room and renovate costs. `_expand` is the
internally-budgeted generator: it returns the unchanged cost plus each legal single
substitution, so "only once per room/action" is structural — `expand_conversions`
applies the generator once, and it offers at most one replacement.

Prototype-slice status (COST_MODIFIER_DESIGN.md §8): only the `renovate` clause is
exercised today (the first action wired through `effective_payments`); `build_room` is
registered for completeness but inert until that path routes through the chokepoint.
The card is live (dealable) — `register_occupation` is below and `cards/__init__`
imports it — with a no-op on-play (its only effect is the passive cost conversion).
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_conversion
from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.resources import Resources

CARD_ID = "frame_builder"


def _expand(state, idx, ctx, cost: Resources) -> list[Resources]:
    """Unchanged cost + each legal "exactly 2 clay OR 2 stone -> 1 wood" substitution.
    Requires the 2 units to be present in the cost ("exactly 2")."""
    out = [cost]
    if cost.clay >= 2:
        out.append(cost - Resources(clay=2) + Resources(wood=1))
    if cost.stone >= 2:
        out.append(cost - Resources(stone=2) + Resources(wood=1))
    return out


register_conversion("renovate", CARD_ID, _expand)
register_conversion("build_room", CARD_ID, _expand)

register_occupation(CARD_ID, _noop_on_play)   # no on-play effect (passive cost card)
