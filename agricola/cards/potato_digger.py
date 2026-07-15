"""Potato Digger (occupation, C161; Corbarius Expansion; players 4+).

Card text (verbatim): "When you play this card, if you have at least 2/4/5
unplanted field tiles, you immediately get 1/2/3 vegetables."

Category 2 (on-play one-shot). "Unplanted field tiles" are FIELD cells holding no
crop — a plowed field that has not been sown (grain == 0 and veg == 0). The
vegetable payout is a step function over that count `n`:
  n >= 5 -> 3 veg,  n >= 4 -> 2 veg,  n >= 2 -> 1 veg,  else nothing.
The bands are "AT LEAST" thresholds. This is a pure goods gain (vegetables always
fit — resources are not capacity-limited), so it is a plain `on_play` grant with no
choice, mirroring `consultant.py`. "Immediately" here names the standard card-play
instant (as in Consultant / Crack Weeder), not a separate timing.

No stored state. Card-only registries default empty -> Family byte-identical, C++
gates untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "potato_digger"

# (threshold unplanted fields, vegetables) bands, highest first.
_BANDS: tuple[tuple[int, int], ...] = (
    (5, 3),
    (4, 2),
    (2, 1),
)


def _unplanted_field_tiles(state: GameState, idx: int) -> int:
    """FIELD cells with no crop sown on them (grain == 0 and veg == 0)."""
    grid = state.players[idx].farmyard.grid
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
        and grid[r][c].grain == 0
        and grid[r][c].veg == 0
    )


def _veg_for(n: int) -> int:
    for threshold, veg in _BANDS:
        if n >= threshold:
            return veg
    return 0


def _on_play(state: GameState, idx: int) -> GameState:
    veg = _veg_for(_unplanted_field_tiles(state, idx))
    if veg == 0:
        return state
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(veg=veg))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, _on_play)
