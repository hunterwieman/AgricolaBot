"""Wool Blankets (minor improvement, A38; Base Revised; prereq 5 sheep, no cost).

Card text: "During scoring, if you live in a wooden/clay/stone house by then, you
get 3/2/0 bonus points." Prerequisite: 5 Sheep (a HAVE-check to play it, never
spent). No printed VPs.

Category 1 (end-game scoring) — a pure derived read of house material. Kept when
played; the scoring term fires for the owner. The 5-sheep prerequisite is a
custom (non-occupation-count) predicate. See CARD_IMPLEMENTATION_PLAN.md Category 1.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import HouseMaterial
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "wool_blankets"

_POINTS_BY_MATERIAL = {
    HouseMaterial.WOOD: 3,
    HouseMaterial.CLAY: 2,
    HouseMaterial.STONE: 0,
}


def _score(state: GameState, idx: int) -> int:
    return _POINTS_BY_MATERIAL[state.players[idx].house_material]


def _prereq_five_sheep(state: GameState, idx: int) -> bool:
    return state.players[idx].animals.sheep >= 5


register_minor(CARD_ID, prereq=_prereq_five_sheep)   # no cost
register_scoring(CARD_ID, _score)
