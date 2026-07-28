"""Truffle Slicer (minor improvement, D39; Consul Dirigens Expansion; Points
Provider; cost 1 wood; prereq "Play in Round 8 or Later").

Card text: "Each time you use a wood accumulation space, if you have at least 1
wild boar, you can pay 1 food for 1 bonus point."

An OPTIONAL action-space trigger hosted on Forest — the only wood accumulation
space in the 2-player game (Copse / Grove are 3–4-player board-extension spaces,
never on the 2-player board). The trigger rides the `before_action_space` event:
the Wood Cutter ruling settles that a bare "each time you use [space]" fires
BEFORE the space's own wood pickup, not after — and the phase is immaterial here
anyway, since paying 1 food for 1 bonus point is independent of the +3 wood the
space grants. Optionality lives in the FireTrigger: declining is simply the host's
`Stop` (no SkipTrigger flag).

Firing pays 1 food for 1 BANKED bonus point:
  - The bonus point is stored in the per-card CardStore (vps=0 on the spec) and
    emitted by `register_scoring` at end-game — the same one-shot-points pattern
    Loppers / Big Country use, because the point is earned at fire time but only
    scored later. The count in the store is "how many times Truffle Slicer was
    used."

THE CONDITION — "if you have at least 1 wild boar" is a plain state read at
fire time (``p.animals.boar >= 1``); the boar is a condition, not a payment,
so it is never reserved.

THE PRICE — 1 food, paid through the shared food-payment path (ruling 82
(2026-07-26); corrected 2026-07-27): the at-any-time conversions are legal
payment routes for a food cost, so a plain food-on-hand gate would delete
rules-legal plays. Eligibility is liquidation-aware (``_liquidatable_to``);
with the food on hand ``_apply`` pays and banks directly, and when short it
pushes a raise-only ``PendingFoodPayment`` whose registered resume
(``_pay_and_bank``) debits the raised food and banks the point.

"Once per use" is automatic — `_apply_fire_trigger` stamps
`triggers_resolved | {card_id}` before applying, and `_eligible` reads it, so
the card fires at most once per Forest use. (It may, however, be used on every
separate Forest use over the game, hence the cumulative bank.)

Card-only state (the CardStore int + the per-frame `triggers_resolved`) defaults
canonically, so the Family game is byte-identical and the C++ gates are untouched.
See loppers.py (optional pay-for-a-banked-point shape), wood_cutter.py (the Forest
before_action_space host), cattle_feeder.py (the food-payment shape), and
CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_minor
from agricola.cards.triggers import register, register_action_space_hook
from agricola.constants import WOOD_ACCUMULATION_SPACES
from agricola.legality import _liquidatable_to
from agricola.pending import PendingFoodPayment, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "truffle_slicer"
_FOOD_COST = 1


def _prereq(state: GameState, idx: int) -> bool:
    """Prerequisite: "Play in Round 8 or Later"."""
    return state.round_number >= 8


def _pay_and_bank(state: GameState, idx: int) -> GameState:
    """Debit 1 food and bank 1 bonus point. Reached directly (food on hand) and
    as the post-food-payment resume (the raise-only frame leaves the raised
    food in supply for this to debit)."""
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
    """Offer the pay-1-food-for-1-point exchange only on a wood-accumulation-space
    use, when the player has a wild boar (the printed condition, read at fire
    time) and the 1 food is payable — directly or by liquidating convertible
    goods — and it has not already fired this use."""
    if CARD_ID in triggers_resolved:                        # once per forest use
        return False
    if state.pending_stack[-1].space_id not in WOOD_ACCUMULATION_SPACES:
        return False
    p = state.players[idx]
    if p.animals.boar < 1:
        return False
    return _liquidatable_to(state, idx, p, Resources(food=_FOOD_COST))


def _apply(state: GameState, idx: int) -> GameState:
    """Pay 1 food for 1 banked bonus point. With the food on hand, directly;
    otherwise push a raise-only PendingFoodPayment and defer to its resume
    (which debits the raised food). The 1 food is the card's only cost, so
    nothing is reserved."""
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_bank(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID,
        reserved=Cost(),
    ))


def _score(state: GameState, idx: int) -> int:
    # 1 bonus point per time the card was used (banked at fire time).
    return state.players[idx].card_state.get(CARD_ID, 0)


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), prereq=_prereq, vps=0)
register("before_action_space", CARD_ID, _eligible, _apply)
register_food_payment_resume(CARD_ID, _pay_and_bank)
register_action_space_hook(CARD_ID, WOOD_ACCUMULATION_SPACES)
register_scoring(CARD_ID, _score)
