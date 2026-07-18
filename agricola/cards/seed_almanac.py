"""Seed Almanac (minor improvement, E18; Ephipparius Expansion; cost 1 reed; prereq 4
occupations; no VP).

Card text: "Each time after you play a minor improvement after this one, you can
pay 1 food to plow 1 field."

Structurally Ox Goad (E19), but fired from the play-minor host instead of an
accumulation space, and paying 1 food instead of 2. "after you play … after this
one" is explicit AFTER timing, so this is an optional `after_play_minor` trigger:
declining = not firing it (the host's Stop). Once fired, paying 1 food and plowing
1 field are mandatory, so eligibility gates on BOTH being possible — 1 food
affordable (with liquidation) AND a plowable cell exists — to never offer a
dead-end (CARD_AUTHORING_GUIDE.md §2).

"after this one" — ownership gating handles later plays automatically: the trigger
only fires while Seed Almanac is in the tableau, and a minor played BEFORE it was
played while it wasn't owned. The ONE case to exclude is Seed Almanac's OWN play:
`_execute_play_minor` adds the card to the tableau before the deferred after-flip
fires `after_play_minor`, so the ownership gate would let its own play qualify. The
play host carries a `played_card_id` stamp (the Clutterer idiom), so eligibility
rejects when the top frame's `played_card_id == CARD_ID`. Any OTHER minor play
counts — bare "Minor Improvement" plays, the composite's child minor, and
traveling-minor plays (Seed Almanac is a bystander; the traveling card leaving the
tableau is irrelevant) — so eligibility does NOT filter on `initiated_by_id`.

`_apply` is the guard, `_pay_and_plow` the body (debit 1 food, push the plow): with
≥ 1 food on hand `_apply` runs it directly; short, it pushes a raise-only
PendingFoodPayment whose `resume_kind` is this card id, so once the food is in
supply `_resume` dispatches back to `_pay_and_plow` (which debits it then). The
frame is raise-only — it never debits — so the grant's resume does the debit,
mirroring Ox Goad. "Each time after you play" is once per play host, enforced by
the host's `triggers_resolved`. Card-game only (ownership-gated registry, and the
play-minor host is card-only), so the Family trace and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_minor
from agricola.cards.triggers import register
from agricola.legality import _can_plow, _liquidatable_to
from agricola.pending import PendingFoodPayment, PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "seed_almanac"
_FOOD_COST = 1


def _pay_and_plow(state: GameState, idx: int) -> GameState:
    """Debit the 1 food, then grant the plow. Reached directly (food on hand) and as the
    post-food-payment continuation (the raise-only frame leaves the food in supply for this to
    debit). Reads the food from supply either way."""
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources - Resources(food=_FOOD_COST))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingPlow(player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per play host
        return False
    # Exclude Seed Almanac's OWN play ("after this one"); any other minor qualifies.
    if getattr(state.pending_stack[-1], "played_card_id", None) == CARD_ID:
        return False
    p = state.players[idx]
    # Never a dead-end: the 1 food must be payable (with liquidation) AND a plow legal.
    return _can_plow(p) and _liquidatable_to(state, idx, p, Resources(food=_FOOD_COST))


def _apply(state: GameState, idx: int) -> GameState:
    """Pay 1 food and grant the plow. With enough food on hand, do it directly; otherwise push
    a raise-only PendingFoodPayment and defer the pay-and-plow to its resume (which debits the
    raised food). Seed Almanac's only cost is the 1 food, so nothing is reserved."""
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_plow(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID, reserved=Cost(),
    ))


register_minor(CARD_ID, cost=Cost(resources=Resources(reed=1)), min_occupations=4)
register("after_play_minor", CARD_ID, _eligible, _apply)
register_food_payment_resume(CARD_ID, _pay_and_plow)
