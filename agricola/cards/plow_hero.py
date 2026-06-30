"""Plow Hero (occupation, C91; Corbarius Expansion; players 1+).

Card text: "Each time you use the 'Farmland' or 'Cultivation' action space with the first
person you place in a round, you can plow 1 additional field for 1 food."

Plow Maker plus a "this is my first worker placement this round" gate. A pay-food → plow
trigger in the Ox Goad shape (FOOD_PAYMENT_DESIGN.md §8): event `before_action_space`,
filter Farmland/Cultivation, food 1 — identical to Plow Maker except the extra
first-placement condition.

"First person you place in a round" — the engine exposes this cleanly without new state.
A round starts with every worker at home (`people_home == people_total`), and each
placement decrements `people_home` by one. The `before_action_space` trigger fires AFTER
`_apply_worker_placement` has decremented `people_home` for the placement now resolving
(see engine._apply_place_worker / resolution._apply_worker_placement), so at firing time
the count of placements made this round is `people_total_at_round_start − people_home`.
Within a round, `people_total` only grows via a newborn (a Wish-for-Children placement),
and each such growth is paired with a worker being consumed — so after k placements of
which w were earlier wishes, `people_home == people_total − k` and the test
`people_home == people_total − 1` is exactly "k == 1 minus prior wishes". For the first
placement on Farmland/Cultivation (neither is a wish, so no prior wish on the firing turn
inflates the count toward it) this holds iff exactly one worker has been placed → the
robust "first person placed this round" predicate. (Worked through in the task analysis;
it correctly rejects a 2nd-or-later placement, including after an earlier same-round
wish.)

"Each time you use" fires in the BEFORE phase (Trigger-Timing ruling). `_apply` is the
guard, `_pay_and_plow` the body. Eligibility is liquidation-aware (`_liquidatable_to`,
NOT `food >= 1`) and gates on a plowable cell (`_can_plow`). Once-per-use via
`triggers_resolved`. Both spaces are non-atomic, so no `register_action_space_hook`. See
PAY_FOOD_PLOW_CARDS.md / FOOD_PAYMENT_DESIGN.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_occupation
from agricola.cards.triggers import register
from agricola.legality import _can_plow, _can_plow_twice, _liquidatable_to
from agricola.pending import PendingFoodPayment, PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "plow_hero"
_SPACES = frozenset({"farmland", "cultivation"})
_FOOD_COST = 1


def _is_first_placement_this_round(state: GameState, idx: int) -> bool:
    """True iff the placement now being resolved is the player's first this round.

    The before_action_space trigger fires after the placing worker has already been
    decremented from people_home, so exactly one worker placed ⟺
    people_home == people_total − 1. (See module docstring for the full derivation,
    including the newborn/Wish interaction.)"""
    p = state.players[idx]
    return p.people_home == p.people_total - 1


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
    if not _is_first_placement_this_round(state, idx):     # only with the first worker
        return False
    p = state.players[idx]
    # Never a dead-end: the 1 food must be payable (with liquidation) AND a plow legal. On
    # Farmland the mandatory base plow must survive the grant (enforce-first → a second
    # sequential plow must exist); Cultivation rides its own host (single plow ok).
    plow_ok = _can_plow_twice(p) if sid == "farmland" else _can_plow(p)
    return plow_ok and _liquidatable_to(state, idx, p, Resources(food=_FOOD_COST))


def _apply(state: GameState, idx: int) -> GameState:
    """Pay 1 food and grant the plow. With enough food on hand, do it directly; otherwise
    push a raise-only PendingFoodPayment and defer the pay-and-plow to its resume (which
    debits the raised food). The only cost is the 1 food, so nothing is reserved."""
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_plow(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID, reserved=Cost(),
    ))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("before_action_space", CARD_ID, _eligible, _apply)
register_food_payment_resume(CARD_ID, _pay_and_plow)
