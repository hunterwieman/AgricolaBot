"""Gift Basket (minor improvement, B73; Bubulcus Expansion; kept).

Card text: "When you play this card, if you have exactly 2/3/4/5 rooms, you
immediately get 1 vegetable/food/grain/vegetable."

Cost 1 reed. Prerequisite: "3 Occupations" (a have-check, ``min_occupations=3``).
1 printed VP. Not a passing card — it stays in front of the player.

Category 2 (on-play one-shot). The slash-list is a BANDED, single-good read:
the reward is selected by EXACTLY how many rooms the player has at play time —

    2 rooms -> 1 vegetable
    3 rooms -> 1 food
    4 rooms -> 1 grain
    5 rooms -> 1 vegetable   (2 and 5 both give a vegetable)

Any other room count (1, or 6 and up) grants nothing. Rooms are counted as
``CellType.ROOM`` cells in the farmyard grid (there is no ``num_rooms`` field on
``PlayerState``); the starting house is 2 rooms, so the minimum reachable count
already lands in the table.
"""
from __future__ import annotations

from agricola.constants import CellType
from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "gift_basket"

# Banded reward: exact room count -> the single good gained. Counts outside this
# table (1, or 6+) grant nothing.
_ROOM_REWARD = {
    2: Resources(veg=1),
    3: Resources(food=1),
    4: Resources(grain=1),
    5: Resources(veg=1),
}


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    n_rooms = sum(
        1
        for row in p.farmyard.grid
        for cell in row
        if cell.cell_type == CellType.ROOM
    )
    gain = _ROOM_REWARD.get(n_rooms)
    if gain is None:
        return state
    p = fast_replace(p, resources=p.resources + gain)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(reed=1)),
    min_occupations=3,
    vps=1,
    on_play=_on_play,
)
