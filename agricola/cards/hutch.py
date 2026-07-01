"""Hutch (minor improvement, D43; Consul Dirigens expansion).

Card text: "Place 0, 1, 2, and 3 food in this order on the next 4 round spaces. At
the start of these rounds, you get the food."
Cost: 1 Wood, 1 Reed. VPs: 1. No prerequisite. Not passing.

Category 8 (deferred goods). On play, schedule increasing food on the next four
round spaces in order: 0 food on round R+1 (the very next round — a genuine no-op),
1 food on R+2, 2 food on R+3, 3 food on R+4 (R = current round_number). The food
rides on the Family-reachable `future_resources` schedule and is collected at the
start of each scheduled round (`engine._complete_preparation`).

This differs from Strawberry Patch / Pond Hut, which place a FLAT amount across
their rounds; Hutch's amount increases with the round (amount k -> round R+1+k for
k in 0..3). `schedule_resources` clamps rounds past 14 (or already entered), so a
late-game play silently drops the overflow slots.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "hutch"


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    # Amounts 0,1,2,3 on rounds R+1,R+2,R+3,R+4 (k -> round R+1+k). The 0-food slot
    # is a no-op, so only schedule k = 1,2,3.
    for k in (1, 2, 3):
        state = schedule_resources(state, idx, (R + 1 + k,), Resources(food=k))
    return state


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1, reed=1)),
    vps=1,
    on_play=_on_play,
)
