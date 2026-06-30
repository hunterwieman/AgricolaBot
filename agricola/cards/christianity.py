"""Christianity (minor improvement, C38; Corbarius Expansion; players -).

Card text: "When you play this card, all other players get 1 food each."

Cost: none (no printed cost). Prerequisite: Exactly 1 Sheep. VPs: 2.
Not passing.

Category 2 (on-play one-shot). The on-play effect is a GIFT to the OPPONENT(s):
in the 2-player game "all other players" is the single opponent (`1 - idx`), who
gets 1 food. The player who plays the card gains nothing from the effect (only the
2 printed VPs at scoring) — so the on-play edit touches the OPPONENT's resources,
not the player's.

"Exactly 1 Sheep" is a PLAY-TIME prerequisite — a have-check on the player's sheep
count (`animals.sheep == 1`, exactly, never `>= 1`), consumed via `prereq_met` in
legality.py. It is NOT a cost: the sheep is never spent, and the prerequisite is
not re-checked after the card is played.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "christianity"


def _prereq(state: GameState, idx: int) -> bool:
    # Exactly 1 sheep — a have-check on the player's herd, never spent.
    return state.players[idx].animals.sheep == 1


def _on_play(state: GameState, idx: int) -> GameState:
    # "all other players get 1 food each" — in the 2-player game, the opponent.
    opp = 1 - idx
    p = state.players[opp]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(
        state, players=tuple(p if i == opp else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(), prereq=_prereq, vps=2, on_play=_on_play)
