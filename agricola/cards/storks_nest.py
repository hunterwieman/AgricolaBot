"""Stork's Nest (minor improvement, D10; Consul Dirigens Expansion;
Farm Planner).

Card text (verbatim): "In the returning home phase of each round, if you have
more rooms than people, you can pay 1 food to take a "Family Growth" action."
Clarification (verbatim): "To clarify, this can only be used once per round."
Cost: 1 Reed. Prerequisite: "5 Occupations". No printed VPs.

TIMING — "in the returning home phase of each round" is the round-end ladder's
``returning_home`` window (user ruling 49, 2026-07-12,
``agricola/cards/round_end.py``: a distinct rung of the round-end ladder — the
same rung Silage / Ale-Benches use). Every round has a returning home phase, so
the effect is offered on all rounds. The printed "once per round" clarification
comes FREE from the window frame's ``triggers_resolved`` (one ``returning_home``
window per round, a fresh frame each round).

THE CONDITION — "if you have more rooms than people": ``people_total <
_num_rooms(p)`` — a free room for the newborn. This IS the standard
family-growth room gate; combined with the family cap ``people_total < 5`` (a
game rule the card does not waive) it is exactly the Autumn Mother eligibility
gate (and the Basic Wish for Children gate). The card does not waive the room
requirement.

THE GRANT — "you can pay 1 food to take a 'Family Growth' action" is an OPTIONAL
trigger ("you can"). Firing pays 1 food through the shared food-payment path
(the Ox Goad / Autumn Mother pattern): with 1 food on hand ``_apply`` debits it
and pushes the growth; short, it pushes a raise-only ``PendingFoodPayment``
whose ``resume_kind`` is this card id, and the registered resume debits the
raised food and pushes the growth. The growth is the card-granted primitive
``PendingFamilyGrowth(place_on_space=False)`` (Group A1 ruling 2026-07-03: the
newborn occupies NO action space — the commit increments people_total/newborns
only). Declining is the window's ``Proceed`` (no SkipTrigger). Eligibility gates
on BOTH the room condition AND the 1 food being payable-with-liquidation, so a
fired trigger is never a dead-end.

The newborn is a normal newborn: it grows up at the next RETURN_HOME like any
other. (On a harvest round the returning home phase precedes that harvest's
feeding, so the newborn feeds at the coming harvest — the engine's uniform
newborn rule.)

Prerequisite "5 Occupations" → ``min_occupations=5``; cost "1 Reed" →
``Cost(resources=Resources(reed=1))``.

Card-game only (ownership-gated registries; no CardStore): the Family game is
byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_minor
from agricola.cards.triggers import register
from agricola.legality import _liquidatable_to, _num_rooms
from agricola.pending import PendingFamilyGrowth, PendingFoodPayment, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "storks_nest"
_FOOD_COST = 1


def _pay_and_grow(state: GameState, idx: int) -> GameState:
    """Debit the 1 food, then grant the growth. Reached directly (food on hand)
    and as the post-food-payment continuation (the raise-only frame leaves the
    food in supply for this to debit)."""
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources - Resources(food=_FOOD_COST))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingFamilyGrowth(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}", place_on_space=False))


def _eligible(state: GameState, idx: int, _resolved: frozenset) -> bool:
    """"More rooms than people" (a free room) AND the family cap AND the 1 food
    payable (with liquidation) — never a dead-end. Ownership is the window
    machinery's gate; once-per-round is the frame's ``triggers_resolved`` (the
    printed clarification)."""
    p = state.players[idx]
    if not (p.people_total < 5 and p.people_total < _num_rooms(p)):
        return False
    return _liquidatable_to(state, idx, p, Resources(food=_FOOD_COST))


def _apply(state: GameState, idx: int) -> GameState:
    """Pay 1 food and grant the Family Growth. With food on hand, do it
    directly; otherwise push a raise-only ``PendingFoodPayment`` and defer the
    pay-and-grow to its resume. The 1 food is the only cost, so nothing is
    reserved."""
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_grow(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID, reserved=Cost(),
    ))


register_minor(CARD_ID, cost=Cost(resources=Resources(reed=1)), min_occupations=5)

# The optional once-per-round pay-1-food-for-a-family-growth on the round-end
# ladder's returning_home window (ruling 49); the 1 food rides the shared
# food-payment path.
register("returning_home", CARD_ID, _eligible, _apply)
register_food_payment_resume(CARD_ID, _pay_and_grow)
