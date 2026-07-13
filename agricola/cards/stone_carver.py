"""Stone Carver (occupation, D108; Consul Dirigens Expansion; players 1+).

Card text (verbatim): "Each harvest, you can use this card to turn exactly
1 stone into 3 food."

Category: Food Provider. No on-play effect (played via Lessons; its on-play is
a no-op). The recurring exchange is the HARVEST_CONVERSIONS seam's native
shape: "Each harvest" = once per harvest — the standard
`harvest_conversions_used` budget — with the conversion offered on the feed
frame (`CommitHarvestConversion`) while unused this harvest and a stone is in
supply.

A PURE building-resource -> food converter (1 stone -> 3 food, no rider
outputs), so it is also reachable through the generalized in-harvest raise
frame — the PendingFoodPayment frontier — via `frontier_fire` (rulings 34/37,
2026-07-12): a raise-frame fire debits the stone, raises the 3 food, and marks
the SAME once-per-harvest budget the feed-seam offer checks, so the two
surfaces share one use per harvest.

`is_owned_fn` checks THIS player's occupations explicitly (the Furniture
Carpenter caution: registrations are global, so without the ownership check
the conversion would be offered to non-owners).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from agricola.cards.harvest_conversions import (
    HarvestConversionSpec,
    register_harvest_conversion,
)
from agricola.cards.specs import register_occupation
from agricola.resources import Resources

if TYPE_CHECKING:
    from agricola.state import GameState

CARD_ID = "stone_carver"


def _owns(state: "GameState", idx: int) -> bool:
    """This player has PLAYED Stone Carver (the per-player ownership gate —
    the conversion registry is global)."""
    return CARD_ID in state.players[idx].occupations


# Pure recurring converter: played via Lessons, its on-play effect is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)

register_harvest_conversion(HarvestConversionSpec(
    conversion_id=CARD_ID,
    input_cost=Resources(stone=1),
    food_out=3,
    is_owned_fn=_owns,
    frontier_fire=((0, 0, 0, 1), 3),   # (wood, clay, reed, stone) -> food
))
