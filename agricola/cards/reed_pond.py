"""Reed Pond (minor improvement, D78; Consul Dirigens Expansion).

Card text: "Place 1 reed on each of the next 3 round spaces. At the start of these
rounds, you get the reed."
Cost: none (free). Prerequisite: 3 Occupations. VPs: none. Not passing.

Category 8 (deferred goods), the Pond Hut shape. The whole effect runs at play
(on_play): schedule 1 reed onto the NEXT 3 round spaces — rounds R+1, R+2, R+3,
RELATIVE to the current round (unlike Reed Belt / Sack Cart, whose rounds are
absolute board numbers). The promise rides on `future_resources` and is collected
at the start of each scheduled round by `engine._complete_preparation`.

`schedule_resources` clamps slots to the 14-round game, so a late play silently
forfeits any of the next-3 rounds that fall past round 14 (matching "each of the
next 3 round spaces"). The "3 Occupations" prerequisite is "at least 3" — the
occupation-count lower bound `min_occupations=3` with NO upper bound.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "reed_pond"


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    return schedule_resources(state, idx, range(R + 1, R + 4), Resources(reed=1))


register_minor(
    CARD_ID,
    cost=Cost(),            # free
    min_occupations=3,      # "3 Occupations" = at least 3 (no upper bound)
    on_play=_on_play,
)
