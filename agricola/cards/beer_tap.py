"""Beer Tap (minor improvement, D62; Dulcinaria Expansion; Food Provider).

Card text: "When you play this card, you immediately get 2 food. In the feeding
phase of each harvest, you can turn 2/3/4 grain into 3/6/9 food."
Cost: 1 Wood. No prerequisite. VPs: 0. Not passing.

Two effects:

1. ON PLAY — the owner immediately gains 2 food (the market_stall on-play
   goods-grant pattern).

2. A recurring, optional, once-per-harvest grain-to-food conversion offered
   during HARVEST_FEED — the exact shape the HarvestConversionSpec hook exists
   for. The player CHOOSES how much grain to spend, and the food scales with it:

     - spend 2 grain -> 3 food
     - spend 3 grain -> 6 food
     - spend 4 grain -> 9 food

   Unlike Beer Keg, there are no banked bonus points and no CardStore: this is a
   pure grain->food conversion (3 food per 2 grain at the cheapest tier, rising
   to 9 food per 4 grain). The HARVEST_FEED enumerator surfaces one
   CommitHarvestConversion per HARVEST_CONVERSIONS entry that is (a) owned,
   (b) not yet fired this harvest, and (c) affordable. So the three grain amounts
   are three separate registry entries (beer_tap_2 / beer_tap_3 / beer_tap_4),
   and the player picks one by firing its CommitHarvestConversion.

ONCE PER HARVEST — a CHOICE, not three independent fires. The card may be used
once per harvest, choosing a single grain amount. Each entry's is_owned_fn
therefore gates on "no beer_tap_* variant has fired yet this harvest" in addition
to actual ownership of the minor: firing beer_tap_3 marks beer_tap_3 in
harvest_conversions_used, but the enumerator re-checks is_owned_fn every call, so
the cross-variant guard reads harvest_conversions_used directly and suppresses the
other two variants for the rest of this harvest. (harvest_conversions_used is reset
to empty at the start of every harvest's FEED phase, so each harvest gets a fresh
single use.) Without this guard, the player could fire all three (2+3+4 grain ->
18 food) in one harvest, which the "turn 2/3/4 grain into 3/6/9 food" tiered
wording forbids.

THE PAYMENT-FRONTIER SURFACE — ruling 77 item 1 (2026-07-21), verbatim: "we
should convert goods to food greedily. For each good type, convert at the
highest rate until you hit the max conversions count. Then convert at the next
highest rate until you hit a limit …". Beer Tap is a feeding-phase CROP
converter, so it joins any `PendingFoodPayment` frame resolved DURING the
feeding phase (the Studio pattern, reversing ruling 37's crop-input exclusion):
each of the three tiers carries a `frontier_fire` (grain -> food) so the raise
frame can pay through it. As a MULTI-VARIANT card (three tiers of one card,
ONE once-per-harvest budget), all three carry `frontier_group="beer_tap"` — a
single payment bundle fires AT MOST ONE tier (co-firing two would use the card
twice in one harvest; the Studio group mechanism). The cross-FRAME budget stays
the prefix guard above (is_owned_fn reads harvest_conversions_used), so the feed
seam and the payment frontier share one use in both directions. is_owned_fn also
gates on `state.phase is Phase.HARVEST_FEED` (printed "in the feeding phase"):
an in-span FIELD/BREED raise frame never offers it; the feed seam is unaffected.

Card-only state (the harvest_conversions_used variants) is empty in the Family
game, so it stays byte-identical and the C++ gates are untouched.
See CARD_AUTHORING_GUIDE.md and harvest_conversions.py / beer_keg.py /
studio.py / market_stall.py.
"""
from __future__ import annotations

from agricola.cards.harvest_conversions import (
    HarvestConversionSpec,
    register_harvest_conversion,
)
from agricola.cards.specs import register_minor
from agricola.constants import Phase
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "beer_tap"

# (grain spent, food produced) for the three tiers of the conversion.
_VARIANTS = ((2, 3), (3, 6), (4, 9))


def _on_play(state: GameState, idx: int) -> GameState:
    """When played, the owner immediately gains 2 food."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=2))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _make_is_owned(grain: int) -> "object":
    """Return is_owned_fn for the beer_tap_<grain> variant.

    The variant is offered iff the player owns Beer Tap AND no beer_tap_* variant
    has already fired this harvest. The cross-variant guard reads
    harvest_conversions_used directly (the enumerator re-checks is_owned_fn on
    every call), so the card is used at most once per harvest even though it has
    three registry entries.
    """
    def fn(state: GameState, idx: int) -> bool:
        # Phase gate (ruling 77 / the Studio pattern): the payment-frontier
        # surface is feeding-phase-scoped (printed "in the feeding phase"). The
        # feed seam is unaffected — its enumerator only runs under HARVEST_FEED.
        if state.phase is not Phase.HARVEST_FEED:
            return False
        p = state.players[idx]
        if CARD_ID not in p.minor_improvements:
            return False
        # Once per harvest across all three variants (the cross-FRAME budget,
        # shared by the feed seam and the payment frontier).
        return not any(cid.startswith(CARD_ID) for cid in p.harvest_conversions_used)
    return fn


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), vps=0, on_play=_on_play)

for _grain, _food in _VARIANTS:
    register_harvest_conversion(HarvestConversionSpec(
        conversion_id=f"{CARD_ID}_{_grain}",
        input_cost=Resources(grain=_grain),
        food_out=_food,
        is_owned_fn=_make_is_owned(_grain),
        side_effect_fn=None,
        # Ruling 77: the grain->food tier on the payment frontier. The 6-tuple
        # is (grain,veg,wood,clay,reed,stone). frontier_group ties the three
        # tiers to ONE budget within a single bundle (the Studio mechanism).
        frontier_fire=((_grain, 0, 0, 0, 0, 0), _food),
        frontier_group=CARD_ID,
    ))
