"""Beer Keg (minor improvement, A62; Artifex Expansion; Food Provider).

Card text: "In the feeding phase of each harvest, you can use this card to
exchange 1/2/3 grain for 0/1/2 bonus points and exactly 3 food."
Cost: 1 Wood. Prerequisite: 2 Grain in Your Supply. VPs: 0. Not passing.

A recurring, optional, once-per-harvest goods-to-food conversion offered during
HARVEST_FEED — the exact shape the HarvestConversionSpec hook exists for. The
twist over the three built-in crafts (joinery/pottery/basketmaker) is that the
player CHOOSES how much grain to spend, and each choice banks a different number
of bonus points:

  - spend 1 grain -> 3 food + 0 bonus points
  - spend 2 grain -> 3 food + 1 bonus point
  - spend 3 grain -> 3 food + 2 bonus points

The food output is always exactly 3, independent of the grain spent; only the
banked-point count differs. The HARVEST_FEED enumerator surfaces one
CommitHarvestConversion per HARVEST_CONVERSIONS entry that is (a) owned, (b) not
yet fired this harvest, and (c) affordable. So the three grain amounts are three
separate registry entries (beer_keg_1 / beer_keg_2 / beer_keg_3), and the player
picks one by firing its CommitHarvestConversion. The Food-Provider value comes
from the per-grain food density: 3 food for 1 grain (≫ the 0.5-ish food a grain
yields elsewhere), with the option to convert more grain for points.

ONCE PER HARVEST — a CHOICE, not three independent fires. The card may be used
once per harvest, choosing a single grain amount. Each entry's is_owned_fn
therefore gates on "no beer_keg_* variant has fired yet this harvest" in addition
to actual ownership of the minor: firing beer_keg_2 marks beer_keg_2 in
harvest_conversions_used, but the enumerator re-checks is_owned_fn every call, so
the cross-variant guard reads harvest_conversions_used directly and suppresses the
other two variants for the rest of this harvest. (harvest_conversions_used is reset
to empty at the start of every harvest's FEED phase, so each harvest gets a fresh
single use.)

The points cannot be granted immediately (there is no immediate-VP mechanism), so
each fire's side_effect_fn increments a per-card CardStore counter (banked across
all six harvests), and the scoring term reads the count back at end-game. This
mirrors Furniture Carpenter's banked-point pattern.

Card-only state (the CardStore int + harvest_conversions_used variants) is empty
in the Family game, so it stays byte-identical and the C++ gates are untouched.
See CARD_AUTHORING_GUIDE.md and harvest_conversions.py / furniture_carpenter.py.
"""
from __future__ import annotations

from agricola.cards.harvest_conversions import (
    HarvestConversionSpec,
    register_harvest_conversion,
)
from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "beer_keg"

# (grain spent, bonus points banked); food_out is always 3.
_VARIANTS = ((1, 0), (2, 1), (3, 2))


def _prereq(state: GameState, idx: int) -> bool:
    """Prerequisite: at least 2 grain in your supply (a HAVE-check at play time,
    not a cost; the grain is NOT spent to play the card)."""
    return state.players[idx].resources.grain >= 2


def _make_is_owned(grain: int) -> "object":
    """Return is_owned_fn for the beer_keg_<grain> variant.

    The variant is offered iff the player owns Beer Keg AND no beer_keg_* variant
    has already fired this harvest. The cross-variant guard reads
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


def _make_award(points: int) -> "object":
    """Return side_effect_fn for the variant that banks `points` bonus points."""
    def fn(state: GameState, idx: int) -> GameState:
        if points == 0:
            return state
        p = state.players[idx]
        banked = p.card_state.get(CARD_ID, 0)
        p = fast_replace(p, card_state=p.card_state.set(CARD_ID, banked + points))
        return fast_replace(
            state, players=tuple(p if i == idx else state.players[i] for i in range(2))
        )
    return fn


def _score(state: GameState, idx: int) -> int:
    """Sum of bonus points banked across all harvests."""
    return state.players[idx].card_state.get(CARD_ID, 0)


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), prereq=_prereq, vps=0)

for _grain, _points in _VARIANTS:
    register_harvest_conversion(HarvestConversionSpec(
        conversion_id=f"{CARD_ID}_{_grain}",
        input_cost=Resources(grain=_grain),
        food_out=3,
        is_owned_fn=_make_is_owned(_grain),
        side_effect_fn=_make_award(_points),
    ))

register_scoring(CARD_ID, _score)
