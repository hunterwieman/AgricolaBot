"""Spice Trader (occupation, E104; Ephipparius Expansion; players 1+).

Card text (verbatim): "If you play this card in round 4 or before, place 3
vegetables on the space for round 11. At the start of that round, you get the
vegetables."

Category 8 (deferred goods), Goods Provider. The whole effect runs at play
(on_play) and is choice-free: if the play happens in round 4 or before
(`state.round_number <= 4` — a play-TIME condition, the printed gate), schedule
3 vegetables onto the FIXED round-11 space via `schedule_resources`
(`future_resources` slot 10 holds round 11; the goods are collected when round
11 is entered, in the preparation ladder's collection step — "at the start of
that round"). Played in round 5 or later the card does nothing — that is the
PRINTED condition, not an engine limitation; the card remains playable.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_occupation
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "spice_trader"

_PLAY_DEADLINE = 4   # "in round 4 or before"
_TARGET_ROUND = 11   # "the space for round 11"


def _on_play(state: GameState, idx: int) -> GameState:
    if state.round_number > _PLAY_DEADLINE:
        return state   # played round 5+ — the printed condition fails, no effect
    return schedule_resources(state, idx, [_TARGET_ROUND], Resources(veg=3))


register_occupation(CARD_ID, _on_play)
