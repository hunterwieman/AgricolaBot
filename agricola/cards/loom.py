"""Loom (minor improvement, B39; Base Revised; cost 2 wood, 2-occupation prereq).

Card text: "In the field phase of each harvest, if you have at least 1/4/7 sheep,
you get 1/2/3 food. During scoring, you get 1 bonus point for every 3 sheep."
Printed VPs: 1. Prerequisite: 2 occupations.

A during-window flat state-reader + a Category 1 scoring term. The field-phase
clause reads the owner's own sheep, not what the crop take harvested, so it is a
plain "field_phase" window auto (HARVEST_WINDOWS_DESIGN.md §4d — flat
state-readers are order-insensitive and anchored pre-take): a MANDATORY,
choice-free income → an automatic effect (register_auto on the "field_phase"
window event), fired by `engine._field_phase_step` via `apply_auto_effects`
before the mechanical crop take, once per player per harvest. The scoring clause
is a pure derived read of the owner's sheep.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
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


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2)), min_occupations=2, vps=1)
register_auto("field_phase", CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, "field_phase")
register_scoring(CARD_ID, _score)
