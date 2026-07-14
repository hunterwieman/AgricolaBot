"""Curator (occupation, A100; Artifex Expansion; players 1+).

Card text: "In the returning home phase of each round, if you return at least 3
people from accumulation spaces, you can buy 1 bonus point for 1 food."
Category: Points Provider. No printed VPs.

TIMING — "in the returning home phase" is the round-end ladder's
``returning_home`` window (ruling 49, 2026-07-12; ``agricola/cards/round_end.py``).
That rung fires PRE-reset — the still-placed board is the event data — which is
exactly what "you return at least 3 people from accumulation spaces" needs: the
condition reads this player's live worker counts on the accumulation spaces at
the moment everyone walks home. The accumulation-space category is the
player-count/mode-aware accessor ``helpers.accumulation_spaces(state)`` (the
same set Wood Pile / Hand Truck / Steam Machine quantify over).

THE PURCHASE — "you CAN buy" → an OPTIONAL trigger (``register``, never an
auto); "1 bonus point" (singular) → at most once per returning-home phase,
which the window frame's ``triggers_resolved`` gives structurally (one
``returning_home`` frame per round, stamped on fire). No immediate-VP mechanism
exists, so the point BANKS in the per-card CardStore counter and a
``register_scoring`` term reads it back at end-game (the Clay Deposit /
Swimming Class banked-VP idiom); the bank accumulates across rounds.

THE FOOD — the 1 food is paid through the shared food-payment path
(FOOD_PAYMENT_DESIGN.md), exactly like Plow Driver's 1-food plow: with the food
on hand ``_apply`` debits and banks directly; short, it pushes a raise-only
``PendingFoodPayment`` whose resume (registered under this card id) debits the
raised food and banks. Eligibility is liquidation-aware (``_liquidatable_to``),
so a player who can cook a good into the food is offered the buy.

Card-game only (ownership-gated registries; the Family game never registers),
so the Family trace and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_occupation
from agricola.cards.triggers import register
from agricola.helpers import accumulation_spaces
from agricola.legality import _liquidatable_to
from agricola.pending import PendingFoodPayment, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState, get_space

CARD_ID = "curator"
_FOOD_COST = 1


def _returners_from_accumulation(state: GameState, idx: int) -> int:
    """This player's people still placed on accumulation spaces — at the
    pre-reset ``returning_home`` window these are exactly the people about to
    return home from them."""
    return sum(get_space(state.board, sid).workers[idx]
               for sid in accumulation_spaces(state))


def _pay_and_bank(state: GameState, idx: int) -> GameState:
    """Debit 1 food and bank 1 bonus point. Reached directly (food on hand) and
    as the post-food-payment resume (the raise-only frame leaves the raised food
    in supply for this to debit)."""
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources - Resources(food=_FOOD_COST),
        card_state=p.card_state.set(CARD_ID, p.card_state.get(CARD_ID, 0) + 1),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    """≥3 of this player's people are returning from accumulation spaces, and
    the 1 food is payable (directly or by liquidating convertible goods).
    Once-per-window comes from the frame's ``triggers_resolved`` stamp."""
    if CARD_ID in triggers_resolved:
        return False
    if _returners_from_accumulation(state, idx) < 3:
        return False
    return _liquidatable_to(state, idx, state.players[idx],
                            Resources(food=_FOOD_COST))


def _apply(state: GameState, idx: int) -> GameState:
    """Buy the point. With the food on hand, directly; otherwise push a
    raise-only PendingFoodPayment and defer to its resume (which debits the
    raised food). The only cost is the 1 food, so nothing is reserved."""
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_bank(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID,
        reserved=Cost(),
    ))


def _score(state: GameState, idx: int) -> int:
    return state.players[idx].card_state.get(CARD_ID, 0)


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("returning_home", CARD_ID, _eligible, _apply)
register_food_payment_resume(CARD_ID, _pay_and_bank)
register_scoring(CARD_ID, _score)
