"""Schnapps Distiller (occupation, C109; Consul Dirigens Expansion; players 1+).

Card text: "In the feeding phase of each harvest, you can use this card to turn
exactly 1 vegetable into 5 food."

Category: Food Provider. No on-play effect (played via Lessons; its on-play is a
no-op). The recurring "in the feeding phase of each harvest, you can turn 1
vegetable into 5 food" is a once-per-harvest goods-to-food conversion offered
during HARVEST_FEED — exactly the shape of the three built-in crafts (joinery /
pottery / basketmaker), which each take one good and PRODUCE food. Here the good
is 1 vegetable and the output is 5 food (no points, no side effect).

"exactly 1 vegetable ... in the feeding phase of each harvest": the once-per-
harvest cap is enforced automatically — firing marks "schnapps_distiller" in
PlayerState.harvest_conversions_used, which the enumerator skips, and that set is
reset at the start of every harvest's FEED. A single registry entry (unlike Beer
Keg's three grain variants), so no cross-variant guard is needed.

The conversion enumerator (legality.py) gates only on is_owned_fn, and
registrations are global, so is_owned_fn MUST confirm THIS player owns the
occupation — otherwise the conversion would be offered to the non-owner.
"""
from __future__ import annotations

from agricola.cards.harvest_conversions import (
    HarvestConversionSpec,
    register_harvest_conversion,
)
from agricola.cards.specs import register_occupation
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "schnapps_distiller"


def _owns(state: GameState, idx: int) -> bool:
    """True iff this player owns Schnapps Distiller.

    The conversion enumerator gates only on is_owned_fn, and registrations are
    global, so the occupation-ownership check must live here — otherwise the
    1-veg->5-food conversion would be offered to the non-owner.
    """
    return CARD_ID in state.players[idx].occupations


# Pure-conversion occupation: played via Lessons, but its on-play effect is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)

# The recurring craft: spend exactly 1 vegetable, produce 5 food.
register_harvest_conversion(HarvestConversionSpec(
    conversion_id=CARD_ID,
    input_cost=Resources(veg=1),
    food_out=5,
    is_owned_fn=_owns,
))
