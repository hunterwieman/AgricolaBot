"""Ox Goad (minor improvement, E19; Ephipparius Expansion; cost 1 wood; prereq 3
occupations; 1 VP).

Card text: "Each time after you use the 'Cattle Market' accumulation space, you can
pay 2 food to plow 1 field."

The first card that pays food from a TRIGGER (FOOD_PAYMENT_DESIGN.md §8/§9): an
optional `after_action_space` trigger on Cattle Market whose apply charges 2 food —
through the shared food-payment path, so the 2 food may be raised by liquidating
crops/animals — and then grants one plow (a `PendingPlow`). The optionality is the
FireTrigger itself: declining = not firing it (the host's Stop). Once fired, the
payment and the plow are mandatory, so eligibility gates on BOTH being possible —
2 food affordable (with liquidation) AND a plowable cell exists — to never offer a
dead-end (CARD_AUTHORING_GUIDE.md §2). "Each time you use" is once per use, enforced
by the host's `triggers_resolved`.

`_apply` is the guard, `_pay_and_plow` the body (debit 2 food, push the plow): with ≥ 2
food on hand `_apply` runs it directly; short, it pushes a raise-only PendingFoodPayment
whose `resume_kind` is this card id, so once the food is in supply `_resume` dispatches back
to `_pay_and_plow` via FOOD_PAYMENT_RESUMES (which debits it then). The frame is raise-only —
it never debits — so the grant's resume does the debit, mirroring how a re-run executor debits
its own cost. Cattle Market is non-atomic (always hosted), so no `register_action_space_hook`
is needed. See CARD_IMPLEMENTATION_PLAN.md / FOOD_PAYMENT_DESIGN.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_minor
from agricola.cards.triggers import register
from agricola.legality import _can_plow, _liquidatable_to
from agricola.pending import PendingFoodPayment, PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "ox_goad"
_SPACE = "cattle_market"
_FOOD_COST = 2


def _pay_and_plow(state: GameState, idx: int) -> GameState:
    """Debit the 2 food, then grant the plow. Reached directly (food on hand) and as the
    post-food-payment continuation (the raise-only frame leaves the food in supply for this to
    debit). Reads the food from supply either way."""
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources - Resources(food=_FOOD_COST))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingPlow(player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per use
        return False
    if state.pending_stack[-1].space_id != _SPACE:
        return False
    p = state.players[idx]
    # Never a dead-end: the 2 food must be payable (with liquidation) AND a plow legal.
    return _can_plow(p) and _liquidatable_to(state, idx, p, Resources(food=_FOOD_COST))


def _apply(state: GameState, idx: int) -> GameState:
    """Pay 2 food and grant the plow. With enough food on hand, do it directly; otherwise push
    a raise-only PendingFoodPayment and defer the pay-and-plow to its resume (which debits the
    raised food). Ox Goad's only cost is the 2 food, so nothing is reserved."""
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_plow(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID, reserved=Cost(),
    ))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), min_occupations=3, vps=1)
register("after_action_space", CARD_ID, _eligible, _apply)
register_food_payment_resume(CARD_ID, _pay_and_plow)
