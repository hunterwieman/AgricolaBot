"""Steam Plow (minor improvement, D18; Dulcinaria Expansion; Farm Planner).

Card text (verbatim): "Immediately after each returning home phase, you can pay
2 wood and 1 food to use the "Farmland" action space without placing a person."
Cost: 1 Wood, 1 Food. No prerequisite. Printed VPs: 1.

TIMING — "immediately after each returning home phase" is the round-end
ladder's ``after_returning_home`` rung (user ruling 49, 2026-07-12, recorded
verbatim in ``agricola/cards/round_end.py``: '"immediately after each returning
home phase" (Steam Plow — concurrent with after_returning_home per ruling 49's
per-instance merge)'). That rung is post-reset (position 5) — placements are
already cleared, which is harmless here (Steam Plow reads no board occupancy).
The "immediately" is settled by ruling 49, not decided here.

THE GRANT — "you can pay 2 wood and 1 food to use the 'Farmland' action space
without placing a person" is an OPTIONAL trigger ("you can"). Farmland's sole
effect is to plow 1 field, so firing grants a single ``PendingPlow`` (the same
"take a [space] action without placing a person" → raw primitive shape Master
Renovator uses for a Renovation and Sundial for a Sow). Declining is the
window's ``Proceed``; once-per-window is the frame's ``triggers_resolved``.

THE COST — 2 wood AND 1 food. The 1 food is paid through the shared
food-payment path (the Ox Goad pattern, FOOD_PAYMENT_DESIGN.md §8/§9): ``_apply``
first debits the 2 wood (eligibility guarantees >= 2 wood on hand), then, with
1 food on hand, ``_pay_food_and_plow`` debits it and pushes the plow directly;
short, it pushes a raise-only ``PendingFoodPayment`` whose ``resume_kind`` is
this card id, so the player may raise the 1 food via the game-wide anytime
conversions and the registered resume debits it then. The frame is
``reserved=Cost()`` because the 2 wood is ALREADY off supply before the food
frame is pushed (wood is never food-liquidation fuel, so nothing needs
reserving). Eligibility gates on ALL THREE being possible — 2 wood on hand, the
1 food payable-with-liquidation, and a legal plow — so a fired trigger is never
a dead-end (CARD_AUTHORING_GUIDE.md §2).

Cost "1 Wood, 1 Food" (the PLAY cost) → ``Cost(resources=Resources(wood=1,
food=1))``; printed VPs 1 → ``vps=1``.

Card-game only (ownership-gated registries; no CardStore): the Family game is
byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_minor
from agricola.cards.triggers import register
from agricola.legality import _can_plow, _liquidatable_to
from agricola.pending import PendingFoodPayment, PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "steam_plow"
_WOOD_COST = 2
_FOOD_COST = 1


def _pay_food_and_plow(state: GameState, idx: int) -> GameState:
    """Debit the 1 food, then grant the plow. Reached directly (food on hand,
    after ``_apply`` debited the 2 wood) and as the post-food-payment
    continuation (the raise-only frame leaves the food in supply for this to
    debit). The 2 wood was already debited by ``_apply`` either way."""
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources - Resources(food=_FOOD_COST))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingPlow(player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))


def _eligible(state: GameState, idx: int, _resolved: frozenset) -> bool:
    """Never a dead-end: 2 wood on hand, the 1 food payable (with liquidation),
    AND a legal plow. Ownership is the window machinery's gate; once-per-window
    is the frame's ``triggers_resolved``."""
    p = state.players[idx]
    return (
        p.resources.wood >= _WOOD_COST
        and _can_plow(p)
        and _liquidatable_to(state, idx, p, Resources(food=_FOOD_COST))
    )


def _apply(state: GameState, idx: int) -> GameState:
    """Pay 2 wood + 1 food and grant the plow. Debit the 2 wood first
    (guaranteed on hand); then pay the food directly (on hand) or defer to a
    raise-only ``PendingFoodPayment`` whose resume does the food debit + plow.
    Nothing is reserved — the wood is already off supply and is not food fuel."""
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources - Resources(wood=_WOOD_COST))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_food_and_plow(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID, reserved=Cost(),
    ))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1, food=1)), vps=1)

# The optional pay-2-wood-1-food-to-plow on the round-end ladder's
# after_returning_home rung (ruling 49); the 1 food rides the shared
# food-payment path.
register("after_returning_home", CARD_ID, _eligible, _apply)
register_food_payment_resume(CARD_ID, _pay_food_and_plow)
