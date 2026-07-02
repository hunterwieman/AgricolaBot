"""Chick Stable (minor improvement, B44; Bubulcus Expansion).

Card text: "Add 3 and 4 to the current round and place 2 food on each corresponding
round space. At the start of these rounds, you get the food."
Cost: "1 Wood/1 Clay" — an ALTERNATIVE cost (pay exactly ONE of 1 wood or 1 clay,
the Chophouse `alt_costs` pattern; the "/" is never a sum). No prerequisite.
VPs: 0. Not passing.

Category 8 (deferred goods). The whole effect runs at play (on_play): schedule
2 food onto the round spaces R+3 and R+4 (where R is the current round) of
`future_resources`, collected at the start of each of those rounds (in
`engine._complete_preparation`). Unlike Pond Hut's "next 3 round spaces"
(R+1..R+3), the two targets here are the SPECIFIC non-consecutive offsets +3 and
+4, so the explicit list [R+3, R+4] is used rather than a range. `schedule_resources`
clamps slots to 1..14 and silently drops any out-of-range round, so a late play
(where R+4 or both exceed 14) correctly forfeits the unreachable round space(s) per
"each corresponding round space".
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "chick_stable"


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    return schedule_resources(state, idx, [R + 3, R + 4], Resources(food=2))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1)),
    alt_costs=(Cost(resources=Resources(clay=1)),),
    on_play=_on_play,
)
