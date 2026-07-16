"""Field Doctor (occupation, E92; Ephipparius Expansion; players 1+).

Card text: "Once this game, if you live in a house with exactly 2 rooms surrounded
by 4 field tiles, you can use any \"Wish for Children\" action space even without
room."
Clarification: Should be "Wish for Children" action space.

USER RULING (2026-07-14), verbatim: '"surrounded by 4 field tiles" — a 2-room
house is always the starting domino at the farmyard's lower-left, which has
exactly 4 surrounding cells counting diagonals; the ruled reading is that ALL
surrounding cells (orthogonal + diagonal, on-board) of the house's 2 room cells
are field tiles. Compute it generically: exactly 2 ROOM cells; the set of
on-board cells adjacent (orth+diag) to either room cell, excluding the room
cells themselves; every cell in that set has cell_type FIELD.'

One mechanism — a LEGALITY RELAXATION on the wish-space spare-room gate
(user-approved extension, 2026-07-14): the owner may take a room-gated "Wish for
Children" growth even when rooms <= people. Registered via
`register_growth_room_override(card_id, fn)`; the OR-consultation lives in
`_legal_basic_wish_for_children` (the placement gate shared by both game modes —
Basic Wish is the only room-gated wish space; Urgent Wish never requires a spare
room, so the card is never load-bearing there and that predicate is untouched).
The `workers_in_supply > 0` family cap (a meeple left in supply) is a game rule the
card does NOT waive — it stays enforced by `_legal_basic_wish_for_children`.

"Once this game" — the latch is CONSUMED by the engine, not by this module: when
a wish-space growth actually commits while the normal room gate fails (rooms <=
people at that moment), `_resolve_wish_for_children` (resolution.py) latches the
permitting card's id into the owner's `fired_once`. A growth taken with a spare
room consumes nothing (the card's permission wasn't used). The override predicate
below self-gates on the unspent latch, so a consumed Field Doctor stops widening
the gate.

"Field tiles" are plowed FIELD cells on the farmyard grid (sown or unsown — a
sown field is still a field tile); per-TILE readers exclude card-fields
(ruling 32, unchanged by ruling 45).

A pure legality relaxer played via Lessons: no cost / prereq / VPs, and its
on-play effect is a no-op. The override registry is empty in the Family game, so
the Family game is byte-identical and the C++ differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.constants import CellType
from agricola.legality import register_growth_room_override
from agricola.state import GameState, PlayerState

CARD_ID = "field_doctor"


def _house_surrounded_by_fields(p: PlayerState) -> bool:
    """The ruled geometry: exactly 2 ROOM cells, and every on-board cell adjacent
    (orthogonally or diagonally) to either room cell — excluding the room cells
    themselves — is a FIELD tile. Vacuously false is impossible on the 3x5 grid
    (a 2-room house always has neighbors), but an empty surround would read True
    by `all`; irrelevant in practice and faithful to 'ALL surrounding cells are
    field tiles'."""
    grid = p.farmyard.grid
    rooms = [
        (r, c)
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type is CellType.ROOM
    ]
    if len(rooms) != 2:
        return False
    room_set = set(rooms)
    surround = {
        (r + dr, c + dc)
        for (r, c) in rooms
        for dr in (-1, 0, 1)
        for dc in (-1, 0, 1)
        if not (dr == 0 and dc == 0)
        and 0 <= r + dr < 3
        and 0 <= c + dc < 5
        and (r + dr, c + dc) not in room_set
    }
    return all(grid[r][c].cell_type is CellType.FIELD for (r, c) in surround)


def _growth_room_override(state: GameState, idx: int) -> bool:
    """Player `idx` may currently take a room-gated wish growth without a spare
    room: owns a played Field Doctor, the once-per-game latch is unspent, and the
    ruled 2-rooms-surrounded-by-fields geometry holds."""
    p = state.players[idx]
    if CARD_ID not in p.occupations:
        return False
    if CARD_ID in p.fired_once:          # "Once this game" — already used
        return False
    return _house_surrounded_by_fields(p)


# Pure legality relaxer: played via Lessons, its on-play effect is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)
register_growth_room_override(CARD_ID, _growth_room_override)
