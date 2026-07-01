"""Club House (minor improvement, B46; Bubulcus Expansion; Food Provider).

Card text: "Place 1 food on each of the next 4 round spaces and 1 stone on the
round space after that. At the start of these rounds, you get the respective
good."
Cost: 3 Wood / 2 Clay. No prerequisite. VPs: 1. Not passing.

Category 8 (deferred goods on future round spaces; CARD_IMPLEMENTATION_PLAN.md
§II.5). Two deferred placements, both onto the player's `future_resources`
schedule (collected at the start of each scheduled round in
`engine._complete_preparation`):

1. **1 food on each of the next 4 round spaces** — rounds R+1, R+2, R+3, R+4
   (R = current round). The range is `range(R + 1, R + 5)` (EXCLUSIVE upper
   bound). Food lands on rounds AFTER the current one, never the current round's
   slot.
2. **1 stone on the round space after that** — the SINGLE round R+5.

`schedule_resources` is additive (each placement stacks on the same slot) and
silently drops any round outside 1..14, so a late-game play places fewer goods
("each of the next ... round spaces" / the remaining spaces) with no manual
bounds check. The two calls compose: each reads `state.players[idx]` fresh.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "club_house"


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    # 1 food on each of the next 4 round spaces (R+1 .. R+4).
    state = schedule_resources(state, idx, range(R + 1, R + 5), Resources(food=1))
    # 1 stone on the round space after that (R+5, a single round).
    return schedule_resources(state, idx, [R + 5], Resources(stone=1))


# Cost is "3 Wood / 2 Clay" — an ALTERNATIVE ("/") cost: pay EITHER 3 wood OR 2 clay,
# not both. The printed 3-wood cost is `cost`; the 2-clay alternative rides on
# `alt_costs`. The play path enumerates one CommitPlayMinor per affordable alternative.
register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=3)),
    alt_costs=(Cost(resources=Resources(clay=2)),),
    vps=1,
    on_play=_on_play,
)
