"""Clay Deliveryman (occupation, D120; Consul Dirigens Expansion; players 1+).

Card text: "Place 1 clay on each remaining space for rounds 6 to 14. At the
start of these rounds, you get the clay."

Category 8 (deferred goods on future round spaces) — the Well / Wood Collector
shape, fixed to the printed round band: on play, schedule 1 clay on every round
space in 6..14 that is still to come ("each REMAINING space" — spaces for
rounds already entered, the current round included, are gone). Played in round
R, that is rounds max(6, R+1)..14: a round-1 play seeds all nine (rounds 6-14),
a round-8 play seeds rounds 9-14, a round-14 play seeds nothing. Collection is
the standard preparation-ladder round-space payout. Choice-free (no
optionality); no prerequisite, no printed VPs.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_occupation
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "clay_deliveryman"


def _on_play(state: GameState, idx: int) -> GameState:
    first = max(6, state.round_number + 1)
    rounds = list(range(first, 15))
    if not rounds:
        return state
    return schedule_resources(state, idx, rounds, Resources(clay=1))


register_occupation(CARD_ID, _on_play)
