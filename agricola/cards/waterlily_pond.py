"""Waterlily Pond (minor improvement, E46; Ephipparius Expansion).

Card text: "Place 1 food on each of the next 2 round spaces. At the start of these
rounds, you get the food."
Cost: none (free). Prerequisite: Exactly 2 Occupations. VPs: 1. Not passing.

Category 8 (deferred goods), the Pond Hut shape. On play, +1 food is scheduled onto
each of the next 2 rounds (R+1, R+2 relative to the current round), riding on
`future_resources` and collected at each round's start by
`engine._complete_preparation`. The "Exactly 2 Occupations" prerequisite is the
occupation-count bound min == max == 2.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "waterlily_pond"


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    return schedule_resources(state, idx, range(R + 1, R + 3), Resources(food=1))


register_minor(
    CARD_ID,
    min_occupations=2,
    max_occupations=2,   # "Exactly 2 Occupations"
    vps=1,
    on_play=_on_play,
)
