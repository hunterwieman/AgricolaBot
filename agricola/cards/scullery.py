"""Scullery (minor improvement, B57; Base Revised; cost 1 wood + 1 clay).

Card text: "At the start of each round, if you live in a wooden house, you get
1 food."
Printed VPs: none (null). Prerequisite: none. Not a passing minor.

Category 7 (start-of-round phase hook). The clause is a MANDATORY, choice-free
income gated on a wooden house → an automatic effect (`register_auto` on the
`start_of_round` event), fired mechanically by the preparation walk for the owner. The
wooden-house condition is re-checked each round, so the income stops once the
player renovates to clay/stone. See CARD_IMPLEMENTATION_PLAN.md Category 7.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.constants import HouseMaterial
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "scullery"


def _eligible(state: GameState, idx: int) -> bool:
    return state.players[idx].house_material is HouseMaterial.WOOD


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1, clay=1)))
register_auto("start_of_round", CARD_ID, _eligible, _apply)
