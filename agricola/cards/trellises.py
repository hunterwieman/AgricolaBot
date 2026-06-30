"""Trellises (minor improvement, A47; Artifex Expansion).

Card text: "Immediately place 1 food on each of the next round spaces, up to the
number of fences you have built. At the start of these rounds, you get the food."
Cost: 1 Wood. No prerequisite. VPs: 0. Not passing.

Category 8 (deferred goods). The whole effect runs at play (on_play): let N be the
number of fence PIECES the player has built (`fences_built` = the sum of the
horizontal + vertical fence arrays, NOT the pasture count). Schedule 1 food onto
each of the next N round spaces — rounds R+1..R+N where R is the current round.
`schedule_resources` clamps slots outside 1..14, so the "up to ... next round
spaces" cap on remaining rounds is handled for free (no separate min against the
rounds left). N == 0 (no fences) schedules nothing — a legal +0.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.helpers import fences_built
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "trellises"


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    n = fences_built(state.players[idx].farmyard)
    return schedule_resources(state, idx, range(R + 1, R + 1 + n), Resources(food=1))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1)),
    on_play=_on_play,
)
