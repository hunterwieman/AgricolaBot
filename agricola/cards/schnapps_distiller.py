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

THE PAYMENT-FRONTIER SURFACE — ruling 77 item 1 (2026-07-21), verbatim: "we
should convert goods to food greedily. For each good type, convert at the
highest rate until you hit the max conversions count. Then convert at the next
highest rate until you hit a limit … So if we have Schnapps Distiller and are
converting N>1 veggies to food during the feeding phase, we should use Schnapps
Distiller for the first veggie and our smaller rate for the remaining N-1."
This is a CROP-input converter, so it REVERSES ruling 37's crop-input exclusion
FOR feeding-phase converters (the Studio pattern, ruling 76 item 1): the card
gains a `frontier_fire` so any `PendingFoodPayment` frame resolved DURING the
feeding phase can raise food through it at the premium rate, with the base rate
cooking any further vegetables. The greedy tiering falls out of the Pareto
enumeration (the converter's 1 veg is subtracted before the base crop core
cooks the rest) — no `frontier_group` is needed for a single-input card. As a
single-veg card its once-per-harvest budget (`harvest_conversions_used`) is
shared across the feed seam and the payment frontier, in both directions.

is_owned_fn additionally gates on `state.phase is Phase.HARVEST_FEED` (the
Studio scoping): the card is printed "in the feeding phase", so a FIELD- or
BREED-phase in-span raise frame must never offer it. The feed seam is unaffected
(its enumerator only runs under HARVEST_FEED anyway).
"""
from __future__ import annotations

from agricola.cards.harvest_conversions import (
    HarvestConversionSpec,
    register_harvest_conversion,
)
from agricola.cards.specs import register_occupation
from agricola.constants import Phase
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "schnapps_distiller"


def _owns(state: GameState, idx: int) -> bool:
    """True iff the state is in the feeding phase and this player owns Schnapps
    Distiller.

    The conversion enumerator gates only on is_owned_fn, and registrations are
    global, so the occupation-ownership check must live here — otherwise the
    1-veg->5-food conversion would be offered to the non-owner. The
    `Phase.HARVEST_FEED` gate (ruling 77 / the Studio pattern) scopes the
    payment-frontier surface to the feeding phase — the card is printed "in the
    feeding phase", so an in-span FIELD/BREED raise frame never offers it. It is
    inert at the feed seam, whose enumerator only runs under HARVEST_FEED.
    """
    if state.phase is not Phase.HARVEST_FEED:
        return False
    return CARD_ID in state.players[idx].occupations


# Pure-conversion occupation: played via Lessons, but its on-play effect is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)

# The recurring craft: spend exactly 1 vegetable, produce 5 food. The
# frontier_fire (ruling 77) is the 6-tuple (grain,veg,wood,clay,reed,stone):
# 1 veg -> 5 food, a crop-input converter on the payment frontier.
register_harvest_conversion(HarvestConversionSpec(
    conversion_id=CARD_ID,
    input_cost=Resources(veg=1),
    food_out=5,
    is_owned_fn=_owns,
    frontier_fire=((0, 1, 0, 0, 0, 0), 5),
))
