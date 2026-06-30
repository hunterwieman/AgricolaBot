"""Clay Supply (minor improvement, C77; Corbarius Expansion).

Card text: "Place 1 clay on each of the next 3 round spaces. At the start of these
rounds, you get the clay."
Cost: 1 Food. No prerequisite. VPs: none. Not passing.

Category 8 (deferred goods), the Lumberjack shape with a fixed relative window of 3.
On play, +1 clay is scheduled onto each of the NEXT 3 round spaces — rounds R+1,
R+2, R+3 (R = the current round). The current round R is excluded: its round-space
goods were already collected when round R was entered, so "next 3 round spaces"
starts at R+1 (`range(R + 1, R + 1 + 3)`, exactly as Lumberjack uses `R+1`).

The clay rides on `PlayerState.future_resources` and is collected at the start of
each scheduled round by `engine._complete_preparation`. `schedule_resources` writes
slot `r-1` (the engine's Well index convention) and silently drops any round > 14,
so a late-game play (e.g. R = 13 → rounds 14, 15, 16) places clay on fewer than 3
spaces ("the next round spaces" that still exist). Clay always fits (no
accommodation), so there is no capacity concern.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "clay_supply"
_N_ROUNDS = 3


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    return schedule_resources(
        state, idx, range(R + 1, R + 1 + _N_ROUNDS), Resources(clay=1)
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=1)),
    on_play=_on_play,
)
