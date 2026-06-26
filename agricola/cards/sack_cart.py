"""Sack Cart (minor improvement, B66; Base Revised).

Card text: "Place 1 grain each on the remaining spaces for rounds 5, 8, 11, and 14.
At the start of these rounds, you get the grain."
Cost: 2 Wood. Prerequisite: 2 Occupations. VPs: none. Not passing.

Category 8 (deferred goods). Unlike the "next N" cards, these are ABSOLUTE round
numbers {5, 8, 11, 14}; "remaining" means only the ones strictly after the current
round (a round already entered has had its space collected). Filter to rounds
> R, then schedule 1 grain onto each in `future_resources`.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "sack_cart"
_SACK_ROUNDS = (5, 8, 11, 14)


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    remaining = [rnd for rnd in _SACK_ROUNDS if rnd > R]
    return schedule_resources(state, idx, remaining, Resources(grain=1))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=2)),
    min_occupations=2,
    on_play=_on_play,
)
