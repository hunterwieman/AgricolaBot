"""Thick Forest (minor improvement, B74; Base Revised).

Card text: "Place 1 wood on each remaining even-numbered round space. At the start
of these rounds, you get the wood."
Cost JSON: "5 Clay in Your Supply". Prerequisite: none. VPs: none. Not passing.

Category 8 (deferred goods). NOTE on the cost (CARD_IMPLEMENTATION_PLAN.md II.4):
"5 Clay in Your Supply" is NOT a spendable cost — it is a PREREQUISITE (hold >=5
clay, do not spend it) that happens to sit in the JSON `cost` field. So this card
has an empty spendable cost and a custom prereq of `clay >= 5`.

The effect schedules 1 wood onto each remaining EVEN-numbered round space — even
rounds strictly after the current round (the current round's space is already
collected) up through 14.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "thick_forest"


def _has_five_clay(state: GameState, idx: int) -> bool:
    return state.players[idx].resources.clay >= 5


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    even_rounds = [rnd for rnd in range(R + 1, 15) if rnd % 2 == 0]
    return schedule_resources(state, idx, even_rounds, Resources(wood=1))


register_minor(
    CARD_ID,
    cost=Cost(),                 # "5 Clay in Your Supply" is a prereq, not a debit
    prereq=_has_five_clay,
    on_play=_on_play,
)
