"""Pumpernickel (minor improvement, deck E #7; Ephipparius Expansion; traveling).

Card text: "You immediately get 4 food. (Effectively, you are turning 1 grain
into 4 food.)" Cost 1 grain, no prerequisite, no printed VPs, and it is a
TRAVELING (passing) card — after the immediate effect it is passed to the
opponent rather than kept.

Category 2 (on-play one-shot) + passing. The 1-grain play cost is debited by the
engine's play path; `on_play` only adds the 4 food. The parenthetical is flavor
describing the net exchange (spend 1 grain, gain 4 food).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "pumpernickel"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=4))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(grain=1)),
    vps=0,
    passing_left=True,
    on_play=_on_play,
)
