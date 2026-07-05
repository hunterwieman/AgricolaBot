"""Lynchet (minor improvement, D63; Dulcinaria Expansion; Food Provider).

Card text (verbatim): "In the field phase of each harvest, you get 1 food for
each harvested field tile that is orthogonally adjacent to your house."

No cost, no prerequisite, no printed VPs, not a passing card.

A take-occasion AUTO (`register_harvest_occasion_auto`, gated
`occasion.source == "take"`) — migrated 2026-07-05 off the legacy pre-take
`harvest_field` grid snapshot onto the take manifest, per the migration review
(HARVEST_WINDOWS_DESIGN.md §7's "verify at migration" row / open question #4):

- **"harvested field tile" = a tile the take actually took a crop from** — a
  board-cell `HarvestEntry` in the take occasion. The old implementation
  PREDICTED this by reading sown adjacent fields pre-take; extensionally equal
  in every state reachable today, but structurally contingent — Grain Thief's
  planned replacement ("leave the grain on the field ... instead") makes a sown
  adjacent field NOT harvested, which the snapshot would miscount and the
  manifest read gets right for free.
- **Counted per TILE, ignoring `amount`** — "for each harvested field tile":
  an adjacent field yielding 2 grain in one combined take (a take-modifier's
  folded-in extra, ruling 11) is still ONE harvested tile → 1 food.
- **The `source == "take"` gate carries the card's scoping** ("in the field
  phase of each HARVEST", ruling 12): the take source only ever comes from a
  real harvest's field phase, so a card-played field phase (Bumper Crop /
  Harvest Festival Planning, ruling 4 — they call the bare take with their own
  source) correctly pays nothing. Card-field entries ("card:<id>") are not
  board TILES and have no adjacency, so they are naturally excluded when they
  land.

"Your house" is the set of ROOM cells; "orthogonally adjacent" is plain
3×5-grid edge adjacency (|dr| + |dc| == 1, in bounds) — not pasture/fence
geometry, so no geometry helper is needed. MANDATORY, choice-free income →
an automatic effect; fires immediately after the take applies.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import (
    register_harvest_occasion_auto,
    register_harvest_window_hook,
)
from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "lynchet"

_ROWS = 3
_COLS = 5


def _room_cells(grid) -> set[tuple[int, int]]:
    """The (row, col) of every ROOM cell — the player's house."""
    return {
        (r, c)
        for r in range(_ROWS)
        for c in range(_COLS)
        if grid[r][c].cell_type == CellType.ROOM
    }


def _adjacent_to_house(r: int, c: int, rooms: set[tuple[int, int]]) -> bool:
    """Is cell (r, c) orthogonally adjacent (edge-sharing) to a ROOM cell?"""
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        if (r + dr, c + dc) in rooms:
            return True
    return False


def _qualifying_count(state: GameState, idx: int, occasion) -> int:
    """Number of harvested field TILES orthogonally adjacent to the house:
    board-cell entries of the take occasion (one entry = one tile the take
    took a crop from, whatever the amount) whose cell borders a ROOM cell."""
    rooms = _room_cells(state.players[idx].farmyard.grid)
    count = 0
    for e in occasion.entries:
        if not e.source.startswith("cell:"):
            continue   # a card-field is not a board tile — no adjacency
        r_s, _, c_s = e.source[len("cell:"):].partition(",")
        if _adjacent_to_house(int(r_s), int(c_s), rooms):
            count += 1
    return count


def _eligible(state: GameState, idx: int, occasion) -> bool:
    # The real harvest's field-phase take only (the "take" source never comes
    # from a card-played field phase), with >= 1 adjacent harvested tile.
    return occasion.source == "take" and _qualifying_count(state, idx, occasion) > 0


def _apply(state: GameState, idx: int, occasion) -> GameState:
    count = _qualifying_count(state, idx, occasion)
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=count))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID)
register_harvest_occasion_auto(CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, "field_phase")
