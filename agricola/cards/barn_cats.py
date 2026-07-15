"""Barn Cats (minor improvement, E43; Ephipparius Expansion).

Card text: "If you have 1/2/3/4 stables, place 1 food on each of the next 2/3/4/5
round spaces. At the start of these rounds, you get the food."
Cost: none (free). Prerequisite: 1 Stable. VPs: 1. Not passing.

Category 8 (deferred goods), the Pond Hut shape. On play, +1 food is scheduled onto
each of the next N rounds (R+1..R+N relative to the current round), where
N = (stables built) + 1 — 1 stable maps to 2 rounds, 2->3, 3->4, 4->5. A player can
build at most 4 stables, so N is always in 2..5. Food rides on `future_resources`,
collected at each round's start by `engine._complete_preparation`. The "1 Stable"
prerequisite is the have-check that at least one stable is on the board (built).
"""
from __future__ import annotations

from agricola import helpers
from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "barn_cats"


def _prereq(state: GameState, idx: int) -> bool:
    return helpers.stables_built(state.players[idx].farmyard) >= 1


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    n_rounds = helpers.stables_built(state.players[idx].farmyard) + 1
    return schedule_resources(
        state, idx, range(R + 1, R + 1 + n_rounds), Resources(food=1))


register_minor(
    CARD_ID,
    prereq=_prereq,
    vps=1,
    on_play=_on_play,
)
