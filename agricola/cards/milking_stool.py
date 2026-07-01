"""Milking Stool (minor improvement, D38; Consul Dirigens; cost 1 wood, 2-occupation prereq).

Card text: "In the field phase of each harvest, if you have at least 1/3/5 cattle,
you get 1/2/3 food. During scoring, you get 1 bonus point for every 2 cattle you
have." Printed VPs: 0 (all victory points come from the cattle scoring term).
Prerequisite: 2 occupations.

Cattle analog of Loom/Butter Churn. Two DISTINCT cattle tables that must not be
conflated: the FIELD-phase food tiers step at >=1 / >=3 / >=5 cattle -> 1 / 2 / 3
food, while SCORING is a separate `cattle // 2` (so e.g. 6 cattle -> +3 food at a
harvest, +3 VP at scoring).

Category 6 (harvest-field hook) + a Category 1 scoring term. The field-phase
clause is a MANDATORY, choice-free income -> an automatic effect (register_auto on
the `harvest_field` event), fired by `_resolve_harvest_field` before the
mechanical crop take. The scoring clause is a pure derived read of the owner's
cattle. See CARD_IMPLEMENTATION_PLAN.md Category 6.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto, register_harvest_field_hook
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "milking_stool"


def _eligible(state: GameState, idx: int) -> bool:
    return True   # always fires; <1 cattle simply yields 0 food (apply is a no-op)


def _apply(state: GameState, idx: int) -> GameState:
    cattle = state.players[idx].animals.cattle
    food = 3 if cattle >= 5 else 2 if cattle >= 3 else 1 if cattle >= 1 else 0
    if food == 0:
        return state
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=food))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    return state.players[idx].animals.cattle // 2   # 1 bonus point per 2 cattle


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), min_occupations=2, vps=0)
register_auto("harvest_field", CARD_ID, _eligible, _apply)
register_harvest_field_hook(CARD_ID)
register_scoring(CARD_ID, _score)
