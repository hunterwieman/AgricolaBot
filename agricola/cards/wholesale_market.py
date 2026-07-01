"""Wholesale Market (minor improvement, D57; Dulcinaria Expansion).

Card text: "Place 1 food on each remaining round space. At the start of these
rounds, you get the food."
Cost: 2 Wood, 2 Vegetable. No prerequisite. VPs: 3. Not passing.

Category 8 (deferred goods). The whole effect runs at play (on_play): schedule
1 food onto every REMAINING round space — rounds R+1..14 where R is the current
round (`state.round_number`). The current round's goods were already collected
when this round was entered, so scheduling starts at R+1, matching Trellises /
Chophouse. There is NO count cap (unlike Trellises, which caps at fences built):
EVERY remaining round gets food. `schedule_resources` writes 1-indexed round
`rnd` into slot `rnd-1` and is collected at the start of round `rnd` (in
`engine._complete_preparation`); slots outside 1..14 are silently dropped, so the
exclusive upper bound 15 includes round 14 and any out-of-range round is a no-op.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "wholesale_market"


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    return schedule_resources(state, idx, range(R + 1, 15), Resources(food=1))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=2, veg=2)),
    vps=3,
    on_play=_on_play,
)
