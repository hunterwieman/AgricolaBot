"""Cube Cutter (occupation, C98; Corbarius Expansion; players 1+).

Card text: "When you play this card, you immediately get 1 wood. In the field
phase of each harvest, you can use this card to exchange exactly 1 wood and 1
food for 1 bonus point."

Category: Points Provider. Two effects:

1. On play (via Lessons): immediately gain 1 wood.

2. A recurring, optional, once-per-harvest exchange — spend exactly 1 wood and 1
   food, produce no food, and bank 1 bonus point. This is the exact shape the
   HarvestConversionSpec.side_effect_fn hook exists for (the inverse of the three
   built-in crafts: instead of taking a good and producing food, it spends goods
   and produces no food, its only effect being the banked point). It mirrors
   Furniture Carpenter's banked-point pattern, differing only in (a) the cost
   (1 wood + 1 food, vs Furniture Carpenter's 2 food) and (b) the eligibility:
   Cube Cutter has NO Joinery/major gate — owning the occupation is sufficient.

The card text says "field phase of each harvest", but this engine surfaces all
harvest conversions during HARVEST_FEED rather than the FIELD sub-phase — the
established, accepted approximation (Furniture Carpenter / Beer Keg do the same).
Field-vs-feed makes no mechanical difference here: the exchange touches no crops.

The point cannot be granted immediately (there is no immediate-VP mechanism), so
each fire increments a per-card CardStore counter (banked across all six
harvests), and the scoring term reads the count back at end-game. Affordability
(1 wood + 1 food) and the once-per-harvest cap are handled automatically by the
HARVEST_FEED legality enumerator (_can_afford + harvest_conversions_used).

The conversion enumerator (legality.py) gates only on is_owned_fn, and
registrations are global, so the occupation-ownership check lives in _eligible —
otherwise the exchange would be offered to the non-owner.

Card-only state (the CardStore int) is empty in the Family game, so it stays
byte-identical and the C++ gates are untouched. See CARD_AUTHORING_GUIDE.md and
harvest_conversions.py / furniture_carpenter.py.
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

CARD_ID = "cube_cutter"


def _on_play(state: GameState, idx: int) -> GameState:
    """On play: immediately gain 1 wood."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible(state: GameState, idx: int) -> bool:
    """True iff this player owns Cube Cutter.

    The conversion enumerator gates only on is_owned_fn, and registrations are
    global, so the occupation-ownership check must live here — otherwise the
    exchange would be offered to the non-owner. There is no major/Joinery gate
    (unlike Furniture Carpenter): owning the occupation is sufficient.
    """
    return CARD_ID in state.players[idx].occupations


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


# Played via Lessons; on-play grants 1 wood.
register_occupation(CARD_ID, _on_play)

# The recurring goods->VP exchange: spend 1 wood + 1 food, produce no food,
# bank +1 point.
register_harvest_conversion(HarvestConversionSpec(
    conversion_id=CARD_ID,
    input_cost=Resources(wood=1, food=1),
    food_out=0,
    is_owned_fn=_eligible,
    side_effect_fn=_award,
))

register_scoring(CARD_ID, _score)
