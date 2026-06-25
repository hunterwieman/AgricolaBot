"""Priest (occupation, A125; Base Revised; players 1+).

Card text: "When you play this card, if you live in a clay house with exactly
2 rooms, you immediately get 3 clay, 2 reed, and 2 stone." The clause is a
play-time CONDITION (checked when played); if it doesn't hold, the card grants
nothing (it still enters the tableau).

Category 2 (on-play one-shot, conditional). No stored state.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.constants import CellType, HouseMaterial
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, PlayerState

CARD_ID = "priest"


def _num_rooms(p: PlayerState) -> int:
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if p.farmyard.grid[r][c].cell_type == CellType.ROOM
    )


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    if p.house_material is HouseMaterial.CLAY and _num_rooms(p) == 2:
        p = fast_replace(p, resources=p.resources + Resources(clay=3, reed=2, stone=2))
        return fast_replace(
            state, players=tuple(p if i == idx else state.players[i] for i in range(2))
        )
    return state


register_occupation(CARD_ID, _on_play)
