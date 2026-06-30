"""Plow Maker (occupation, D90; Consul Dirigens Expansion; players 1+).

Card text: "Each time you use the 'Farmland' or 'Cultivation' action space, you can
pay 1 food to plow 1 additional field."

A pay-food → plow trigger in the exact shape of Ox Goad (FOOD_PAYMENT_DESIGN.md §8),
differing only in event, filter, and food amount. "Each time you use [space]" fires in
the BEFORE phase (the Trigger-Timing ruling, CARD_AUTHORING_GUIDE.md §2) — so the
"additional" field is plowed before the space's own plow, which can change field
adjacency (the phase is observable, not cosmetic). The filter is the Farmland or
Cultivation action space.

Both Farmland and Cultivation are non-atomic (always hosted), so NO
`register_action_space_hook` is needed — just register the trigger on
`before_action_space` and filter by `space_id` in eligibility.

`_apply` is the guard, `_pay_and_plow` the body (debit 1 food, push the plow): with
≥ 1 food on hand `_apply` runs it directly; short, it pushes a raise-only
PendingFoodPayment whose `resume_kind` is this card id, so once the food is in supply
`_resume` dispatches back to `_pay_and_plow` (which debits it then). Eligibility is
liquidation-aware (`_liquidatable_to`, NOT `food >= 1`) so the card fires with 0 food
but convertible goods, and gates on a plowable cell (`_can_plow`) so a fired plow never
dead-ends. "Each time you use" is once per use, enforced by the host's
`triggers_resolved`. See PAY_FOOD_PLOW_CARDS.md / FOOD_PAYMENT_DESIGN.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_occupation
from agricola.cards.triggers import register
from agricola.legality import _can_plow, _can_plow_twice, _liquidatable_to
from agricola.pending import PendingFoodPayment, PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "plow_maker"
_SPACES = frozenset({"farmland", "cultivation"})
_FOOD_COST = 1


def _pay_and_plow(state: GameState, idx: int) -> GameState:
    """Debit 1 food, then grant the plow. Reached directly (food on hand) and as the
    post-food-payment resume (the raise-only frame leaves the food in supply to debit)."""
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources - Resources(food=_FOOD_COST))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingPlow(player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per use
        return False
    sid = state.pending_stack[-1].space_id
    if sid not in _SPACES:
        return False
    p = state.players[idx]
    # Never a dead-end: the 1 food must be payable (with liquidation) AND a plow legal. On
    # Farmland the mandatory base plow must also survive the grant (enforce-first), so a
    # second sequential plow must exist; Cultivation rides its own host (single plow ok).
    plow_ok = _can_plow_twice(p) if sid == "farmland" else _can_plow(p)
    return plow_ok and _liquidatable_to(state, idx, p, Resources(food=_FOOD_COST))


def _apply(state: GameState, idx: int) -> GameState:
    """Pay 1 food and grant the plow. With enough food on hand, do it directly; otherwise
    push a raise-only PendingFoodPayment and defer the pay-and-plow to its resume (which
    debits the raised food). Plow Maker's only cost is the 1 food, so nothing is reserved."""
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_plow(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID, reserved=Cost(),
    ))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("before_action_space", CARD_ID, _eligible, _apply)
register_food_payment_resume(CARD_ID, _pay_and_plow)
