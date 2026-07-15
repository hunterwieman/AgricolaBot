"""Almsbag (minor improvement, E65; Ephipparius Expansion; players -).

Card text: "When you play this card, you immediately get 1 grain for every 2
completed rounds."

No cost; prerequisite "No Occupations" (the player may not have played any
occupation -> `max_occupations=0`); no printed VPs; KEPT (not traveling).

Category 2 (on-play one-shot). "Completed rounds" is `round_number - 1`: the
current round is in progress and not yet complete (the same reading Growing Farm
and Big Country use). So the grain gained is `(round_number - 1) // 2` — one
grain per whole two completed rounds, rounding down. Reads the DECIDER's own
state only. No stored state.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "almsbag"


def _on_play(state: GameState, idx: int) -> GameState:
    completed_rounds = state.round_number - 1
    grain = completed_rounds // 2
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(grain=grain))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    max_occupations=0,   # "No Occupations"
    on_play=_on_play,
)
