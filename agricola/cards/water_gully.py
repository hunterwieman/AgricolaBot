"""Water Gully (minor improvement, E42; Ephipparius Expansion; cost 1 stone).

Card text (verbatim): "Place 1 cattle, 1 grain, and 1 cattle on the next 3 round
spaces (in that order). At the start of these rounds, you get the respective
good."
Prerequisite: the "Well" Major Improvement. No printed VPs.

Category 8 (deferred goods), the mixed animal/resource variant: the next 3 round
spaces (R+1..R+3) get cattle, grain, cattle in order. The cattle ride on the
card-only `future_rewards` (`schedule_animals`, reconciled by the accommodation
barrier at round start if they overflow); the grain rides on `future_resources`
(`schedule_resources`). Out-of-game rounds are dropped by the helpers.

Prerequisite "'Well' Major Improvement" — a HAVE-check that the player currently
owns the Well (major index 4): `major_improvement_owners[4] == idx`.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_animals, schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Animals, Cost, Resources
from agricola.state import GameState

CARD_ID = "water_gully"
_WELL_MAJOR_IDX = 4


def _prereq(state: GameState, idx: int) -> bool:
    return state.board.major_improvement_owners[_WELL_MAJOR_IDX] == idx


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    state = schedule_animals(state, idx, (R + 1,), Animals(cattle=1))
    state = schedule_resources(state, idx, (R + 2,), Resources(grain=1))
    state = schedule_animals(state, idx, (R + 3,), Animals(cattle=1))
    return state


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(stone=1)),
    prereq=_prereq,
    on_play=_on_play,
)
