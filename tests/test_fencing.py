"""Tests for the Fencing action space (TASK_6).

Engine-level integration tests under the default (RESTRICTED) universe
unless a test explicitly swaps. Covers:
  - basic walks (single and multi-pasture commits)
  - subdivisions + canonicalization
  - first-pasture-anywhere and adjacency rules
  - enclosable filter, affordability, fences-in-supply
  - Stop-legality at both pendings
  - builds-before-subdivisions ordering rule
  - universe-swap via kwarg and via module constant
  - random-agent end-to-end smoke
"""
from __future__ import annotations

import dataclasses

import pytest

from agricola.actions import (
    ChooseSubAction,
    CommitBuildPasture,
    PlaceWorker,
    Stop,
)
from agricola.engine import step
from agricola import legality
from agricola.fences import (
    ENTRIES_BY_BM,
    NUM_COLS,
    UNIVERSE_EXTENDED_ENTRIES,
    UNIVERSE_EXTENDED_SET,
    UNIVERSE_EXTENDED_SMALLEST_ENTRIES,
    UNIVERSE_RESTRICTED_ENTRIES,
    UNIVERSE_RESTRICTED_SET,
    UNIVERSE_RESTRICTED_SMALLEST_ENTRIES,
    apply_fence_edges_h,
    apply_fence_edges_v,
)
from agricola.legality import legal_actions
from agricola.pasture import compute_pastures_from_arrays
from agricola.pending import (
    PendingBuildFences,
    PendingSubActionSpace,
)
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import Cell
from agricola.constants import CellType

from tests.factories import (
    with_current_player,
    with_grid,
    with_resources,
    with_space,
)
from tests.test_utils import run_actions


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _fencing_setup(*, wood=8, current_player=0):
    """Standard setup: Fencing revealed, fresh farmyard, ample wood."""
    state = setup(seed=0)
    state = with_current_player(state, current_player)
    state = with_resources(state, current_player, wood=wood)
    state = with_space(state, "fencing", revealed=True)
    return state


def _with_initial_pasture(state, player_idx, cells):
    """Place fences around `cells` to form an initial enclosed pasture.

    Bypasses normal gameplay (no wood debit, no worker placement). The cells
    must form an entry in UNIVERSE_FULL (i.e., enclosable, connected, no
    hole). Returns a new state with the fence arrays + pastures cache
    updated.
    """
    cells_bm = sum(1 << (r * NUM_COLS + c) for (r, c) in cells)
    entry = ENTRIES_BY_BM[cells_bm]
    p = state.players[player_idx]
    farmyard = p.farmyard
    new_h = apply_fence_edges_h(farmyard.horizontal_fences, entry.h_boundary_bm)
    new_v = apply_fence_edges_v(farmyard.vertical_fences, entry.v_boundary_bm)
    new_pastures = compute_pastures_from_arrays(farmyard.grid, new_h, new_v)
    new_farmyard = dataclasses.replace(
        farmyard,
        horizontal_fences=new_h,
        vertical_fences=new_v,
        pastures=new_pastures,
    )
    new_player = dataclasses.replace(p, farmyard=new_farmyard)
    new_players = tuple(
        new_player if i == player_idx else state.players[i]
        for i in range(len(state.players))
    )
    return dataclasses.replace(state, players=new_players)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_single_pasture_basic_walk():
    """Wood + supply, no existing pastures → build a 1×1 → Stop → Stop."""
    state = _fencing_setup(wood=4)
    state = run_actions(state, [
        PlaceWorker(space="fencing"),
        ChooseSubAction(name="build_fences"),
        CommitBuildPasture(cells=frozenset({(0, 1)})),
        Stop(),                                    # pops PendingBuildFences
        Stop(),                                    # pops PendingSubActionSpace
    ])
    assert state.pending_stack == ()
    fy = state.players[0].farmyard
    assert state.players[0].resources.wood == 0   # 4 wood debited
    # 4 fences placed → 11 in supply.
    placed = sum(sum(row) for row in fy.horizontal_fences) + sum(sum(row) for row in fy.vertical_fences)
    assert placed == 4
    # Pasture cache reflects the new 1×1.
    assert len(fy.pastures) == 1
    assert fy.pastures[0].cells == frozenset({(0, 1)})


def test_multi_pasture_in_one_action():
    """Build two adjacent 1×1 pastures in one Build Fences invocation."""
    state = _fencing_setup(wood=10)
    state = run_actions(state, [
        PlaceWorker(space="fencing"),
        ChooseSubAction(name="build_fences"),
        CommitBuildPasture(cells=frozenset({(0, 1)})),     # 4 fences, 4 wood
        CommitBuildPasture(cells=frozenset({(0, 2)})),     # adjacent; 3 new fences
        Stop(),
        Stop(),
    ])
    assert state.pending_stack == ()
    fy = state.players[0].farmyard
    pasture_cells = {tuple(sorted(P.cells)) for P in fy.pastures}
    assert pasture_cells == {((0, 1),), ((0, 2),)}
    assert state.players[0].resources.wood == 10 - 4 - 3


def test_subdivision_splits_existing_pasture():
    """Start with a 2×1 pasture; subdivide into two 1×1s."""
    state = _fencing_setup(wood=4)
    state = _with_initial_pasture(state, 0, [(0, 1), (1, 1)])
    # Subdivide naming the lex-smaller half. Only 1 new fence edge (the
    # horizontal between rows 0 and 1 at col 1).
    state = run_actions(state, [
        PlaceWorker(space="fencing"),
        ChooseSubAction(name="build_fences"),
        CommitBuildPasture(cells=frozenset({(0, 1)})),
        Stop(),
        Stop(),
    ])
    fy = state.players[0].farmyard
    # Two 1×1 pastures after the split.
    assert len(fy.pastures) == 2
    pasture_cells = {tuple(sorted(P.cells)) for P in fy.pastures}
    assert pasture_cells == {((0, 1),), ((1, 1),)}
    # Wood debit = 1.
    assert state.players[0].resources.wood == 3


def test_subdivision_canonicalization():
    """In a 2×1 pasture, only the lex-smaller half appears in legal_actions."""
    state = _fencing_setup(wood=4)
    state = _with_initial_pasture(state, 0, [(0, 1), (1, 1)])
    state = run_actions(state, [
        PlaceWorker(space="fencing"),
        ChooseSubAction(name="build_fences"),
    ])
    legal = legal_actions(state)
    commits = [a for a in legal if isinstance(a, CommitBuildPasture)]
    # Both halves are valid subdivisions but only the lex-smaller is emitted.
    lex_smaller = CommitBuildPasture(cells=frozenset({(0, 1)}))
    lex_larger = CommitBuildPasture(cells=frozenset({(1, 1)}))
    assert lex_smaller in commits
    assert lex_larger not in commits


def test_first_pasture_anywhere_no_adjacency_required():
    """With no existing pastures, all enclosable 1×1s appear in legal_actions."""
    state = _fencing_setup(wood=99)
    state = run_actions(state, [
        PlaceWorker(space="fencing"),
        ChooseSubAction(name="build_fences"),
    ])
    legal = legal_actions(state)
    commits = {tuple(sorted(a.cells)) for a in legal if isinstance(a, CommitBuildPasture)}
    # Every ENCLOSABLE cell's 1×1 is in RESTRICTED (post-(0,0) addition).
    for cell in [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4),
                 (1, 1), (1, 2), (1, 3), (1, 4),
                 (2, 1), (2, 2), (2, 3), (2, 4)]:
        assert (cell,) in commits, f"1×1 at {cell} missing"


def test_adjacency_required_for_subsequent_new_pasture():
    """With an existing pasture, new pastures non-adjacent to it are filtered."""
    state = _fencing_setup(wood=99)
    state = _with_initial_pasture(state, 0, [(0, 1)])
    state = run_actions(state, [
        PlaceWorker(space="fencing"),
        ChooseSubAction(name="build_fences"),
    ])
    legal = legal_actions(state)
    commits = {tuple(sorted(a.cells)) for a in legal if isinstance(a, CommitBuildPasture)}
    # (0, 2) is adjacent to (0, 1) → legal.
    assert ((0, 2),) in commits
    # (1, 1) is adjacent (below (0, 1)) → legal.
    assert ((1, 1),) in commits
    # (0, 4) is NOT adjacent to (0, 1) → filtered.
    assert ((0, 4),) not in commits
    # (2, 4) is NOT adjacent → filtered.
    assert ((2, 4),) not in commits


def test_enclosable_filter_excludes_rooms_and_fields():
    """Cells with rooms or fields are not enclosable; their 1×1s are filtered."""
    state = _fencing_setup(wood=99)
    # Plow a field at (0, 1). Default ROOM cells at (1, 0) and (2, 0).
    state = with_grid(state, 0, {(0, 1): Cell(cell_type=CellType.FIELD)})
    state = run_actions(state, [
        PlaceWorker(space="fencing"),
        ChooseSubAction(name="build_fences"),
    ])
    legal = legal_actions(state)
    commits = {tuple(sorted(a.cells)) for a in legal if isinstance(a, CommitBuildPasture)}
    # (0, 1) is now a FIELD → filtered. (1, 0) and (2, 0) are ROOMs.
    assert ((0, 1),) not in commits
    assert ((1, 0),) not in commits
    assert ((2, 0),) not in commits
    # Other enclosable cells still present.
    assert ((0, 0),) in commits
    assert ((1, 1),) in commits


def test_wood_affordability_binding():
    """A pasture needing 3 new fences is excluded if the player has only 2 wood."""
    # Start with an existing pasture; subdivisions need fewer fences than full
    # new builds. We give 1 wood — only the 1-new-edge subdivision is legal.
    state = _fencing_setup(wood=1)
    state = _with_initial_pasture(state, 0, [(0, 1), (1, 1)])
    state = run_actions(state, [
        PlaceWorker(space="fencing"),
        ChooseSubAction(name="build_fences"),
    ])
    legal = legal_actions(state)
    commits = [a for a in legal if isinstance(a, CommitBuildPasture)]
    # The only legal commit is the 1-new-edge subdivision (canonicalized).
    assert commits == [CommitBuildPasture(cells=frozenset({(0, 1)}))]


def test_fences_in_supply_binding():
    """Same as wood-affordability but for fences-in-supply.

    Strategy: deplete fences via the existing fence arrays directly, leaving
    only 1 fence in supply. The subdivision needing 1 new fence remains;
    larger shapes filter out.
    """
    state = _fencing_setup(wood=99)
    # _with_initial_pasture(2x1) places 6 fences; supply = 15 - 6 = 9.
    state = _with_initial_pasture(state, 0, [(0, 1), (1, 1)])
    # Manually place 8 more fences to leave only 1 in supply. Pick edges that
    # don't form pasture boundaries — top-of-row-0 across cols 2, 3, 4 plus
    # left edges in row 2 cols 2-4 plus two more arbitrary.
    fy = state.players[0].farmyard
    h_arr = [list(row) for row in fy.horizontal_fences]
    h_arr[0][2] = True
    h_arr[0][3] = True
    h_arr[0][4] = True
    h_arr[3][2] = True
    h_arr[3][3] = True
    h_arr[3][4] = True
    h_arr[2][3] = True
    h_arr[2][4] = True
    new_h = tuple(tuple(row) for row in h_arr)
    new_pastures = compute_pastures_from_arrays(fy.grid, new_h, fy.vertical_fences)
    new_farmyard = dataclasses.replace(
        fy, horizontal_fences=new_h, pastures=new_pastures,
    )
    state = dataclasses.replace(
        state,
        players=(dataclasses.replace(state.players[0], farmyard=new_farmyard),
                 state.players[1]),
    )
    # Should have 1 fence in supply now (6 + 8 = 14 placed; 15 - 14 = 1).
    from agricola.helpers import fences_in_supply
    assert fences_in_supply(new_farmyard) == 1
    state = run_actions(state, [
        PlaceWorker(space="fencing"),
        ChooseSubAction(name="build_fences"),
    ])
    legal = legal_actions(state)
    commits = [a for a in legal if isinstance(a, CommitBuildPasture)]
    # Only the 1-new-edge subdivision is legal.
    assert commits == [CommitBuildPasture(cells=frozenset({(0, 1)}))]


def test_restate_existing_pasture_filtered():
    """Naming an existing pasture's cell-set produces 0 new fences → filtered."""
    state = _fencing_setup(wood=99)
    state = _with_initial_pasture(state, 0, [(0, 1), (1, 1)])
    state = run_actions(state, [
        PlaceWorker(space="fencing"),
        ChooseSubAction(name="build_fences"),
    ])
    legal = legal_actions(state)
    commits = {tuple(sorted(a.cells)) for a in legal if isinstance(a, CommitBuildPasture)}
    # Re-stating the entire existing pasture (0,1)-(1,1) would place 0 edges.
    assert ((0, 1), (1, 1)) not in commits


def test_stop_legality_on_build_fences():
    """Stop illegal at pastures_built=0; legal at pastures_built≥1."""
    state = _fencing_setup(wood=4)
    state = run_actions(state, [
        PlaceWorker(space="fencing"),
        ChooseSubAction(name="build_fences"),
    ])
    assert Stop() not in legal_actions(state)
    state = step(state, CommitBuildPasture(cells=frozenset({(0, 1)})))
    assert Stop() in legal_actions(state)


def test_stop_legality_on_fencing_parent():
    """Stop illegal on the fencing host before subaction_complete; legal after."""
    state = _fencing_setup(wood=4)
    state = step(state, PlaceWorker(space="fencing"))
    # On PendingSubActionSpace(space_id="fencing") with subaction_complete=False.
    legal = legal_actions(state)
    assert Stop() not in legal
    assert ChooseSubAction(name="build_fences") in legal


def test_counter_updates_across_commits():
    """pastures_built and fences_built increment correctly."""
    state = _fencing_setup(wood=10)
    state = run_actions(state, [
        PlaceWorker(space="fencing"),
        ChooseSubAction(name="build_fences"),
        CommitBuildPasture(cells=frozenset({(0, 1)})),     # 4 new fences
    ])
    pending = state.pending_stack[-1]
    assert isinstance(pending, PendingBuildFences)
    assert pending.pastures_built == 1
    assert pending.fences_built == 4
    state = step(state, CommitBuildPasture(cells=frozenset({(0, 2)})))  # 3 new
    pending = state.pending_stack[-1]
    assert pending.pastures_built == 2
    assert pending.fences_built == 7


# ─── Ordering rule (builds before subdivisions) ───────────────────────────

def test_ordering_rule_new_pasture_then_subdivision():
    """New-pasture build, then subdivision of pre-existing pasture: both legal."""
    state = _fencing_setup(wood=10)
    # Pre-existing 2x1 pasture at (0, 1)-(1, 1).
    state = _with_initial_pasture(state, 0, [(0, 1), (1, 1)])
    # First commit: new 1×1 at (0, 2) (adjacent to existing pasture).
    # This is a NEW pasture build — subdivision_started should stay False.
    state = run_actions(state, [
        PlaceWorker(space="fencing"),
        ChooseSubAction(name="build_fences"),
        CommitBuildPasture(cells=frozenset({(0, 2)})),     # new pasture
    ])
    pending = state.pending_stack[-1]
    assert isinstance(pending, PendingBuildFences)
    assert pending.subdivision_started is False

    # Second commit: subdivide the original 2×1 by naming (0, 1).
    state = step(state, CommitBuildPasture(cells=frozenset({(0, 1)})))
    pending = state.pending_stack[-1]
    assert pending.subdivision_started is True


def test_ordering_rule_subdivision_blocks_subsequent_new_pasture():
    """After a subdivision, new-pasture commits are no longer offered."""
    state = _fencing_setup(wood=10)
    state = _with_initial_pasture(state, 0, [(0, 1), (1, 1)])
    # Subdivide first.
    state = run_actions(state, [
        PlaceWorker(space="fencing"),
        ChooseSubAction(name="build_fences"),
        CommitBuildPasture(cells=frozenset({(0, 1)})),     # subdivision
    ])
    pending = state.pending_stack[-1]
    assert pending.subdivision_started is True
    # Now check legal_actions: no new-pasture commits should appear.
    legal = legal_actions(state)
    existing_cells = {(0, 1), (1, 1)}    # cells in some existing pasture
    for action in legal:
        if isinstance(action, CommitBuildPasture):
            # Every CommitBuildPasture must be a subdivision (cells overlap
            # some existing pasture). The new 1×1 pastures at (0, 2), (1, 2),
            # etc. are NEW pastures and must NOT appear.
            assert any(c in existing_cells for c in action.cells), (
                f"new-pasture commit {action} appeared after subdivision_started=True"
            )


def test_ordering_rule_subdivision_started_flag_semantics():
    """`subdivision_started` flips True iff a commit is a subdivision."""
    state = _fencing_setup(wood=10)
    state = _with_initial_pasture(state, 0, [(0, 1), (1, 1)])
    state = run_actions(state, [
        PlaceWorker(space="fencing"),
        ChooseSubAction(name="build_fences"),
    ])
    # Starts False.
    assert state.pending_stack[-1].subdivision_started is False
    # Apply a NEW-pasture commit. Flag stays False.
    state = step(state, CommitBuildPasture(cells=frozenset({(0, 2)})))
    assert state.pending_stack[-1].subdivision_started is False
    # Apply a SUBDIVISION commit. Flag flips True.
    state = step(state, CommitBuildPasture(cells=frozenset({(0, 1)})))
    assert state.pending_stack[-1].subdivision_started is True


def test_stack_invariants():
    """Verify pendings, flags, and provenance throughout a walk."""
    state = _fencing_setup(wood=4)

    # PlaceWorker pushes PendingSubActionSpace(space_id="fencing").
    state = step(state, PlaceWorker(space="fencing"))
    assert len(state.pending_stack) == 1
    pf = state.pending_stack[-1]
    assert isinstance(pf, PendingSubActionSpace)
    assert pf.space_id == "fencing"
    assert pf.initiated_by_id == "space:fencing"
    assert pf.subaction_complete is False

    # ChooseSubAction sets flag and pushes PendingBuildFences.
    state = step(state, ChooseSubAction(name="build_fences"))
    assert len(state.pending_stack) == 2
    assert state.pending_stack[0].subaction_complete is True
    pbf = state.pending_stack[-1]
    assert isinstance(pbf, PendingBuildFences)
    assert pbf.initiated_by_id == "fencing"           # parent's space_id
    assert pbf.pastures_built == 0
    assert pbf.fences_built == 0
    assert pbf.subdivision_started is False

    # CommitBuildPasture: does NOT pop (the dispatcher never pops; Stop pops).
    state = step(state, CommitBuildPasture(cells=frozenset({(0, 1)})))
    assert len(state.pending_stack) == 2
    assert state.pending_stack[-1].pastures_built == 1

    # Stop on PendingBuildFences pops it; auto-advance flips host to after.
    state = step(state, Stop())
    assert len(state.pending_stack) == 1
    assert isinstance(state.pending_stack[-1], PendingSubActionSpace)

    # Stop on the fencing host pops the parent.
    state = step(state, Stop())
    assert state.pending_stack == ()


# ─── _legal_fencing predicate ──────────────────────────────────────────────

def test_legal_fencing_baseline_true():
    state = _fencing_setup(wood=4)
    assert PlaceWorker(space="fencing") in legal_actions(state)


def test_legal_fencing_false_when_no_wood():
    state = _fencing_setup(wood=0)
    assert PlaceWorker(space="fencing") not in legal_actions(state)


def test_legal_fencing_false_when_no_fences_in_supply():
    """Deplete fences-in-supply to 0; fencing should not appear."""
    state = _fencing_setup(wood=99)
    # Manually fill every fence-edge to drive supply to 0.
    fy = state.players[0].farmyard
    full_h = tuple(tuple(True for _ in range(NUM_COLS)) for _ in range(4))
    full_v = tuple(tuple(True for _ in range(NUM_COLS + 1)) for _ in range(3))
    new_pastures = compute_pastures_from_arrays(fy.grid, full_h, full_v)
    new_farmyard = dataclasses.replace(
        fy, horizontal_fences=full_h, vertical_fences=full_v,
        pastures=new_pastures,
    )
    state = dataclasses.replace(
        state,
        players=(dataclasses.replace(state.players[0], farmyard=new_farmyard),
                 state.players[1]),
    )
    assert PlaceWorker(space="fencing") not in legal_actions(state)


def test_legal_fencing_false_when_all_cells_unenclosable():
    """With every enclosable cell filled by fields, no pasture commit is legal."""
    state = _fencing_setup(wood=99)
    # Plow every cell except the starting rooms.
    field_cells = {(r, c) for r in range(3) for c in range(5)
                          if (r, c) not in {(1, 0), (2, 0)}}
    overrides = {cell: Cell(cell_type=CellType.FIELD) for cell in field_cells}
    state = with_grid(state, 0, overrides)
    assert PlaceWorker(space="fencing") not in legal_actions(state)


# ─── Universe-swap mechanisms ─────────────────────────────────────────────

def _shape_only_in_extended() -> frozenset:
    """Return a cell-set in EXTENDED \\ RESTRICTED that we can target.

    A 1×2 horizontal in PASTURE but not in NARROW: e.g., (0, 1)-(0, 2).
    EXTENDED includes 1×2 horizontals on PASTURE_CELLS; RESTRICTED only
    on NARROW_CELLS.
    """
    return frozenset({(0, 1), (0, 2)})


def test_universe_swap_via_kwarg():
    """Pass `entries`/`smallest_entries`/`universe_set` to the enumerator."""
    state = _fencing_setup(wood=99)
    state = run_actions(state, [
        PlaceWorker(space="fencing"),
        ChooseSubAction(name="build_fences"),
    ])
    pending = state.pending_stack[-1]
    target = _shape_only_in_extended()
    target_bm = sum(1 << (r * NUM_COLS + c) for (r, c) in target)

    # Under RESTRICTED: target not in universe_set.
    assert target_bm not in UNIVERSE_RESTRICTED_SET
    restricted_commits = [
        a for a in legality._enumerate_pending_build_fences(state, pending)
        if isinstance(a, CommitBuildPasture)
    ]
    assert all(a.cells != target for a in restricted_commits)

    # Under EXTENDED: target should appear.
    assert target_bm in UNIVERSE_EXTENDED_SET
    extended_commits = [
        a for a in legality._enumerate_pending_build_fences(
            state, pending,
            entries=UNIVERSE_EXTENDED_ENTRIES,
            universe_set=UNIVERSE_EXTENDED_SET,
        )
        if isinstance(a, CommitBuildPasture)
    ]
    assert any(a.cells == target for a in extended_commits)


def test_universe_swap_via_module_constant():
    """Reassigning legality.ACTIVE_FENCE_UNIVERSE_* changes enumerator output.

    Default-kwarg call sites pick up the swap because the enumerators read
    the active-universe constants at call time, not definition time.
    """
    state = _fencing_setup(wood=99)
    state = run_actions(state, [
        PlaceWorker(space="fencing"),
        ChooseSubAction(name="build_fences"),
    ])
    pending = state.pending_stack[-1]
    target = _shape_only_in_extended()

    # Baseline: RESTRICTED does not include the target shape.
    baseline = legality._enumerate_pending_build_fences(state, pending)
    assert all(a.cells != target for a in baseline if isinstance(a, CommitBuildPasture))

    # Swap to EXTENDED globally. No kwargs needed at the call site.
    saved_entries = legality.ACTIVE_FENCE_UNIVERSE_ENTRIES
    saved_smallest = legality.ACTIVE_FENCE_UNIVERSE_SMALLEST_ENTRIES
    saved_set = legality.ACTIVE_FENCE_UNIVERSE_SET
    try:
        legality.ACTIVE_FENCE_UNIVERSE_ENTRIES = UNIVERSE_EXTENDED_ENTRIES
        legality.ACTIVE_FENCE_UNIVERSE_SMALLEST_ENTRIES = UNIVERSE_EXTENDED_SMALLEST_ENTRIES
        legality.ACTIVE_FENCE_UNIVERSE_SET = UNIVERSE_EXTENDED_SET
        # The active fence universe is a HIDDEN input to the fence-scan cache
        # (not in its key), so a raw module-constant swap must flush it — exactly
        # what active_universe() does for you. With FENCE_SCAN_CACHE on by
        # default, skipping this would return the stale RESTRICTED scan.
        legality._legal_pasture_commits_cached.cache_clear()
        swapped = legality._enumerate_pending_build_fences(state, pending)
        assert any(a.cells == target for a in swapped if isinstance(a, CommitBuildPasture))
    finally:
        legality.ACTIVE_FENCE_UNIVERSE_ENTRIES = saved_entries
        legality.ACTIVE_FENCE_UNIVERSE_SMALLEST_ENTRIES = saved_smallest
        legality.ACTIVE_FENCE_UNIVERSE_SET = saved_set
        legality._legal_pasture_commits_cached.cache_clear()


def test_active_universe_defaults_to_restricted():
    """Fresh-import default is the RESTRICTED universe."""
    assert legality.ACTIVE_FENCE_UNIVERSE_ENTRIES is UNIVERSE_RESTRICTED_ENTRIES
    assert legality.ACTIVE_FENCE_UNIVERSE_SMALLEST_ENTRIES is UNIVERSE_RESTRICTED_SMALLEST_ENTRIES
    assert legality.ACTIVE_FENCE_UNIVERSE_SET is UNIVERSE_RESTRICTED_SET


# ─── fence_universe.py: context manager + restrict_to builder ─────────────

def test_active_universe_context_manager_swaps_globally():
    """`with active_universe(...)`: no kwargs needed at the enumerator call site."""
    from agricola.fence_universe import active_universe

    state = _fencing_setup(wood=99)
    state = run_actions(state, [
        PlaceWorker(space="fencing"),
        ChooseSubAction(name="build_fences"),
    ])
    pending = state.pending_stack[-1]
    target = _shape_only_in_extended()

    # Baseline (RESTRICTED): target absent.
    baseline = legality._enumerate_pending_build_fences(state, pending)
    assert all(a.cells != target for a in baseline if isinstance(a, CommitBuildPasture))

    # Inside the context, default-kwarg call picks up the swap.
    with active_universe("extended"):
        swapped = legality._enumerate_pending_build_fences(state, pending)
    assert any(a.cells == target for a in swapped if isinstance(a, CommitBuildPasture))

    # Restored on exit.
    after = legality._enumerate_pending_build_fences(state, pending)
    assert all(a.cells != target for a in after if isinstance(a, CommitBuildPasture))


def test_active_universe_restores_on_exception():
    """The context manager restores the trio even when the block raises."""
    from agricola.fence_universe import active_universe, current_universe

    before = current_universe()
    with pytest.raises(RuntimeError):
        with active_universe("extended"):
            raise RuntimeError("boom")
    assert current_universe() == before


def test_active_universe_nests():
    """Nested `with active_universe(...)` blocks save/restore correctly."""
    from agricola.fence_universe import active_universe

    assert legality.ACTIVE_FENCE_UNIVERSE_ENTRIES is UNIVERSE_RESTRICTED_ENTRIES
    with active_universe("extended"):
        assert legality.ACTIVE_FENCE_UNIVERSE_ENTRIES is UNIVERSE_EXTENDED_ENTRIES
        with active_universe("restricted"):
            assert legality.ACTIVE_FENCE_UNIVERSE_ENTRIES is UNIVERSE_RESTRICTED_ENTRIES
        # Outer scope is restored.
        assert legality.ACTIVE_FENCE_UNIVERSE_ENTRIES is UNIVERSE_EXTENDED_ENTRIES
    assert legality.ACTIVE_FENCE_UNIVERSE_ENTRIES is UNIVERSE_RESTRICTED_ENTRIES


def test_active_universe_accepts_explicit_triple():
    """`active_universe(triple)` accepts the same shape `restrict_to` returns."""
    from agricola.fence_universe import active_universe

    triple = (
        UNIVERSE_EXTENDED_ENTRIES,
        UNIVERSE_EXTENDED_SMALLEST_ENTRIES,
        UNIVERSE_EXTENDED_SET,
    )
    with active_universe(triple):
        assert legality.ACTIVE_FENCE_UNIVERSE_ENTRIES is UNIVERSE_EXTENDED_ENTRIES
        assert legality.ACTIVE_FENCE_UNIVERSE_SMALLEST_ENTRIES is UNIVERSE_EXTENDED_SMALLEST_ENTRIES
        assert legality.ACTIVE_FENCE_UNIVERSE_SET is UNIVERSE_EXTENDED_SET


def test_active_universe_rejects_unknown_name():
    from agricola.fence_universe import active_universe

    with pytest.raises(ValueError, match="Unknown universe name"):
        with active_universe("not-a-universe"):
            pass


def test_active_universe_rejects_bad_shape():
    from agricola.fence_universe import active_universe

    with pytest.raises(TypeError):
        with active_universe(42):  # type: ignore[arg-type]
            pass


def test_restrict_to_filters_universe():
    """`restrict_to` returns a triple whose entries all satisfy the predicate."""
    from agricola.fence_universe import restrict_to

    small = restrict_to(lambda e: e.cells_bm.bit_count() <= 2, base="extended")
    entries, smallest, uset = small

    # All entries pass the predicate.
    assert entries  # non-empty (1×1's alone satisfy ≤2)
    assert all(e.cells_bm.bit_count() <= 2 for e in entries)
    # smallest_entries is the 1-cell subset of entries.
    assert all(e.cells_bm.bit_count() == 1 for e in smallest)
    # universe_set matches the entries.
    assert uset == frozenset(e.cells_bm for e in entries)
    # Strict subset of base (predicate excludes ≥3-cell entries).
    assert len(entries) < len(UNIVERSE_EXTENDED_ENTRIES)


def test_restrict_to_default_base_is_full():
    """Default base for `restrict_to` is UNIVERSE_FULL."""
    from agricola.fences import UNIVERSE_FULL_ENTRIES
    from agricola.fence_universe import restrict_to

    # Identity predicate: restrict_to should return everything in FULL.
    everything = restrict_to(lambda e: True)
    entries, _, _ = everything
    assert len(entries) == len(UNIVERSE_FULL_ENTRIES)


def test_restrict_to_composes_with_active_universe():
    """A derived universe applies cleanly inside `active_universe`."""
    from agricola.actions import CommitBuildPasture
    from agricola.fence_universe import active_universe, restrict_to

    # Only 1×1 pastures.
    singletons_only = restrict_to(lambda e: e.cells_bm.bit_count() == 1, base="full")

    state = _fencing_setup(wood=99)
    state = run_actions(state, [
        PlaceWorker(space="fencing"),
        ChooseSubAction(name="build_fences"),
    ])
    pending = state.pending_stack[-1]

    with active_universe(singletons_only):
        commits = [
            a for a in legality._enumerate_pending_build_fences(state, pending)
            if isinstance(a, CommitBuildPasture)
        ]
    # Every emitted commit names a single cell.
    assert commits  # non-empty
    assert all(len(a.cells) == 1 for a in commits)


def test_current_universe_reads_active_constants():
    """`current_universe()` reflects whatever is currently active."""
    from agricola.fence_universe import active_universe, current_universe

    # Default: RESTRICTED.
    e, s, u = current_universe()
    assert e is UNIVERSE_RESTRICTED_ENTRIES
    assert s is UNIVERSE_RESTRICTED_SMALLEST_ENTRIES
    assert u is UNIVERSE_RESTRICTED_SET

    with active_universe("extended"):
        e, s, u = current_universe()
        assert e is UNIVERSE_EXTENDED_ENTRIES
        assert s is UNIVERSE_EXTENDED_SMALLEST_ENTRIES
        assert u is UNIVERSE_EXTENDED_SET


def test_named_universes_keys():
    """Sanity check: NAMED_UNIVERSES has the four expected entries."""
    from agricola.fence_universe import NAMED_UNIVERSES

    assert set(NAMED_UNIVERSES) == {"restricted", "extended", "family", "full"}


# ─── Pasture cache + random-agent smoke ───────────────────────────────────

def test_pasture_cache_recompute_after_commit():
    """new_farmyard.pastures reflects the new pasture(s) after each commit."""
    state = _fencing_setup(wood=10)
    assert state.players[0].farmyard.pastures == ()
    state = run_actions(state, [
        PlaceWorker(space="fencing"),
        ChooseSubAction(name="build_fences"),
        CommitBuildPasture(cells=frozenset({(0, 1)})),
    ])
    fy = state.players[0].farmyard
    assert len(fy.pastures) == 1
    assert fy.pastures[0].cells == frozenset({(0, 1)})

    # Second commit grows the cache.
    state = step(state, CommitBuildPasture(cells=frozenset({(0, 2)})))
    fy = state.players[0].farmyard
    assert len(fy.pastures) == 2


@pytest.mark.parametrize("seed", list(range(10)))
def test_random_agent_smoke_with_fencing(seed):
    """Random agent plays to BEFORE_SCORING with fencing in the action set."""
    from tests.test_utils import IMPLEMENTED_NON_ATOMIC_SPACES, random_agent_play
    # IMPLEMENTED_NON_ATOMIC_SPACES is derived from NONATOMIC_HANDLERS at
    # import time; post-TASK_6 it includes both "fencing" and
    # "farm_redevelopment".
    assert "fencing" in IMPLEMENTED_NON_ATOMIC_SPACES
    assert "farm_redevelopment" in IMPLEMENTED_NON_ATOMIC_SPACES
    state, trace = random_agent_play(setup(seed=seed), seed=seed)
    from agricola.constants import Phase
    assert state.phase == Phase.BEFORE_SCORING
