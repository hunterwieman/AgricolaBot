"""Zigzag Harrow (minor improvement, D1; Dulcinaria Expansion; Farm Planner;
traveling/passing).

Card text (verbatim): "You can immediately plow 1 field such that it completes
a \"zigzag\" pattern."
Cost: 1 Wood. Prerequisite: "3 Fields in an \"L\" Shape". No printed VPs.
PASSING (traveling minor — ``passing_left`` is "X" in the data): after its
on-play effect the card is passed to the OPPONENT's hand, never kept in the
tableau.

USER RULING (2026-07-20, verbatim): zigzag means a pattern like
{(x, y), (x+1, y), (x+1, y+1), (x+2, y+1)},
{(x, y), (x, y+1), (x+1, y+1), (x+1, y+2)},
{(x, y), (x+1, y-1), (x+1, y), (x+2, y-1)}, or
{(x, y), (x-1, y+1), (x, y+1), (x-1, y+2)}. These four templates are the four
orientations (rotations + reflections) of the S/Z tetromino; the coordinates
are axis-agnostic — implement over (row, col) with all four templates,
translated anywhere on the 3-row x 5-col farmyard grid (grid[r][c], row 0 =
top).

SEMANTICS: "completes a zigzag" = after the plow, the NEW field plus 3 EXISTING
field TILES form one of the four templates. A zigzag-completing cell is always
orthogonally adjacent to at least one of its template's other 3 cells (the S/Z
tetromino is orthogonally connected), so the base plow adjacency rule is
automatically satisfied — the card never relaxes it, and the candidate set is
computed as an intersection with the ordinary plow legality
(``_legal_plow_cells``: empty, non-enclosed, adjacent to a field). The
prerequisite "3 Fields in an "L" Shape" = there exist 3 field TILES forming a
bent tromino (an L of 3 cells, any of its 4 orientations). Field TILES only in
both checks — card-fields have no geometry (ruling 32: a card-field is never a
field tile).

SHAPE — WIDE (play-variant), mirroring Double-Turn Plow (the on-play
optional-plow exemplar) and the passing-card rationale from Furrows: "You can"
makes the grant optional (ruling 17 — the on-play optional grant declines
wide), and a grant on a PASSING card cannot use an ownership-gated
``after_play_minor`` trigger (the card leaves the tableau into the opponent's
hand before the after-phase — the Dwelling Plan passing bug). So
``register_play_minor_variant`` registers two zero-surcharge routes:
  - "plow" — offered ONLY when a zigzag-completing legal plow cell exists
    (else pushing PendingPlow with an empty menu would dead-end); and
  - "skip" — ALWAYS offered (plow 0 fields; "you can" is optional), so the
    variant list is never empty and the card is playable whenever its base
    cost + prerequisite are.

The 3-arg ``on_play(state, idx, variant)``:
  - "plow" -> push ``PendingPlow(allowed_cells=<the zigzag-completing cells>)``
    (initiated_by_id "card:zigzag_harrow"). ``allowed_cells`` is the cell MENU
    the plow enumerator intersects with the ordinary legal plow cells
    (mirroring ``PendingBuildStables.allowed_cells``, the Shelter pattern).
    ``_execute_play_minor`` debits the cost and passes the card to the
    opponent's hand BEFORE running on_play, but neither touches the farmyard
    grid, so the candidate set recomputed here equals the one the variant
    enumeration saw — a "plow" route offered at enumeration always has a
    target at on_play time. The plow is mandatory once "plow" is chosen (the
    "skip" route was the take-or-leave moment); max_plows stays 1 ("plow 1
    field").
  - "skip" -> no-op (played without plowing).

Family-inertness: minors exist only under GameMode.CARDS, and
``PendingPlow.allowed_cells`` is a Family-constant default (None,
canonical-skip), so the Family game is byte-identical and the C++ differential
gates are untouched.
"""
from __future__ import annotations

from agricola.cards.display import register_action_labeler
from agricola.cards.specs import register_minor, register_play_minor_variant
from agricola.constants import CellType
from agricola.legality import _legal_plow_cells
from agricola.pending import PendingPlow, push
from agricola.resources import Cost, Resources
from agricola.state import GameState, PlayerState

CARD_ID = "zigzag_harrow"

_ROWS, _COLS = 3, 5

# The four zigzag templates (user ruling 2026-07-20, quoted verbatim in the
# module docstring), as (dr, dc) offsets from the template's base cell (x, y),
# read as (row, col):
#   {(x,y), (x+1,y),   (x+1,y+1), (x+2,y+1)}
#   {(x,y), (x,y+1),   (x+1,y+1), (x+1,y+2)}
#   {(x,y), (x+1,y-1), (x+1,y),   (x+2,y-1)}
#   {(x,y), (x-1,y+1), (x,y+1),   (x-1,y+2)}
_ZIGZAG_TEMPLATES = (
    ((0, 0), (1, 0), (1, 1), (2, 1)),
    ((0, 0), (0, 1), (1, 1), (1, 2)),
    ((0, 0), (1, -1), (1, 0), (2, -1)),
    ((0, 0), (-1, 1), (0, 1), (-1, 2)),
)

# The bent tromino (an L of 3 cells) in its 4 orientations, for the
# prerequisite — as absolute shapes within a 2x2 box, translated below.
_L_TEMPLATES = (
    ((0, 0), (1, 0), (1, 1)),
    ((0, 0), (0, 1), (1, 0)),
    ((0, 0), (0, 1), (1, 1)),
    ((0, 1), (1, 0), (1, 1)),
)


def _placements(templates) -> tuple[frozenset, ...]:
    """Every translation of each template that fits fully on the 3x5 grid."""
    out = set()
    for offs in templates:
        for r in range(_ROWS):
            for c in range(_COLS):
                cells = frozenset((r + dr, c + dc) for (dr, dc) in offs)
                if all(0 <= rr < _ROWS and 0 <= cc < _COLS for (rr, cc) in cells):
                    out.add(cells)
    return tuple(sorted(out, key=sorted))


_ZIGZAG_PLACEMENTS = _placements(_ZIGZAG_TEMPLATES)   # 20 on the 3x5 grid
_L_PLACEMENTS = _placements(_L_TEMPLATES)             # 32 on the 3x5 grid


def _field_tiles(p: PlayerState) -> frozenset:
    """The (row, col) set of board-grid FIELD tiles (card-fields excluded —
    they have no geometry; ruling 32)."""
    grid = p.farmyard.grid
    return frozenset(
        (r, c)
        for r in range(_ROWS) for c in range(_COLS)
        if grid[r][c].cell_type == CellType.FIELD
    )


def _zigzag_candidates(p: PlayerState) -> frozenset:
    """Every legal plow target cell that completes a zigzag: an ordinary legal
    plow cell (empty, non-enclosed, field-adjacent — ``_legal_plow_cells``)
    `c` such that for some translated template T, c is in T and the other 3
    cells of T are all existing FIELD tiles."""
    fields = _field_tiles(p)
    legal = set(_legal_plow_cells(p))
    out = set()
    for placement in _ZIGZAG_PLACEMENTS:
        missing = placement - fields
        if len(missing) == 1:
            (cell,) = missing
            if cell in legal:
                out.add(cell)
    return frozenset(out)


def _prereq(state: GameState, idx: int) -> bool:
    """"3 Fields in an "L" Shape": 3 board-grid field TILES forming a bent
    tromino (any of its 4 orientations), anywhere on the grid. An existence
    check — extra fields elsewhere don't hurt."""
    fields = _field_tiles(state.players[idx])
    return any(placement <= fields for placement in _L_PLACEMENTS)


def _variants(state: GameState, idx: int) -> list:
    """The wide on-play choice (zero surcharge on both routes): "plow" is
    offered only when a zigzag-completing legal plow cell exists (else pushing
    PendingPlow with an empty allowed_cells menu would dead-end); "skip" (plow
    0 fields — "you can") is always offered, so the list is never empty and
    the card is always playable when its base cost + prerequisite are."""
    routes = [("skip", Resources())]
    if _zigzag_candidates(state.players[idx]):
        routes.insert(0, ("plow", Resources()))
    return routes


def _on_play(state: GameState, idx: int, variant: str | None = None) -> GameState:
    """"plow" pushes a single-shot PendingPlow whose cell menu (allowed_cells)
    is exactly the zigzag-completing legal plow cells; "skip" plays the card
    without plowing. The card has already been passed to the opponent's hand
    by ``_execute_play_minor`` before this runs (passing minor)."""
    if variant == "plow":
        cells = tuple(sorted(_zigzag_candidates(state.players[idx])))
        return push(state, PendingPlow(
            player_idx=idx, initiated_by_id=f"card:{CARD_ID}",
            allowed_cells=cells))
    assert variant == "skip", variant
    return state


# Cost: 1 Wood; prerequisite: 3 fields in an L shape; no printed VP;
# PASSING (travels to the opponent).
register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1)),
    prereq=_prereq,
    passing_left=True,
    on_play=_on_play,
)

# The optional plow grant surfaces WIDE (CARD_ENGINE_IMPLEMENTATION.md §6): one
# play route per choice, "skip" always present so the list is never empty.
register_play_minor_variant(CARD_ID, _variants)


def _action_label(variant: str) -> str | None:
    """Web-UI label for the two play routes (terse/mechanical, matching the
    Double-Turn Plow labeler style)."""
    return {"plow": "plow a zigzag-completing field", "skip": "no plow"}.get(variant)


register_action_labeler(CARD_ID, _action_label)
