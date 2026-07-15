"""Fruit Ladder (minor improvement, E45; Ephipparius Expansion).

Card text: "Place 1 food on each remaining even-numbered round space. At the start of
these rounds, you get the food."
Cost: 2 Wood. Prerequisite: none. VPs: 1. Not passing.

Category 8 (deferred goods), the Pond Hut shape. On play, +1 food is scheduled onto
each remaining EVEN-numbered round space — the even rounds strictly after the current
round (from rounds 2, 4, 6, 8, 10, 12, 14, only those > R). Food rides on
`future_resources`, collected at each round's start by `engine._complete_preparation`.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "fruit_ladder"


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    rounds = [r for r in range(R + 1, 15) if r % 2 == 0]
    return schedule_resources(state, idx, rounds, Resources(food=1))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=2)),
    vps=1,
    on_play=_on_play,
)
