"""Small Greenhouse (minor improvement, D69; Consul Dirigens Expansion; Crop
Provider; cost 2 Wood; prereq 1 Occupation; 1 VP).

Card text: "Add 4 and 7 to the current round and place 1 vegetable on each
corresponding round space. At the start of these rounds, you can buy the vegetable
for 1 food."

This is the *paid* sibling of Large Greenhouse (A69, "Add 4, 7, and 9 … you GET the
vegetable", a FREE pickup via `schedule_resources`). Here the vegetable on each
scheduled round space is BOUGHT for 1 food — so the round-start collection is an
OPTIONAL paid grant, not an automatic goods drop. The two ideas it fuses:

- **Schedule the rounds as effect-hooks, not goods** (like Chain Float, B20). "Add 4
  and 7 to the current round" → offsets R+4 and R+7 (the current round number plus
  each, exactly parallel to Large Greenhouse's "Add 4, 7, 9" = R+4/R+7/R+9 and
  Handplow's "Add 5" = R+5; NOT fixed rounds 4 and 7). Because the round-start effect
  is a *decision* (buy or not), it rides on `future_rewards` (the FutureReward
  effect-hook set) via `schedule_effect`, NOT on `future_resources`. The schedule
  itself drives hosting (the trigger's own eligibility reads the slot — the
  preparation ladder's eligibility-driven model, ruling 54, 2026-07-14), so the card
  hosts a window frame only on the rounds its vegetables come due. `schedule_effect` clamps to the 14-round game, so
  an offset past round 14 is silently dropped ("place on each corresponding round
  space" — there is no space past 14); played late enough that both offsets exceed 14
  it is a wasted but legal play.

- **The paid optional pickup** (like Plow Driver, A90). "you CAN buy" is OPTIONAL — a
  granted paid action the player takes or declines. Surfaced as a FireTrigger on the
  `round_space_collection` window's choice host, with the host's Proceed as the decline. The 1 food is paid through the shared food-payment path
  (FOOD_PAYMENT_DESIGN.md): `_apply` is the guard and `_buy_veg` the body. With the food
  on hand it runs directly; short, it pushes a raise-only PendingFoodPayment whose
  resume (registered under this card id) debits the raised food then grants the veg.
  Eligibility is therefore liquidation-aware (`_liquidatable_to`) so it never offers a
  dead-end.

The two scheduled rounds need NO two-round-specific code: the per-round slot
(`_scheduled_slot`) IS the gate AND the once-per-round latch. `_buy_veg` consumes ONLY
the current round's slot, so buying on round R+4 leaves the R+7 slot intact for that
later round, and each scheduled round fires its own grant independently, at most once.

**The slot consume lives in `_buy_veg`, the single post-payment body** (not in
`_apply`): that body is reached BOTH directly (food on hand) and via the food-payment
resume (the raise-only frame leaves the raised food in supply for the body to debit). If
the slot-consume were done at `_apply`, the resume path would grant the veg without
consuming the slot (re-offering it next visit) — so debit, veg grant, and slot consume
are kept together in `_buy_veg`. See chain_float.py (per-slot scheduling/scoping),
plow_driver.py (the paid optional start-of-round grant + food-payment resume), and
large_greenhouse.py (the FREE-pickup sibling).
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_effect
from agricola.cards.specs import register_food_payment_resume, register_minor
from agricola.cards.triggers import register
from agricola.legality import _liquidatable_to
from agricola.pending import PendingFoodPayment, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "small_greenhouse"
_FOOD_COST = 1


def _on_play(state: GameState, idx: int) -> GameState:
    # "Add 4 and 7 to the current round" → schedule the paid veg pickup on each of
    # rounds R+4 and R+7. schedule_effect silently drops any slot past round 14.
    R = state.round_number
    return schedule_effect(state, idx, (R + 4, R + 7), CARD_ID)


def _scheduled_slot(p, round_number: int):
    """The future_rewards slot index for `round_number` if it carries this card's
    grant, else None."""
    slot = round_number - 1
    fr = p.future_rewards
    if 0 <= slot < len(fr) and CARD_ID in fr[slot].effect_card_ids:
        return slot
    return None


def _buy_veg(state: GameState, idx: int) -> GameState:
    """Debit 1 food, grant +1 veg, and consume ONLY this round's slot (so the other
    scheduled round keeps its grant). Reached directly (food on hand) and as the
    post-food-payment resume (the raise-only frame leaves the raised food in supply for
    this to debit)."""
    p = state.players[idx]
    slot = _scheduled_slot(p, state.round_number)
    reward = p.future_rewards[slot]
    new_reward = fast_replace(
        reward, effect_card_ids=reward.effect_card_ids - {CARD_ID})
    new_rewards = p.future_rewards[:slot] + (new_reward,) + p.future_rewards[slot + 1:]
    p = fast_replace(
        p,
        resources=p.resources - Resources(food=_FOOD_COST) + Resources(veg=1),
        future_rewards=new_rewards,
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    """Offer the buy only on a scheduled round (the slot is the per-round gate AND the
    once-per-round latch) when the 1 food is payable (possibly by liquidation)."""
    p = state.players[idx]
    return (_scheduled_slot(p, state.round_number) is not None
            and _liquidatable_to(state, idx, p, Resources(food=_FOOD_COST)))


def _apply(state: GameState, idx: int) -> GameState:
    """Buy 1 veg for 1 food. With the food on hand, do it directly; otherwise push a
    raise-only PendingFoodPayment and defer the buy to its resume (which debits the raised
    food). The only cost is the 1 food, so nothing is reserved."""
    if state.players[idx].resources.food >= _FOOD_COST:
        return _buy_veg(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID, reserved=Cost(),
    ))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=2)),
    min_occupations=1,
    vps=1,
    on_play=_on_play,
)
# "At the start of these rounds, you can [take the thing on the round
# space]" — the round_space_collection window (user ruling 2026-07-14:
# round-space schedule grants resolve at COLLECTION time, immediately
# after the mechanical collect, not at the start_of_round rung).
register("round_space_collection", CARD_ID, _eligible, _apply)
register_food_payment_resume(CARD_ID, _buy_veg)
