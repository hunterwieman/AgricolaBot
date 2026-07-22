"""Studio (minor improvement, C55; Corbarius Expansion; Food Provider).

Card text: "In the feeding phase of each harvest, you can use this card to turn
exactly 1 wood/clay/stone into 2/2/3 food."
Cost: 1 Clay, 1 Reed. VPs: 1. No prerequisite. Not passing.

A recurring, optional, once-per-harvest goods-to-food conversion offered during
HARVEST_FEED — the exact shape the HarvestConversionSpec hook exists for. The
player may use the card once per harvest, choosing which single building
resource to convert:

  - turn 1 wood  -> 2 food
  - turn 1 clay  -> 2 food
  - turn 1 stone -> 3 food

This is the same conversion shape as the three built-in crafts
(joinery/pottery/basketmaker), bundled onto one card. The "exactly 1
wood/clay/stone" wording means the card fires AT MOST ONCE per harvest (a CHOICE
of which resource, not three independent fires) — distinct from owning all three
crafts, which would let you fire each independently.

Simpler than Beer Keg (the multi-variant template): Studio banks no points, so
there is no CardStore, no side_effect_fn, and no scoring term. The printed 1
victory point is handled entirely by register_minor's vps=1.

ONCE PER HARVEST — the load-bearing subtlety. The card has three registry
entries (studio_wood / studio_clay / studio_stone), but the HARVEST_FEED
enumerator surfaces one CommitHarvestConversion per entry that is (a) owned,
(b) not yet fired this harvest, and (c) affordable. Each variant's is_owned_fn
therefore gates on "no studio_* variant has fired yet this harvest" in addition
to actual ownership: firing studio_wood marks studio_wood in
harvest_conversions_used, but the enumerator re-checks is_owned_fn every call, so
the cross-variant guard reads harvest_conversions_used directly and suppresses
the OTHER two variants for the rest of this harvest. (Without this guard a player
could illegally fire wood+clay+stone in a single harvest.) harvest_conversions_used
is reset to empty at the start of every harvest's FEED phase, so each of the six
harvests gets a fresh single use.

THE PAYMENT-FRONTIER SURFACE — ruling 76 item 1 (2026-07-21), verbatim: Studio's
"3 conversions are offered at the same time the craft majors' conversions are
offered, and additionally any `PendingFoodPayment` frame resolved DURING the
feeding phase can and should offer Studio's conversions." Driver reading
(recorded with the ruling): Studio stays FEEDING-PHASE-scoped per its printed
text — the feed-seam offering above stands, and the card gains payment-frontier
participation for frames resolved during the feeding phase; it does NOT gain
span windows outside the feeding phase (contrast the craft majors'
craft_major_span.py triggers). Implementation: each variant carries
`frontier_fire` (its pure resource->food exchange, consumed by
`available_span_converters` -> `_food_payment_generalized`), and is_owned_fn
additionally gates on `state.phase is Phase.HARVEST_FEED` — the whole FEED band
(start_of_feeding through after_feeding, engine._advance_harvest's phase flip),
which scopes the frontier surface without machinery changes: the feed-seam
enumerator only runs under HARVEST_FEED anyway, and `in_conversion_span` already
excludes non-harvest frames. A FIELD- or BREED-phase raise frame therefore sees
the craft majors but never Studio.

EXACTLY ONE, within a single bundle too: all three entries carry
`frontier_group="studio"`, so one payment bundle fires at most one variant
(`_food_payment_generalized` skips subsets with two same-group members). Settled
by the printed "exactly 1" + the existing cross-surface once-per-harvest budget
above — a bundle firing studio_wood + studio_clay would use the card twice in
one harvest. The raise-frame fire marks the exact variant id in
harvest_conversions_used (the executor), which the prefix guard then reads — so
the budget is shared across ALL surfaces in both directions with no extra code.

Action-shaping (ruling 76 item 1, user verbatim): "At the moment Studio's rates
are less than or equal to the rates offered by all other conversion cards …, so
a strategy of greedily converting with the restricted cards (meaning the cards
that offer conversions for only one resource type) before converting with
studio preserves optionality. Concretely … a player who chooses to convert a
wood to food should use the joinery over the studio if they have both and both
are available." In the bundled frontier this is the grouped-count tie-break in
`_food_payment_generalized`: a bundle firing studio_X instead of an available
equal-rate restricted converter produces the IDENTICAL remaining-goods vector
and collapses into the restricted card's bundle (structural, not id-ordering
luck); bundles firing BOTH (the greedy sequence's second same-type conversion)
have distinct vectors and correctly survive. At the sequential feed seam the
guidance needs no code — both offers coexist and firing the restricted card
first leaves Studio available.

Card-only state (the harvest_conversions_used studio_* variants) is empty in the
Family game — and the raise frame itself (PendingFoodPayment) is card-game-only —
so the Family game stays byte-identical and the C++ gates are untouched. See
CARD_AUTHORING_GUIDE.md and harvest_conversions.py / beer_keg.py.
"""
from __future__ import annotations

from typing import Callable

from agricola.cards.harvest_conversions import (
    HarvestConversionSpec,
    register_harvest_conversion,
)
from agricola.cards.specs import register_minor
from agricola.constants import Phase
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "studio"

# (resource name, input Resources, (w,c,r,s) frontier input, food produced)
# for the three conversion variants.
_VARIANTS = (
    ("wood", Resources(wood=1), (1, 0, 0, 0), 2),
    ("clay", Resources(clay=1), (0, 1, 0, 0), 2),
    ("stone", Resources(stone=1), (0, 0, 0, 1), 3),
)


def _is_owned() -> Callable[[GameState, int], bool]:
    """Return the is_owned_fn shared by all three Studio variants.

    A variant is offered iff the state is in the feeding phase, the player owns
    Studio, AND no studio_* variant has already fired this harvest.

    The phase gate (`Phase.HARVEST_FEED` — ruling 76 item 1's driver reading:
    Studio is feeding-phase-scoped per its printed text) scopes the
    payment-frontier surface: `available_span_converters` consults is_owned_fn
    with the live state, so an in-span FIELD- or BREED-phase raise frame never
    offers Studio. It is inert at the feed seam, whose enumerator only runs
    under HARVEST_FEED.

    The cross-variant guard reads harvest_conversions_used directly (both
    consumers re-check is_owned_fn on every call), so the card is used at most
    once per harvest — on ANY surface — even though it has three registry
    entries. Within one payment bundle the same exactly-once rule is
    frontier_group's job (see the module docstring).
    """
    def fn(state: GameState, idx: int) -> bool:
        if state.phase is not Phase.HARVEST_FEED:
            return False
        p = state.players[idx]
        if CARD_ID not in p.minor_improvements:
            return False
        # Once per harvest across all three variants.
        return not any(cid.startswith(CARD_ID) for cid in p.harvest_conversions_used)
    return fn


register_minor(CARD_ID, cost=Cost(resources=Resources(clay=1, reed=1)), vps=1)

for _name, _input, _vec, _food in _VARIANTS:
    register_harvest_conversion(HarvestConversionSpec(
        conversion_id=f"{CARD_ID}_{_name}",
        input_cost=_input,
        food_out=_food,
        is_owned_fn=_is_owned(),
        frontier_fire=(_vec, _food),
        frontier_group=CARD_ID,
    ))
