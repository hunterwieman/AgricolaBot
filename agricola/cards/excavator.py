"""Excavator (occupation, C126; Consul Dirigens Expansion; players 1+).

Card text: "Each time after you use the 'Day Laborer' action space, you get 1
additional wood and clay, and you can buy 1 stone for 1 food."
Clarification: "These resources may not be used to pay for the effect of the
Cottager B087."

Two coexisting effects on the one Day Laborer host's after-phase (the `after_action_space`
event — the text's "each time AFTER you use" is the explicit "immediately after"
exception to the default "each time you use [space]" = before ruling, confirmed by Wood
Cutter / Clay Puncher / Carpenter's Axe):

  - +1 wood and +1 clay — choiceless income → a MANDATORY automatic effect
    (`register_auto`, applied directly at the after-phase flip, never surfaced to the
    agent).

  - buy 1 stone for 1 food — a player CHOICE ("you can buy") → an OPTIONAL FireTrigger
    (`register`, not `register_auto`). Declining is simply not firing it (the host's Stop
    exits the after-phase). "Each time" = once per use, enforced by `CARD_ID not in
    triggers_resolved`. The 1 food rides the shared food-payment path (ruling 82
    (2026-07-26); corrected 2026-07-27): the at-any-time conversions are legal payment
    routes for a food cost, so a plain food-on-hand gate would delete rules-legal plays.
    Eligibility is liquidation-aware (`_liquidatable_to`); with the food on hand
    `_apply_buy` pays and grants directly, and when short it pushes a raise-only
    `PendingFoodPayment` whose registered resume (`_pay_and_buy`) debits the raised
    food and grants the stone.

Day Laborer is an ATOMIC action space, so it must be explicitly hosted
(`register_action_space_hook`) to push a PendingActionSpace frame whose Proceed runs Day
Laborer's own pickup first, then flips to the after-phase where the auto fires and the
optional FireTrigger is surfaced.

The clarification ("these resources may not be used to pay for the Cottager B087") is
enforced FOR FREE by the before/after timing split: Cottager fires on
`before_action_space`, so its build/renovate resolves BEFORE this card's after-phase
grants exist. No code is needed for the cross-card constraint.

No on-play effect, no cost / prereq / VPs.
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_occupation
from agricola.cards.triggers import register, register_action_space_hook, register_auto
from agricola.legality import _liquidatable_to
from agricola.pending import PendingFoodPayment, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "excavator"

# The single space whose AFTER-use grants the wood/clay income + offers the stone buy.
EXCAVATOR_SPACES = frozenset({"day_laborer"})

_FOOD_COST = 1  # for the optional 1-stone purchase


def _set_player(state: GameState, idx: int, p) -> GameState:
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Mandatory: +1 wood and +1 clay (choiceless → register_auto)
# ---------------------------------------------------------------------------

def _eligible_auto(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in EXCAVATOR_SPACES


def _apply_auto(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    return _set_player(state, idx,
                       fast_replace(p, resources=p.resources + Resources(wood=1, clay=1)))


# ---------------------------------------------------------------------------
# Optional: buy 1 stone for 1 food (player choice → register FireTrigger)
# ---------------------------------------------------------------------------

def _pay_and_buy(state: GameState, idx: int) -> GameState:
    """Debit 1 food and grant 1 stone. Reached directly (food on hand) and as
    the post-food-payment resume (the raise-only frame leaves the food in
    supply for this to debit)."""
    p = state.players[idx]
    return _set_player(state, idx,
                       fast_replace(p, resources=p.resources + Resources(food=-_FOOD_COST, stone=1)))


def _eligible_buy(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per use
        return False
    if state.pending_stack[-1].space_id not in EXCAVATOR_SPACES:
        return False
    # Payable outright or by liquidating convertible goods to the 1 food.
    return _liquidatable_to(state, idx, state.players[idx],
                            Resources(food=_FOOD_COST))


def _apply_buy(state: GameState, idx: int) -> GameState:
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_buy(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID,
        reserved=Cost(),
    ))


register_occupation(CARD_ID, lambda s, i: s)               # no on-play effect
register_auto("after_action_space", CARD_ID, _eligible_auto, _apply_auto)
register("after_action_space", CARD_ID, _eligible_buy, _apply_buy)
register_food_payment_resume(CARD_ID, _pay_and_buy)
register_action_space_hook(CARD_ID, EXCAVATOR_SPACES)      # atomic Day Laborer host
