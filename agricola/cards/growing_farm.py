"""Growing Farm (minor improvement, B52; Bubulcus Expansion).

Card text: "You can only play this card if you have at least as many pasture
spaces as the number of completed rounds. If you do, you get a number of food
equal to the current round."

Cost 2 Clay, 1 Reed. Printed 2 VPs (kept-card scoring, handled by the engine via
`vps=`). Category 2 (on-play one-shot) with a play prerequisite.

Two off-by-one / terminology points the verbatim text turns on:

- "Pasture spaces" = the number of CELLS enclosed in pastures, where a 2-cell
  pasture counts as 2 spaces. That is `len(enclosed_cells(fy))` (the union of all
  cells inside any pasture), NOT the number of distinct pasture OBJECTS
  (`len(farmyard.pastures)`). A pasture is not its own `CellType`, so it is read
  off the BFS-derived enclosed-cell set, never `cell_type`.

- "Completed rounds" = `round_number - 1`. The current round is in progress (not
  yet complete), exactly as Big Country reads "complete rounds left to play" as
  `14 - round_number`. So the prerequisite is
  `pasture_cells >= round_number - 1`.

- The food grant is "the current round" = `round_number` (NOT `round_number - 1`).
  The prerequisite threshold and the food amount therefore differ by exactly 1 and
  must not be conflated.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.helpers import enclosed_cells
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "growing_farm"


def _prereq(state: GameState, idx: int) -> bool:
    """Playable iff the player's pasture-cell count is at least the number of
    completed rounds (`round_number - 1`)."""
    fy = state.players[idx].farmyard
    return len(enclosed_cells(fy)) >= state.round_number - 1


def _on_play(state: GameState, idx: int) -> GameState:
    """Gain food equal to the current round number."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=state.round_number))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(clay=2, reed=1)),
    prereq=_prereq,
    vps=2,
    on_play=_on_play,
)
