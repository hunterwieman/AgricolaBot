"""Loom (minor improvement, B39; Base Revised; cost 1 wood, 2-occupation prereq).

Card text: "In the field phase of each harvest, if you have at least 1/4/7 sheep,
you get 1/2/3 food. During scoring, you get 1 bonus point for every 3 sheep."
Printed VPs: 1. Prerequisite: 2 occupations.

Category 6 (harvest-field hook) + a Category 1 scoring term. The field-phase
clause is a MANDATORY, choice-free income → an automatic effect (register_auto on
the `harvest_field` event), fired by `_resolve_harvest_field` before the
mechanical crop take. The scoring clause is a pure derived read of the owner's
sheep. See CARD_IMPLEMENTATION_PLAN.md Category 6.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto, register_harvest_field_hook
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "loom"


def _eligible(state: GameState, idx: int) -> bool:
    return True   # always fires; 0 sheep simply yields 0 food (apply is a no-op)


def _apply(state: GameState, idx: int) -> GameState:
    sheep = state.players[idx].animals.sheep
    food = 3 if sheep >= 7 else 2 if sheep >= 4 else 1 if sheep >= 1 else 0
    if food == 0:
        return state
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=food))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    return state.players[idx].animals.sheep // 3   # 1 bonus point per 3 sheep


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), min_occupations=2, vps=1)
register_auto("harvest_field", CARD_ID, _eligible, _apply)
register_harvest_field_hook(CARD_ID)
register_scoring(CARD_ID, _score)
