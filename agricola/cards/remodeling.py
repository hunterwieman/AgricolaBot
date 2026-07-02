"""Remodeling (minor improvement, C5; Corbarius Expansion; players -).

Card text: "You immediately get 1 clay for each clay room and for each major
improvement you have."

Category 2 (on-play one-shot). Cost 1 food, no prerequisite, no printed VPs,
PASSING (traveling minor — `passing_left='X'` in the catalog: after the on-play
effect the card moves to the opponent's hand). At play time, the player gains
clay equal to:
  - the number of CLAY rooms they have (rooms count only if the house is
    currently a CLAY house — a stone house has zero clay rooms, mirroring the
    scoring idiom in scoring.py), PLUS
  - the number of major improvements they own (every major counts +1,
    regardless of type — Fireplace, Cooking Hearth, ovens, Well, etc.).

The gain may legitimately be 0 (e.g. a wood house with no majors); that is fine.
No stored state.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import CellType, HouseMaterial
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, PlayerState

CARD_ID = "remodeling"


def _clay_rooms(p: PlayerState) -> int:
    """Number of clay rooms — rooms only if the house is currently CLAY."""
    if p.house_material is not HouseMaterial.CLAY:
        return 0
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if p.farmyard.grid[r][c].cell_type == CellType.ROOM
    )


def _num_majors_owned(state: GameState, idx: int) -> int:
    return sum(1 for owner in state.board.major_improvement_owners if owner == idx)


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    gain = _clay_rooms(p) + _num_majors_owned(state, idx)
    if gain == 0:
        return state
    p = fast_replace(p, resources=p.resources + Resources(clay=gain))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=1)),
    passing_left=True,
    on_play=_on_play,
)
