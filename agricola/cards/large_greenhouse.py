"""Large Greenhouse (minor improvement, A69; Base Revised).

Card text: "Add 4, 7, and 9 to the current round and place 1 vegetable on each
corresponding round space. At the start of these rounds, you get the vegetable."
Cost: 2 Wood. Prerequisite: 2 Occupations. VPs: none. Not passing.

Category 8 (deferred goods). "Add 4, 7, and 9 to the current round" → schedule
1 vegetable onto rounds R+4, R+7, R+9 (1-indexed) of `future_resources`; any that
fall beyond round 14 are dropped by schedule_resources. "2 Occupations" is the
occupation-count bound min=2 (at least 2).
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "large_greenhouse"


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    return schedule_resources(state, idx, (R + 4, R + 7, R + 9), Resources(veg=1))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=2)),
    min_occupations=2,
    on_play=_on_play,
)
