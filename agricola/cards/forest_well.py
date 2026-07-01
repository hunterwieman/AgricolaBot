"""Forest Well (minor improvement, D44; Dulcinaria Expansion).

Card text: "Place 1 food on each remaining round space, up to the amount of wood in
your supply. At the start of these rounds, you get the food."
Cost: 1 Stone, 1 Food. Prerequisite: 2 Occupations. VPs: 1. Not passing.

Category 8 (deferred goods) — the food sibling of Thick Forest / Private Forest, but
with a COUNT CAP instead of an even/odd filter. The effect places 1 food on each of
the FIRST `wood` remaining round spaces, where `wood` is the amount of wood the player
holds in supply AT THE MOMENT OF PLAY.

Reading the cap precisely: "up to the amount of wood in your supply" bounds the NUMBER
of round spaces that receive food — it is NOT a per-space wood debit. Wood is never
spent (the printed spendable cost is only 1 stone + 1 food). So we take the remaining
round spaces in board order (rounds strictly after the current one, R+1 .. 14 — the
current round's space is already collected) and keep the first `wood` of them. If the
player holds more wood than there are remaining round spaces, every remaining space
gets food and the surplus wood is simply unused (the `[:wood]` slice is a no-op past
the end of the list).

The food lands in the player's per-round schedule (`future_resources`) and is collected
at the start of each scheduled round in `engine._complete_preparation`. The cost
(1 stone + 1 food) is debited by the play-card engine BEFORE `on_play` runs; spending
stone/food does not touch the wood count, so the cost ordering is immaterial here.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "forest_well"


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    wood = state.players[idx].resources.wood
    # Remaining round spaces, in board order, capped to the wood count. The current
    # round's space is already collected at its start, so the lower bound is strictly
    # R+1. schedule_resources clamps slots to 1..14, so an oversized wood count just
    # maxes out at "every remaining round space".
    rounds = list(range(R + 1, 15))[:wood]
    return schedule_resources(state, idx, rounds, Resources(food=1))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(stone=1, food=1)),  # spendable 1 stone + 1 food
    min_occupations=2,                                 # prereq: hold >=2 occupations
    vps=1,
    on_play=_on_play,
)
