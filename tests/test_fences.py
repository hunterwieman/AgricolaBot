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
        # TASK_6 Part 1.8: switched category-1 (1×1) from PASTURE_CELLS to
        # ENCLOSABLE_CELLS, adding the 1×1 at (0, 0). Size grew 192 → 193.
        assert len(UNIVERSE_EXTENDED) == 193


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
        # TASK_6 Part 1.8: switched category-1 (1×1) from PASTURE_CELLS to
        # ENCLOSABLE_CELLS, adding the 1×1 at (0, 0). Size grew 108 → 109.
        assert len(UNIVERSE_RESTRICTED) == 109


# ─── TASK_6 additions: edge metadata, SMALLEST tuples, ENTRIES_BY_BM, packers ──

from dataclasses import is_dataclass

from agricola.fences import (
    PastureCandidate,
    _boundary_h_bm, _boundary_v_bm, _adjacency_bm,
    UNIVERSE_FULL_ENTRIES,
    UNIVERSE_FAMILY_ENTRIES,
    UNIVERSE_EXTENDED_ENTRIES,
    UNIVERSE_RESTRICTED_ENTRIES,
    UNIVERSE_FULL_SMALLEST_ENTRIES,
    UNIVERSE_FAMILY_SMALLEST_ENTRIES,
    UNIVERSE_EXTENDED_SMALLEST_ENTRIES,
    UNIVERSE_RESTRICTED_SMALLEST_ENTRIES,
    ENTRIES_BY_BM,
    pack_fences_h, pack_fences_v,
    apply_fence_edges_h, apply_fence_edges_v,
    compute_new_fence_edges,
)


class TestPastureCandidate:
    def test_is_frozen_dataclass_with_five_fields(self):
        assert is_dataclass(PastureCandidate)
        entry = UNIVERSE_FULL_ENTRIES[0]
        assert hasattr(entry, "cells_bm")
        assert hasattr(entry, "h_boundary_bm")
        assert hasattr(entry, "v_boundary_bm")
        assert hasattr(entry, "adjacency_bm")
        assert hasattr(entry, "cells")
        # Frozen → assignment raises.
        import dataclasses
        try:
            entry.cells_bm = 0
            raised = False
        except dataclasses.FrozenInstanceError:
            raised = True
        except AttributeError:
            raised = True
        assert raised


def _h_bit(r, c):
    return 1 << (r * NUM_COLS + c)


def _v_bit(r, c):
    return 1 << (r * (NUM_COLS + 1) + c)


class TestBoundaryH:
    def test_1x1_at_0_1(self):
        # 1×1 at (0, 1): top edge = horizontal_fences[0][1]; bottom edge = horizontal_fences[1][1].
        bm = _bm({(0, 1)})
        assert _boundary_h_bm(bm) == _h_bit(0, 1) | _h_bit(1, 1)

    def test_1x1_at_2_4(self):
        # 1×1 at (2, 4): top = horizontal_fences[2][4]; bottom = horizontal_fences[3][4].
        bm = _bm({(2, 4)})
        assert _boundary_h_bm(bm) == _h_bit(2, 4) | _h_bit(3, 4)

    def test_2x2_at_pasture_cells(self):
        # 2×2 at (0,1)-(0,2)-(1,1)-(1,2): horizontal boundary is top of row 0 (cols 1, 2)
        # and bottom of row 1 (cols 1, 2) = 4 bits. Internal hr line is NOT in boundary.
        bm = _bm({(0, 1), (0, 2), (1, 1), (1, 2)})
        expected = _h_bit(0, 1) | _h_bit(0, 2) | _h_bit(2, 1) | _h_bit(2, 2)
        assert _boundary_h_bm(bm) == expected

    def test_full_3x4_pasture(self):
        # Full 3×4 PASTURE_CELLS: horizontal boundary = top of row 0 (cols 1-4) +
        # bottom of row 2 (cols 1-4) = 8 bits. No internal horizontal edges.
        bm = _bm(PASTURE_CELLS)
        expected = sum(_h_bit(0, c) for c in range(1, 5)) | sum(_h_bit(3, c) for c in range(1, 5))
        assert _boundary_h_bm(bm) == expected

    def test_1x3_horizontal_strip_row_1(self):
        # 1×3 at (1,1)-(1,2)-(1,3): horizontal boundary = top of row 1 (cols 1,2,3)
        # + bottom of row 1 (i.e. horizontal_fences[2][cols 1,2,3]). 6 bits.
        bm = _bm({(1, 1), (1, 2), (1, 3)})
        expected = (
            _h_bit(1, 1) | _h_bit(1, 2) | _h_bit(1, 3)
            | _h_bit(2, 1) | _h_bit(2, 2) | _h_bit(2, 3)
        )
        assert _boundary_h_bm(bm) == expected


class TestBoundaryV:
    def test_1x1_at_0_1(self):
        # 1×1 at (0, 1): left = vertical_fences[0][1]; right = vertical_fences[0][2].
        bm = _bm({(0, 1)})
        assert _boundary_v_bm(bm) == _v_bit(0, 1) | _v_bit(0, 2)

    def test_1x1_at_2_0(self):
        # 1×1 at (2, 0): left edge at vertical_fences[2][0], right at vertical_fences[2][1].
        # Note: (2, 0) is a starting room so this isn't in any universe, but the
        # boundary computation is universe-agnostic — testing the formula.
        bm = _bm({(2, 0)})
        assert _boundary_v_bm(bm) == _v_bit(2, 0) | _v_bit(2, 1)

    def test_2x2_at_pasture_cells(self):
        # 2×2 at (0,1)-(0,2)-(1,1)-(1,2): vertical boundary = left of col 1 (rows 0, 1)
        # + right of col 2 (rows 0, 1) = 4 bits.
        bm = _bm({(0, 1), (0, 2), (1, 1), (1, 2)})
        expected = _v_bit(0, 1) | _v_bit(1, 1) | _v_bit(0, 3) | _v_bit(1, 3)
        assert _boundary_v_bm(bm) == expected

    def test_full_3x4_pasture(self):
        # Full 3×4 PASTURE_CELLS: vertical boundary = left of col 1 (rows 0-2) +
        # right of col 4 (rows 0-2) = 6 bits.
        bm = _bm(PASTURE_CELLS)
        expected = sum(_v_bit(r, 1) for r in range(3)) | sum(_v_bit(r, 5) for r in range(3))
        assert _boundary_v_bm(bm) == expected

    def test_1x3_horizontal_strip_row_1(self):
        # 1×3 at (1,1)-(1,2)-(1,3): vertical boundary = left of col 1 (row 1) +
        # right of col 3 (row 1) = 2 bits. Internal vertical lines NOT in boundary.
        bm = _bm({(1, 1), (1, 2), (1, 3)})
        expected = _v_bit(1, 1) | _v_bit(1, 4)
        assert _boundary_v_bm(bm) == expected


class TestAdjacency:
    def test_interior_cell(self):
        # 1×1 at (1, 2): four orthogonal neighbors all in-grid.
        bm = _bm({(1, 2)})
        adj = _adjacency_bm(bm)
        expected_cells = {(0, 2), (2, 2), (1, 1), (1, 3)}
        expected_bm = _bm(expected_cells)
        assert adj == expected_bm

    def test_corner_cell(self):
        # 1×1 at (0, 0): two orthogonal in-grid neighbors only.
        bm = _bm({(0, 0)})
        adj = _adjacency_bm(bm)
        assert adj == _bm({(0, 1), (1, 0)})

    def test_edge_non_corner_cell(self):
        # 1×1 at (0, 2): three orthogonal in-grid neighbors.
        bm = _bm({(0, 2)})
        adj = _adjacency_bm(bm)
        assert adj == _bm({(0, 1), (0, 3), (1, 2)})

    def test_adjacency_excludes_cells_in_set(self):
        # For a 2-cell horizontal strip (0, 1)-(0, 2), neighbors should be the
        # surrounding cells but NOT (0, 1) or (0, 2) themselves.
        bm = _bm({(0, 1), (0, 2)})
        adj = _adjacency_bm(bm)
        # Neighbors: (0, 0), (0, 3), (1, 1), (1, 2). Note (0, 1) and (0, 2) excluded.
        assert adj == _bm({(0, 0), (0, 3), (1, 1), (1, 2)})


class TestUniverseEntriesParallel:
    def _check(self, bms, entries):
        assert len(bms) == len(entries)
        for bm, entry in zip(bms, entries):
            assert entry.cells_bm == bm
            assert entry.cells == frozenset(_cells_of(bm))
            assert entry.h_boundary_bm == _boundary_h_bm(bm)
            assert entry.v_boundary_bm == _boundary_v_bm(bm)
            assert entry.adjacency_bm == _adjacency_bm(bm)

    def test_full_parallel(self):
        self._check(UNIVERSE_FULL, UNIVERSE_FULL_ENTRIES)

    def test_family_parallel(self):
        self._check(UNIVERSE_FAMILY, UNIVERSE_FAMILY_ENTRIES)

    def test_extended_parallel(self):
        self._check(UNIVERSE_EXTENDED, UNIVERSE_EXTENDED_ENTRIES)

    def test_restricted_parallel(self):
        self._check(UNIVERSE_RESTRICTED, UNIVERSE_RESTRICTED_ENTRIES)


class TestEntriesByBM:
    def test_keyed_by_cells_bm(self):
        for bm in UNIVERSE_FULL:
            assert bm in ENTRIES_BY_BM
            assert ENTRIES_BY_BM[bm].cells_bm == bm

    def test_covers_every_other_universe(self):
        # Containment chain: RESTRICTED ⊆ EXTENDED ⊆ FAMILY ⊆ FULL,
        # so ENTRIES_BY_BM (keyed off FULL) covers all of them.
        for other in (UNIVERSE_FAMILY_SET, UNIVERSE_EXTENDED_SET, UNIVERSE_RESTRICTED_SET):
            assert other <= frozenset(ENTRIES_BY_BM.keys())


class TestSmallestEntries:
    def _check(self, bms_set, entries, smallest):
        # Every smallest entry has popcount-1 cells.
        for e in smallest:
            assert e.cells_bm.bit_count() == 1
            assert e.cells_bm in bms_set
        # smallest length equals number of popcount-1 entries in the parent.
        expected_count = sum(1 for e in entries if e.cells_bm.bit_count() == 1)
        assert len(smallest) == expected_count
        # Lex-on-cells order preserved (since smallest filters in order).
        assert list(smallest) == sorted(smallest, key=lambda e: _cells_of(e.cells_bm))

    def test_full(self):
        self._check(UNIVERSE_FULL_SET, UNIVERSE_FULL_ENTRIES, UNIVERSE_FULL_SMALLEST_ENTRIES)

    def test_family(self):
        self._check(UNIVERSE_FAMILY_SET, UNIVERSE_FAMILY_ENTRIES, UNIVERSE_FAMILY_SMALLEST_ENTRIES)

    def test_extended(self):
        self._check(UNIVERSE_EXTENDED_SET, UNIVERSE_EXTENDED_ENTRIES, UNIVERSE_EXTENDED_SMALLEST_ENTRIES)

    def test_restricted(self):
        self._check(UNIVERSE_RESTRICTED_SET, UNIVERSE_RESTRICTED_ENTRIES, UNIVERSE_RESTRICTED_SMALLEST_ENTRIES)

    def test_restricted_count_equals_enclosable_cells(self):
        # After Part 1.8's (0, 0) addition, RESTRICTED's 1×1 set covers
        # exactly the 13 ENCLOSABLE cells.
        assert len(UNIVERSE_RESTRICTED_SMALLEST_ENTRIES) == len(ENCLOSABLE_CELLS)


class TestSingletonAt00Addition:
    """Part 1.8: 1×1 at (0, 0) added to RESTRICTED and EXTENDED."""

    def test_present_in_all_four_universes(self):
        bm = _bm({(0, 0)})
        assert bm in UNIVERSE_FULL_SET
        assert bm in UNIVERSE_FAMILY_SET
        assert bm in UNIVERSE_EXTENDED_SET
        assert bm in UNIVERSE_RESTRICTED_SET

    def test_containment_chain_still_holds(self):
        assert UNIVERSE_RESTRICTED_SET <= UNIVERSE_EXTENDED_SET
        assert UNIVERSE_EXTENDED_SET <= UNIVERSE_FAMILY_SET
        assert UNIVERSE_FAMILY_SET <= UNIVERSE_FULL_SET


class TestPackFences:
    def _empty_h(self):
        return tuple(tuple(False for _ in range(NUM_COLS)) for _ in range(NUM_ROWS + 1))

    def _empty_v(self):
        return tuple(tuple(False for _ in range(NUM_COLS + 1)) for _ in range(NUM_ROWS))

    def test_pack_h_empty(self):
        assert pack_fences_h(self._empty_h()) == 0

    def test_pack_v_empty(self):
        assert pack_fences_v(self._empty_v()) == 0

    def test_pack_h_single_bit(self):
        # Flip horizontal_fences[2][3] to True; should set bit 2*5+3 = 13.
        h = list(list(row) for row in self._empty_h())
        h[2][3] = True
        h_tup = tuple(tuple(row) for row in h)
        assert pack_fences_h(h_tup) == (1 << 13)

    def test_pack_v_single_bit(self):
        # Flip vertical_fences[1][4] to True; should set bit 1*6+4 = 10.
        v = list(list(row) for row in self._empty_v())
        v[1][4] = True
        v_tup = tuple(tuple(row) for row in v)
        assert pack_fences_v(v_tup) == (1 << 10)

    def test_apply_h_then_pack_round_trip(self):
        h0 = self._empty_h()
        # Apply a multi-bit bitmap (top edges of row 0 cols 0, 1, 2).
        new_bm = (1 << 0) | (1 << 1) | (1 << 2)
        h1 = apply_fence_edges_h(h0, new_bm)
        assert pack_fences_h(h1) == new_bm

    def test_apply_v_then_pack_round_trip(self):
        v0 = self._empty_v()
        new_bm = (1 << 0) | (1 << 6) | (1 << 11)   # bits at (0,0), (1,0), (1,5)
        v1 = apply_fence_edges_v(v0, new_bm)
        assert pack_fences_v(v1) == new_bm

    def test_apply_h_is_additive(self):
        # Starting with some bits set, applying more bits unions them.
        h0 = self._empty_h()
        first = apply_fence_edges_h(h0, (1 << 0) | (1 << 5))
        second = apply_fence_edges_h(first, (1 << 5) | (1 << 10))
        # Union: bits 0, 5, 10.
        assert pack_fences_h(second) == (1 << 0) | (1 << 5) | (1 << 10)

    def test_apply_v_is_additive(self):
        v0 = self._empty_v()
        first = apply_fence_edges_v(v0, (1 << 0) | (1 << 6))
        second = apply_fence_edges_v(first, (1 << 6) | (1 << 12))
        assert pack_fences_v(second) == (1 << 0) | (1 << 6) | (1 << 12)


class TestComputeNewFenceEdges:
    """The shared cost helper. Duck-typed farmyard input: only .horizontal_fences
    and .vertical_fences are read."""

    class _FakeFarmyard:
        def __init__(self, h, v):
            self.horizontal_fences = h
            self.vertical_fences = v

    def _empty_h(self):
        return tuple(tuple(False for _ in range(NUM_COLS)) for _ in range(NUM_ROWS + 1))

    def _empty_v(self):
        return tuple(tuple(False for _ in range(NUM_COLS + 1)) for _ in range(NUM_ROWS))

    def test_1x1_at_0_1_on_empty_farmyard(self):
        # All 4 boundary edges are new; wood cost = 4.
        fy = self._FakeFarmyard(self._empty_h(), self._empty_v())
        bm = _bm({(0, 1)})
        h_new, v_new, wood = compute_new_fence_edges(fy, bm)
        assert wood == 4
        assert h_new == _h_bit(0, 1) | _h_bit(1, 1)
        assert v_new == _v_bit(0, 1) | _v_bit(0, 2)

    def test_2x2_at_pasture_cells_on_empty_farmyard(self):
        # 4 horizontal + 4 vertical = 8 new edges.
        fy = self._FakeFarmyard(self._empty_h(), self._empty_v())
        bm = _bm({(0, 1), (0, 2), (1, 1), (1, 2)})
        h_new, v_new, wood = compute_new_fence_edges(fy, bm)
        assert wood == 8

    def test_pre_fenced_edges_reduce_cost(self):
        # Pre-fence the top of (0, 1), then build the 1×1 at (0, 1).
        # Only 3 new edges should be placed; wood cost = 3.
        h = apply_fence_edges_h(self._empty_h(), _h_bit(0, 1))
        fy = self._FakeFarmyard(h, self._empty_v())
        bm = _bm({(0, 1)})
        h_new, v_new, wood = compute_new_fence_edges(fy, bm)
        assert wood == 3
        # The pre-fenced edge is NOT in h_new.
        assert h_new == _h_bit(1, 1)            # only the bottom edge is new
