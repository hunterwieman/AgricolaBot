"""Basket Carrier (occupation, C105; Corbarius Expansion; players 1+).

Card text (verbatim): "Once each harvest, you can buy 1 wood, 1 reed, and 1
grain for 2 food total."

Category: Goods Provider. No on-play effect (played via Lessons; its on-play is
a no-op). The recurring effect is a single optional bundle buy — spend 2 food,
gain 1 wood + 1 reed + 1 grain, at most once per harvest.

Timing — the free span (user ruling 36, 2026-07-12): an anytime food->resources
buy like this one is available THROUGHOUT the harvest span — the player's field
band's start through ``end_of_harvest`` — not anchored to any single moment.
And because the buy's output is GOODS, not food, it is a STANDALONE trigger
(user ruling 37, 2026-07-12): rider-output buys are never folded into the feed
payment frontier or the in-harvest raise frame, so this card sets NO
``frontier_fire``.

Two surfaces carry the buy, sharing ONE once-per-harvest budget (the id
``"basket_carrier"`` in ``PlayerState.harvest_conversions_used``, reset by the
harvest walk at each fresh FIELD entry):

1. **Every free-span window/event** — ``register_free_span_trigger`` registers
   an optional ``FireTrigger`` on all eleven in-span surfaces (the nine simple
   windows, the FIELD during-window, and the breed frame's pre-commit
   stretch). The window machinery carries no cost layer or cross-frame budget
   of its own, so ``_span_buy`` debits the 2 food, grants the bundle, and marks
   the shared budget itself; ``_span_eligible`` gates the budget and the
   2-food affordability (plus ownership — the trigger enumerator and the
   window-host push both gate ownership via ``_owns``, but the check is kept
   here explicitly, matching the surrounding card idiom).

2. **The FEED payment frame** — the one in-span surface the window events do
   not cover — via a ``HarvestConversionSpec`` (``food_out=0``; the enumerator
   gates the budget and affordability, and its executor
   ``_execute_harvest_conversion`` debits the 2-food input and marks the SAME
   budget id itself, so ``_grant_bundle`` only grants the three goods).
   ``is_owned_fn`` must check occupation ownership: registrations are global
   and the conversion enumerator gates only on ``is_owned_fn``.

Firing on either surface therefore withholds the buy from every other surface
for the rest of that harvest, and the next harvest offers it afresh.

The bundle is all-or-nothing as printed ("1 wood, 1 reed, and 1 grain for 2
food total") — there is no partial buy, so a plain trigger / plain conversion
(no variants) is the exact shape. Card-only state is empty in the Family game,
so the Family trace stays byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_conversions import (
    HarvestConversionSpec,
    register_harvest_conversion,
)
from agricola.cards.harvest_windows import register_free_span_trigger
from agricola.cards.specs import register_occupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "basket_carrier"

# The printed bundle: 1 wood, 1 reed, and 1 grain (for 2 food total).
_BUNDLE = Resources(wood=1, reed=1, grain=1)


def _replace_player(state: GameState, idx: int, p) -> GameState:
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _owns_occupation(state: GameState, idx: int) -> bool:
    """is_owned_fn for the feed-seam entry: has this player PLAYED the card?

    Registrations are global and the HARVEST_FEED conversion enumerator gates
    only on is_owned_fn, so the occupation-ownership check must live here —
    otherwise the buy would be offered to the non-owner.
    """
    return CARD_ID in state.players[idx].occupations


def _grant_bundle(state: GameState, idx: int) -> GameState:
    """side_effect_fn for the feed-seam entry: grant 1 wood + 1 reed + 1 grain.

    The seam's executor (_execute_harvest_conversion) has already debited the
    2-food input_cost and marked the shared budget in harvest_conversions_used;
    this only adds the goods.
    """
    p = state.players[idx]
    return _replace_player(state, idx, fast_replace(p, resources=p.resources + _BUNDLE))


def _span_eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Free-span eligibility: owns the card, once-per-HARVEST budget unfired,
    and can pay the 2 food.

    The budget lives on PlayerState.harvest_conversions_used — shared with the
    feed-seam entry and reset at each fresh harvest FIELD entry — NOT on the
    host frame's triggers_resolved (which scopes a single window). Ownership is
    also gated by the trigger enumerator / window-host push (_owns), but is
    kept here explicitly per the surrounding card idiom (winter_caretaker).
    """
    p = state.players[idx]
    return (
        CARD_ID in p.occupations
        and CARD_ID not in p.harvest_conversions_used
        and p.resources.food >= 2
    )


def _span_buy(state: GameState, idx: int) -> GameState:
    """Free-span apply: spend 2 food, gain the bundle, mark the shared budget.

    The window machinery carries no cost layer or budget bookkeeping of its
    own, so all three live here (mirroring winter_caretaker's _buy, plus the
    budget mark that makes the two surfaces mutually exclusive per harvest).
    """
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources + Resources(food=-2) + _BUNDLE,
        harvest_conversions_used=p.harvest_conversions_used | {CARD_ID},
    )
    return _replace_player(state, idx, p)


# Pure recurring-effect occupation: played via Lessons, its on-play is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)

# Surface 1 — the free span (ruling 36, 2026-07-12): an optional trigger on
# every in-span window/event, field band through end_of_harvest.
register_free_span_trigger(CARD_ID, _span_eligible, _span_buy)

# Surface 2 — the FEED payment frame, via the conversion seam. food_out=0 and
# NO frontier_fire: the output is goods, and ruling 37 (2026-07-12) keeps
# rider-output buys standalone — never folded into the payment frontier or the
# raise frame.
register_harvest_conversion(HarvestConversionSpec(
    conversion_id=CARD_ID,
    input_cost=Resources(food=2),
    food_out=0,
    is_owned_fn=_owns_occupation,
    side_effect_fn=_grant_bundle,
))
