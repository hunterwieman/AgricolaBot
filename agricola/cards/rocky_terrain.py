"""Rocky Terrain (minor improvement, C80; Corbarius Expansion).

Card text: "Each time you plow a field (tile or card), you can also buy 1 stone
for 1 food."

Clarification: "Playing field cards counts as plowing a field." (Inert in the
current engine — field-tile cards are not implemented, and the play-minor path
never creates a FIELD cell — so there is no separate play_minor hook to add. If
field-tile cards are ever implemented, that path would need to fire `after_plow`.)

Shape: an OPTIONAL, declinable reward that fires once per field plowed. The plow
is the TRIGGER and the +1-stone purchase is the REWARD, so the event is
`after_plow` (NOT `before_action_space`): `_enter_after_phase` fires `after_plow`
once per `PendingPlow` commit for the plowing player (see barrow_pusher), so a
multi-field plow action (Cultivation, Mole Plow, …) offers the buy once per
field — exactly "each time you plow a field." The PendingPlow's after-phase
enumerator surfaces this card's `FireTrigger` (declinable: `Stop` declines).

Cost shape: the buy is "1 stone for 1 food". Unlike the pay-food → plow cards
(Plow Maker, Plow Hero, …) whose reward is a granted plow, this card's reward is
plain GOODS (+1 stone, −1 food). So:
  - There is NO `_can_plow` eligibility gate: the reward never dead-states (it is
    goods, not a plow that could have no legal target cell).
  - Eligibility is liquidation-aware (`_liquidatable_to`, NOT `food >= 1`): food
    is an at-any-time convertible good, so the 1 food may be raised by converting
    crops/animals (FOOD_PAYMENT_DESIGN.md). With food on hand the buy is direct;
    otherwise a raise-only `PendingFoodPayment` is pushed and `_buy_stone` runs as
    its resume (the resume mechanism is reward-agnostic — it raises the food into
    supply, then the resume debits it and grants the +1 stone).
  - Once per plow via `triggers_resolved` on the host `PendingPlow` frame (each
    plowed field pushes a fresh PendingPlow, so the scope is naturally per-field).

Played via the four minor-play entry points; no on-play effect, no prereq, no VPs.
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_minor
from agricola.cards.triggers import register
from agricola.legality import _liquidatable_to
from agricola.pending import PendingFoodPayment, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "rocky_terrain"
_FOOD_COST = 1


def _buy_stone(state: GameState, idx: int) -> GameState:
    """Debit 1 food, gain 1 stone. Reached directly (food on hand) and as the
    post-food-payment resume (the raise-only frame leaves the raised food in
    supply to debit). The reward is plain goods — nothing is pushed."""
    p = state.players[idx]
    p = fast_replace(
        p, resources=p.resources + Resources(stone=1) - Resources(food=_FOOD_COST))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per plowed field
        return False
    # The 1 food must be payable (with liquidation). No plow gate: the reward is
    # goods (+1 stone), so it can never dead-state on a missing plow target.
    p = state.players[idx]
    return _liquidatable_to(state, idx, p, Resources(food=_FOOD_COST))


def _apply(state: GameState, idx: int) -> GameState:
    """Buy 1 stone for 1 food. With food on hand, do it directly; otherwise push a
    raise-only PendingFoodPayment and defer the buy to its resume (which debits the
    raised food). The only cost is the 1 food, so nothing is reserved."""
    if state.players[idx].resources.food >= _FOOD_COST:
        return _buy_stone(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID, reserved=Cost(),
    ))


register_minor(CARD_ID, cost=Cost(resources=Resources(food=1)))
register("after_plow", CARD_ID, _eligible, _apply)
register_food_payment_resume(CARD_ID, _buy_stone)
