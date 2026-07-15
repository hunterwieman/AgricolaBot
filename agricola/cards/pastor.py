"""Pastor (occupation, B163; Base Revised; players 4+).

Card text (verbatim): "Once you are the only player to live in a house with only 2
rooms, you immediately get 3 wood, 2 clay, 1 reed, and 1 stone (only once)."

A once-per-game reward keyed to a comparison of ROOM COUNTS across players: the
first moment the owner lives in a 2-room house AND is the ONLY player to do so
(every OTHER player's house has a room count other than 2), they gain 3 wood, 2
clay, 1 reed, 1 stone. The starting house is 2 rooms, so at game start BOTH players
have 2 rooms and the owner is NOT alone — the condition becomes true only once every
other player has expanded past (or is otherwise away from) 2 rooms while the owner
still holds exactly 2.

WHY THE BOUNDARY SWEEP, NOT `register_conditional`: the condition flips on an
OPPONENT'S Build-Rooms action (their room count leaving 2), which the
renovate/card-play conditional sweep never sees. The decision-BOUNDARY one-shot
sweep (`register_boundary_one_shot`, run by `engine._fire_boundary_one_shots` at
every agent-decision boundary) does see it. Room count is public and derived from
the grid (ROOM cells), so both halves of the comparison are common knowledge.
Latched in `fired_once` ("only once"). The reward is pure goods (they always fit),
so `_apply` is a plain resource gain — no scoring term.

Card-only state (the `fired_once` latch) is empty in the Family game -> byte-
identical, C++ gates untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_boundary_one_shot
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, PlayerState

CARD_ID = "pastor"

_GRANT = Resources(wood=3, clay=2, reed=1, stone=1)


def _num_rooms(p: PlayerState) -> int:
    """Number of ROOM cells in the player's farmyard (mirrors scoring.py)."""
    grid = p.farmyard.grid
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.ROOM
    )


def _condition(state: GameState, idx: int) -> bool:
    """Owner lives in a 2-room house AND is the only player who does (every other
    player has a room count != 2). Generalizes across player counts."""
    if _num_rooms(state.players[idx]) != 2:
        return False
    return all(
        _num_rooms(pl) != 2
        for j, pl in enumerate(state.players)
        if j != idx
    )


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + _GRANT)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


# Pure boundary-one-shot occupation: played via Lessons, on-play is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)
register_boundary_one_shot(CARD_ID, _condition, _apply)
