"""Small-scale Farmer (occupation, B118; Base Revised; players 1+).

Card text: "As long as you live in a house with exactly 2 rooms, at the start of
each round, you get 1 wood."

Category 7 (start-of-round phase hook). The clause is a MANDATORY, choice-free
income gated on a 2-room house → an automatic effect (`register_auto` on the
`start_of_round` event), fired at the PendingPreparation push for the owner. The
condition (exactly 2 rooms) is re-checked each round in the eligibility, so the
income stops once the player expands or contracts. See
CARD_IMPLEMENTATION_PLAN.md Category 7.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto, register_start_of_round_hook
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, PlayerState

CARD_ID = "small_scale_farmer"


def _num_rooms(p: PlayerState) -> int:
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if p.farmyard.grid[r][c].cell_type == CellType.ROOM
    )


def _eligible(state: GameState, idx: int) -> bool:
    return _num_rooms(state.players[idx]) == 2   # exactly 2 rooms


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("start_of_round", CARD_ID, _eligible, _apply)
register_start_of_round_hook(CARD_ID)
