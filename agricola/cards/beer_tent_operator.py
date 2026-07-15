"""Beer Tent Operator (occupation, D133; Dulcinaria Expansion; players 3+; Points
Provider).

Card text (verbatim): "In the feeding phase of each harvest, you can use this card
to turn 1 wood plus 1 grain into 1 bonus point and 2 food."
No clarifications / errata printed.

A recurring, optional, once-per-harvest goods-to-food conversion offered DURING
`HARVEST_FEED` — exactly the shape the `HarvestConversionSpec` hook exists for.
Spend 1 wood + 1 grain, produce 2 food (routable into the feeding payment) plus 1
banked bonus point. It is a single fixed exchange (no grain-amount choice, unlike
Beer Keg's three variants), so it registers as ONE `HarvestConversionSpec`:

  - input_cost = 1 wood + 1 grain
  - food_out   = 2
  - side_effect = bank 1 bonus point

ONCE PER HARVEST — the FEED enumerator surfaces one CommitHarvestConversion per
entry that is owned, affordable, and not yet fired this harvest. The is_owned_fn
therefore gates on ownership of the occupation AND `CARD_ID not in
harvest_conversions_used` (reset at the start of each harvest's FEED phase), so
the card is usable at most once per harvest.

BONUS POINTS — there is no immediate-VP mechanism, so the fire's `side_effect_fn`
increments a per-card CardStore counter (banked across all six harvests), read
back by the end-game scoring term. Mirrors Beer Keg / Furniture Carpenter's
banked-point pattern.

Played via Lessons; no on-play effect. Card-only state (the CardStore int +
harvest_conversions_used entry) is empty in the Family game, so it stays
byte-identical and the C++ gates are untouched. See beer_keg.py (the same seam)
and harvest_conversions.py.
"""
from __future__ import annotations

from agricola.cards.harvest_conversions import (
    HarvestConversionSpec,
    register_harvest_conversion,
)
from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "beer_tent_operator"


def _is_owned(state: GameState, idx: int) -> bool:
    """Offered iff the player owns Beer Tent Operator AND has not already used it
    this harvest (once-per-harvest across the single conversion entry)."""
    p = state.players[idx]
    return CARD_ID in p.occupations and CARD_ID not in p.harvest_conversions_used


def _bank_point(state: GameState, idx: int) -> GameState:
    """Side effect of the fire: bank 1 bonus point in the per-card CardStore."""
    p = state.players[idx]
    banked = p.card_state.get(CARD_ID, 0)
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, banked + 1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    """The banked bonus points, summed across all harvests."""
    return state.players[idx].card_state.get(CARD_ID, 0)


register_occupation(CARD_ID, _noop_on_play)   # no on-play effect

register_harvest_conversion(HarvestConversionSpec(
    conversion_id=CARD_ID,
    input_cost=Resources(wood=1, grain=1),
    food_out=2,
    is_owned_fn=_is_owned,
    side_effect_fn=_bank_point,
))

register_scoring(CARD_ID, _score)
