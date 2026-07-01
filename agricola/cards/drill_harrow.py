"""Drill Harrow (minor improvement, D17; Dulcinaria Expansion; cost 1 wood).

Card text: "Each time before you take an unconditional 'Sow' action, you can pay 3 food
to plow 1 field."

A pay-food → plow trigger in the exact shape of Ox Goad (FOOD_PAYMENT_DESIGN.md §8),
differing only in event (the BEFORE-Sow sub-action hook) and food amount (3). The card
text's "before you take a Sow action" is the literal `before_sow` event — the before-
phase of the PendingSow host (no separate ruling needed; the text states the phase).

"Unconditional Sow" distinguishes the standard Sow sub-action (Grain Utilization /
Cultivation) from a card-granted *conditional* sow. No conditional-sow card exists in
the implemented set, so every `before_sow` event is an unconditional sow — this fires on
all of them. (If a conditional-sow card is ever added, this eligibility must additionally
inspect the PendingSow's provenance to exclude it; flagged here for that future session.)

`_apply` is the guard, `_pay_and_plow` the body (debit 3 food, push the plow). With ≥ 3
food on hand `_apply` runs it directly; short, it pushes a raise-only PendingFoodPayment
whose resume (registered under this card id) debits the raised food then plows.
Eligibility is liquidation-aware (`_liquidatable_to`, NOT `food >= 3`) and gates on a
plowable cell (`_can_plow`) so a fired plow never dead-ends. Once-per-sow via the host's
`triggers_resolved`. See PAY_FOOD_PLOW_CARDS.md / FOOD_PAYMENT_DESIGN.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_minor
from agricola.cards.triggers import register
from agricola.legality import _can_afford, _can_plow, _liquidatable_to
from agricola.pending import PendingFoodPayment, PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "drill_harrow"
_FOOD_COST = 3


def _pay_and_plow(state: GameState, idx: int) -> GameState:
    """Debit 3 food, then grant the plow. Reached directly (food on hand) and as the
    post-food-payment resume (the raise-only frame leaves the food in supply to debit)."""
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources - Resources(food=_FOOD_COST))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingPlow(player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))


def _seed_reserving_liquidatable(state: GameState, idx: int) -> bool:
    """True iff the 3 food can be raised while leaving the mandatory Sow at least one seed.

    The host is a PendingSow whose before-phase offers only FireTrigger + CommitSow — no
    Stop — so the sow is forced and needs >= 1 seed (grain OR veg) to have any legal
    CommitSow after this trigger resolves. A plain `_liquidatable_to(food=3)` would freely
    burn grain AND veg as conversion fuel, so it can raise the 3 food by consuming the
    player's LAST seed and strand the sow (empty legal set on a non-empty stack).

    Guard: the 3 food must be raisable from everything EXCEPT one reserved seed — either
    reserving 1 grain OR reserving 1 veg. We check by running the liquidation-affordability
    test against a player copy whose resources hold one fewer of that seed (so it is not in
    the conversion pool); if either reservation still affords the 3 food, the reserved seed
    survives to feed the mandatory sow."""
    p = state.players[idx]
    for reserve in (Resources(grain=1), Resources(veg=1)):
        if not _can_afford(p, reserve):
            continue   # no such seed to reserve
        reserved_p = fast_replace(p, resources=p.resources - reserve)
        if _liquidatable_to(state, idx, reserved_p, Resources(food=_FOOD_COST)):
            return True
    return False


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per this sow
        return False
    p = state.players[idx]
    # Never a dead-end: a plow must be legal AND the 3 food payable via liquidation WITHOUT
    # burning the mandatory sow's last seed (grain OR veg). See _seed_reserving_liquidatable.
    return _can_plow(p) and _seed_reserving_liquidatable(state, idx)


def _apply(state: GameState, idx: int) -> GameState:
    """Pay 3 food and grant the plow. With enough food on hand, do it directly; otherwise
    push a raise-only PendingFoodPayment and defer the pay-and-plow to its resume (which
    debits the raised food). The only cost is the 3 food, so nothing is reserved."""
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_plow(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID, reserved=Cost(),
    ))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register("before_sow", CARD_ID, _eligible, _apply)
register_food_payment_resume(CARD_ID, _pay_and_plow)
