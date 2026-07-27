"""Plow Hero (occupation, C91; Corbarius Expansion; players 1+).

Card text: "Each time you use the 'Farmland' or 'Cultivation' action space with the first
person you place in a round, you can plow 1 additional field for 1 food."

Plow Maker plus a "this is my first worker placement this round" gate. A pay-food → plow
trigger in the Ox Goad shape (FOOD_PAYMENT_DESIGN.md §8): event `before_action_space`,
filter Farmland/Cultivation, food 1 — identical to Plow Maker except the extra
first-placement condition.

"First person you place in a round" is the ACTING person's ordinal, read via
helpers.acting_placement_number (the standing-worker ledger's number at the acting
space — ruling 79): the just-minted number at an ordinary placement, the moved
worker's preserved number at a relocated use (Straw Hat). Earlier derivations
(`people_home == people_total − 1`, then the raw mint counter) are retired — the
first broke on loaner placements, the second at relocations.

"Each time you use" fires in the BEFORE phase (Trigger-Timing ruling). `_apply` is the
guard, `_pay_and_plow` the body. Eligibility is liquidation-aware (`_liquidatable_to`,
NOT `food >= 1`) and gates on a plowable cell (`_can_plow`). Once-per-use via
`triggers_resolved`. Both spaces are non-atomic, so no `register_action_space_hook`. See
PAY_FOOD_PLOW_CARDS.md / FOOD_PAYMENT_DESIGN.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_occupation
from agricola.cards.triggers import register
from agricola.helpers import acting_placement_number
from agricola.legality import _can_plow_twice, _liquidatable_to
from agricola.pending import PendingFoodPayment, PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "plow_hero"
_SPACES = frozenset({"farmland", "cultivation"})
_FOOD_COST = 1


def _is_first_placement_this_round(state: GameState, idx: int) -> bool:
    """True iff the use now being resolved is by the player's FIRST-placed person
    of the round.

    Read via helpers.acting_placement_number — the acting worker's number from the
    standing-worker ledger, which equals the just-minted counter at every ordinary
    placement but stays the moved worker's PRESERVED number at a relocated use
    (Straw Hat's end-of-work move; ruling 79 items 3/4). History of shortcuts this
    read replaced: `people_home == people_total − 1` broke on a LOANER placement
    (a loaner debits `workers_in_supply`, never `people_home`), and the raw mint
    counter breaks at a relocation (it holds the round's total mints, not the
    moved worker's number)."""
    return acting_placement_number(state, idx) == 1


def _pay_and_plow(state: GameState, idx: int) -> GameState:
    """Debit 1 food, then grant the plow. Reached directly (food on hand) and as the
    post-food-payment resume (the raise-only frame leaves the food in supply to debit)."""
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources - Resources(food=_FOOD_COST))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    # Restrict the granted plow's cells (safe_plow_cells) so the base plow stays legal — on
    # both Farmland and Cultivation (loss-less; see _eligible).
    return push(state, PendingPlow(player_idx=idx, initiated_by_id=f"card:{CARD_ID}",
                                   must_preserve_base=True))


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per use
        return False
    sid = state.pending_stack[-1].space_id
    if sid not in _SPACES:
        return False
    if not _is_first_placement_this_round(state, idx):     # only with the first worker
        return False
    p = state.players[idx]
    # Never a dead-end: the 1 food must be payable (with liquidation) AND the grant must leave
    # the base plow legal (`_can_plow_twice` + must_preserve_base=True) — on BOTH spaces
    # (loss-less on Cultivation; see mole_plow / CARD_AUTHORING_GUIDE.md — no card rewards
    # declining the base plow; Lazy Sowman A94 rewards declining the sow, untouched here).
    return _can_plow_twice(p) and _liquidatable_to(state, idx, p, Resources(food=_FOOD_COST))


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
