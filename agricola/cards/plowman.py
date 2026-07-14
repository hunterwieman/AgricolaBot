"""Plowman (occupation, D91; Consul Dirigens Expansion; players 1+).

Card text: "Add 4, 7, and 10 to the current round and place a field tile on each
corresponding round space. At the start of these rounds, you can plow the field for
1 food."
Cost: none. Prerequisite: none. VPs: none. Not passing.

A FUSION of two existing patterns:

- **Handplow's deferred-plow schedule** (Category 8 effect-hook). On play, the three
  due rounds R+4 / R+7 / R+10 (R = the current round) each receive this card's id in
  the `future_rewards` schedule (`schedule_effect`, which silently drops rounds past
  the 14-round game — matching "place a field tile on each corresponding round space",
  the same physical-tile clause Handplow models as cosmetic since no field-tile supply
  is tracked). The schedule alone drives hosting on exactly those three rounds (the
  trigger's own eligibility reads the slot) — eligibility-driven under the preparation
  ladder (ruling 54, 2026-07-14), with no ownership index.

- **Plow Driver's pay-1-food-to-plow body** (Category 7). "you **can** plow the field
  for 1 food" is an OPTIONAL granted sub-action carrying a 1-food price, surfaced as a
  FireTrigger at the collection window's choice host with the host's Proceed as the
  decline.
  The 1 food is paid through the shared food-payment path (FOOD_PAYMENT_DESIGN.md): with
  the food on hand it runs directly; short, it pushes a raise-only PendingFoodPayment
  whose resume (`_pay_and_plow`, registered under this card id) debits the raised food
  then plows. Eligibility is therefore liquidation-aware (`_liquidatable_to`) and also
  requires a plowable cell (`_can_plow`), so it never grants a dead-end.

**The once-per-scheduled-round guarantee comes from CONSUMING the schedule slot**
(Handplow's pattern), NOT from a `used_this_round` latch (Plow Driver's, which it needs
only because it fires every round). `_apply` removes this card's id from the round's
schedule slot FIRST — the guard — and only THEN runs the pay-and-plow body. Consuming
the slot before the food-payment branch means that when food is short and a
PendingFoodPayment is pushed, the start-of-round trigger no longer re-qualifies while
that raise frame resolves (putting the consume in the body/resume would re-offer the
trigger mid-raise). See CARD_IMPLEMENTATION_PLAN.md Category 7/8 / FOOD_PAYMENT_DESIGN.md.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_effect
from agricola.cards.specs import register_food_payment_resume, register_occupation
from agricola.cards.triggers import register
from agricola.legality import _can_plow, _liquidatable_to
from agricola.pending import PendingFoodPayment, PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "plowman"
_FOOD_COST = 1


def _on_play(state: GameState, idx: int) -> GameState:
    # "Add 4, 7, and 10 to the current round" → schedule the deferred plow on those
    # three rounds (rounds past 14 are dropped for free by schedule_effect).
    R = state.round_number
    return schedule_effect(state, idx, (R + 4, R + 7, R + 10), CARD_ID)


def _scheduled_slot(p, round_number: int):
    """The future_rewards slot index for `round_number` if it carries this card's
    grant, else None."""
    slot = round_number - 1
    fr = p.future_rewards
    if 0 <= slot < len(fr) and CARD_ID in fr[slot].effect_card_ids:
        return slot
    return None


def _pay_and_plow(state: GameState, idx: int) -> GameState:
    """Debit 1 food, push the plow. Reached directly (food on hand) and as the
    post-food-payment resume (the raise-only frame leaves the raised food in supply for
    this to debit). The once-per-round guard already fired in `_apply` (the slot was
    consumed there), so nothing is latched here."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(food=_FOOD_COST))
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingPlow(player_idx=idx, initiated_by_id="card:plowman"))


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    p = state.players[idx]
    return (_scheduled_slot(p, state.round_number) is not None
            and _liquidatable_to(state, idx, p, Resources(food=_FOOD_COST))
            and _can_plow(p))


def _apply(state: GameState, idx: int) -> GameState:
    """GUARD then body. First consume the schedule slot (remove "plowman" from this
    round's slot) so it fires at most once per scheduled round and never re-qualifies
    while a food-raise resolves. Then pay 1 food and plow: with the food on hand do it
    directly; otherwise push a raise-only PendingFoodPayment and defer the pay-and-plow
    to its resume. Plowman's only cost is the 1 food, so nothing is reserved."""
    p = state.players[idx]
    slot = _scheduled_slot(p, state.round_number)
    reward = p.future_rewards[slot]
    new_reward = fast_replace(
        reward, effect_card_ids=reward.effect_card_ids - {CARD_ID})
    new_rewards = p.future_rewards[:slot] + (new_reward,) + p.future_rewards[slot + 1:]
    p = fast_replace(p, future_rewards=new_rewards)
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))

    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_plow(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID, reserved=Cost(),
    ))


register_occupation(CARD_ID, _on_play)
# "At the start of these rounds, you can [take the thing on the round
# space]" — the round_space_collection window (user ruling 2026-07-14:
# round-space schedule grants resolve at COLLECTION time, immediately
# after the mechanical collect, not at the start_of_round rung).
register("round_space_collection", CARD_ID, _eligible, _apply)
register_food_payment_resume(CARD_ID, _pay_and_plow)
