"""Sculpture (minor improvement, D37; Consul Dirigens Expansion).

Card text: "You can only play this card if there are more complete rounds left to
play than you have unused farmyard spaces."
Cost: 1 Stone. VPs: 2. Not passing.

Category 1 (printed-VP minor with a play prerequisite). The card has no on-play
effect and no derived end-game scoring term — its 2 victory points are the printed
yellow circle, auto-summed at scoring time (scoring.py reads `MinorSpec.vps` for
each kept minor). All that is bespoke is the prerequisite predicate.

The prerequisite compares two play-time quantities, with a STRICT ">":

  "complete rounds left to play"  >  "unused farmyard spaces"

- "Complete rounds left to play" — the current round is in progress (not yet
  complete), so the rounds that will be played AFTER it number `14 − round_number`
  (rounds round_number+1 … 14). Played in round 14 there are 0 left. This mirrors
  Big Country's `_complete_rounds_left`.

- "Unused farmyard spaces" — a farmyard cell that is neither a room/field/stable
  nor a fenced pasture cell. A pasture is not its own `CellType`; a fenced-but-empty
  pasture cell keeps `cell_type == EMPTY` but is a USED space, so it must NOT be
  counted as unused. The unused count is therefore cells that are EMPTY *and* not
  enclosed — exactly the complement of Big Country's "all farmyard spaces used"
  predicate. Counting raw `cell_type == EMPTY` would overcount unused spaces and
  wrongly relax the prerequisite.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.helpers import enclosed_cells
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "sculpture"


def _complete_rounds_left(state: GameState) -> int:
    """Rounds that will be played AFTER the current (in-progress) one."""
    return 14 - state.round_number


def _unused_farmyard_spaces(state: GameState, idx: int) -> int:
    """Count cells that are EMPTY and NOT enclosed by fences.

    A fenced-but-empty pasture cell has `cell_type == EMPTY` but is a used space,
    so it is excluded here (it is enclosed). Rooms / fields / stables are non-EMPTY
    and so are likewise excluded."""
    fy = state.players[idx].farmyard
    grid = fy.grid
    enclosed = enclosed_cells(fy)
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type is CellType.EMPTY and (r, c) not in enclosed
    )


def _prereq(state: GameState, idx: int) -> bool:
    """Playable iff strictly more complete rounds remain than unused spaces."""
    return _complete_rounds_left(state) > _unused_farmyard_spaces(state, idx)


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(stone=1)),
    prereq=_prereq,
    vps=2,
)
