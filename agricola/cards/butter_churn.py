"""Butter Churn (minor improvement, B50; Base Revised; cost 1 wood, ≤3 occupations).

Card text: "In the field phase of each harvest, you get 1 food for every 3 sheep
and 1 food for every 2 cattle you have." Printed VPs: 1. Prerequisite: at most 3
occupations.

Category 6 (harvest-field hook). A MANDATORY, choice-free income → an automatic
effect (register_auto on the `harvest_field` event), fired by
`_resolve_harvest_field` before the mechanical crop take. See
CARD_IMPLEMENTATION_PLAN.md Category 6.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto, register_harvest_field_hook
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "butter_churn"


def _eligible(state: GameState, idx: int) -> bool:
    return True


def _apply(state: GameState, idx: int) -> GameState:
    animals = state.players[idx].animals
    food = animals.sheep // 3 + animals.cattle // 2
    if food == 0:
        return state
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=food))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), max_occupations=3, vps=1)
register_auto("harvest_field", CARD_ID, _eligible, _apply)
register_harvest_field_hook(CARD_ID)
