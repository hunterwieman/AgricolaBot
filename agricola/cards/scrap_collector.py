"""Scrap Collector (occupation, E120; Ephipparius Expansion; players 1+).

Card text: "Alternate placing 1 wood and 1 clay on each of the next 6 round
spaces, starting with wood. At the start of these rounds, you get the
respective resource."

Category 8 (deferred goods on round spaces), on_play and choice-free. Played
in round R, "the next 6 round spaces" are rounds R+1 .. R+6, alternating
starting with wood: R+1 wood, R+2 clay, R+3 wood, R+4 clay, R+5 wood,
R+6 clay. The alternation is anchored to the OFFSET from the play round, not
to which rounds survive the 14-round clip — a round-10 play gives 11 wood,
12 clay, 13 wood, 14 clay and nothing else (rounds 15/16 are silently dropped
by `schedule_resources`, the standard "each remaining round space" clamp).

Implemented as two `schedule_resources` calls: wood on the odd offsets
(R+1, R+3, R+5), clay on the even offsets (R+2, R+4, R+6). The goods land in
`PlayerState.future_resources` and are collected automatically at the start of
each scheduled round (the preparation ladder's `__collect__` step).
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_occupation
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "scrap_collector"


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    # Alternation anchored to offsets from the play round: wood on the odd
    # offsets, clay on the even offsets. schedule_resources drops rounds > 14.
    state = schedule_resources(state, idx, (R + 1, R + 3, R + 5), Resources(wood=1))
    return schedule_resources(state, idx, (R + 2, R + 4, R + 6), Resources(clay=1))


register_occupation(CARD_ID, _on_play)
