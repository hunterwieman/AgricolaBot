"""Barley Mill (minor improvement, A64; Artifex Expansion; players -).

Card text: "In the field phase of each harvest, you get 1 food for each grain
field that you harvest."

Cost: "1 Wood, 4 Clay/2 Stone" — always 1 wood, plus EITHER 4 clay OR 2 stone
(the "/" is an alternative on the clay/stone component, never a sum). Registered
as base `Cost(wood=1, clay=4)` with one `alt_costs` member `Cost(wood=1,
stone=2)` (the `_minor_cost_alternatives` "pay exactly one full alternative"
shape). VPs: 1. No prerequisite. Not passing.

On-play is a no-op.

Per-occasion consequence (`register_harvest_occasion_auto`). Barley Mill reads
the specifics of the field-phase take: it fires once, with the take occasion, and
pays 1 food per grain FIELD harvested in that occasion.

Governing user ruling 9 (2026-07-03): a "take-once" card like Barley Mill (the
Grain Sieve shape) "fires once, with the take occasion: the crops are taken off
of fields (the main field-phase effect) and their bonuses are based off of the
specifics of what happened in that action." It reads the take occasion's manifest
— which under ruling 11 includes every take-modifier's folded-in extras (Scythe
Worker's, Stable Manure's) — but NOT a separate card-granted additional-harvest
occasion. It is therefore NOT a window-exit aggregate over all occasions, and we
gate on `occasion.source == "take"` so a card-granted additional harvest never
triggers it. "In the field phase of each harvest" is satisfied by the take being
the real harvest's sole field-phase occasion.

COUNTING RULE — "for each grain FIELD that you harvest" counts grain-bearing
FIELDS, i.e. the number of grain ENTRIES in the take occasion (one `HarvestEntry`
is one field), NOT the number of grain UNITS. The `amount` is ignored: a field
that yields 2 grain in one combined take (a take-modifier's folded-in extra, e.g.
Scythe Worker's) is still ONE grain field harvested -> 1 food. Two grain fields
-> 2 food. Veg fields are not grain fields (they carry `crop == "veg"`). A field
with no crop this phase produces no entry and does not count.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_occasion_auto
from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "barley_mill"


def _grain_fields_harvested(occasion) -> int:
    """Number of grain FIELDS this occasion harvested (count of grain entries —
    one HarvestEntry is one field; the per-field `amount` is deliberately not
    summed)."""
    return sum(1 for e in occasion.entries if e.crop == "grain")


def _eligible(state: GameState, idx: int, occasion) -> bool:
    return occasion.source == "take" and _grain_fields_harvested(occasion) >= 1


def _apply(state: GameState, idx: int, occasion) -> GameState:
    """Grant 1 food per grain field harvested in this take occasion."""
    n = _grain_fields_harvested(occasion)
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=n))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(Resources(wood=1, clay=4)),
    alt_costs=(Cost(Resources(wood=1, stone=2)),),
    vps=1,
)  # no on-play effect
register_harvest_occasion_auto(CARD_ID, _eligible, _apply)
