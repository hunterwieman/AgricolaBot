"""Elephantgrass Plant (minor improvement, C34; Corbarius Expansion; Points Provider).

Card text: "Immediately after each harvest, you can use this card to exchange
exactly 1 reed for 1 bonus point."
Cost: 2 Clay, 1 Stone. Prerequisite: 2 Occupations. VPs: 0 (printed). Not passing.

A recurring, optional, once-per-harvest goods-to-no-food conversion — the exact
shape the HarvestConversionSpec hook exists for, mirroring Furniture Carpenter
("each harvest, buy 1 point for 2 food") and Beer Keg. The twist over the three
built-in crafts (joinery/pottery/basketmaker, which take a good and PRODUCE food)
is that this one spends 1 reed and produces NO food (food_out=0); its only effect
is the banked bonus point.

Timing — "immediately after each harvest": the only once-per-harvest seam in the
engine is the FEED sub-phase's HARVEST_CONVERSIONS mechanism (each conversion is
offered once per harvest because harvest_conversions_used is reset once at the
start of every harvest's FEED phase). This is the same accepted home Furniture
Carpenter and Beer Keg use; there is no separate post-BREED hook. Surfacing the
reed->VP swap mid-FEED rather than strictly after BREED is behaviorally inert
here because reed is never a feeding or cooking input, so the swap never interacts
with the feed decision.

The single registry entry (conversion_id == CARD_ID) gives the once-per-harvest
limit for free: once fired, conversion_id sits in harvest_conversions_used and the
enumerator stops offering it for the rest of the harvest. The enumerator also
gates on _can_afford(reed=1), so the swap is offered only when the player owns a
reed to spend.

The point cannot be granted immediately (there is no immediate-VP mechanism), so
each fire's side_effect_fn increments a per-card CardStore counter (banked across
all six harvests), and the scoring term reads the count back at end-game. Do NOT
set vps= (that scores the printed keep VP, which is 0 here) — the point is earned,
not printed.

Unlike Furniture Carpenter (which gates on the Joinery being owned), this card has
no extra ownership condition: the only gate is owning the minor itself. Since
HarvestConversionSpec registrations are global and the enumerator gates only on
is_owned_fn, the ownership check (CARD_ID in this player's minor_improvements) must
live in is_owned_fn — otherwise the swap would be offered to the non-owner.

Card-only state (the CardStore int + harvest_conversions_used entry) is empty in
the Family game, so it stays byte-identical and the C++ gates are untouched.
See CARD_AUTHORING_GUIDE.md and harvest_conversions.py / furniture_carpenter.py /
beer_keg.py.
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

CARD_ID = "elephantgrass_plant"


def _is_owned(state: GameState, idx: int) -> bool:
    """True iff this player owns Elephantgrass Plant.

    The conversion enumerator (legality.py) gates only on is_owned_fn, and
    registrations are global, so the minor-ownership check must live here —
    otherwise the reed->point swap would be offered to the non-owner. The
    once-per-harvest limit is handled separately by the enumerator (it skips any
    conversion_id already in harvest_conversions_used).
    """
    return CARD_ID in state.players[idx].minor_improvements


def _award(state: GameState, idx: int) -> GameState:
    """side_effect_fn: bank one bonus point (incremented per harvest, up to 6)."""
    p = state.players[idx]
    banked = p.card_state.get(CARD_ID, 0)
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, banked + 1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    """Sum of bonus points banked across all harvests."""
    return state.players[idx].card_state.get(CARD_ID, 0)


# Cost 2 clay + 1 stone; prereq 2 occupations; printed VP 0 (points are earned).
register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(clay=2, stone=1)),
    min_occupations=2,
    vps=0,
)

# The recurring reed->VP swap: spend 1 reed, produce no food, bank +1 point.
register_harvest_conversion(HarvestConversionSpec(
    conversion_id=CARD_ID,
    input_cost=Resources(reed=1),
    food_out=0,
    is_owned_fn=_is_owned,
    side_effect_fn=_award,
))

register_scoring(CARD_ID, _score)
