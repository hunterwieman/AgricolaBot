"""Estate Worker (occupation, B125; Bubulcus Expansion; players 1+).

Card text: "Place 1 wood, 1 clay, 1 reed, and 1 stone in this order on the next 4
round spaces. At the start of these rounds, you get the respective building
resource."

Category 8 (deferred goods on round spaces). One building resource is placed per
round, mapped POSITIONALLY: wood on the 1st of the next 4 round spaces (round R+1),
clay on R+2, reed on R+3, stone on R+4. Each is collected at the START of its round
(in `engine._complete_preparation`). This is NOT the same-good-on-all-4 shape of
Wall Builder — each round carries a different single good.

`schedule_resources` uses 1-indexed rounds and silently drops any round > 14, so a
late play places only on the next round spaces that still exist ("the next 4 round
spaces"). Played via Lessons; the on-play schedule IS the effect. No cost / prereq /
vps / passing — all defaults.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_occupation
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "estate_worker"


def _on_play(state: GameState, idx: int) -> GameState:
    # "In this order on the next 4 round spaces": one good per round, positionally
    # mapped wood→R+1, clay→R+2, reed→R+3, stone→R+4. Thread the returned state
    # through each single-good placement.
    R = state.round_number
    state = schedule_resources(state, idx, (R + 1,), Resources(wood=1))
    state = schedule_resources(state, idx, (R + 2,), Resources(clay=1))
    state = schedule_resources(state, idx, (R + 3,), Resources(reed=1))
    state = schedule_resources(state, idx, (R + 4,), Resources(stone=1))
    return state


register_occupation(CARD_ID, _on_play)
