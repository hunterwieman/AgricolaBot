"""Brushwood Collector (occupation, B145; Base Revised; players 3+).

Card text: "Each time you renovate or build a room, you can replace the required 1 or 2
reed with a total of 1 wood."

A passive optional-CONVERSION card (COST_MODIFIER_DESIGN.md §1.1), the Frame Builder
shape: it registers a conversion on the renovate and build_room costs that swaps the
whole reed requirement for a single wood. Renovate requires 1 reed (num_rooms of the
target material + 1 reed) and a room requires 2 reed (ROOM_COSTS), so "the required 1 or
2 reed" is exactly those two cases — the substitution removes ALL the required reed and
adds a total of 1 wood (not 1 wood per reed). "you can" → optional, so `_expand` returns
the unchanged cost PLUS the single substitution variant, and the play path offers both.

Both clauses resolve through the `effective_payments` chokepoint with a `CostCtx`
carrying the matching `action_kind`. This is a [3+] occupation — not dealt in the
2-player game, but valid to implement and unit-test now. No on-play effect.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_conversion
from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.resources import Resources

CARD_ID = "brushwood_collector"


def _expand(state, idx, ctx, cost: Resources) -> list[Resources]:
    """Unchanged cost + the "replace the required 1 or 2 reed with a total of 1 wood"
    substitution (offered only when the cost's reed is the printed 1 or 2)."""
    out = [cost]
    if 1 <= cost.reed <= 2:
        out.append(cost - Resources(reed=cost.reed) + Resources(wood=1))
    return out


register_conversion("renovate", CARD_ID, _expand)
register_conversion("build_room", CARD_ID, _expand)

register_occupation(CARD_ID, _noop_on_play)   # no on-play effect (passive cost card)
