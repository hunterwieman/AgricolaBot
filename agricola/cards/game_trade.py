"""Game Trade (minor improvement, D9; Consul Dirigens Expansion; cost 2 sheep, traveling).

Card text: "You immediately get 1 wild boar and 1 cattle. (Effectively, you are
exchanging 2 sheep for 1 wild boar and 1 cattle.)" Cost: 2 Sheep. No prerequisite,
no printed VPs; a TRAVELING (passing) card.

Category 2 (on-play one-shot) + passing, the ANIMAL-cost shape (cf. Young Animal
Market, A9). The cost (2 sheep) is debited by `_execute_play_minor` via
`Cost.animals`; the on-play effect is the immediate gain of 1 wild boar + 1 cattle.
The parenthetical in the card text merely restates the cost+gain as an exchange —
no extra mechanic. Net animals fall by 1 (give 2, get 2) and the gain, like the
other on-play animal gains, is not forced through accommodation (the engine does
not force accommodation on a gain). See CARD_IMPLEMENTATION_PLAN.md Category 2.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost
from agricola.state import GameState

CARD_ID = "game_trade"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, animals=p.animals + Animals(boar=1, cattle=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(animals=Animals(sheep=2)),
               passing_left=True, on_play=_on_play)
