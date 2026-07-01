"""Sheep Well (minor improvement, D45; Consul Dirigens Expansion).

Card text: "Place 1 food on each of the next round spaces, up to the number of
sheep you have. At the start of these rounds, you get the food."
Cost: 2 Stone. No prerequisite. VPs: 2. Not passing.

Category 8 (deferred goods). The whole effect runs at play (on_play): let N be the
number of sheep the player currently owns (`animals.sheep` — evaluated ONCE at play
time, a fixed number of consecutive next-round spaces, NOT re-checked per round and
NOT one-food-per-future-round-while-you-own-sheep). Schedule 1 food onto each of the
next N round spaces — rounds R+1..R+N where R is the current round.
`schedule_resources` clamps slots outside 1..14, so the "up to ... next round spaces"
cap on remaining rounds is handled for free (no separate min against the rounds left).
N == 0 (no sheep) schedules nothing — a legal +0.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "sheep_well"


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    n = state.players[idx].animals.sheep
    return schedule_resources(state, idx, range(R + 1, R + 1 + n), Resources(food=1))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(stone=2)),
    vps=2,
    on_play=_on_play,
)
