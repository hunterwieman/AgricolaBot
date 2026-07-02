"""Writing Boards (minor improvement, C #4; Corbarius Expansion; Building Resource Provider).

Card text: "You immediately get 1 wood for each occupation you have in front of
you." Cost 1 food, no prerequisite, no printed VPs, PASSING (traveling minor —
`passing_left='X'` in the catalog: after the on-play effect the card moves to
the opponent's hand, like Market Stall).

Category 2 (on-play one-shot). The grant is the player's CURRENT occupation
count at play time. Playing this minor does not add to `occupations` (that
frozenset holds played OCCUPATION card_ids only), so there is no self-counting:
a player with no occupations played gets 0 wood. No stored state.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "writing_boards"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    n = len(p.occupations)
    p = fast_replace(p, resources=p.resources + Resources(wood=n))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=1)),
    passing_left=True,
    on_play=_on_play,
)
