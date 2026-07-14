"""Plow Driver (occupation, A90; Base Revised; players 1+).

Card text: "Once you live in a stone house, at the start of each round, you can pay
1 food to plow 1 field."

Category 7 (start-of-round phase hook). An OPTIONAL trigger (the "you can"): once in
a stone house, at round start the owner may pay 1 food to plow 1 field — a
fixed-price granted sub-action (not a cost-modifier). Surfaced as a FireTrigger on
the `start_of_round` event; once-per-round via the `used_this_round` latch (II.3).

The 1 food is paid through the shared food-payment path (FOOD_PAYMENT_DESIGN.md), so it
may be raised by converting crops/animals if food is short: `_apply` is the guard and
`_pay_and_plow` the body (debit 1 food, latch, push the plow). With the food on hand it
runs directly; short, it pushes a raise-only PendingFoodPayment whose resume (registered
under this card id) debits the raised food then plows. Eligibility is therefore
liquidation-aware (`_liquidatable_to`) and also requires a plowable cell, so it never
grants a dead-end. See CARD_IMPLEMENTATION_PLAN.md Category 7 / FOOD_PAYMENT_DESIGN.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_occupation
from agricola.cards.triggers import register
from agricola.constants import HouseMaterial
from agricola.legality import _can_plow, _liquidatable_to
from agricola.pending import PendingFoodPayment, PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "plow_driver"
_FOOD_COST = 1


def _pay_and_plow(state: GameState, idx: int) -> GameState:
    """Debit 1 food, latch once-per-round, push the plow. Reached directly (food on hand)
    and as the post-food-payment resume (the raise-only frame leaves the food in supply for
    this to debit)."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(food=_FOOD_COST),
                     used_this_round=p.used_this_round | {CARD_ID})
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    return push(state, PendingPlow(player_idx=idx, initiated_by_id="card:plow_driver"))


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    p = state.players[idx]
    return (CARD_ID not in p.used_this_round
            and p.house_material is HouseMaterial.STONE
            and _liquidatable_to(state, idx, p, Resources(food=_FOOD_COST))
            and _can_plow(p))


def _apply(state: GameState, idx: int) -> GameState:
    """Pay 1 food and plow. With the food on hand, do it directly; otherwise push a
    raise-only PendingFoodPayment and defer the pay-and-plow to its resume (which debits
    the raised food). Plow Driver's only cost is the 1 food, so nothing is reserved."""
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_plow(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID, reserved=Cost(),
    ))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("start_of_round", CARD_ID, _eligible, _apply)
register_food_payment_resume(CARD_ID, _pay_and_plow)
