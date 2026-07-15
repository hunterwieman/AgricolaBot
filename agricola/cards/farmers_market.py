"""Farmers Market (minor improvement, E8; Ephipparius Expansion; traveling).

Card text: "You immediately get 1 vegetable. (Effectively, you are buying 1
vegetable for 2 food.)" Cost 2 Food, no prerequisite, no printed VPs, and it is
a TRAVELING (passing) card — after the immediate effect it is passed to the
opponent rather than kept.

Category 2 (on-play one-shot) + passing — the exact Market Stall shape (which is
"buy 1 vegetable for 1 grain"); here the cost is 2 food and the gain is 1 veg, so
the parenthetical "buying 1 vegetable for 2 food" is just cost (2 food) + effect
(+1 veg). No stored state.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "farmers_market"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(veg=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=2)),
    passing_left=True,
    on_play=_on_play,
)
