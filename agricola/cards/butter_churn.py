"""Butter Churn (minor improvement, B50; Base Revised; cost 1 wood, ≤3 occupations).

Card text: "In the field phase of each harvest, you get 1 food for every 3 sheep
and 1 food for every 2 cattle you have." Printed VPs: 1. Prerequisite: at most 3
occupations.

A during-window flat state-reader: the income reads the owner's own animals, not
what the crop take harvested, so it is a plain "field_phase" window auto
(HARVEST_WINDOWS_DESIGN.md §4d — flat state-readers are order-insensitive and
anchored pre-take). A MANDATORY, choice-free income → an automatic effect
(register_auto on the "field_phase" window event), fired by
`engine._field_phase_step` via `apply_auto_effects` before the mechanical crop
take, once per player per harvest.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
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
register_auto("field_phase", CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, "field_phase")
