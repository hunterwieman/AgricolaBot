"""Private Forest (minor improvement, C74; Consul Dirigens Expansion).

Card text: "Place 1 wood on each remaining even-numbered round space. At the start
of these rounds, you get the wood."
Cost: 2 Food. Prerequisite: 1 Occupation. VPs: none. Not passing.

Category 8 (deferred goods). The effect is byte-identical to Thick Forest (B74):
schedule 1 wood onto each remaining EVEN-numbered round space — even rounds strictly
after the current round (the current round's space is already collected at the start
of that round) up through 14. The wood lands in the player's per-round schedule
(`future_resources`) and is collected at the start of each scheduled round in
`engine._complete_preparation`.

Private Forest differs from Thick Forest only in its cost/prereq: here the cost is a
genuine SPENDABLE 2 Food (`Cost(resources=Resources(food=2))`, the established pattern
of Debt Security / Forestry Studies / Excursion to the Quarry), and the prerequisite
is holding at least 1 occupation (`min_occupations=1`) — a HAVE-check, never spent.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "private_forest"


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    # Strict R+1 lower bound: the current round's space is already collected at the
    # start of round R, so scheduling onto it would be lost. schedule_resources clamps
    # slots to 1..14, so no extra upper guard is needed.
    even_rounds = [rnd for rnd in range(R + 1, 15) if rnd % 2 == 0]
    return schedule_resources(state, idx, even_rounds, Resources(wood=1))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=2)),  # spendable 2 Food
    min_occupations=1,                        # prereq: hold >=1 occupation
    on_play=_on_play,
)
