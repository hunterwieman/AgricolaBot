# Task 6_pre — Fencing Universe Enumeration

A precursor to the broader Fencing implementation (`TASK_6.md`). This task stands up the precomputed universe of pasture shapes that `legal_actions` will iterate over at Fencing-time, validates the layered-universe design from `FENCE_IDEAS.md`, and ships the supporting module + tests. It does *not* introduce any new pending types, commit actions, legality predicates, resolution code, or engine wiring — all of that lands in `TASK_6.md` and consumes the universes built here.

The document is split into:

- **Part 1 — Module layout and conventions.** Bitmap encoding for cells and edges; precomputed neighbor / perimeter / starting-room bitmaps; per-cell perimeter-edge counts.
- **Part 2 — The `UNIVERSE_FULL` and `UNIVERSE_FAMILY` filters.** Connectivity, fence-count (two variants: internal-only for FULL, total for FAMILY), donut detection, starting-room overlap.
- **Part 3 — Restricted and extended universes.** Cell-scope constants, shape-category helpers, and the two strategist-curated enumerators.
- **Part 4 — Module-level universe constants and the size-print entry point.** Eager construction at module import; `__main__` block for size measurement.
- **Part 5 — Tests.** New file `tests/test_fences.py`.
- **Part 6 — Documentation updates.** CLAUDE.md edits.
- **Part 7 — Order of work.**
- **Part 8 — Acceptance criteria.**
- **Part 9 — Open questions deferred to `TASK_6`.**

After this task, `agricola/fences.py` exists and exports four universes; the broader engine remains unchanged (`step()` still raises `NotImplementedError` for `PlaceWorker(space="fencing")` and `PlaceWorker(space="farm_redevelopment")`).

See **`FENCE_IDEAS.md`** for the broader design rationale — especially Section 3 (enumeration strategy: fixed-list filtering with bitmaps), Section 4 (the unified pasture-commit design), and Section 6 (open sub-questions). The four-filter formulation and the layered-universe design were settled in the design conversation that produced this task; the rationale is captured in CLAUDE.md once this task lands.

---

## Scope

| Component | Status |
|---|---|
| `agricola/fences.py` — bitmap conventions, four filters, four enumerators (full / family / extended / restricted), module-level constants, `__main__` size printer | new |
| `tests/test_fences.py` — filter unit tests, universe construction tests, containment-chain validation | new |
| CLAUDE.md — directory tree, file descriptions, status table | updated |

**Out of scope** (deferred to `TASK_6.md`):

- `PendingBuildFences` dataclass, `CommitBuildPasture` action class, and the related changes to `pending.py` / `actions.py`.
- `_can_fence` predicate, `_enumerate_pending_build_fences` enumerator, `NON_ATOMIC_LEGALITY` / `PENDING_ENUMERATORS` registration.
- `_initiate_fencing`, `_execute_build_pasture` in `resolution.py`; `NONATOMIC_HANDLERS` / `COMMIT_SUBACTION_HANDLERS` registration.
- Removal of the `fencing` `NotImplementedError` in `engine.py`.
- Per-entry metadata (boundary fence-edge bitmaps, cell-adjacency bitmap, frozenset-of-cells for `CommitBuildPasture` construction).
- Per-commit cost-modifier extension registry.
- The 4th cost-handling bucket entry in CLAUDE.md.

---

## Motivation

Pasture-build legality during a Fencing action is enumerated against a precomputed universe of candidate cell-sets. Three reasons to do this enumeration up-front, in its own task:

1. **It is the load-bearing design decision behind Fencing.** The action representation the policy network will learn over, and that MCTS will branch on, is the set of bitmaps returned by these enumerators. Building and validating it before any engine wiring lets us settle the shape decisively.
2. **It is large enough to merit its own validation surface.** ~1000–2000 entries in the full universe across four interacting filters; ~100 entries in the restricted set across 17 shape categories. Bugs in either filter or category logic are silent (the universe is just smaller or larger than expected), so an isolated test file catches them at the right granularity.
3. **It is independent.** The module imports only `from __future__ import annotations` and stdlib. Nothing else in the engine touches it until `TASK_6` lands. Splitting the task off lets it land cleanly with no engine-wide changes.

The layered design (`UNIVERSE_FULL` baseline + `UNIVERSE_FAMILY` Family-mode baseline + `UNIVERSE_EXTENDED` policy-output space + `UNIVERSE_RESTRICTED` runtime default) is built directly per `FENCE_IDEAS.md` Section 3. `UNIVERSE_FULL` is the mechanically-derived rules-permissible baseline accommodating the perimeter-fence card (internal-fence count ≤ 15). `UNIVERSE_FAMILY` is the rules-correct universe for the currently-implemented Family game mode (no perimeter-fence card; total-fence count ≤ 15). `UNIVERSE_RESTRICTED` is the strategist-curated set used at legality-check time. `UNIVERSE_EXTENDED` sits between RESTRICTED and FAMILY as the policy output space, allowing relaxation without retraining if the restricted set turns out to omit a move. Containment chain: `RESTRICTED ⊆ EXTENDED ⊆ FAMILY ⊆ FULL`.

---

# Part 1 — Module layout and conventions

## Bitmap encoding

Three independent bit-indexed spaces:

| Space | Width | Indexing |
|---|---|---|
| Cells | 15 bits | Cell `(r, c)` → bit `r * NUM_COLS + c` (row-major) |
| Horizontal edges | 20 bits | Edge `horizontal_fences[r][c]` → bit `r * NUM_COLS + c`. `r` in `0..NUM_ROWS`, `c` in `0..NUM_COLS-1`. |
| Vertical edges | 18 bits | Edge `vertical_fences[r][c]` → bit `r * (NUM_COLS+1) + c`. `r` in `0..NUM_ROWS-1`, `c` in `0..NUM_COLS`. |

For TASK_6_pre, only the cell encoding is used (filters operate on cell bitmaps; per-entry edge metadata is deferred to `TASK_6`). The horizontal/vertical edge encodings are noted here for forward consistency.

Cells use the same `(r, c) → r * NUM_COLS + c` mapping that `Farmyard.grid` uses elsewhere in the engine. No transformation is needed when bridging between `(r, c)` tuples and bitmaps.

## Precomputed constants and helpers

Five module-level constants and one helper, all derived from grid geometry alone (3×5), all built once at import:

- `NEIGHBOR_BM: tuple[int, ...]` — length-15. `NEIGHBOR_BM[idx]` is a 15-bit bitmap of cell `idx`'s in-grid orthogonal neighbors. Lookup table for connectivity / flood-fill BFS.
- `PERIMETER_BM: int` — 15-bit bitmap of grid-perimeter cells (any cell with `r ∈ {0, NUM_ROWS-1}` or `c ∈ {0, NUM_COLS-1}`). Used by `_has_hole` as the seed-cell source for complement flood-fill.
- `FULL_GRID_BM: int` — `(1 << NUM_CELLS) - 1`, all 15 bits set. Used to compute the complement bitmap for `_has_hole`.
- `STARTING_ROOM_BM: int` — `(1 << 5) | (1 << 10)`, the bits for cells `(1, 0)` and `(2, 0)`. Used by the starting-room overlap filter.
- `PERIMETER_EDGE_COUNT_PER_CELL: tuple[int, ...]` — length-15. For each cell, the count of its 4 cell-edges that lie on the grid perimeter (0 for interior cells, 1 for non-corner perimeter cells, 2 for corner cells). Used by `_perimeter_fence_count`.
- `_cells_of(bm) -> tuple[(r, c), ...]` — return the cells of a bitmap in lex (row-major) order. Doubles as the sort key for every universe enumerator (see Part 4 paragraph on iteration order).

## Code

**`agricola/fences.py`**:

```python
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
```

---

# Part 2 — The `UNIVERSE_FULL` and `UNIVERSE_FAMILY` filters

Both universes share three filters and differ only on the fence-count filter:

| # | Filter | `UNIVERSE_FULL` | `UNIVERSE_FAMILY` |
|---|---|---|---|
| 1 | No starting-room overlap (`bm & STARTING_ROOM_BM == 0`) | required | required |
| 2 | Orthogonal connectivity (BFS visits every cell) | required | required |
| 3 | Fence-count cap | `_internal_fence_count(bm) ≤ 15` | `_total_fence_count(bm) ≤ 15` |
| 4 | No enclosed holes (complement flood-fill is exhaustive) | required | required |

*Rationale for the FULL fence-count rule:* the player has 15 fence pieces in supply; a known full-game card grants *additional* pieces only for grid-perimeter placements. So pastures whose boundary needs more than 15 *internal* pieces are unbuildable regardless of cards, while pastures with high perimeter contribution may still be buildable once the card lands.

*Rationale for the FAMILY fence-count rule:* the Family game has no such card. Total fences (internal + perimeter) must be ≤ 15. This is strictly stronger than the FULL rule because total ≥ internal, so `UNIVERSE_FAMILY ⊆ UNIVERSE_FULL`. FAMILY is the rules-correct universe for the engine as currently scoped.

The filters are applied in the order above. The starting-room check is the cheapest (one bitwise AND + comparison), so it short-circuits the heavier filters when it fails.

## Change 2.1 — `_is_connected`

```python
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
```

Bit-tricks: `(x & -x)` isolates the lowest set bit of `x`, and its `bit_length() - 1` gives that bit's index. `x &= x - 1` clears that bit. Both are standard idioms for set-bit iteration on Python's arbitrary-precision ints.

The function is undefined on `cells_bm == 0` (would shift by -1). The universe loop in `enumerate_universe_full` starts at `bm = 1`, so 0 is never passed.

## Change 2.2 — `_internal_fence_count`

```python
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
```

The 22 internal edges of the 3×5 grid are: 10 horizontal (`r ∈ 1..2` × `c ∈ 0..4`) + 12 vertical (`r ∈ 0..2` × `c ∈ 1..4`). For each, we test whether the two adjacent cells differ in membership in `cells_bm`. If they do, the edge is on the cell-set's boundary.

## Change 2.3 — `_has_hole`

```python
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
```

The conceptual move: imagine the 3×5 grid embedded in the infinite plane, with a virtual "outside" cell connected to every grid-perimeter cell. A grid cell not in `cells_bm` is "open to outside" iff there's a path through the complement to a perimeter cell. Cells that can't reach the perimeter through the complement are surrounded by `cells_bm` cells — an enclosed hole.

## Change 2.4 — `enumerate_universe_full`

```python
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
```

The four filters are short-circuit-and'd in the order: cheapest check first (starting-room overlap), then connectivity (BFS), then internal-fence count (linear scan of 22 edges), then donut detection (second BFS). For module-import cost, this ordering matters: most candidate bitmaps fail the cheap checks early. The sort runs once at the end over the survivors.

## Change 2.5 — `_perimeter_fence_count` and `_total_fence_count`

```python
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
```

The disjointness invariant: every boundary edge of `cells_bm` is either internal (between two in-grid cells of differing membership) OR grid-perimeter (between an in-set cell and off-grid), never both. So `_total_fence_count = _internal_fence_count + _perimeter_fence_count` is exact, not approximate.

## Change 2.6 — `enumerate_universe_family`

```python
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
```

Same four-filter short-circuit structure as `enumerate_universe_full`. The single difference: filter 3 swaps `_internal_fence_count(bm) <= 15` for `_total_fence_count(bm) <= 15`.

---

# Part 3 — Restricted and extended universes

## Cell-scope constants

```python
ALL_CELLS = frozenset((r, c) for r in range(NUM_ROWS) for c in range(NUM_COLS))
STARTING_ROOMS = frozenset({(1, 0), (2, 0)})
ENCLOSABLE_CELLS = ALL_CELLS - STARTING_ROOMS                   # 13 cells (physically buildable)
PASTURE_CELLS = frozenset((r, c) for r in range(NUM_ROWS)
                                  for c in range(1, NUM_COLS))   # 12 cells: cols 1-4
NARROW_CELLS = frozenset((r, c) for r in range(NUM_ROWS)
                                 for c in range(2, NUM_COLS))    # 9 cells: cols 2-4
```

`PASTURE_CELLS` is the user's `legal_cells` from the design conversation — column 0 is excluded by strategic preference, *not* by rules (cell `(0, 0)` is rules-legal but strategically a horrible decision). `NARROW_CELLS` (cols 2-4) is the tighter sub-grid used in the original sketch for several shape categories.

## Shape-category helpers

```python
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
    """2×2 + two cells, **both** orthogonally adjacent to the original 2×2 square.

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
```

## Change 3.1 — `enumerate_universe_restricted`

Seventeen shape categories per the design conversation (16 from the original sketch plus the two ad-hoc shapes the user requested be present in both universes):

```python
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
```

## Change 3.2 — `enumerate_universe_extended`

Same structure as restricted with the following changes per the design conversation:

- Categories 3, 5, 6, 9 lose their `NARROW_CELLS` restriction (use `PASTURE_CELLS` instead).
- Category 7 is subsumed by category 6 under the relaxed scope; the explicit `_enum_3cell_Ls_2right_1left` call is removed (its outputs are a strict subset of `_enum_3cell_Ls(PASTURE_CELLS)`).
- Category 11 replaces the four named 4-cell L's with `_enum_4cell_Ls(PASTURE_CELLS)`.
- Category 13 replaces the single 3×3 with all 3×3 sub-rectangles in `PASTURE_CELLS` (= 2 shapes).
- Category 15 replaces "narrow minus a corner" with "every 3×3 sub-rectangle in `PASTURE_CELLS` minus each of its four corners" (= 8 shapes).
- A new category for 6-cell 2×2-plus-2 shapes is added.
- The same two ad-hoc shapes as restricted-category 17 (11-cell `PASTURE_CELLS - {(0, 1)}` and 10-cell `PASTURE_CELLS - {(0, 1), (0, 2)}`) are included.

```python
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
```

---

# Part 4 — Module-level universe constants and the size-print entry point

At the bottom of `agricola/fences.py`, after all the enumerators are defined:

```python
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
```

Each universe is exported as a parallel `(tuple, frozenset)` pair: the tuple gives deterministic lex-on-cells-ordered iteration (see `_cells_of`), the frozenset gives O(1) membership lookup. `TASK_6`'s enumerator will consume one of the tuples for iteration and use the corresponding set for canonicalization-via-complement-lookup.

The `__main__` block runs only when `agricola.fences` is invoked as a script (e.g. `python -m agricola.fences`). It does not fire on `import agricola.fences` — module-level imports stay silent.

Module-import cost is dominated by `enumerate_universe_full` and `enumerate_universe_family`, each a candidate-by-candidate scan of 32,767 bitmaps with up to four bitwise filters each. Expected total module-import time: a few hundred milliseconds (pin via measurement during step 3 / step 6; if unacceptably slow, the easy optimization is precomputing the universes once to disk and loading at import — deferred to `TASK_6` if needed).

---

# Part 5 — Tests

Create `tests/test_fences.py`. Test groups:

- Filter unit tests (one class per filter).
- Universe construction tests (one class per universe).
- Containment-chain validation.

## Code

```python
"""Tests for agricola/fences.py — bitmap conventions, filters, and the four
layered pasture-shape universes."""

import pytest

from agricola.fences import (
    NUM_ROWS, NUM_COLS, NUM_CELLS,
    NEIGHBOR_BM, PERIMETER_BM, FULL_GRID_BM, STARTING_ROOM_BM,
    PERIMETER_EDGE_COUNT_PER_CELL,
    ALL_CELLS, STARTING_ROOMS, ENCLOSABLE_CELLS,
    PASTURE_CELLS, NARROW_CELLS,
    _bm, _cells_of,
    _is_connected, _internal_fence_count,
    _perimeter_fence_count, _total_fence_count,
    _has_hole,
    UNIVERSE_FULL, UNIVERSE_FULL_SET,
    UNIVERSE_FAMILY, UNIVERSE_FAMILY_SET,
    UNIVERSE_EXTENDED, UNIVERSE_EXTENDED_SET,
    UNIVERSE_RESTRICTED, UNIVERSE_RESTRICTED_SET,
)


# ─── Constants and conventions ─────────────────────────────────────────

class TestGridConstants:
    def test_grid_dimensions(self):
        assert NUM_ROWS == 3
        assert NUM_COLS == 5
        assert NUM_CELLS == 15

    def test_full_grid_bm(self):
        assert FULL_GRID_BM == (1 << 15) - 1

    def test_starting_room_bm_covers_1_0_and_2_0(self):
        assert STARTING_ROOM_BM == (1 << 5) | (1 << 10)
        assert STARTING_ROOM_BM & (1 << (1 * NUM_COLS + 0))     # (1, 0)
        assert STARTING_ROOM_BM & (1 << (2 * NUM_COLS + 0))     # (2, 0)

    def test_perimeter_bm_includes_corners_excludes_center(self):
        # Corners: (0,0), (0,4), (2,0), (2,4).
        for r, c in [(0, 0), (0, 4), (2, 0), (2, 4)]:
            assert PERIMETER_BM & (1 << (r * NUM_COLS + c))
        # Interior cells (1, 1), (1, 2), (1, 3) are not on the perimeter.
        for r, c in [(1, 1), (1, 2), (1, 3)]:
            assert not (PERIMETER_BM & (1 << (r * NUM_COLS + c)))

    def test_neighbor_bm_corner(self):
        # (0, 0): neighbors are (0, 1) and (1, 0).
        assert NEIGHBOR_BM[0] == (1 << 1) | (1 << 5)

    def test_neighbor_bm_center_interior(self):
        # (1, 2): neighbors are (0, 2), (2, 2), (1, 1), (1, 3).
        idx = 1 * NUM_COLS + 2
        expected = (1 << (0 * NUM_COLS + 2)) | (1 << (2 * NUM_COLS + 2)) \
                 | (1 << (1 * NUM_COLS + 1)) | (1 << (1 * NUM_COLS + 3))
        assert NEIGHBOR_BM[idx] == expected


# ─── Filter unit tests ─────────────────────────────────────────────────

class TestIsConnected:
    def test_single_cell(self):
        assert _is_connected(1)

    def test_two_adjacent_horizontal(self):
        # (0, 0) and (0, 1).
        assert _is_connected((1 << 0) | (1 << 1))

    def test_two_adjacent_vertical(self):
        # (0, 0) and (1, 0).
        assert _is_connected((1 << 0) | (1 << 5))

    def test_two_non_adjacent_same_row(self):
        # (0, 0) and (0, 2): not adjacent.
        assert not _is_connected((1 << 0) | (1 << 2))

    def test_l_shape(self):
        # (0, 0), (0, 1), (1, 0).
        assert _is_connected((1 << 0) | (1 << 1) | (1 << 5))

    def test_disconnected_corners(self):
        # (0, 0) and (2, 4).
        assert not _is_connected((1 << 0) | (1 << 14))

    def test_two_diagonal_cells(self):
        # (0, 0) and (1, 1): orthogonally non-adjacent (diagonal).
        assert not _is_connected((1 << 0) | (1 << 6))


class TestInternalFenceCount:
    def test_corner_cell(self):
        # (0, 0): boundary edges are top, left, right, bottom.
        # Top + left are grid-perimeter; right + bottom are internal.
        # → 2 internal boundary edges.
        assert _internal_fence_count(1) == 2

    def test_center_cell(self):
        # (1, 1): all 4 boundary edges are internal.
        bm = 1 << (1 * NUM_COLS + 1)
        assert _internal_fence_count(bm) == 4

    def test_edge_cell(self):
        # (0, 1): top is perimeter; left, right, bottom are internal. → 3.
        assert _internal_fence_count(1 << 1) == 3

    def test_full_grid(self):
        # Every cell in the set. Every internal edge has both sides in the set
        # → none lie on the boundary.
        assert _internal_fence_count(FULL_GRID_BM) == 0

    def test_full_grid_minus_center(self):
        # Grid minus (1, 2): the 4 boundary edges of (1, 2) are all internal.
        bm = FULL_GRID_BM & ~(1 << (1 * NUM_COLS + 2))
        assert _internal_fence_count(bm) == 4

    def test_2x2_at_origin(self):
        # 2×2 at (0, 0). Internal boundary edges: right side (2 cells) + bottom
        # side (2 cells). The right edges are between cols 1-2; the bottom edges
        # are between rows 1-2. → 4 internal boundary edges.
        bm = (1 << 0) | (1 << 1) | (1 << 5) | (1 << 6)
        assert _internal_fence_count(bm) == 4


class TestPerimeterEdgeCountPerCell:
    def test_corner_cells_have_two(self):
        for r, c in [(0, 0), (0, NUM_COLS - 1), (NUM_ROWS - 1, 0), (NUM_ROWS - 1, NUM_COLS - 1)]:
            assert PERIMETER_EDGE_COUNT_PER_CELL[r * NUM_COLS + c] == 2

    def test_non_corner_perimeter_cells_have_one(self):
        # Top/bottom row non-corners, left/right col non-corners.
        for r, c in [(0, 1), (0, 2), (0, 3), (2, 1), (2, 2), (2, 3), (1, 0), (1, 4)]:
            assert PERIMETER_EDGE_COUNT_PER_CELL[r * NUM_COLS + c] == 1

    def test_interior_cells_have_zero(self):
        for r, c in [(1, 1), (1, 2), (1, 3)]:
            assert PERIMETER_EDGE_COUNT_PER_CELL[r * NUM_COLS + c] == 0

    def test_grid_total_is_16(self):
        # 4 corners × 2 + 8 non-corner perimeter cells × 1 = 16.
        assert sum(PERIMETER_EDGE_COUNT_PER_CELL) == 16


class TestPerimeterFenceCount:
    def test_corner_cell(self):
        # (0, 0): 2 grid-perimeter edges (top + left).
        assert _perimeter_fence_count(1) == 2

    def test_interior_cell(self):
        # (1, 1): no grid-perimeter edges.
        assert _perimeter_fence_count(1 << (1 * NUM_COLS + 1)) == 0

    def test_edge_cell(self):
        # (0, 1): 1 grid-perimeter edge (top only).
        assert _perimeter_fence_count(1 << 1) == 1

    def test_full_grid(self):
        # Every cell in the set; every grid-perimeter edge is on the boundary.
        assert _perimeter_fence_count(FULL_GRID_BM) == 16

    def test_pasture_cells_3x4(self):
        # PASTURE_CELLS = cols 1-4. Perimeter edges contributed:
        #   - top edges of row 0 cols 1-4: 4
        #   - bottom edges of row 2 cols 1-4: 4
        #   - right edges of col 4 (3 cells): 3
        # Total = 11. (No left perimeter contribution because col 0 isn't in set.)
        assert _perimeter_fence_count(_bm(PASTURE_CELLS)) == 11


class TestTotalFenceCount:
    def test_corner_cell(self):
        # (0, 0): 2 internal + 2 perimeter = 4.
        assert _total_fence_count(1) == 4

    def test_interior_cell(self):
        # (1, 1): 4 internal + 0 perimeter = 4.
        assert _total_fence_count(1 << (1 * NUM_COLS + 1)) == 4

    def test_full_grid(self):
        # 0 internal + 16 perimeter = 16. (> 15 → not in UNIVERSE_FAMILY.)
        assert _total_fence_count(FULL_GRID_BM) == 16

    def test_pasture_cells_3x4(self):
        # 3 internal + 11 perimeter = 14. (≤ 15 → in UNIVERSE_FAMILY.)
        assert _total_fence_count(_bm(PASTURE_CELLS)) == 14

    def test_total_is_internal_plus_perimeter(self):
        # Sanity: the additive identity should hold for any bitmap.
        for bm in [1, 1 << 7, _bm(PASTURE_CELLS), _bm(NARROW_CELLS), FULL_GRID_BM]:
            assert _total_fence_count(bm) == _internal_fence_count(bm) + _perimeter_fence_count(bm)


class TestHasHole:
    def test_single_cell_no_hole(self):
        assert not _has_hole(1)

    def test_l_shape_no_hole(self):
        bm = (1 << 0) | (1 << 1) | (1 << 5)
        assert not _has_hole(bm)

    def test_donut_around_center_has_hole(self):
        # Grid minus (1, 2): the cell (1, 2) is fully surrounded.
        bm = FULL_GRID_BM & ~(1 << (1 * NUM_COLS + 2))
        assert _has_hole(bm)

    def test_full_grid_no_hole(self):
        assert not _has_hole(FULL_GRID_BM)

    def test_top_and_bottom_rows_no_hole(self):
        # Top row and bottom row only (two disconnected horizontal lines, but
        # _has_hole works independently of connectivity). Middle row is in the
        # complement, with (1, 0) and (1, 4) on the grid perimeter — flood-fill
        # from them visits the rest of the middle row, so no enclosed pocket.
        bm = 0
        for c in range(NUM_COLS):
            bm |= 1 << (0 * NUM_COLS + c)
            bm |= 1 << (2 * NUM_COLS + c)
        assert not _has_hole(bm)

    def test_donut_in_pasture_cells_has_hole(self):
        # PASTURE_CELLS minus (1, 2): a donut whose complement *does* contain
        # perimeter cells ((0, 0), (1, 0), (2, 0)), so the BFS branch fires
        # — but (1, 2) is unreachable from those perimeter cells through the
        # complement, so a hole is correctly detected. Distinct from
        # `test_donut_around_center_has_hole`, which triggers the `seed_bm == 0`
        # short-circuit instead.
        bm = _bm(PASTURE_CELLS - {(1, 2)})
        assert _has_hole(bm)


# ─── Universe construction tests ───────────────────────────────────────

class TestUniverseFull:
    def test_non_empty(self):
        assert len(UNIVERSE_FULL) > 0

    def test_no_duplicates(self):
        assert len(UNIVERSE_FULL) == len(UNIVERSE_FULL_SET)

    def test_lex_sorted(self):
        # Universe order is lex-on-cells, NOT bitmap-numeric.
        assert list(UNIVERSE_FULL) == sorted(UNIVERSE_FULL, key=_cells_of)

    def test_set_matches_tuple(self):
        assert UNIVERSE_FULL_SET == frozenset(UNIVERSE_FULL)

    def test_every_entry_passes_all_filters(self):
        for bm in UNIVERSE_FULL:
            assert (bm & STARTING_ROOM_BM) == 0
            assert _is_connected(bm)
            assert _internal_fence_count(bm) <= 15
            assert not _has_hole(bm)

    def test_excludes_starting_room_cells(self):
        for bm in UNIVERSE_FULL:
            assert (bm & STARTING_ROOM_BM) == 0

    def test_excludes_full_grid(self):
        # The 15-cell-fills-everything entry overlaps starting rooms → excluded.
        assert FULL_GRID_BM not in UNIVERSE_FULL_SET

    def test_excludes_donut(self):
        # PASTURE_CELLS minus (1, 2): a donut whose only filter rejection is
        # the `_has_hole` check (no starting-room overlap, connected, internal
        # fences ≤ 15). Cleanly isolates the donut filter.
        donut_bm = _bm(PASTURE_CELLS - {(1, 2)})
        assert _has_hole(donut_bm)                  # confirm it is a donut
        assert donut_bm not in UNIVERSE_FULL_SET

    def test_includes_single_pasture_cells(self):
        # Every individual cell in PASTURE_CELLS is a valid 1-cell pasture.
        for cell in PASTURE_CELLS:
            assert _bm(frozenset({cell})) in UNIVERSE_FULL_SET

    def test_includes_pasture_cells_3x4(self):
        # PASTURE_CELLS (= the 3×4 covering cols 1-4) is a valid pasture.
        assert _bm(PASTURE_CELLS) in UNIVERSE_FULL_SET

    def test_includes_narrow_cells_3x3(self):
        assert _bm(NARROW_CELLS) in UNIVERSE_FULL_SET

    def test_size_is_recorded(self):
        # Pin the size once the actual value is known. Update this assertion
        # in the same commit that runs the universe for the first time.
        # Until then, assert a non-trivial lower bound.
        assert len(UNIVERSE_FULL) >= 500


class TestUniverseFamily:
    def test_non_empty(self):
        assert len(UNIVERSE_FAMILY) > 0

    def test_no_duplicates(self):
        assert len(UNIVERSE_FAMILY) == len(UNIVERSE_FAMILY_SET)

    def test_lex_sorted(self):
        assert list(UNIVERSE_FAMILY) == sorted(UNIVERSE_FAMILY, key=_cells_of)

    def test_is_subset_of_full(self):
        # FAMILY uses total-fence ≤ 15, FULL uses internal-fence ≤ 15.
        # Total ≥ internal, so total ≤ 15 implies internal ≤ 15. FAMILY ⊆ FULL.
        assert UNIVERSE_FAMILY_SET <= UNIVERSE_FULL_SET

    def test_every_entry_passes_all_filters(self):
        for bm in UNIVERSE_FAMILY:
            assert (bm & STARTING_ROOM_BM) == 0
            assert _is_connected(bm)
            assert _total_fence_count(bm) <= 15
            assert not _has_hole(bm)

    def test_excludes_full_grid(self):
        # Total = 16 > 15 → not in FAMILY (also overlaps starting rooms, but
        # the total-fence filter alone is sufficient).
        assert FULL_GRID_BM not in UNIVERSE_FAMILY_SET

    def test_includes_pasture_cells_3x4(self):
        # PASTURE_CELLS has total fence count 14 → in FAMILY.
        assert _bm(PASTURE_CELLS) in UNIVERSE_FAMILY_SET

    def test_excludes_pasture_cells_plus_0_0(self):
        # PASTURE_CELLS + (0, 0) has total fence count 16 → in FULL but NOT in
        # FAMILY. Directly exercises the FULL-vs-FAMILY filter divergence.
        shape = _bm(PASTURE_CELLS | {(0, 0)})
        assert _total_fence_count(shape) == 16
        assert shape in UNIVERSE_FULL_SET
        assert shape not in UNIVERSE_FAMILY_SET

    def test_size_is_recorded(self):
        # Pin to exact value once measured. Lower bound placeholder.
        # FAMILY should be strictly smaller than FULL.
        assert len(UNIVERSE_FAMILY) >= 400
        assert len(UNIVERSE_FAMILY) < len(UNIVERSE_FULL)


class TestUniverseExtended:
    def test_non_empty(self):
        assert len(UNIVERSE_EXTENDED) > 0

    def test_no_duplicates(self):
        assert len(UNIVERSE_EXTENDED) == len(UNIVERSE_EXTENDED_SET)

    def test_lex_sorted(self):
        assert list(UNIVERSE_EXTENDED) == sorted(UNIVERSE_EXTENDED, key=_cells_of)

    def test_is_subset_of_family(self):
        # Extended shapes all have total-fence count ≤ 14 (the 3×4 PASTURE_CELLS
        # is the largest at 14), so EXTENDED ⊆ FAMILY.
        assert UNIVERSE_EXTENDED_SET <= UNIVERSE_FAMILY_SET

    def test_is_subset_of_full(self):
        # Transitively follows, but explicit.
        assert UNIVERSE_EXTENDED_SET <= UNIVERSE_FULL_SET

    def test_includes_adhoc_11_cell(self):
        assert _bm(PASTURE_CELLS - {(0, 1)}) in UNIVERSE_EXTENDED_SET

    def test_includes_adhoc_10_cell(self):
        assert _bm(PASTURE_CELLS - {(0, 1), (0, 2)}) in UNIVERSE_EXTENDED_SET

    def test_includes_a_4cell_L_beyond_the_named_four(self):
        # A 4-cell L not in the four named ones of restricted-category 11:
        # horizontal top-row line (0, 1)-(0, 3) + perpendicular tab at (1, 1).
        # Extended replaces the four-named-L category with all 4-cell L's
        # in PASTURE_CELLS, so this should be present.
        L = frozenset({(0, 1), (0, 2), (0, 3), (1, 1)})
        assert _bm(L) in UNIVERSE_EXTENDED_SET

    def test_size_is_recorded(self):
        # Pin to exact value once measured during step 9. Lower bound placeholder.
        assert len(UNIVERSE_EXTENDED) >= 200


class TestUniverseRestricted:
    def test_non_empty(self):
        assert len(UNIVERSE_RESTRICTED) > 0

    def test_no_duplicates(self):
        assert len(UNIVERSE_RESTRICTED) == len(UNIVERSE_RESTRICTED_SET)

    def test_lex_sorted(self):
        assert list(UNIVERSE_RESTRICTED) == sorted(UNIVERSE_RESTRICTED, key=_cells_of)

    def test_is_subset_of_extended(self):
        assert UNIVERSE_RESTRICTED_SET <= UNIVERSE_EXTENDED_SET

    def test_is_subset_of_family(self):
        # Restricted ⊆ Extended ⊆ Family, transitively. Explicit for safety.
        assert UNIVERSE_RESTRICTED_SET <= UNIVERSE_FAMILY_SET

    def test_is_subset_of_full(self):
        # Restricted ⊆ Extended ⊆ Family ⊆ Full, transitively. Explicit for safety.
        assert UNIVERSE_RESTRICTED_SET <= UNIVERSE_FULL_SET

    def test_includes_named_4cell_Ls(self):
        for L in [
            {(0, 2), (0, 3), (0, 4), (1, 2)},
            {(2, 2), (2, 3), (2, 4), (1, 2)},
            {(0, 3), (0, 4), (1, 4), (2, 4)},
            {(2, 3), (0, 4), (1, 4), (2, 4)},
        ]:
            assert _bm(frozenset(L)) in UNIVERSE_RESTRICTED_SET

    def test_includes_pasture_cells_3x4(self):
        assert _bm(PASTURE_CELLS) in UNIVERSE_RESTRICTED_SET

    def test_includes_narrow_cells_3x3(self):
        assert _bm(NARROW_CELLS) in UNIVERSE_RESTRICTED_SET

    def test_includes_narrow_minus_corner(self):
        for corner in [(0, 2), (2, 2), (0, 4), (2, 4)]:
            assert _bm(NARROW_CELLS - {corner}) in UNIVERSE_RESTRICTED_SET

    def test_includes_adhoc_11_cell(self):
        # Category 17: PASTURE_CELLS minus (0, 1). Also present in UNIVERSE_EXTENDED.
        assert _bm(PASTURE_CELLS - {(0, 1)}) in UNIVERSE_RESTRICTED_SET

    def test_includes_adhoc_10_cell(self):
        # Category 17: PASTURE_CELLS minus (0, 1) and (0, 2). Also in UNIVERSE_EXTENDED.
        assert _bm(PASTURE_CELLS - {(0, 1), (0, 2)}) in UNIVERSE_RESTRICTED_SET

    def test_excludes_1x4_horizontal_line(self):
        # A 1×4 horizontal line on cols 1-4. Restricted categories cover 1×2 and
        # 1×3 on NARROW_CELLS, plus rectangles ≥ 2 rows on PASTURE_CELLS, but
        # have no 1×4 category. Confirm absence to lock in the restriction.
        shape = frozenset({(0, 1), (0, 2), (0, 3), (0, 4)})
        assert _bm(shape) not in UNIVERSE_RESTRICTED_SET

    def test_size_is_recorded(self):
        # Pin to exact value once measured during step 9. Lower bound placeholder.
        assert len(UNIVERSE_RESTRICTED) >= 80
```

Notes on test stability:

- Several tests assert specific counts or specific membership; update these in lockstep with any future change to the shape categories.
- The four `test_size_is_recorded` assertions are placeholders until the actual `len(UNIVERSE_*)` values are measured via `python -m agricola.fences`; update each to an exact equality assertion in the same commit that records the measurements.

---

# Part 6 — Documentation updates

## CLAUDE.md — Directory Structure section

Add `fences.py` to the `agricola/` block and `test_fences.py` to the `tests/` block:

```
AgricolaBot/
    agricola/                   # Game engine package
        ...
        fences.py               # pasture-shape universe (TASK_6_pre)
        ...
    tests/                      # pytest test suite
        ...
        test_fences.py          # universe enumeration tests (TASK_6_pre)
        ...
```

## CLAUDE.md — Python File Descriptions

After the `agricola/cards/potter_ceramics.py` description, add:

```markdown
### `agricola/fences.py`

Precomputed universe of candidate pasture shapes for the Fencing action.

- Bitmap encoding: cell `(r, c)` ↔ bit `r * NUM_COLS + c` (row-major, 15 bits).
- Four shared filters with a fence-count variant per universe: starting-room overlap (cells (1, 0) and (2, 0) excluded by construction), orthogonal connectivity (BFS), fence-count cap (internal-only ≤ 15 for `UNIVERSE_FULL`, total ≤ 15 for `UNIVERSE_FAMILY`), no enclosed holes (complement-flood-fill detects donuts).
- Cell-scope constants: `ALL_CELLS`, `STARTING_ROOMS`, `ENCLOSABLE_CELLS` (13 cells), `PASTURE_CELLS` (12 cells, cols 1-4 — the user's `legal_cells`), `NARROW_CELLS` (9 cells, cols 2-4).
- Four enumerators returning sorted bitmap tuples: `enumerate_universe_full`, `enumerate_universe_family`, `enumerate_universe_extended`, `enumerate_universe_restricted`.
- Module-level constants: `UNIVERSE_FULL` / `UNIVERSE_FULL_SET`, `UNIVERSE_FAMILY` / `UNIVERSE_FAMILY_SET`, `UNIVERSE_EXTENDED` / `UNIVERSE_EXTENDED_SET`, `UNIVERSE_RESTRICTED` / `UNIVERSE_RESTRICTED_SET`. Each pair has the tuple for lex-on-cells-ordered iteration (see `_cells_of`) and the frozenset for O(1) membership lookup. Containment chain: `RESTRICTED ⊆ EXTENDED ⊆ FAMILY ⊆ FULL`.
- `__main__` block prints universe sizes when invoked as `python -m agricola.fences`. Stays silent on `import`.
- Per-entry metadata (boundary fence-edge bitmaps, adjacency bitmaps, frozenset-of-cells representations) is intentionally absent here — added in `TASK_6` when consumers (`_enumerate_pending_build_fences`, `_execute_build_pasture`) land.
```

After the `tests/test_potter_ceramics.py` description, add:

```markdown
### `tests/test_fences.py`

Tests for `agricola/fences.py`: grid constant correctness, the filter primitives (`_is_connected`, `_internal_fence_count`, `_perimeter_fence_count`, `_total_fence_count`, `_has_hole`), and the four universes (sizes non-trivial, no duplicates, lex-on-cells sort, every `UNIVERSE_FULL` / `UNIVERSE_FAMILY` entry passes all four filters, named shapes present, specific shapes absent, containment chain `UNIVERSE_RESTRICTED ⊆ UNIVERSE_EXTENDED ⊆ UNIVERSE_FAMILY ⊆ UNIVERSE_FULL`).
```

## CLAUDE.md — Current Status table

Add a row to the table:

```
| Fencing pasture-shape universe (`agricola/fences.py`) | Complete | TASK_6_pre.md |
```

---

# Part 7 — Order of work

1. **Step 1.** Create `agricola/fences.py` with Part 1 contents (grid constants, `NEIGHBOR_BM`, `PERIMETER_BM`, `FULL_GRID_BM`, `STARTING_ROOM_BM`, `PERIMETER_EDGE_COUNT_PER_CELL`, `_cells_of`). Smoke-import in a Python REPL.
2. **Step 2.** Add `_is_connected`, `_internal_fence_count`, `_perimeter_fence_count`, `_total_fence_count`, `_has_hole`. Smoke-test each on a handful of cell-sets.
3. **Step 3.** Add `enumerate_universe_full` and `enumerate_universe_family`. Measure module-import time.
4. **Step 4.** Add the cell-scope constants and shape-category helpers from Part 3.
5. **Step 5.** Add `enumerate_universe_restricted` and verify the size matches the design conversation's rough estimate (~100 entries).
6. **Step 6.** Add `enumerate_universe_extended`, including the two ad-hoc shapes and the 6-cell category.
7. **Step 7.** Add the four pairs of module-level universe constants at the bottom of the file, plus the `__main__` block.
8. **Step 8.** Run `python -m agricola.fences` to print the four universe sizes. Record them in step 9.
9. **Step 9.** Create `tests/test_fences.py` with the test classes from Part 5. Update each `test_size_is_recorded` (four total: `TestUniverseFull`, `TestUniverseFamily`, `TestUniverseExtended`, `TestUniverseRestricted`) from its placeholder lower bound to an exact-equality assertion using the values measured in step 8.
10. **Step 10.** Run the full test suite — all of `tests/test_fences.py` should pass, and all 343 existing tests should continue to pass.
11. **Step 11.** Apply the CLAUDE.md updates from Part 6.

---

# Part 8 — Acceptance criteria

- `agricola/fences.py` is importable; module-level imports do not raise.
- `UNIVERSE_FULL_SET ⊇ UNIVERSE_FAMILY_SET ⊇ UNIVERSE_EXTENDED_SET ⊇ UNIVERSE_RESTRICTED_SET` (the full containment chain).
- Every bitmap in `UNIVERSE_FULL` and `UNIVERSE_FAMILY` passes its four filters individually (validated by `test_every_entry_passes_all_filters` in `TestUniverseFull` and `TestUniverseFamily`).
- `python -m agricola.fences` prints non-zero sizes for all four universes.
- The four `test_size_is_recorded` assertions are pinned to exact values matching the printed sizes.
- All tests in `tests/test_fences.py` pass.
- All 343 existing tests still pass.
- CLAUDE.md updated with the new module description and status-table row.
- No engine wiring change. `step(state, PlaceWorker(space="fencing"))` still raises `NotImplementedError`.

---

# Part 9 — Open questions deferred to TASK_6

- **Per-entry metadata representation.** Three options: (a) parallel arrays indexed by universe-tuple position (`H_BOUNDARY_BMS`, `V_BOUNDARY_BMS`, `ADJACENCY_BMS`); (b) a `UniverseEntry` frozen dataclass holding all bitmaps + frozenset cells; (c) a dict keyed by `cells_bm` mapping to an entry record. Pick during enumerator/effect-function design.
- **Frozenset-of-cells construction timing.** Eager at module load (one frozenset per universe entry, stored alongside the bitmap) vs lazy from bitmap at `CommitBuildPasture` construction time. Memory vs. cold-path cost tradeoff.
- **Which universe `_enumerate_pending_build_fences` iterates by default.** `UNIVERSE_RESTRICTED` per the design conversation, but the question of how to surface "use the full universe instead" (a runtime config flag? environment variable? per-call override?) is unresolved.
- **Researcher-applied universe restriction predicates.** A runtime filter wrapping `UNIVERSE_FULL` (or `UNIVERSE_EXTENDED`) for opt-in experimental restrictions, sitting orthogonal to the shipped `UNIVERSE_RESTRICTED`.
- **Per-edge cost-modifier registry for cards.** Section 4 of FENCE_IDEAS calls out fence-building's cost handling as a 4th bucket (cost as a pure function of state + commit params). The first card that exercises this will pin the registry shape.
- **`after_build_fences` trigger mechanism.** The vegetable card the user described ("each time you build N fences where N ≥ current round, gain 1 vegetable") is a candidate consumer for an `after_build_fences` event. Its exact mechanism (fire at Stop time before popping, push wrapper pending, hook on `_apply_stop`, etc.) is open per FENCE_IDEAS Section 9.

---

End of TASK_6_pre.
