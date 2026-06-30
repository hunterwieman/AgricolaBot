"""Hardware Store (minor improvement, C82; Corbarius Expansion; cost 1 wood + 1 clay;
1 VP).

Card text: "Each time after you use the 'Day Laborer' action space, you can pay 2 food
total to buy 1 wood, 1 clay, 1 reed, and 1 stone."

An optional, paid `after_action_space` trigger on Day Laborer — the same shape as Ox
Goad (food-paid after-trigger, FOOD_PAYMENT_DESIGN.md §8/§9), but on the *atomic* Day
Laborer space (so it needs a `register_action_space_hook` to be hosted, like Loam Pit)
and granting flat goods rather than a sub-action.

"each time AFTER you use" → `after_action_space` (fires once the space's primary effect
has been applied — contrast Loam Pit's same-space "each time you use", which fires
before). It is OPTIONAL: the trigger is offered as a `FireTrigger` and declining is
simply not firing it (the host's Stop). "each time" = once per use, enforced by the
host's `triggers_resolved`.

The 2-food cost routes through the shared food-payment liquidation path (NOT a bare
food subtraction), so a player short on banked food but rich in crops/animals may raise
the 2 food by cooking them. `_apply` is the guard, `_buy` the body: with ≥ 2 food on
hand `_apply` debits and grants directly; short, it pushes a raise-only
PendingFoodPayment whose `resume_kind` is this card id, and once the food is in supply
the resume dispatches back to `_buy` (which debits it then). The frame is raise-only —
it never debits — so the grant's resume does the debit, mirroring Ox Goad.

The goods grant is flat (no sub-action), so it can never be a dead-end; eligibility
therefore gates ONLY on the 2 food being payable (with liquidation). See
CARD_IMPLEMENTATION_PLAN.md / FOOD_PAYMENT_DESIGN.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_minor
from agricola.cards.triggers import register, register_action_space_hook
from agricola.legality import _liquidatable_to
from agricola.pending import PendingFoodPayment, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "hardware_store"
SPACES = frozenset({"day_laborer"})
_FOOD_COST = 2
_GOODS = Resources(wood=1, clay=1, reed=1, stone=1)


def _buy(state: GameState, idx: int) -> GameState:
    """Debit the 2 food, then grant the 4 goods. Reached directly (food on hand) and as
    the post-food-payment continuation (the raise-only frame leaves the food in supply
    for this to debit). Reads the food from supply either way."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(food=_FOOD_COST) + _GOODS)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per use
        return False
    if state.pending_stack[-1].space_id not in SPACES:
        return False
    p = state.players[idx]
    # Never a dead-end: the goods grant is always possible, so only the 2-food
    # payment must be affordable (possibly by liquidating crops/animals).
    return _liquidatable_to(state, idx, p, Resources(food=_FOOD_COST))


def _apply(state: GameState, idx: int) -> GameState:
    """Pay 2 food and grant the goods. With enough food on hand, do it directly;
    otherwise push a raise-only PendingFoodPayment and defer the buy to its resume
    (which debits the raised food). The only cost is the 2 food, so nothing is
    reserved."""
    if state.players[idx].resources.food >= _FOOD_COST:
        return _buy(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID, reserved=Cost(),
    ))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1, clay=1)), vps=1)
register("after_action_space", CARD_ID, _eligible, _apply)
register_food_payment_resume(CARD_ID, _buy)
register_action_space_hook(CARD_ID, SPACES)
