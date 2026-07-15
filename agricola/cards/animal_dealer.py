"""Animal Dealer (occupation, A147; Base Revised; players 3+).

Card text: "Each time you use the 'Sheep Market', 'Pig Market', or 'Cattle Market'
accumulation space, you can buy 1 additional animal of the respective type for 1
food."

A bare "each time you use … you can" → an OPTIONAL trigger in the BEFORE phase of
the market host (the Trigger-Timing ruling), surfaced as a FireTrigger the player
may take or decline (the market's CommitAccommodate is the decline — it pivots the
host to its after-phase, closing the before-window). Owner-gated ("you"); once per
use via the host frame's ``triggers_resolved``.

Firing pays 1 food and buys 1 more animal of the market's type. The extra animal is
staged by bumping the market frame's ``gained`` by 1 (the Cowherd idiom) — NOT
added to the player directly — so it flows through the SAME accommodation/overflow
frontier (capacity, conversion-on-overflow) as the market's own animals at
CommitAccommodate. The frame type (Sheep/Pig/Cattle Market) already maps ``gained``
to the "respective type" in _enumerate_pending_animal_market, so a type-agnostic +1
is correct.

The "1 food" is payable outright OR by liquidating convertible goods to food (the
Sugar Baker idiom): eligibility gates on ``_liquidatable_to``; firing pays directly
when food is on hand, else raises the food via a PendingFoodPayment whose registered
resume debits the food and bumps ``gained``. Either way the market host is back on
top when the debit+bump runs, so replace_top targets it.

The animal markets are NON-ATOMIC (always hosted, firing before_action_space), so
no register_action_space_hook is needed. On-play is a no-op. Card-game only
(ownership-gated registries), so the Family trace and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_occupation
from agricola.cards.triggers import register
from agricola.legality import _liquidatable_to
from agricola.pending import PendingFoodPayment, push, replace_top
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "animal_dealer"
_MARKET_SPACES = frozenset({"sheep_market", "pig_market", "cattle_market"})
_FOOD_COST = 1


def _pay_and_bump(state: GameState, idx: int) -> GameState:
    """Debit 1 food and bump the market's staged ``gained`` by 1. Reached both
    directly (food on hand) and as the post-food-payment resume — in both cases the
    market host is on top, so replace_top targets it."""
    top = state.pending_stack[-1]   # the market host
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(food=_FOOD_COST))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    return replace_top(state, fast_replace(top, gained=top.gained + 1))


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:
        return False
    if state.pending_stack[-1].space_id not in _MARKET_SPACES:
        return False
    # Payable outright or by liquidating convertible goods to the 1 food.
    return _liquidatable_to(state, idx, state.players[idx],
                            Resources(food=_FOOD_COST))


def _apply(state: GameState, idx: int) -> GameState:
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_bump(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID,
        reserved=Cost(),
    ))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("before_action_space", CARD_ID, _eligible, _apply)
register_food_payment_resume(CARD_ID, _pay_and_bump)
