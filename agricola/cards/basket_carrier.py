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
   of its own, so the fire debits the 2 food, grants the bundle, and marks the
   shared budget itself; ``_span_eligible`` gates the budget and — corrected
   per ruling 82 (2026-07-27): "An implementation must never make a
   rules-legal move unplayable. The canonical violation: a 'pay N food' cost
   gated on food-on-hand — in Agricola the at-any-time conversions are legal
   payment routes, so the plain gate deletes options" — the 2-food fee's
   payability by ANY legal route (``_liquidatable_to``, which in-span
   delegates to the same frontier the raise frame enumerates). With the food
   on hand ``_span_buy`` pays directly; when short it pushes a raise-only
   ``PendingFoodPayment`` whose registered resume (``_pay_and_grant``) debits
   the 2 food, grants the bundle, and marks the budget. (Ownership is also
   gated by the trigger enumerator and the window-host push via ``_owns``,
   but the check is kept here explicitly, matching the surrounding card
   idiom. Ruling 37 governs the food-RAISING machinery — this buy never
   appears inside anyone's raising frontier, ``frontier_fire`` None — not how
   this card's own fee is paid.)

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
from agricola.cards.specs import (
    register_food_payment_resume,
    register_occupation,
)
from agricola.legality import _liquidatable_to
from agricola.pending import PendingFoodPayment, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
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
    and the 2-food fee payable by ANY legal route — on hand OR raised by the
    at-any-time conversions (ruling 82, corrected 2026-07-27: a plain
    food-on-hand gate makes rules-legal moves unplayable; in-span
    `_liquidatable_to` delegates to the same frontier the raise frame
    enumerates).

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
        and _liquidatable_to(state, idx, p, Resources(food=2))
    )


def _pay_and_grant(state: GameState, idx: int) -> GameState:
    """Spend 2 food, gain the bundle, mark the shared budget. Reached directly
    (food on hand) and as the post-food-payment resume (the raise-only frame
    leaves the raised food in supply for this to debit).

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


def _span_buy(state: GameState, idx: int) -> GameState:
    """Free-span apply: pay-and-grant directly when the 2 food is on hand,
    else push the raise-only PendingFoodPayment (ruling 82's corrected payment
    shape; the fee is the only cost, so nothing is reserved). The fire is
    already recorded on the host's `triggers_resolved`, and the resume marks
    the shared budget, so no surface re-offers the buy this harvest."""
    if state.players[idx].resources.food >= 2:
        return _pay_and_grant(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=2, resume_kind=CARD_ID, reserved=Cost(),
    ))


# Pure recurring-effect occupation: played via Lessons, its on-play is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)

# Surface 1 — the free span (ruling 36, 2026-07-12): an optional trigger on
# every in-span window/event, field band through end_of_harvest.
register_free_span_trigger(CARD_ID, _span_eligible, _span_buy)
# The raise-only food frame's continuation (ruling 82's corrected payment shape).
register_food_payment_resume(CARD_ID, _pay_and_grant)

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
