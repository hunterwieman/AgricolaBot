"""Bottles (minor improvement, B36; Base Revised; cost: see below).

Card text: "For each person you have, you must pay an additional 1 clay and 1 food
to play this card."
Clarification: A newborn is a person.
Printed VPs: 4. No prerequisites.

Cost is people_total × (1 clay + 1 food), computed at play time via cost_fn.
`people_total` already includes newborns (the clarification matches the field's
definition). No on-play effect; the 4 VPs come from the printed vps field.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "bottles"


def _cost(state: GameState, idx: int) -> Cost:
    n = state.players[idx].people_total
    return Cost(resources=Resources(clay=n, food=n))


register_minor(CARD_ID, cost_fn=_cost, vps=4)
