"""Market Stall (minor improvement, B8; Base Revised; traveling).

Card text: "You immediately get 1 vegetable. (Effectively, you are exchanging
1 grain for 1 vegetable)." Cost 1 grain, no prerequisite, no printed VPs, and
it is a TRAVELING (passing) card — after the immediate effect it is passed to
the opponent rather than kept.

Category 2 (on-play one-shot) + passing. The cost (1 grain) and the gain
(1 veg) together are the exchange.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "market_stall"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(veg=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(grain=1)),
    passing_left=True,
    on_play=_on_play,
)
