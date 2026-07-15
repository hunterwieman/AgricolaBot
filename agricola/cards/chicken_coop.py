"""Chicken Coop (minor improvement, C44; Consul Dirigens Expansion).

Card text: "Place 1 food on each of the next 8 round spaces. At the start of these
rounds, you get the food."
Cost: 2 Wood/2 Clay, 1 Reed. Prerequisite: none. VPs: 1. Not passing.

Category 8 (deferred goods), the Pond Hut shape. On play, +1 food is scheduled onto
each of the next 8 rounds (R+1..R+8 relative to the current round), riding on
`future_resources` and collected at each round's start by
`engine._complete_preparation`. The "/" in the cost is an ALTERNATIVE (2 Wood OR 2
Clay); the ",1 Reed" is added to BOTH payment options — modeled as the base cost
`Cost(wood=2, reed=1)` plus one `alt_costs` member `Cost(clay=2, reed=1)`.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "chicken_coop"


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    return schedule_resources(state, idx, range(R + 1, R + 9), Resources(food=1))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=2, reed=1)),
    alt_costs=(Cost(resources=Resources(clay=2, reed=1)),),
    vps=1,
    on_play=_on_play,
)
