"""Consultant (occupation, B102; Base Revised; players 1+).

Card text: "When you play this card in a 1-/2-/3-/4- player game, you immediately
get 2 grain/3 clay/2 reed/2 sheep." The slash list is positional against the
player count; this engine is 2-player, so the effect is **immediately get 3 clay**.

Category 2 (on-play one-shot). No stored state.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "consultant"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(clay=3))  # 2-player branch
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, _on_play)
