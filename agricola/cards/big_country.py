"""Big Country (minor improvement, A33; Base Revised; no cost).

Card text: "For each complete round left to play, you immediately get 1 bonus point
and 2 food." Prerequisite "All Farmyard Spaces Used" (every farmyard cell is
non-empty); no printed VPs.

Category 2 (on-play one-shot) with a TWIST: the food is granted immediately, but
the bonus points must be BANKED — they are scored at end-game, yet computed at play
time (the number of complete rounds left is a play-time quantity, not a derived
end-game read). So on_play stores the banked point total in the per-card CardStore
(II.7), and the scoring term simply reads it back.

"Complete rounds left to play" — the current round is in progress (not complete),
so the rounds remaining after it are 14 − round_number (rounds round_number+1 … 14).
Played in round 14 there are 0 left → no points, no food. See
CARD_IMPLEMENTATION_PLAN.md Category 1 / II.7.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.helpers import enclosed_cells
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "big_country"


def _all_farmyard_spaces_used(state: GameState, idx: int) -> bool:
    """Prerequisite: every farmyard space is used — a room, field, stable, or a
    fenced pasture cell.

    A pasture is not its own `CellType`; it is derived from the fence arrays, so a
    fenced-but-empty pasture cell keeps `cell_type == EMPTY`. Such a cell IS a used
    space (it is a pasture), so the check is "cell_type != EMPTY OR the cell is
    enclosed by fences" — not "cell_type != EMPTY" alone, which would wrongly fail
    the prereq on any farm whose pastures contain an empty, stable-less cell."""
    fy = state.players[idx].farmyard
    grid = fy.grid
    enclosed = enclosed_cells(fy)
    return all(
        grid[r][c].cell_type is not CellType.EMPTY or (r, c) in enclosed
        for r in range(3)
        for c in range(5)
    )


def _complete_rounds_left(state: GameState) -> int:
    """Rounds that will be played AFTER the current (in-progress) one."""
    return 14 - state.round_number


def _on_play(state: GameState, idx: int) -> GameState:
    n = _complete_rounds_left(state)
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources + Resources(food=2 * n),   # immediate food
        card_state=p.card_state.set(CARD_ID, n),          # bank the bonus points
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    # The banked points (1 per complete round that was left when played).
    return state.players[idx].card_state.get(CARD_ID, 0)


register_minor(CARD_ID, prereq=_all_farmyard_spaces_used, on_play=_on_play)
register_scoring(CARD_ID, _score)
