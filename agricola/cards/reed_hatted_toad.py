"""Reed-Hatted Toad (minor improvement, C78; Corbarius Expansion).

Card text: "Add 5, 7, 9, 11, and 13 to the current round and place 1 reed on each
corresponding round space. At the start of these rounds, you get the reed."
Cost: 1 Food. No prerequisite. VPs: 0. Not passing.
(Clarification: the card was named "Toad" in the Wizkids printing.)

Category 8 (deferred goods). The whole effect runs at play (on_play): the printed
numbers 5/7/9/11/13 are OFFSETS added to the current round R (exactly like Chick
Stable's "Add 3 and 4 to the current round" = [R+3, R+4]), so the scheduled round
spaces are R+5, R+7, R+9, R+11 and R+13. 1 reed is placed on each, collected at the
start of each of those rounds (in `engine._complete_preparation`). The offsets are
the specific non-consecutive list [R+5, R+7, R+9, R+11, R+13] rather than a range.
`schedule_resources` clamps slots to 1..14 and silently drops any out-of-range
round, so a late play (where the later offsets exceed 14) correctly forfeits the
unreachable round space(s) per "each corresponding round space".
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "reed_hatted_toad"


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    return schedule_resources(
        state, idx, [R + 5, R + 7, R + 9, R + 11, R + 13], Resources(reed=1))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=1)),
    on_play=_on_play,
)
