"""Field Clay (minor improvement, D5; Dulcinaria Expansion; players -).

Card text: "You immediately get 1 clay for each planted field you have."
Prerequisite: 1 planted field. Cost: 1 Food. Printed 0 VP.

Category: on-play one-shot (kept, not passing). When played, count the player's
PLANTED fields — FIELD cells holding at least one crop (grain or veg) — and grant
that many clay immediately. A freshly-plowed-but-unsown FIELD does NOT count (it is
not planted), so counting all FIELD cells would over-grant; the predicate matches a
field with a crop on it (grain > 0 or veg > 0), the same "planted = sown" reading
used by Ash Trees.

The prerequisite (1 planted field) guarantees the count is >= 1, so the grant is
always >= 1 clay. No CardStore, no triggers, no passing.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "field_clay"


def _planted_field_count(state: GameState, idx: int) -> int:
    """FIELD cells with a crop on them (planted = sown — grain or veg present)."""
    grid = state.players[idx].farmyard.grid
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
        and (grid[r][c].grain > 0 or grid[r][c].veg > 0)
    )


def _prereq_one_planted_field(state: GameState, idx: int) -> bool:
    return _planted_field_count(state, idx) >= 1


def _on_play(state: GameState, idx: int) -> GameState:
    n = _planted_field_count(state, idx)            # >= 1 by the prerequisite
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(clay=n))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=1)),
    prereq=_prereq_one_planted_field,
    on_play=_on_play,
)
