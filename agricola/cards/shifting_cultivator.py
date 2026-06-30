"""Shifting Cultivator (occupation, A91; Artifex Expansion; players 1+).

Card text: "Each time you use a wood accumulation space, you can also play 3 food to
plow 1 field."
Clarification: "Food obtained via the Basket A056, or any other effect 'after' using
the space may not be used to pay for this effect."

A pay-food → plow trigger in the exact shape of Ox Goad (FOOD_PAYMENT_DESIGN.md §8),
differing only in event, filter, and food amount (3). "Each time you use [space]" fires
in the BEFORE phase (the Trigger-Timing ruling, CARD_AUTHORING_GUIDE.md §2) — which is
exactly consistent with the clarification that food obtained *after* using the space
(e.g. via Basket) may not pay: firing in the before-phase means the space's own food has
not yet been collected, so it could not be used here anyway (no extra code needed).

"A wood accumulation space" in the 2-player engine is the single Forest space (verified
against constants.SPACE_IDS: forest is the only wood accumulation space; clay_pit/
reed_bank/fishing accumulate clay/reed/food). Forest is ATOMIC (it normally resolves in
one step with no host frame), so the card must call `register_action_space_hook` to give
it a PendingActionSpace host whenever Shifting Cultivator is owned — otherwise there is
nothing for the before-trigger to attach to (CARD_AUTHORING_GUIDE.md §2).

`_apply` is the guard, `_pay_and_plow` the body (debit 3 food, push the plow). With ≥ 3
food on hand `_apply` runs it directly; short, it pushes a raise-only PendingFoodPayment
whose resume (registered under this card id) debits the raised food then plows.
Eligibility is liquidation-aware (`_liquidatable_to`, NOT `food >= 3`) and gates on a
plowable cell (`_can_plow`) so a fired plow never dead-ends. Once-per-use via the host's
`triggers_resolved`. See PAY_FOOD_PLOW_CARDS.md / FOOD_PAYMENT_DESIGN.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_occupation
from agricola.cards.triggers import register, register_action_space_hook
from agricola.legality import _can_plow, _liquidatable_to
from agricola.pending import PendingFoodPayment, PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "shifting_cultivator"
SPACES = frozenset({"forest"})    # the only wood accumulation space in the 2-player engine
_FOOD_COST = 3


def _pay_and_plow(state: GameState, idx: int) -> GameState:
    """Debit 3 food, then grant the plow. Reached directly (food on hand) and as the
    post-food-payment resume (the raise-only frame leaves the food in supply to debit)."""
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources - Resources(food=_FOOD_COST))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingPlow(player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per use
        return False
    if state.pending_stack[-1].space_id not in SPACES:
        return False
    p = state.players[idx]
    # Never a dead-end: the 3 food must be payable (with liquidation) AND a plow legal.
    return _can_plow(p) and _liquidatable_to(state, idx, p, Resources(food=_FOOD_COST))


def _apply(state: GameState, idx: int) -> GameState:
    """Pay 3 food and grant the plow. With enough food on hand, do it directly; otherwise
    push a raise-only PendingFoodPayment and defer the pay-and-plow to its resume (which
    debits the raised food). The only cost is the 3 food, so nothing is reserved."""
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_plow(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID, reserved=Cost(),
    ))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("before_action_space", CARD_ID, _eligible, _apply)
register_food_payment_resume(CARD_ID, _pay_and_plow)
register_action_space_hook(CARD_ID, SPACES)              # Forest is atomic → host it
