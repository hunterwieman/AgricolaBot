"""Grain Sieve (minor improvement, D65; Dulcinaria Expansion; players -).

Card text: "In the field phase of each harvest, if you harvest at least 2 grain,
you get 1 additional grain from the general supply."

Cost: 1 wood. On-play is a no-op.

Per-occasion consequence (`register_harvest_occasion_auto`). The card reads the
specifics of the field-phase take: it fires once, with the take occasion, and
its threshold is measured against the grain actually taken in that occasion.

Governing user ruling 9 (2026-07-03): a "take-once" card like Grain Sieve
"fires once, with the take occasion: the crops are taken off of fields (the main
field-phase effect) and their bonuses are based off of the specifics of what
happened in that action." It reads the take occasion's manifest — which will
include future take-fold-in extras (Scythe Worker's, when that card migrates)
but NOT separate occasions (card-granted additional harvests like Stable
Manure's). It is therefore NOT a window-exit aggregate over all occasions, and
we gate on `occasion.source == "take"` so a card-granted additional harvest
never triggers it.

Counting "harvest at least 2 grain": the take occasion emits one
`HarvestEntry(crop="grain", amount=1, …)` per grain-bearing field (grain over
veg precedence; a field harvests exactly 1 crop per phase). The threshold sums
those grain amounts — for the take occasion that equals the number of
grain-bearing fields, so a single field sown to 3 grain harvests only 1 grain
and does not reach the threshold, while two 1-grain fields harvest 2 and do.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_occasion_auto
from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "grain_sieve"


def _grain_taken(occasion) -> int:
    """Total grain removed by this occasion (sum of its grain entry amounts)."""
    return sum(e.amount for e in occasion.entries if e.crop == "grain")


def _eligible(state: GameState, idx: int, occasion) -> bool:
    return occasion.source == "take" and _grain_taken(occasion) >= 2


def _apply(state: GameState, idx: int, occasion) -> GameState:
    """Grant 1 additional grain from the general supply."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(grain=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(Resources(wood=1)))  # no on-play effect
register_harvest_occasion_auto(CARD_ID, _eligible, _apply)
