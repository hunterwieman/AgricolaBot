"""Clay Embankment (minor improvement, A5; Base Revised; cost 1 food, traveling).

Card text: "You immediately get 1 clay for every 2 clay you already have in your
supply." No prerequisite, no printed VPs; a TRAVELING (passing) card — executed
then passed to the opponent, never kept.

Category 2 (on-play one-shot) + passing. The cost is 1 food, so the clay held at
play time (used to scale the gain) is unaffected by paying the cost. See
CARD_IMPLEMENTATION_PLAN.md Category 2.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "clay_embankment"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    gain = p.resources.clay // 2
    p = fast_replace(p, resources=p.resources + Resources(clay=gain))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(food=1)),
               passing_left=True, on_play=_on_play)
