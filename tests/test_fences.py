"""Tests for agricola/fences.py — bitmap conventions, filters, and the four
layered pasture-shape universes."""

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
        # Measured via `python -m agricola.fences`.
        assert len(UNIVERSE_FULL) == 1518


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
        # Measured via `python -m agricola.fences`.
        assert len(UNIVERSE_FAMILY) == 762
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
        # Measured via `python -m agricola.fences`.
        assert len(UNIVERSE_EXTENDED) == 192


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
        # Measured via `python -m agricola.fences`.
        assert len(UNIVERSE_RESTRICTED) == 108
