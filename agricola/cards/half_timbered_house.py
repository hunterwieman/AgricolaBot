"""Half-Timbered House (minor improvement, C30; Consul Dirigens Expansion;
cost 1 Wood / 1 Clay / 2 Stone / 1 Reed).

Card text: "During scoring, you get 1 bonus point for each stone room you have.
You can only use one card to get bonus points for your stone house."

A pure end-game scoring term — no on-play effect (its on-play is a no-op). A
"stone room" is a ROOM cell when the player's house is made of stone: all of a
player's rooms share one material (``ps.house_material``), so the stone-room
count is the room count IF the house is STONE, else 0 — mirroring scoring.py's
``stone_rooms = num_rooms if ps.house_material == HouseMaterial.STONE else 0``.
A wood or clay house therefore scores 0 from this card.

The trailing "you can only use one card to get bonus points for your stone
house" clause is a mutual-exclusion with Luxurious Hostel (the other
stone-house bonus card): a player who owns both may only benefit from ONE of
them — whichever scores higher — not the sum. Both cards register into the
shared "stone_house_bonus" scoring GROUP (via register_scoring_group), which
`score()` resolves by taking the max of the owned members exactly once (never
also summing them through SCORING_TERMS).

Category 1 (end-game scoring). No stored state — derived from the farmyard.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import CellType, HouseMaterial
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring_group
from agricola.state import GameState

CARD_ID = "half_timbered_house"
STONE_HOUSE_BONUS_GROUP = "stone_house_bonus"


def _score(state: GameState, idx: int) -> int:
    """1 VP per stone room: the ROOM-cell count, but only for a STONE house."""
    ps = state.players[idx]
    if ps.house_material != HouseMaterial.STONE:
        return 0
    grid = ps.farmyard.grid
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.ROOM
    )


# Pure scoring minor: no on-play effect.
register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1, clay=1, stone=2, reed=1)),
    on_play=lambda state, idx: state,
)
register_scoring_group(STONE_HOUSE_BONUS_GROUP, CARD_ID, _score)
