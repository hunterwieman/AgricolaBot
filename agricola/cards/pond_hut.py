"""Pond Hut (minor improvement, A44; Base Revised).

Card text: "Place 1 food on each of the next 3 round spaces. At the start of these
rounds, you get the food."
Cost: 1 Wood. Prerequisite: Exactly 2 Occupations. VPs: 1. Not passing.

Category 8 (deferred goods). The whole effect runs at play (on_play): schedule
1 food onto the next 3 round spaces (rounds R+1..R+3) of `future_resources`. The
"exactly 2 occupations" prerequisite is the occupation-count bound min==max==2.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "pond_hut"


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    return schedule_resources(state, idx, range(R + 1, R + 4), Resources(food=1))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1)),
    min_occupations=2,
    max_occupations=2,   # "Exactly 2 Occupations"
    vps=1,
    on_play=_on_play,
)
