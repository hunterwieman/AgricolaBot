"""Furniture Carpenter (occupation, B101; Bubulcus Expansion; players 1+).

Card text: "Each harvest, if any player (including you) owns the Joinery or an
upgrade thereof, you can buy exactly 1 bonus point for 2 food."

Category: Points Provider. No on-play effect (played via Lessons; its on-play is
a no-op). The recurring "each harvest, you can buy 1 point for 2 food" is a
once-per-harvest goods-to-no-food conversion offered during HARVEST_FEED — the
exact shape the HarvestConversionSpec.side_effect_fn hook exists for (its
docstring names "Stone Sculptor +1 point per harvest"). Unlike the three
built-in crafts (which take a good and PRODUCE food), this one spends 2 food and
produces no food (food_out=0); its only effect is the banked bonus point.

The point cannot be granted immediately (there is no immediate-VP mechanism), so
each buy increments a per-card CardStore counter (banked across all six
harvests), and the scoring term reads the count back at end-game.

"the Joinery or an upgrade thereof": in this engine the ten majors are distinct
and there is no upgraded Joinery (Pottery and the Basketmaker's Workshop are
separate crafts, not Joinery upgrades), so the condition is "any player owns the
Joinery" — major improvement index 7. The conversion enumerator gates only on
is_owned_fn, so the eligibility check MUST also confirm this player actually owns
the occupation (registrations are global) — otherwise the buy would be offered to
the non-owner.
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

CARD_ID = "furniture_carpenter"

# The Joinery is major improvement index 7 (see harvest_conversions.py).
_JOINERY_MAJOR_IDX = 7


def _eligible(state: GameState, idx: int) -> bool:
    """True iff this player owns Furniture Carpenter AND any player owns the
    Joinery (major idx 7).

    The conversion enumerator (legality.py) gates only on is_owned_fn, and
    registrations are global, so the occupation-ownership check must live here —
    otherwise the buy-a-point would be offered to the non-owner.
    """
    if CARD_ID not in state.players[idx].occupations:
        return False
    return state.board.major_improvement_owners[_JOINERY_MAJOR_IDX] is not None


def _award(state: GameState, idx: int) -> GameState:
    """side_effect_fn: bank one bonus point (incremented per harvest, up to 6)."""
    p = state.players[idx]
    banked = p.card_state.get(CARD_ID, 0)
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, banked + 1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    return state.players[idx].card_state.get(CARD_ID, 0)


# Pure-conversion occupation: played via Lessons, but its on-play effect is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)

# The recurring food->VP buy: spend 2 food, produce no food, bank +1 point.
register_harvest_conversion(HarvestConversionSpec(
    conversion_id=CARD_ID,
    input_cost=Resources(food=2),
    food_out=0,
    is_owned_fn=_eligible,
    side_effect_fn=_award,
))

register_scoring(CARD_ID, _score)
