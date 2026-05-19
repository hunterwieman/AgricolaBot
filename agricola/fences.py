"""Universe of candidate pasture shapes for the Fencing action.

Bitmap conventions (cells only — edge bitmaps are introduced in TASK_6):
- Cell `(r, c)` ↔ bit `r * NUM_COLS + c` (row-major).
- A cell-set is a 15-bit integer.
- Adjacency is 4-neighbor (orthogonal) only.

The four universes (full, family, extended, restricted) are built once at
module import. See FENCE_IDEAS.md and CLAUDE.md for design rationale.
"""

from __future__ import annotations


NUM_ROWS, NUM_COLS = 3, 5
NUM_CELLS = NUM_ROWS * NUM_COLS  # 15

FULL_GRID_BM = (1 << NUM_CELLS) - 1


def _neighbor_bm(idx: int) -> int:
    """Bitmap of `idx`'s orthogonal in-grid neighbors."""
    r, c = divmod(idx, NUM_COLS)
    bm = 0
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < NUM_ROWS and 0 <= nc < NUM_COLS:
            bm |= 1 << (nr * NUM_COLS + nc)
    return bm


NEIGHBOR_BM: tuple[int, ...] = tuple(_neighbor_bm(i) for i in range(NUM_CELLS))


PERIMETER_BM: int = sum(
    1 << (r * NUM_COLS + c)
    for r in range(NUM_ROWS) for c in range(NUM_COLS)
    if r in (0, NUM_ROWS - 1) or c in (0, NUM_COLS - 1)
)


# Cells (1, 0) and (2, 0) are the two starting rooms — placed by `setup` in every
# game and never relocated by any current engine mechanic. Rules prohibit
# enclosing room cells, so no pasture in any reachable state includes either.
STARTING_ROOM_BM: int = (1 << (1 * NUM_COLS + 0)) | (1 << (2 * NUM_COLS + 0))


def _cells_of(bm: int) -> tuple[tuple[int, int], ...]:
    """Cells of `bm` in lex (row-major) order, as a tuple of (r, c) pairs.

    Doubles as the sort key for every universe enumerator: sorting bitmaps
    by `_cells_of` orders them lexicographically by their sorted cell-set,
    so shapes sharing a smaller-prefix come together and "extensions" of a
    prefix come before unrelated shapes whose smallest cell is later. This
    is more intuitive than bitmap-numeric order for human inspection of
    test output and trace logs.
    """
    return tuple(divmod(i, NUM_COLS) for i in range(NUM_CELLS) if bm & (1 << i))


PERIMETER_EDGE_COUNT_PER_CELL: tuple[int, ...] = tuple(
    (1 if r == 0 else 0)
    + (1 if r == NUM_ROWS - 1 else 0)
    + (1 if c == 0 else 0)
    + (1 if c == NUM_COLS - 1 else 0)
    for r in range(NUM_ROWS) for c in range(NUM_COLS)
)
# Sanity: corners contribute 2, edge cells 1, interior 0. Total over the full
# 3×5 grid = 16 perimeter edges (4 corners × 2 + 8 non-corner-perimeter × 1).


# ─── Part 2: UNIVERSE_FULL and UNIVERSE_FAMILY filters ───────────────────


def _is_connected(cells_bm: int) -> bool:
    """True iff the non-empty cell-set is orthogonally connected.

    BFS from the lowest-index cell in `cells_bm`, traversing only to cells
    in `cells_bm`. Connected iff the BFS visits every cell of `cells_bm`.

    Pre: `cells_bm != 0`.
    """
    first = (cells_bm & -cells_bm).bit_length() - 1   # index of lowest set bit
    visited = 1 << first
    frontier = visited
    while frontier:
        new_frontier = 0
        f = frontier
        while f:
            idx = (f & -f).bit_length() - 1
            new_frontier |= NEIGHBOR_BM[idx] & cells_bm & ~visited
            f &= f - 1                                # clear lowest set bit
        visited |= new_frontier
        frontier = new_frontier
    return visited == cells_bm


def _internal_fence_count(cells_bm: int) -> int:
    """Count of `cells_bm`'s boundary fence-edges that lie strictly inside the
    grid — i.e. edges between two in-grid cells, not edges between a grid-cell
    and "outside the farmyard"."""
    count = 0
    # Internal horizontal edges: between rows r-1 and r, for r in 1..NUM_ROWS-1.
    for r in range(1, NUM_ROWS):
        for c in range(NUM_COLS):
            above_in = bool(cells_bm & (1 << ((r - 1) * NUM_COLS + c)))
            below_in = bool(cells_bm & (1 << (r * NUM_COLS + c)))
            if above_in != below_in:
                count += 1
    # Internal vertical edges: between cols c-1 and c, for c in 1..NUM_COLS-1.
    for r in range(NUM_ROWS):
        for c in range(1, NUM_COLS):
            left_in = bool(cells_bm & (1 << (r * NUM_COLS + (c - 1))))
            right_in = bool(cells_bm & (1 << (r * NUM_COLS + c)))
            if left_in != right_in:
                count += 1
    return count


def _has_hole(cells_bm: int) -> bool:
    """True iff `cells_bm` topologically encloses at least one hole (donut)."""
    complement_bm = FULL_GRID_BM & ~cells_bm
    if complement_bm == 0:
        return False                                # cells_bm fills the grid; no hole.

    seed_bm = complement_bm & PERIMETER_BM
    if seed_bm == 0:
        # cells_bm covers every grid-perimeter cell yet leaves some interior cell
        # uncovered — that interior is enclosed by construction.
        return True

    # Flood-fill the complement starting from every perimeter-complement cell
    # simultaneously. Anything unreached is an enclosed pocket.
    visited = seed_bm
    frontier = seed_bm
    while frontier:
        new_frontier = 0
        f = frontier
        while f:
            idx = (f & -f).bit_length() - 1
            new_frontier |= NEIGHBOR_BM[idx] & complement_bm & ~visited
            f &= f - 1
        visited |= new_frontier
        frontier = new_frontier
    return visited != complement_bm


def _perimeter_fence_count(cells_bm: int) -> int:
    """Count of `cells_bm`'s boundary fence-edges that lie on the grid perimeter.

    A grid-perimeter edge is a boundary edge of an in-set cell that faces
    off-grid (top edge of row 0, bottom edge of last row, left edge of col 0,
    right edge of last col). Each in-set cell contributes 1 perimeter edge for
    each grid-edge it touches; corners contribute 2.
    """
    count = 0
    b = cells_bm
    while b:
        idx = (b & -b).bit_length() - 1
        count += PERIMETER_EDGE_COUNT_PER_CELL[idx]
        b &= b - 1
    return count


def _total_fence_count(cells_bm: int) -> int:
    """Total fence-edges (internal + grid-perimeter) on the boundary of `cells_bm`.

    Used by the `UNIVERSE_FAMILY` filter: must be ≤ 15 for any buildable pasture
    in Family game mode (no perimeter-fence card; player has 15 fences total)."""
    return _internal_fence_count(cells_bm) + _perimeter_fence_count(cells_bm)


def enumerate_universe_full() -> tuple[int, ...]:
    """All non-empty connected, simply-connected, internal-fence-≤-15 cell-set
    bitmaps that do not overlap starting-room cells. Lex-on-cells order
    (see `_cells_of` for the sort-key definition)."""
    bms = [
        bm for bm in range(1, 1 << NUM_CELLS)
        if (bm & STARTING_ROOM_BM) == 0
        and _is_connected(bm)
        and _internal_fence_count(bm) <= 15
        and not _has_hole(bm)
    ]
    return tuple(sorted(bms, key=_cells_of))


def enumerate_universe_family() -> tuple[int, ...]:
    """All non-empty connected, simply-connected, total-fences-≤-15 cell-set
    bitmaps that do not overlap starting-room cells. Lex-on-cells order.

    Rules-correct universe for Family game mode. Strict subset of UNIVERSE_FULL
    because the total-fence filter is strictly stronger than internal-only."""
    bms = [
        bm for bm in range(1, 1 << NUM_CELLS)
        if (bm & STARTING_ROOM_BM) == 0
        and _is_connected(bm)
        and _total_fence_count(bm) <= 15
        and not _has_hole(bm)
    ]
    return tuple(sorted(bms, key=_cells_of))


# ─── Part 3: Cell-scope constants and shape-category helpers ─────────────


ALL_CELLS = frozenset((r, c) for r in range(NUM_ROWS) for c in range(NUM_COLS))
STARTING_ROOMS = frozenset({(1, 0), (2, 0)})
ENCLOSABLE_CELLS = ALL_CELLS - STARTING_ROOMS                   # 13 cells (physically buildable)
PASTURE_CELLS = frozenset((r, c) for r in range(NUM_ROWS)
                                  for c in range(1, NUM_COLS))   # 12 cells: cols 1-4
NARROW_CELLS = frozenset((r, c) for r in range(NUM_ROWS)
                                 for c in range(2, NUM_COLS))    # 9 cells: cols 2-4


def _bm(cells) -> int:
    """Encode a cell-set (iterable of (r, c)) as a 15-bit bitmap."""
    return sum(1 << (r * NUM_COLS + c) for r, c in cells)


def _rect(r0: int, c0: int, rows: int, cols: int) -> frozenset:
    return frozenset((r, c) for r in range(r0, r0 + rows) for c in range(c0, c0 + cols))


def _enum_rects(rows: int, cols: int, scope: frozenset) -> list[frozenset]:
    """All `rows × cols` axis-aligned rectangles entirely within `scope`."""
    out = []
    for r0 in range(NUM_ROWS - rows + 1):
        for c0 in range(NUM_COLS - cols + 1):
            rect = _rect(r0, c0, rows, cols)
            if rect <= scope:
                out.append(rect)
    return out


def _enum_3cell_Ls(scope: frozenset) -> list[frozenset]:
    """All 3-cell L-shapes (2×2 minus one corner) entirely within `scope`."""
    return [square - {miss}
            for square in _enum_rects(2, 2, scope)
            for miss in square]


def _enum_3cell_Ls_2right_1left(scope: frozenset) -> list[frozenset]:
    """3-cell L's: two cells in the right column of a 2-col span + one in the left column."""
    out = []
    for r0 in range(NUM_ROWS - 1):
        for c0 in range(NUM_COLS - 1):
            right_pair = frozenset({(r0, c0 + 1), (r0 + 1, c0 + 1)})
            for left_cell in [(r0, c0), (r0 + 1, c0)]:
                L = right_pair | {left_cell}
                if L <= scope:
                    out.append(L)
    return out


def _enum_4cell_Ls(scope: frozenset) -> list[frozenset]:
    """All 4-cell L-shapes (3-cell line + 1 perpendicular at one end)."""
    out = []
    for r in range(NUM_ROWS):                                # horizontal lines
        for c in range(NUM_COLS - 2):
            line = frozenset({(r, c), (r, c + 1), (r, c + 2)})
            for er, ec in [(r-1, c), (r+1, c), (r-1, c+2), (r+1, c+2)]:
                if 0 <= er < NUM_ROWS and 0 <= ec < NUM_COLS:
                    L = line | {(er, ec)}
                    if L <= scope:
                        out.append(L)
    for c in range(NUM_COLS):                                # vertical lines
        for r in range(NUM_ROWS - 2):
            line = frozenset({(r, c), (r + 1, c), (r + 2, c)})
            for er, ec in [(r, c-1), (r, c+1), (r+2, c-1), (r+2, c+1)]:
                if 0 <= er < NUM_ROWS and 0 <= ec < NUM_COLS:
                    L = line | {(er, ec)}
                    if L <= scope:
                        out.append(L)
    return out


def _adjacents_of(cells: frozenset) -> set:
    """Orthogonal in-grid neighbors of `cells` not themselves in `cells`."""
    out = set()
    for (r, c) in cells:
        for (dr, dc) in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < NUM_ROWS and 0 <= nc < NUM_COLS and (nr, nc) not in cells:
                out.add((nr, nc))
    return out


def _enum_5cell_2x2_plus1(square_scope: frozenset, extra_scope: frozenset) -> list[frozenset]:
    """2×2 (cells in `square_scope`) + one orthogonally adjacent cell (in `extra_scope`)."""
    return [square | {extra}
            for square in _enum_rects(2, 2, square_scope)
            for extra in _adjacents_of(square)
            if extra in extra_scope]


def _enum_6cell_2x2_plus2(square_scope: frozenset, extra_scope: frozenset) -> list[frozenset]:
    """2×2 + two cells, both orthogonally adjacent to the original 2×2 square.

    Deduplicated — the same 6-cell shape can arise from different 2×2 decompositions
    (e.g. a 2×3 rectangle, whose left 2×2 and right 2×2 both qualify).
    """
    out = set()
    for square in _enum_rects(2, 2, square_scope):
        adjs = sorted(a for a in _adjacents_of(square) if a in extra_scope)
        for i in range(len(adjs)):
            for j in range(i + 1, len(adjs)):
                out.add(square | {adjs[i], adjs[j]})
    return list(out)


def enumerate_universe_restricted() -> tuple[int, ...]:
    """Strategist-curated restricted universe. Lex-on-cells order."""
    shapes: set[frozenset] = set()

    # 1-2. 1×1 and 2×1 (vertical) on PASTURE_CELLS.
    shapes.update(_enum_rects(1, 1, PASTURE_CELLS))
    shapes.update(_enum_rects(2, 1, PASTURE_CELLS))

    # 3. 1×2 (horizontal) on NARROW_CELLS only.
    shapes.update(_enum_rects(1, 2, NARROW_CELLS))

    # 4. 3×1 (vertical) on PASTURE_CELLS.
    shapes.update(_enum_rects(3, 1, PASTURE_CELLS))

    # 5. 1×3 (horizontal) on NARROW_CELLS only.
    shapes.update(_enum_rects(1, 3, NARROW_CELLS))

    # 6. All 3-cell L's on NARROW_CELLS.
    shapes.update(_enum_3cell_Ls(NARROW_CELLS))

    # 7. Additional 3-cell L's with two cells in the right column and one in
    #    the left, on PASTURE_CELLS. Those entirely in NARROW_CELLS are already
    #    in category 6; duplicates are absorbed by set semantics.
    shapes.update(_enum_3cell_Ls_2right_1left(PASTURE_CELLS))

    # 8. All 2×2 on PASTURE_CELLS.
    shapes.update(_enum_rects(2, 2, PASTURE_CELLS))

    # 9. All 3×2 on NARROW_CELLS.
    shapes.update(_enum_rects(3, 2, NARROW_CELLS))

    # 10. All 2×3 on PASTURE_CELLS.
    shapes.update(_enum_rects(2, 3, PASTURE_CELLS))

    # 11. Four named 4-cell L-shapes.
    shapes.add(frozenset({(0, 2), (0, 3), (0, 4), (1, 2)}))
    shapes.add(frozenset({(2, 2), (2, 3), (2, 4), (1, 2)}))
    shapes.add(frozenset({(0, 3), (0, 4), (1, 4), (2, 4)}))
    shapes.add(frozenset({(2, 3), (0, 4), (1, 4), (2, 4)}))

    # 12. All 2×4 on PASTURE_CELLS.
    shapes.update(_enum_rects(2, 4, PASTURE_CELLS))

    # 13. The 3×3 covering NARROW_CELLS exactly.
    shapes.add(NARROW_CELLS)

    # 14. The 3×4 covering PASTURE_CELLS exactly.
    shapes.add(PASTURE_CELLS)

    # 15. Four 8-cell shapes: NARROW_CELLS minus each of its four corners.
    for corner in [(0, 2), (2, 2), (0, 4), (2, 4)]:
        shapes.add(NARROW_CELLS - {corner})

    # 16. All 5-cell 2×2-plus-1 shapes. Extra cell may be (0, 0) per design
    #     conversation; the square itself must be on PASTURE_CELLS.
    shapes.update(_enum_5cell_2x2_plus1(
        square_scope=PASTURE_CELLS, extra_scope=ENCLOSABLE_CELLS,
    ))

    # 17. Two ad-hoc shapes the user added explicitly. Also present in
    #     UNIVERSE_EXTENDED.
    shapes.add(PASTURE_CELLS - {(0, 1)})                            # 11-cell
    shapes.add(PASTURE_CELLS - {(0, 1), (0, 2)})                    # 10-cell

    return tuple(sorted((_bm(s) for s in shapes), key=_cells_of))


def enumerate_universe_extended() -> tuple[int, ...]:
    """Strategist-curated extended universe (relaxations over restricted).
    Lex-on-cells order."""
    shapes: set[frozenset] = set()

    shapes.update(_enum_rects(1, 1, PASTURE_CELLS))
    shapes.update(_enum_rects(2, 1, PASTURE_CELLS))
    shapes.update(_enum_rects(1, 2, PASTURE_CELLS))                # narrow → pasture
    shapes.update(_enum_rects(3, 1, PASTURE_CELLS))
    shapes.update(_enum_rects(1, 3, PASTURE_CELLS))                # narrow → pasture
    shapes.update(_enum_3cell_Ls(PASTURE_CELLS))                   # subsumes 2-right + 1-left
    shapes.update(_enum_rects(2, 2, PASTURE_CELLS))
    shapes.update(_enum_rects(3, 2, PASTURE_CELLS))                # narrow → pasture
    shapes.update(_enum_rects(2, 3, PASTURE_CELLS))
    shapes.update(_enum_4cell_Ls(PASTURE_CELLS))                   # all 4-cell L's
    shapes.update(_enum_rects(2, 4, PASTURE_CELLS))
    shapes.update(_enum_rects(3, 3, PASTURE_CELLS))                # all 3×3 sub-rectangles
    shapes.add(PASTURE_CELLS)                                      # the full 3×4

    # 3×3 sub-rectangle minus a corner (across both 3×3's in PASTURE_CELLS).
    for square in _enum_rects(3, 3, PASTURE_CELLS):
        rs = sorted({r for r, _ in square})
        cs = sorted({c for _, c in square})
        for corner in [(rs[0], cs[0]), (rs[0], cs[-1]),
                       (rs[-1], cs[0]), (rs[-1], cs[-1])]:
            shapes.add(square - {corner})

    # 5-cell 2×2 + 1 (unchanged from restricted).
    shapes.update(_enum_5cell_2x2_plus1(
        square_scope=PASTURE_CELLS, extra_scope=ENCLOSABLE_CELLS,
    ))

    # 6-cell 2×2 + 2 (new in extended). Both extras must be orthogonally
    # adjacent to the 2×2 square (the user-confirmed reading).
    shapes.update(_enum_6cell_2x2_plus2(
        square_scope=PASTURE_CELLS, extra_scope=ENCLOSABLE_CELLS,
    ))

    # Ad-hoc shapes the user added explicitly. Also present in UNIVERSE_RESTRICTED.
    shapes.add(PASTURE_CELLS - {(0, 1)})                            # 11-cell
    shapes.add(PASTURE_CELLS - {(0, 1), (0, 2)})                    # 10-cell

    return tuple(sorted((_bm(s) for s in shapes), key=_cells_of))


# ─── Part 4: Module-level universe constants and size-print entry point ──


UNIVERSE_FULL: tuple[int, ...] = enumerate_universe_full()
UNIVERSE_FULL_SET: frozenset[int] = frozenset(UNIVERSE_FULL)

UNIVERSE_FAMILY: tuple[int, ...] = enumerate_universe_family()
UNIVERSE_FAMILY_SET: frozenset[int] = frozenset(UNIVERSE_FAMILY)

UNIVERSE_EXTENDED: tuple[int, ...] = enumerate_universe_extended()
UNIVERSE_EXTENDED_SET: frozenset[int] = frozenset(UNIVERSE_EXTENDED)

UNIVERSE_RESTRICTED: tuple[int, ...] = enumerate_universe_restricted()
UNIVERSE_RESTRICTED_SET: frozenset[int] = frozenset(UNIVERSE_RESTRICTED)


if __name__ == "__main__":
    # Run `python -m agricola.fences` to print sizes of each universe.
    # Used during step 9 to pin the placeholder `test_size_is_recorded`
    # lower bounds to exact values.
    print(f"UNIVERSE_FULL:       {len(UNIVERSE_FULL):>5,} entries")
    print(f"UNIVERSE_FAMILY:     {len(UNIVERSE_FAMILY):>5,} entries")
    print(f"UNIVERSE_EXTENDED:   {len(UNIVERSE_EXTENDED):>5,} entries")
    print(f"UNIVERSE_RESTRICTED: {len(UNIVERSE_RESTRICTED):>5,} entries")
