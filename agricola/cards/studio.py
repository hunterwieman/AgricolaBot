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

Card-only state (the harvest_conversions_used studio_* variants) is empty in the
Family game, so it stays byte-identical and the C++ gates are untouched. See
CARD_AUTHORING_GUIDE.md and harvest_conversions.py / beer_keg.py.
"""
from __future__ import annotations

from typing import Callable

from agricola.cards.harvest_conversions import (
    HarvestConversionSpec,
    register_harvest_conversion,
)
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "studio"

# (resource name, input Resources, food produced) for the three conversion variants.
_VARIANTS = (
    ("wood", Resources(wood=1), 2),
    ("clay", Resources(clay=1), 2),
    ("stone", Resources(stone=1), 3),
)


def _is_owned() -> Callable[[GameState, int], bool]:
    """Return the is_owned_fn shared by all three Studio variants.

    A variant is offered iff the player owns Studio AND no studio_* variant has
    already fired this harvest. The cross-variant guard reads
    harvest_conversions_used directly (the enumerator re-checks is_owned_fn on
    every call), so the card is used at most once per harvest even though it has
    three registry entries.
    """
    def fn(state: GameState, idx: int) -> bool:
        p = state.players[idx]
        if CARD_ID not in p.minor_improvements:
            return False
        # Once per harvest across all three variants.
        return not any(cid.startswith(CARD_ID) for cid in p.harvest_conversions_used)
    return fn


register_minor(CARD_ID, cost=Cost(resources=Resources(clay=1, reed=1)), vps=1)

for _name, _input, _food in _VARIANTS:
    register_harvest_conversion(HarvestConversionSpec(
        conversion_id=f"{CARD_ID}_{_name}",
        input_cost=_input,
        food_out=_food,
        is_owned_fn=_is_owned(),
    ))
