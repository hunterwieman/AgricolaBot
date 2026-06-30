"""Farm Store (minor improvement, C41; Consul Dirigens Expansion; Goods Provider).

Card text: "After the feeding phase of each harvest, you can exchange exactly 1
food for 2 different building resources of your choice or 1 vegetable."
Cost: 2 Wood, 2 Clay. VPs: 0. No prerequisite. Not passing.

A recurring, optional, once-per-harvest food-to-goods conversion offered during
HARVEST_FEED — the exact shape the HarvestConversionSpec hook exists for. Each
harvest the player MAY spend exactly 1 food and, in return, CHOOSE one of:

  - 2 *different* building resources (an unordered pair from
    {wood, clay, reed, stone} — six distinct pairs), or
  - 1 vegetable.

"2 different building resources" is read as exactly the six distinct unordered
pairs C(4,2) over {wood, clay, reed, stone} — the card's word "different" rules
out doubles like wood+wood. With the single-veg option that is seven output
variants, so the card is seven HarvestConversionSpec registry entries
(farm_store_wood_clay, …, farm_store_veg). The player picks one by firing its
CommitHarvestConversion. Each variant spends 1 food (input_cost) and grants its
goods via side_effect_fn (food_out=0, so there is no food double-count — the net
is exactly −1 food +the chosen goods).

ONCE PER HARVEST — a CHOICE, not seven independent fires. The card may be used
once per harvest, picking a single output. Each entry's is_owned_fn therefore
gates on "no farm_store_* variant has fired yet this harvest" in addition to
actual ownership of the minor: firing one variant marks only its own
conversion_id in harvest_conversions_used, but the enumerator re-checks
is_owned_fn every call, so the cross-variant guard reads harvest_conversions_used
directly and suppresses the other six variants for the rest of this harvest.
(harvest_conversions_used is reset to empty at the start of every harvest's FEED
phase, so each harvest gets a fresh single use.) This is the Beer Keg / Furniture
Carpenter cross-variant pattern.

Timing: "after the feeding phase of each harvest" maps exactly to spending
surplus food during HARVEST_FEED — conversions are offered after the feeding cost
is pre-debited and only when the 1 food is affordable (the enumerator's
_can_afford gate), so the player can only ever spend food they have to spare
(precedent: Furniture Carpenter's "each harvest you can buy ... for food").

Card-only state (the harvest_conversions_used variants) is empty in the Family
game, so it stays byte-identical and the C++ gates are untouched. See
CARD_AUTHORING_GUIDE.md and harvest_conversions.py / beer_keg.py /
furniture_carpenter.py.
"""
from __future__ import annotations

from typing import Callable

from agricola.cards.harvest_conversions import (
    HarvestConversionSpec,
    register_harvest_conversion,
)
from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "farm_store"

# The seven output variants: the six distinct unordered building-resource pairs
# over {wood, clay, reed, stone} ("2 different building resources"), plus the
# single-vegetable option. (tag, goods granted).
_OUTPUTS: tuple[tuple[str, Resources], ...] = (
    ("wood_clay",  Resources(wood=1, clay=1)),
    ("wood_reed",  Resources(wood=1, reed=1)),
    ("wood_stone", Resources(wood=1, stone=1)),
    ("clay_reed",  Resources(clay=1, reed=1)),
    ("clay_stone", Resources(clay=1, stone=1)),
    ("reed_stone", Resources(reed=1, stone=1)),
    ("veg",        Resources(veg=1)),
)


def _make_is_owned() -> Callable[[GameState, int], bool]:
    """Return is_owned_fn shared by every farm_store_<tag> variant.

    The variant is offered iff the player owns Farm Store AND no farm_store_*
    variant has already fired this harvest. The cross-variant guard reads
    harvest_conversions_used directly (the enumerator re-checks is_owned_fn on
    every call), so the card is used at most once per harvest even though it has
    seven registry entries.
    """
    def fn(state: GameState, idx: int) -> bool:
        p = state.players[idx]
        if CARD_ID not in p.minor_improvements:
            return False
        # Once per harvest across all seven variants.
        return not any(cid.startswith(CARD_ID) for cid in p.harvest_conversions_used)
    return fn


def _make_grant(out: Resources) -> Callable[[GameState, int], GameState]:
    """Return side_effect_fn that adds `out` to the player's supply.

    The 1-food input is paid by the conversion's input_cost; food_out is 0, so
    this only adds the chosen goods (the net is exactly −1 food +out).
    """
    def fn(state: GameState, idx: int) -> GameState:
        p = state.players[idx]
        p = fast_replace(p, resources=p.resources + out)
        return fast_replace(
            state, players=tuple(p if i == idx else state.players[i] for i in range(2))
        )
    return fn


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2, clay=2)), vps=0)

for _tag, _out in _OUTPUTS:
    register_harvest_conversion(HarvestConversionSpec(
        conversion_id=f"{CARD_ID}_{_tag}",
        input_cost=Resources(food=1),
        food_out=0,
        is_owned_fn=_make_is_owned(),
        side_effect_fn=_make_grant(_out),
    ))
