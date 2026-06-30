"""Feeding Dish (minor improvement, A66; Artifex Expansion; cost 1 wood).

Card text: "Each time you use an animal accumulation space while already having
an animal of that type, you get 1 grain."

Clarification on card: "Animal Dealer A147's effect can be used before this."
(Animal Dealer is a 3+ player occupation, out of 2-player scope, so the
interaction never arises here. It only confirms the BEFORE-phase ordering:
Feeding Dish evaluates the PRE-PURCHASE animal count.)

Category 3 (action-space hook, automatic income) on the three NON-atomic animal
markets (Sheep / Pig / Cattle Market). Like Milk Jug (and unlike Canoe's atomic
Fishing), the markets always push a host frame and fire `before_action_space`
from their `_initiate_*_market` handler, so no `register_action_space_hook` is
needed (that index only gates the conditional hosting of ATOMIC spaces).

Owner-gated (`any_player=False`): "each time YOU use a space" — fires only on the
acting owner's market turn. The check reads the player's animals at before-fire
time, which is the pre-purchase count: `_initiate_*_market` stages the bought
animals on the pending's `gained` field (NOT on the player) and fires
`before_action_space` BEFORE CommitAccommodate moves them onto the player. The
check is per-SPACE-type (Sheep Market -> sheep, Pig Market -> boar, Cattle
Market -> cattle), threshold >= 1 of that specific type, never total animals.
On-play is a no-op. See CARD_IMPLEMENTATION_PLAN.md Category 3.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "feeding_dish"

# Animal-market space id -> the Animals field that space type stocks.
_SPACE_ANIMAL = {
    "sheep_market":  "sheep",
    "pig_market":    "boar",
    "cattle_market": "cattle",
}


def _eligible(state: GameState, idx: int) -> bool:
    space_id = state.pending_stack[-1].space_id
    field = _SPACE_ANIMAL.get(space_id)
    if field is None:
        return False
    # Pre-purchase count: the bought animals are staged on the pending's `gained`,
    # not yet on the player, so player.animals is the holding before this use.
    return getattr(state.players[idx].animals, field) >= 1


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(grain=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register_auto("before_action_space", CARD_ID, _eligible, _apply)
