"""Baseboards (minor improvement, A4; Artifex Expansion; traveling).

Card text: "You immediately get 1 wood for each room you have. If you have more
rooms than people, you get 1 additional wood."

Cost: "2 Food / 1 Grain" — an ALTERNATIVE ("/") cost: pay EITHER 2 food OR 1
grain, not both (the printed first cost in `cost`, the alternative in
`alt_costs`; the play path enumerates one CommitPlayMinor per affordable
alternative — the Chophouse idiom). No prerequisite, no printed VPs; a TRAVELING
(passing) card — after the immediate effect it passes to the opponent.

Category 2 (on-play one-shot) + passing. Rooms are ROOM cells on the farmyard
grid (all rooms share one house material — the count is material-independent).
"People" is the total people in play (home + placed) = `people_total`. The bonus
is a STRICT comparison: rooms > people grants +1 (equal rooms and people does
NOT). Reads the DECIDER's OWN farmyard only. No stored state.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "baseboards"


def _num_rooms(p) -> int:
    grid = p.farmyard.grid
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.ROOM
    )


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    rooms = _num_rooms(p)
    wood = rooms + (1 if rooms > p.people_total else 0)
    p = fast_replace(p, resources=p.resources + Resources(wood=wood))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=2)),
    alt_costs=(Cost(resources=Resources(grain=1)),),
    passing_left=True,
    on_play=_on_play,
)
