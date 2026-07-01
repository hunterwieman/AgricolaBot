"""Reap Hook (minor improvement, D67; Dulcinaria Expansion; Crop Provider).

Card text: "Place 1 grain on each of the next 3 of the round spaces 4, 7, 9, 11,
13, and 14. At the start of these rounds, you get the grain."
Cost: 1 Wood. No prerequisite. VPs: none. Not passing.

Category 8 (deferred goods on future round spaces; CARD_IMPLEMENTATION_PLAN.md
§II.5). The "next 3" are the next 3 ENTRIES of the specific list {4, 7, 9, 11,
13, 14} strictly after the current round — NOT the literal next 3 rounds
(R+1, R+2, R+3), and NOT all remaining entries of the list (that is Sack Cart's
"remaining"). Filter the list to entries `> R`, then take the first 3.

`> R` (strictly greater) mirrors Sack Cart: a round whose space has already been
collected (the current round has been entered) must not be scheduled, or
`schedule_resources` would write a slot that is never paid out (or double-pay if
the current round's payout has not yet fired). The 1 grain lands on each of those
rounds in the player's `future_resources` schedule, collected at the start of each
scheduled round (in `engine._complete_preparation`). `schedule_resources` is
additive and silently drops any round outside 1..14, so a late-game play simply
places fewer grain (e.g. played after round 13, only round 14 remains).
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "reap_hook"
_ROUND_SPACES = (4, 7, 9, 11, 13, 14)


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    rounds = [rnd for rnd in _ROUND_SPACES if rnd > R][:3]
    return schedule_resources(state, idx, rounds, Resources(grain=1))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1)),
    on_play=_on_play,
)
