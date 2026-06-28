"""Tests for the Farm Expansion action space.

Farm Expansion is the first space using the multi-shot sub-action pending
pattern introduced in Task 5D. Coverage:

- Basic walks (rooms-only, stables-only, rooms-then-stables, stables-then-rooms).
- Multi-room and multi-stable within one session (within-action adjacency
  chaining for rooms; supply decrement for stables).
- max_builds semantics (None from Farm Expansion = unbounded; dynamic
  constraints in the enumerator handle bounding).
- Singleton-Stop states (supply exhausted, affordability exhausted) under
  Approach 2 — Stop is always the explicit exit.
- Once-per-category rule (parametrized over rooms/stables).
- Adjacency rule for rooms (incl. within-action chaining).
- Pasture cache recompute when a stable lands inside an existing pasture
  (the fix for the latent bug in Task 5C's _execute_build_stable).
- Cost on pending (parametrized over wood/clay/stone house).
- Stack invariants (CommitBuildX does NOT pop; Stop pops).
- Placement legality.
"""
from __future__ import annotations

import dataclasses

import pytest

from agricola.actions import (
    ChooseSubAction,
    CommitBuildRoom,
    CommitBuildStable,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.constants import CellType, HouseMaterial
from agricola.engine import step
from agricola.legality import (
    _build_room_ctx,
    effective_payments,
    legal_actions,
    legal_placements,
)
from agricola.pasture import compute_pastures_from_arrays
from agricola.pending import (
    PendingBuildRooms,
    PendingBuildStables,
    PendingFarmExpansion,
)
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import (
    with_current_player,
    with_grid,
    with_house,
    with_resources,
)
from tests.test_utils import run_actions


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------

def _fe_setup(*, wood=0, clay=0, stone=0, reed=0, house=HouseMaterial.WOOD):
    """Fresh seed-0 state, player 0 active, with the given resources and house."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, wood=wood, clay=clay, stone=stone, reed=reed)
    if house is not HouseMaterial.WOOD:
        state = with_house(state, 0, house)
    return state


# ---------------------------------------------------------------------------
# Basic walks
# ---------------------------------------------------------------------------

def test_farm_expansion_rooms_only():
    """Build 1 room in a wood house: PlaceWorker -> ChooseSubAction(build_rooms)
    -> CommitBuildRoom -> Proceed (flip PendingBuildRooms to after) -> Stop (pops it)
    -> Proceed (flip parent to after-phase) -> Stop (pops parent).
    """
    state = _fe_setup(wood=5, reed=2)
    pre_wood = state.players[0].resources.wood
    state = run_actions(state, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
        CommitBuildRoom(row=0, col=0),  # adjacent to (1,0)
        Proceed(),    # flip PendingBuildRooms to its after-phase
        Stop(),       # pop PendingBuildRooms
        Proceed(),    # flip the parent to its after-phase
        Stop(),       # pop the parent
    ])
    assert state.pending_stack == ()
    assert state.players[0].farmyard.grid[0][0].cell_type == CellType.ROOM
    assert state.players[0].resources.wood == pre_wood - 5
    assert state.players[0].resources.reed == 0


def test_farm_expansion_stables_only():
    """Build 1 stable on Farm Expansion (costs 2 wood, distinct from Side Job)."""
    state = _fe_setup(wood=2)
    state = run_actions(state, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        CommitBuildStable(row=0, col=2),
        Proceed(),    # flip PendingBuildStables to its after-phase
        Stop(),       # pop PendingBuildStables
        Proceed(),    # flip the parent to its after-phase
        Stop(),       # pop the parent
    ])
    assert state.pending_stack == ()
    assert state.players[0].farmyard.grid[0][2].cell_type == CellType.STABLE
    assert state.players[0].resources.wood == 0


def test_farm_expansion_rooms_then_stables():
    """rooms-then-stables and stables-then-rooms reach identical end states."""
    state_rs = _fe_setup(wood=7, reed=2)  # 5 wood + 2 reed for room, +2 wood for stable
    state_rs = run_actions(state_rs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
        CommitBuildRoom(row=0, col=0),
        Proceed(),    # flip PendingBuildRooms to after
        Stop(),
        ChooseSubAction(name="build_stables"),
        CommitBuildStable(row=0, col=2),
        Proceed(),    # flip PendingBuildStables to after
        Stop(),       # pop PendingBuildStables
        Proceed(),    # flip the parent to its after-phase
        Stop(),       # pop the parent
    ])

    state_sr = _fe_setup(wood=7, reed=2)
    state_sr = run_actions(state_sr, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        CommitBuildStable(row=0, col=2),
        Proceed(),    # flip PendingBuildStables to after
        Stop(),
        ChooseSubAction(name="build_rooms"),
        CommitBuildRoom(row=0, col=0),
        Proceed(),    # flip PendingBuildRooms to after
        Stop(),       # pop PendingBuildRooms
        Proceed(),    # flip the parent to its after-phase
        Stop(),       # pop the parent
    ])

    # Both end states have: empty stack, room at (0,0), stable at (0,2), 0 wood, 0 reed.
    for state in (state_rs, state_sr):
        assert state.pending_stack == ()
        assert state.players[0].farmyard.grid[0][0].cell_type == CellType.ROOM
        assert state.players[0].farmyard.grid[0][2].cell_type == CellType.STABLE
        assert state.players[0].resources.wood == 0
        assert state.players[0].resources.reed == 0


# ---------------------------------------------------------------------------
# Multi-room / multi-stable semantics
# ---------------------------------------------------------------------------

def test_farm_expansion_multi_room_adjacency_chaining():
    """Within-action adjacency chaining: after building a new room, the cell
    adjacent to it becomes legal for the next commit."""
    state = _fe_setup(wood=15, reed=6)  # enough for 3 rooms
    # Step 1: confirm (0,0) is legal but (0,1) is NOT (no room adjacent yet).
    state = run_actions(state, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
    ])
    cells_before = {
        (a.row, a.col) for a in legal_actions(state)
        if isinstance(a, CommitBuildRoom)
    }
    assert (0, 0) in cells_before
    assert (0, 1) not in cells_before

    # Step 2: build at (0,0). Now (0,1) should appear (adjacent to (0,0)).
    state = run_actions(state, [CommitBuildRoom(row=0, col=0)])
    cells_after = {
        (a.row, a.col) for a in legal_actions(state)
        if isinstance(a, CommitBuildRoom)
    }
    assert (0, 1) in cells_after

    # Step 3: build at (0,1) and confirm both rooms are in place.
    state = run_actions(state, [
        CommitBuildRoom(row=0, col=1), Proceed(), Stop(), Proceed(), Stop()])
    assert state.players[0].farmyard.grid[0][0].cell_type == CellType.ROOM
    assert state.players[0].farmyard.grid[0][1].cell_type == CellType.ROOM


def test_farm_expansion_four_stables_exhausts_supply():
    """Build all 4 stables in one Farm Expansion; 5th commit becomes illegal."""
    state = _fe_setup(wood=8)
    state = run_actions(state, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        CommitBuildStable(row=0, col=1),
        CommitBuildStable(row=0, col=2),
        CommitBuildStable(row=0, col=3),
        CommitBuildStable(row=0, col=4),
    ])
    # 4 stables built, supply exhausted; before-phase work-complete → only Proceed.
    actions = legal_actions(state)
    assert actions == [Proceed()]


# ---------------------------------------------------------------------------
# Singleton-Stop states (Approach 2: Stop is always the explicit exit)
# ---------------------------------------------------------------------------

def test_farm_expansion_supply_exhausted_singleton_stop():
    """With 2 stables already built (via fixture), Farm Expansion can build
    2 more; after that, supply=0 and only Stop is legal."""
    state = _fe_setup(wood=10)
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.STABLE),
        (0, 1): Cell(cell_type=CellType.STABLE),
    })
    state = run_actions(state, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        CommitBuildStable(row=0, col=2),
        CommitBuildStable(row=0, col=3),
    ])
    # 4 stables on the grid; supply = 0. Before-phase work-complete → only Proceed.
    actions = legal_actions(state)
    assert actions == [Proceed()]


def test_farm_expansion_affordability_exhausted_singleton_stop():
    """Player has wood for 2 stables but supply for 4. After 2 commits,
    wood=0 (affordability is the binding constraint); supply still > 0;
    only Stop is legal. Proves the affordability check fires independently
    of supply / cap."""
    state = _fe_setup(wood=4)  # exactly 2 stables' worth
    state = run_actions(state, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        CommitBuildStable(row=0, col=1),
        CommitBuildStable(row=0, col=2),
    ])
    p = state.players[0]
    assert p.resources.wood == 0
    # 2 stables in supply still, but no wood => not buildable. Before-phase
    # work-complete → only Proceed.
    actions = legal_actions(state)
    assert actions == [Proceed()]


# ---------------------------------------------------------------------------
# Stop legality
# ---------------------------------------------------------------------------

def test_stop_not_legal_in_pending_build_stables_at_num_built_zero():
    """At num_built=0, Stop is not legal — must commit at least one."""
    state = _fe_setup(wood=10)
    state = run_actions(state, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
    ])
    actions = legal_actions(state)
    assert Stop() not in actions


def test_stop_not_legal_in_pending_build_rooms_at_num_built_zero():
    state = _fe_setup(wood=10, reed=4)
    state = run_actions(state, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
    ])
    actions = legal_actions(state)
    assert Stop() not in actions


def test_stop_not_legal_in_farm_expansion_until_category_chosen():
    """At PendingFarmExpansion with neither category chosen, Stop is illegal."""
    state = _fe_setup(wood=10, reed=4)
    state = run_actions(state, [PlaceWorker(space="farm_expansion")])
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFarmExpansion)
    assert top.room_chosen is False
    assert top.stable_chosen is False
    actions = legal_actions(state)
    assert Stop() not in actions


# ---------------------------------------------------------------------------
# Cost on pending (parametrized over house material)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("house,expected_cost", [
    (HouseMaterial.WOOD,  Resources(wood=5,  reed=2)),
    (HouseMaterial.CLAY,  Resources(clay=5,  reed=2)),
    (HouseMaterial.STONE, Resources(stone=5, reed=2)),
])
def test_pending_build_rooms_cost_by_house_material(house, expected_cost):
    state = _fe_setup(wood=10, clay=10, stone=10, reed=10, house=house)
    state = run_actions(state, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
    ])
    pending = state.pending_stack[-1]
    assert isinstance(pending, PendingBuildRooms)
    assert pending.max_builds is None
    assert pending.num_built == 0
    # The room cost now lives on the cost-modifier frontier (a singleton == ROOM_COSTS
    # in the Family game), resolved at the build, not stored on the frame.
    p = state.players[pending.player_idx]
    assert effective_payments(
        state, pending.player_idx, _build_room_ctx(p, 0)) == [expected_cost]


def test_pending_build_stables_farm_expansion_cost():
    """Farm Expansion's stable cost is 2 wood (distinct from Side Job's 1)."""
    state = _fe_setup(wood=5)
    state = run_actions(state, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
    ])
    pending = state.pending_stack[-1]
    assert isinstance(pending, PendingBuildStables)
    assert pending.cost == Resources(wood=2)
    assert pending.max_builds is None
    assert pending.num_built == 0


# ---------------------------------------------------------------------------
# Adjacency / placement rules for rooms
# ---------------------------------------------------------------------------

def test_room_adjacency_non_adjacent_cell_illegal():
    """A room cannot be placed on a cell with no orthogonally adjacent ROOM."""
    state = _fe_setup(wood=10, reed=4)
    # Starting rooms are at (1,0) and (2,0); (0,4) is not adjacent to either.
    state = run_actions(state, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
    ])
    cells = {(a.row, a.col) for a in legal_actions(state) if isinstance(a, CommitBuildRoom)}
    assert (0, 0) in cells  # adjacent to (1,0)
    assert (1, 1) in cells  # adjacent to (1,0)
    assert (2, 1) in cells  # adjacent to (2,0)
    assert (0, 4) not in cells  # far away


def test_room_cannot_be_built_inside_pasture():
    """Empty cells inside a pasture are off-limits for rooms (RULES.md
    'House and Rooms': new rooms must be on an empty, non-enclosed cell)."""
    state = _fe_setup(wood=15, reed=6)
    # Enclose the cell at (0,4) by setting fences around it. Need:
    #   - vertical fence at (row=0, col=4) (left edge of (0,4))
    #   - vertical fence at (row=0, col=5) (right edge of (0,4))
    #   - horizontal fence at (row=0, col=4) (top edge of (0,4))
    #   - horizontal fence at (row=1, col=4) (bottom edge of (0,4))
    p = state.players[0]
    fy = p.farmyard
    new_h = list(list(row) for row in fy.horizontal_fences)
    new_v = list(list(row) for row in fy.vertical_fences)
    new_h[0][4] = True
    new_h[1][4] = True
    new_v[0][4] = True
    new_v[0][5] = True
    new_h_t = tuple(tuple(row) for row in new_h)
    new_v_t = tuple(tuple(row) for row in new_v)
    new_pastures = compute_pastures_from_arrays(fy.grid, new_h_t, new_v_t)
    new_farmyard = dataclasses.replace(
        fy, horizontal_fences=new_h_t, vertical_fences=new_v_t, pastures=new_pastures,
    )
    new_player = dataclasses.replace(p, farmyard=new_farmyard)
    state = dataclasses.replace(
        state, players=(new_player, state.players[1]),
    )
    # (0,4) is now enclosed. It's not adjacent to any ROOM anyway, but the
    # enclosed check is independently enforced — and there's no way to put
    # a room there even if we tried.
    state = run_actions(state, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
    ])
    cells = {(a.row, a.col) for a in legal_actions(state) if isinstance(a, CommitBuildRoom)}
    assert (0, 4) not in cells


# ---------------------------------------------------------------------------
# Pasture cache recompute when a stable lands inside an existing pasture
# (the fix for the latent bug in Task 5C's _execute_build_stable)
# ---------------------------------------------------------------------------

def test_stable_inside_pasture_recomputes_pasture_cache():
    """Prefab a state with an existing 2-cell pasture (cells (0,3) and (0,4),
    enclosed by fences, both empty). Run Farm Expansion to place a stable
    at (0,4). Verify the resulting pasture has num_stables=1 and capacity
    doubled compared to the pre-build state.

    This is the fix for a latent bug in Task 5C: pasture cache wasn't
    being recomputed when a stable was placed. The bug couldn't be
    triggered in current gameplay (no resolver creates fences), but
    becomes real once Fencing lands.
    """
    state = _fe_setup(wood=2)
    p = state.players[0]
    fy = p.farmyard
    # Enclose cells (0,3) and (0,4) as a single 2-cell pasture.
    # Boundary fences:
    #   top: horizontal_fences[0][3], horizontal_fences[0][4]
    #   bottom: horizontal_fences[1][3], horizontal_fences[1][4]
    #   left: vertical_fences[0][3]
    #   right: vertical_fences[0][5]
    new_h = [list(row) for row in fy.horizontal_fences]
    new_v = [list(row) for row in fy.vertical_fences]
    new_h[0][3] = True
    new_h[0][4] = True
    new_h[1][3] = True
    new_h[1][4] = True
    new_v[0][3] = True
    new_v[0][5] = True
    new_h_t = tuple(tuple(row) for row in new_h)
    new_v_t = tuple(tuple(row) for row in new_v)
    new_pastures_before = compute_pastures_from_arrays(fy.grid, new_h_t, new_v_t)
    new_farmyard = dataclasses.replace(
        fy, horizontal_fences=new_h_t, vertical_fences=new_v_t,
        pastures=new_pastures_before,
    )
    new_player = dataclasses.replace(p, farmyard=new_farmyard)
    state = dataclasses.replace(state, players=(new_player, state.players[1]))

    # Pre-build state: one pasture covering (0,3) and (0,4), 0 stables.
    pastures_before = state.players[0].farmyard.pastures
    assert len(pastures_before) == 1
    assert pastures_before[0].cells == frozenset({(0, 3), (0, 4)})
    assert pastures_before[0].num_stables == 0
    assert pastures_before[0].capacity == 2 * 2 * (2 ** 0)  # 4

    # Run Farm Expansion: build a stable at (0,4), which is inside the pasture.
    state = run_actions(state, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        CommitBuildStable(row=0, col=4),
        Proceed(),    # flip PendingBuildStables to its after-phase
        Stop(),       # pop PendingBuildStables
        Proceed(),    # flip the parent to its after-phase
        Stop(),       # pop the parent
    ])

    # Post-build: same pasture, but now num_stables=1, capacity doubled.
    pastures_after = state.players[0].farmyard.pastures
    assert len(pastures_after) == 1
    assert pastures_after[0].cells == frozenset({(0, 3), (0, 4)})
    assert pastures_after[0].num_stables == 1
    assert pastures_after[0].capacity == 2 * 2 * (2 ** 1)  # 8
    # Sanity: the stable cell is now STABLE.
    assert state.players[0].farmyard.grid[0][4].cell_type == CellType.STABLE


# ---------------------------------------------------------------------------
# Once-per-category rule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("category,commit", [
    ("build_rooms", CommitBuildRoom(row=0, col=0)),
    ("build_stables", CommitBuildStable(row=0, col=2)),
])
def test_once_per_category_after_stop(category, commit):
    """After Proceed+Stop exits a build-X session, ChooseSubAction(category) is no
    longer legal at the parent PendingFarmExpansion."""
    state = _fe_setup(wood=15, reed=6)  # enough for either category
    state = run_actions(state, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name=category),
        commit,
        Proceed(),    # flip the build host to after
        Stop(),       # pop the build host
    ])
    # Back at PendingFarmExpansion; the chosen category is now flagged.
    actions = legal_actions(state)
    choose_names = {a.name for a in actions if isinstance(a, ChooseSubAction)}
    assert category not in choose_names


# ---------------------------------------------------------------------------
# Placement legality at the action-space level
# ---------------------------------------------------------------------------

def test_farm_expansion_not_legal_when_no_action_possible():
    """No wood, no reed — neither room nor stable is buildable."""
    state = _fe_setup()  # zero resources
    spaces = {pw.space for pw in legal_placements(state)}
    assert "farm_expansion" not in spaces


def test_farm_expansion_legal_rooms_only():
    """Enough resources for a room, but the player has no stable supply."""
    state = _fe_setup(wood=5, reed=2)
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.STABLE),
        (0, 1): Cell(cell_type=CellType.STABLE),
        (0, 2): Cell(cell_type=CellType.STABLE),
        (0, 3): Cell(cell_type=CellType.STABLE),
    })
    spaces = {pw.space for pw in legal_placements(state)}
    assert "farm_expansion" in spaces


def test_farm_expansion_legal_stables_only():
    """Enough resources for a stable, but not for a room (no reed)."""
    state = _fe_setup(wood=2)  # 2 wood = 1 stable, no reed for a room
    spaces = {pw.space for pw in legal_placements(state)}
    assert "farm_expansion" in spaces


# ---------------------------------------------------------------------------
# Stack invariants (choose-time flags, no-pop on commit, Stop pops)
# ---------------------------------------------------------------------------

def test_choose_subaction_writes_room_chosen_and_pushes_pending():
    state = _fe_setup(wood=5, reed=2)
    state = run_actions(state, [PlaceWorker(space="farm_expansion")])
    assert isinstance(state.pending_stack[-1], PendingFarmExpansion)
    assert state.pending_stack[-1].room_chosen is False

    state = run_actions(state, [ChooseSubAction(name="build_rooms")])
    # Top is now PendingBuildRooms; parent has room_chosen=True.
    assert isinstance(state.pending_stack[-1], PendingBuildRooms)
    parent = state.pending_stack[-2]
    assert isinstance(parent, PendingFarmExpansion)
    assert parent.room_chosen is True
    assert parent.stable_chosen is False


def test_commit_build_room_does_not_pop():
    """CommitBuildRoom leaves PendingBuildRooms on top (Approach 2)."""
    state = _fe_setup(wood=10, reed=4)
    state = run_actions(state, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
        CommitBuildRoom(row=0, col=0),
    ])
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildRooms)
    assert top.num_built == 1


def test_stop_pops_pending_build_stables_back_to_parent():
    state = _fe_setup(wood=10)
    state = run_actions(state, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        CommitBuildStable(row=0, col=2),
        Proceed(),    # flip PendingBuildStables to after
        Stop(),
    ])
    # PendingBuildStables popped; back at PendingFarmExpansion.
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFarmExpansion)
    assert top.stable_chosen is True
