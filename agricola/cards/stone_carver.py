"""Stone Carver (occupation, D108; Consul Dirigens Expansion; players 1+).

Card text (verbatim): "Each harvest, you can use this card to turn exactly
1 stone into 3 food."

Category: Food Provider. No on-play effect (played via Lessons; its on-play is
a no-op). A PURE building-resource -> food converter (1 stone -> 3 food, no
rider outputs), classified into the harvest-SPAN conversion family:

> **Ruling 75 (user, 2026-07-21, CARD_DEFERRED_PLANS.md):** "The span family:
> Stone Carver joins the harvest span, and the craft majors join (done); ALL
> of these are additionally payable-from during any harvest-time
> `PendingFoodPayment`/`CommitConvert`."

So ONE once-per-harvest budget ("Each harvest, you can…" — the standard
``harvest_conversions_used`` entry under id ``"stone_carver"``, reset at each
fresh harvest FIELD entry) is spendable on any of three surfaces (the Braid
Maker clause-1 shape):

1. **The FEED payment frame** — the ``HarvestConversionSpec`` below (1 stone
   in, 3 food out, no riders, no variants). This is also what puts the card
   on the feed frame's offer list; the seam's executor debits the stone, adds
   the food, and marks the budget.
2. **The generalized in-harvest raise frame** (rulings 34/37, 2026-07-12: a
   pure converter joins the payment frontier) — ``frontier_fire=((0, 0, 0, 0,
   0, 1), 3)`` (the 6-tuple (grain,veg,wood,clay,reed,stone); 1 stone) on the
   same spec, so any harvest-time ``PendingFoodPayment`` frontier
   offers the fire. ``_execute_food_payment`` debits the stone, adds the food,
   and marks the SAME budget.
3. **The free span** (ruling 36, 2026-07-12, extended to this card by ruling
   75's span classification): ``register_free_span_trigger`` puts an optional
   ``FireTrigger`` on every in-span window/event — the player's field band
   through ``end_of_harvest``, the FIELD during-window and the breed frame's
   pre-commit stretch included. The window machinery carries no cost layer or
   budget bookkeeping of its own, so the apply debits the stone, grants the
   food, and marks the shared budget itself (the basket_carrier idiom).

Any one surface's fire marks ``"stone_carver"`` in
``harvest_conversions_used``, withholding the other surfaces for the rest of
that harvest; the next harvest offers it afresh.

`is_owned_fn` checks THIS player's occupations explicitly (the Furniture
Carpenter caution: registrations are global, so without the ownership check
the conversion would be offered to non-owners). The span registration keeps
the default tableau-ownership gate (a normal occupation — no `is_owned_fn`
override) and needs no mode gate: Family players own no cards, so nothing
here ever surfaces in the Family game.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from agricola.cards.harvest_conversions import (
    HarvestConversionSpec,
    register_harvest_conversion,
)
from agricola.cards.harvest_windows import register_free_span_trigger
from agricola.cards.specs import register_occupation
from agricola.replace import fast_replace
from agricola.resources import Resources

if TYPE_CHECKING:
    from agricola.state import GameState

CARD_ID = "stone_carver"


def _owns(state: "GameState", idx: int) -> bool:
    """This player has PLAYED Stone Carver (the per-player ownership gate —
    the conversion registry is global)."""
    return CARD_ID in state.players[idx].occupations


def _span_eligible(state: "GameState", idx: int, triggers_resolved) -> bool:
    """Free-span trigger eligibility: owns the card, the once-per-harvest
    budget is unused (SHARED with the feed-seam / raise-frame fires via
    ``harvest_conversions_used``), and the stone is on hand."""
    p = state.players[idx]
    return (CARD_ID in p.occupations
            and CARD_ID not in p.harvest_conversions_used
            and p.resources.stone >= 1)


def _span_exchange(state: "GameState", idx: int) -> "GameState":
    """Free-span trigger fire: debit the 1 stone, grant the 3 food, mark the
    shared budget (the window machinery carries no cost layer or budget
    bookkeeping of its own — the basket_carrier idiom)."""
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources + Resources(stone=-1, food=3),
        harvest_conversions_used=p.harvest_conversions_used | {CARD_ID},
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


# Pure recurring converter: played via Lessons, its on-play effect is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)

# Surfaces 1+2 — the FEED offer list and (frontier_fire) the generalized raise
# frame / payment frontier, sharing one budget.
register_harvest_conversion(HarvestConversionSpec(
    conversion_id=CARD_ID,
    input_cost=Resources(stone=1),
    food_out=3,
    is_owned_fn=_owns,
    frontier_fire=((0, 0, 0, 0, 0, 1), 3),   # (grain,veg,wood,clay,reed,stone) -> food
))

# Surface 3 — the free span (rulings 36 + 75): an optional trigger on every
# in-span window/event, field band through end_of_harvest, on the same budget.
register_free_span_trigger(CARD_ID, _span_eligible, _span_exchange)
