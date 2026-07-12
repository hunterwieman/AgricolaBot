"""Frame Builder (occupation, A123; Building Resource Provider).

Card text: "Each time you build a room/renovate, but only once per room/action, you
can replace exactly 2 clay or 2 stone with 1 wood."

A passive optional-CONVERSION card (COST_MODIFIER_DESIGN.md §1.1): no on-play effect —
it registers a conversion on the room and renovate costs. `_expand` is the
internally-budgeted generator: it returns the unchanged cost plus each legal single
substitution, so "only once per room/action" is structural — `expand_conversions`
applies the generator once, and it offers at most one replacement.

Both clauses are live: renovate and build_room each resolve through the
`effective_payments` chokepoint with a `CostCtx` carrying the matching `action_kind`
(the prototype-slice era, when only renovate was wired, is over — end-to-end coverage
in tests/test_cost_modifiers.py::test_frame_builder_room_conversion_two_step). The card
is dealable — `register_occupation` is below and `cards/__init__` imports it — with a
no-op on-play (its only effect is the passive cost conversion).
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
