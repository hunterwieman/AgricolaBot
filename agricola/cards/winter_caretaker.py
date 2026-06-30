"""Winter Caretaker (occupation, C113; Consul Dirigens Expansion; players 1+).

Card text: "When you play this card, you immediately get 1 grain. At the end of
each harvest, you can buy exactly 1 vegetable for 2 food."

Category: Crop Provider. Two effects:

1. On play (via Lessons): immediately +1 grain. A one-shot resource grant, the
   same shape as Consultant's on-play.

2. A recurring, optional, once-per-harvest food-to-good buy: spend 2 food, get 1
   vegetable. This is the exact shape the HarvestConversionSpec hook exists for —
   but inverted from the three built-in crafts (joinery/pottery/basketmaker),
   which take a good and PRODUCE food. Here the player spends food and produces
   NO food (food_out=0); the vegetable is granted by the side_effect_fn. This
   mirrors Furniture Carpenter (food_out=0 + side_effect_fn banks a point) — the
   only difference being that the side effect adds a normal good (1 veg) rather
   than a banked bonus point, so there is no scoring term.

   "buy EXACTLY 1": the once-per-harvest guard is automatic — firing the
   conversion adds its id to harvest_conversions_used, so the enumerator stops
   offering it for the rest of the harvest. harvest_conversions_used resets at
   the start of each harvest's FEED phase, so each harvest gets a fresh single
   buy. The HARVEST_FEED enumerator also gates on affordability, so the buy is
   only surfaced when the player holds at least 2 food, and declining is implicit
   (commit the feeding CommitConvert without firing it).

Timing note: the card says "at the end of each harvest", whereas the
harvest-conversion registry is surfaced during the FEED sub-phase
(FIELD -> FEED -> BREED). The difference is mechanically harmless here — nothing
observable happens between FEED and harvest-end that interacts with holding +1
vegetable, and the once-per-harvest guard correctly enforces "buy exactly 1". A
strict end-of-harvest (post-BREED) hook does not exist and is not warranted for
this card.

The conversion enumerator gates only on is_owned_fn, and registrations are
global, so the occupation-ownership check lives in _eligible — otherwise the buy
would be offered to a non-owner.

Card-only state is empty in the Family game, so it stays byte-identical and the
C++ gates are untouched. See harvest_conversions.py / furniture_carpenter.py.
"""
from __future__ import annotations

from agricola.cards.harvest_conversions import (
    HarvestConversionSpec,
    register_harvest_conversion,
)
from agricola.cards.specs import register_occupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "winter_caretaker"


def _on_play(state: GameState, idx: int) -> GameState:
    """When you play this card, you immediately get 1 grain."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(grain=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible(state: GameState, idx: int) -> bool:
    """True iff this player owns Winter Caretaker.

    The conversion enumerator gates only on is_owned_fn, and registrations are
    global, so the occupation-ownership check must live here — otherwise the
    buy-a-vegetable would be offered to the non-owner. There is no further
    prerequisite (affordability — 2 food — is checked by the enumerator).
    """
    return CARD_ID in state.players[idx].occupations


def _grant_veg(state: GameState, idx: int) -> GameState:
    """side_effect_fn: grant 1 vegetable (the 2 food cost was already paid by the
    conversion executor; food_out=0 so no food is produced)."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(veg=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


# On-play: +1 grain.
register_occupation(CARD_ID, _on_play)

# Recurring once-per-harvest buy: 2 food -> 1 vegetable (food_out=0; the
# vegetable is granted by the side_effect_fn).
register_harvest_conversion(HarvestConversionSpec(
    conversion_id=CARD_ID,
    input_cost=Resources(food=2),
    food_out=0,
    is_owned_fn=_eligible,
    side_effect_fn=_grant_veg,
))
