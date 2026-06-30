"""Reed Belt (minor improvement, B78; Bubulcus Expansion).

Card text: "Place 1 reed on each of the remaining space for rounds 5, 8, 10, and 12.
At the start of these rounds, you get the reed."
Cost: 2 Food. No prerequisite. VPs: none. Not passing.

Category 8 (deferred goods). Like Sack Cart, the rounds are ABSOLUTE board numbers
{5, 8, 10, 12}; "remaining" means only the ones strictly after the current round (a
round already entered has had its space collected). Filter to rounds > R, then
schedule 1 reed onto each in `future_resources`, collected at each round's start by
`engine._complete_preparation`. Reed always fits (no accommodation), so there is no
animal/capacity concern.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "reed_belt"
_REED_ROUNDS = (5, 8, 10, 12)


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    remaining = [rnd for rnd in _REED_ROUNDS if rnd > R]
    return schedule_resources(state, idx, remaining, Resources(reed=1))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=2)),
    on_play=_on_play,
)
