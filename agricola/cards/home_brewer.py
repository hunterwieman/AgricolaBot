"""Home Brewer (occupation, C #110; Consul Dirigens Expansion; Food Provider).

Card text: "After the field phase of each harvest, you can use this card to turn
exactly 1 grain into your choice of 3 food or 1 bonus point."
Occupation. Players 1+. VPs: 0. No cost / prerequisite. Not passing.

A recurring, optional, once-per-harvest conversion offered at the harvest's
goods-to-food seam (the engine surfaces HARVEST_CONVERSIONS entries during
HARVEST_FEED, which runs immediately after the mechanical FIELD phase — so "after
the field phase" and the engine's feeding-phase conversion seam are the same
moment). Each harvest the player MAY spend exactly 1 grain and pick ONE of two
outputs:

  - 1 grain -> 3 food          (the Food-Provider density: 3 food for 1 grain)
  - 1 grain -> 1 bonus point   (banked, awarded at scoring)

This is NOT an OR on the cost (the input is always exactly 1 grain); it is a
choice between two outputs. The two outputs are two HARVEST_CONVERSIONS registry
entries that share a single cross-variant once-per-harvest guard, mirroring Beer
Keg's multi-variant pattern. The HARVEST_FEED enumerator surfaces one
CommitHarvestConversion per entry that is (a) owned, (b) not yet fired this
harvest, and (c) affordable (1 grain); the player fires exactly one.

ONCE PER HARVEST — a CHOICE, not two independent fires. Each entry's is_owned_fn
gates on "no home_brewer_* variant has fired yet this harvest" in addition to
actual ownership of the occupation: firing home_brewer_food marks it in
harvest_conversions_used, but the enumerator re-checks is_owned_fn every call, so
the cross-variant guard reads harvest_conversions_used directly and suppresses the
other variant for the rest of this harvest. (harvest_conversions_used is reset to
empty at the start of every harvest's FEED phase, so each harvest gets a fresh
single use; the card text "turn exactly 1 grain" is one grain, one output, once
per harvest.)

The bonus point cannot be granted immediately (there is no immediate-VP
mechanism), so the VP variant's side_effect_fn increments a per-card CardStore
counter (banked across all six harvests), and the scoring term reads the count
back at end-game. This mirrors Beer Keg's / Furniture Carpenter's banked-point
pattern. The food variant has no side effect (food_out=3 does all the work).

Card-only state (the CardStore int + harvest_conversions_used variants) is empty
in the Family game, so it stays byte-identical and the C++ gates are untouched.
See CARD_AUTHORING_GUIDE.md and harvest_conversions.py / beer_keg.py.
"""
from __future__ import annotations

from agricola.cards.harvest_conversions import (
    HarvestConversionSpec,
    register_harvest_conversion,
)
from agricola.cards.specs import register_occupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "home_brewer"


def _is_owned(state: GameState, idx: int) -> bool:
    """The card is usable iff the player owns Home Brewer AND no home_brewer_*
    variant has already fired this harvest.

    The cross-variant guard reads harvest_conversions_used directly (the
    enumerator re-checks is_owned_fn on every call), so the card is used at most
    once per harvest even though it has two registry entries — firing one output
    suppresses the other for the rest of this harvest.
    """
    p = state.players[idx]
    if CARD_ID not in p.occupations:
        return False
    # Once per harvest across both variants (food / VP).
    return not any(cid.startswith(CARD_ID) for cid in p.harvest_conversions_used)


def _bank_point(state: GameState, idx: int) -> GameState:
    """side_effect_fn for the VP variant: bank +1 bonus point in the CardStore."""
    p = state.players[idx]
    banked = p.card_state.get(CARD_ID, 0)
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, banked + 1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    """Bonus points banked across all harvests via the VP variant."""
    return state.players[idx].card_state.get(CARD_ID, 0)


# Pure recurring-conversion occupation: played via Lessons, on-play is a no-op
# (the effect is the recurring harvest conversion only).
register_occupation(CARD_ID, lambda state, idx: state)

# Variant 1: 1 grain -> 3 food (no side effect).
register_harvest_conversion(HarvestConversionSpec(
    conversion_id=f"{CARD_ID}_food",
    input_cost=Resources(grain=1),
    food_out=3,
    is_owned_fn=_is_owned,
))

# Variant 2: 1 grain -> 1 bonus point (food_out=0; banks +1 VP via side effect).
register_harvest_conversion(HarvestConversionSpec(
    conversion_id=f"{CARD_ID}_vp",
    input_cost=Resources(grain=1),
    food_out=0,
    is_owned_fn=_is_owned,
    side_effect_fn=_bank_point,
))

register_scoring(CARD_ID, _score)
