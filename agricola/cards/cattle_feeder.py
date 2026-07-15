"""Cattle Feeder (occupation, B166; Base Revised; players 4+).

Card text (verbatim): "Each time you use the 'Grain Seeds' action space, you can
also buy 1 cattle for 1 food."
No cost / prerequisite / passing / printed VPs.

TIMING — "Each time you use ... you can also ..." → the trigger-timing ruling
puts a bare "each time you use [space]" in the BEFORE window
(``before_action_space``). The reward is FLAT (1 cattle for 1 food, independent
of what Grain Seeds produced), so before is correct. Grain Seeds is an atomic
space, so ``register_action_space_hook`` hosts it — the ``before_action_space``
frame the trigger attaches to only exists once this card is owned.

FIRING KIND — "you can also buy ..." is OPTIONAL → an optional trigger
(``register``, not ``register_auto``); not firing is the host's Proceed. Once per
use via the host frame's ``triggers_resolved``.

THE PRICE — 1 food, paid through the shared food-payment path (the Plow Driver /
Sugar Baker idiom): a food cost in Agricola may be raised by converting
crops/animals, so gating on food-on-hand alone would narrow the printed
legality. Eligibility is therefore liquidation-aware (``_liquidatable_to``); with
food on hand ``_apply`` pays and grants directly, and when short it pushes a
raise-only ``PendingFoodPayment`` whose registered resume (``_pay_and_grant``)
debits the raised food and grants. The food is not a resource Grain Seeds needs,
so firing before the take strands nothing.

THE ANIMAL — 1 cattle via ``helpers.grant_animals`` (add + flag), so an
over-capacity buy reconciles through the accommodation barrier at the next
decision boundary; never a raw ``p.animals + ...``.

Card-game only (ownership-gated registries; grant_animals' card-only flag is
default-skipped): the Family game is byte-identical and the C++ gates are
untouched. Played via Lessons; on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_occupation
from agricola.cards.triggers import register, register_action_space_hook
from agricola.helpers import grant_animals
from agricola.legality import _liquidatable_to
from agricola.pending import PendingFoodPayment, push
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.state import GameState

CARD_ID = "cattle_feeder"
_SPACES = frozenset({"grain_seeds"})
_FOOD_COST = 1


def _pay_and_grant(state: GameState, idx: int) -> GameState:
    """Debit 1 food and grant 1 cattle. Reached directly (food on hand) and as
    the post-food-payment resume (the raise-only frame leaves the food in supply
    for this to debit). Cattle Feeder's only cost is the 1 food, so nothing is
    reserved."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(food=_FOOD_COST))
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    return grant_animals(state, idx, Animals(cattle=1))


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per use
        return False
    if getattr(state.pending_stack[-1], "space_id", None) not in _SPACES:
        return False
    return _liquidatable_to(state, idx, state.players[idx],
                            Resources(food=_FOOD_COST))


def _apply(state: GameState, idx: int) -> GameState:
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_grant(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID,
        reserved=Cost(),
    ))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("before_action_space", CARD_ID, _eligible, _apply)
register_food_payment_resume(CARD_ID, _pay_and_grant)
register_action_space_hook(CARD_ID, _SPACES)
