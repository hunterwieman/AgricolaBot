"""Young Animal Market (minor improvement, A9; Base Revised; cost 1 sheep, traveling).

Card text: "You immediately get 1 cattle. (Effectively, you are exchanging 1 sheep
for 1 cattle.)" No prerequisite, no printed VPs; a TRAVELING (passing) card.

Category 2 (on-play one-shot) + passing — the first card with an ANIMAL cost
(1 sheep, debited by _execute_play_minor via Cost.animals), gaining 1 cattle.
Net animal count is unchanged, so no new accommodation overflow is introduced
(the engine, like the other on-play gains, does not force accommodation on gain).
See CARD_IMPLEMENTATION_PLAN.md Category 2.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost
from agricola.state import GameState

CARD_ID = "young_animal_market"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, animals=p.animals + Animals(cattle=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(animals=Animals(sheep=1)),
               passing_left=True, on_play=_on_play)
