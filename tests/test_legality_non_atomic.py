"""Tests for legal_placements — non-atomic action space legality and shared helpers.

The atomic-space tests live in test_legality_atomic.py. This file covers:
  - Each shared helper (_can_bake_bread, _can_sow, _can_plow, _can_build_stable,
    _can_afford_room, _has_room_placement, _can_build_room, _can_renovate,
    _can_afford_any_major_improvement) directly.
  - Per-space legality for: farm_expansion, farmland, side_job, grain_utilization,
    sheep_market, pig_market, cattle_market, major_improvement, house_redevelopment,
    cultivation, farm_redevelopment.
  - Cross-cutting: fencing and lessons never appear in legal_placements output.
"""
from __future__ import annotations

import dataclasses

import pytest

from agricola.actions import PlaceWorker
from agricola.constants import CellType, HouseMaterial
from agricola.legality import (
    _can_afford_any_major_improvement,
    _can_afford_room,
    _can_bake_bread,
    _can_build_room,
    _can_build_stable,
    _can_plow,
    _can_renovate,
    _can_sow,
    _has_room_placement,
    legal_placements,
)
from agricola.pasture import compute_pastures_from_arrays
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import Cell, get_space, with_space


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _spaces(result: list[PlaceWorker]) -> set[str]:
    return {pw.space for pw in result}


def _set_space(state, space_id: str, **kwargs):
    new_space = dataclasses.replace(get_space(state.board, space_id), **kwargs)
    new_board = with_space(state.board, space_id, new_space)
    return dataclasses.replace(state, board=new_board)


def _reveal_space(state, space_id: str):
    return _set_space(state, space_id, revealed=True)


def _set_player(state, player_idx: int, **kwargs):
    old = state.players[player_idx]
    new_player = dataclasses.replace(old, **kwargs)
    new_players = (
        new_player if player_idx == 0 else state.players[0],
        new_player if player_idx == 1 else state.players[1],
    )
    return dataclasses.replace(state, players=new_players)


def _set_grid(state, player_idx: int, cells: dict):
    """Return a new state with specific (r, c) cells replaced on the player's grid.

    `cells` is a dict mapping (r, c) -> Cell.

    Recomputes `pastures` explicitly because auto-fill was removed in
    CHANGES.md Change 3 — adding a STABLE inside an existing pasture would
    change `num_stables`/`capacity`, so this helper recomputes unconditionally.
    """
    player = state.players[player_idx]
    grid = [list(row) for row in player.farmyard.grid]
    for (r, c), cell in cells.items():
        grid[r][c] = cell
    new_grid = tuple(tuple(row) for row in grid)
    new_farmyard = dataclasses.replace(
        player.farmyard,
        grid=new_grid,
        pastures=compute_pastures_from_arrays(
            new_grid,
            player.farmyard.horizontal_fences,
            player.farmyard.vertical_fences,
        ),
    )
    new_player = dataclasses.replace(player, farmyard=new_farmyard)
    return _set_player(state, player_idx, farmyard=new_player.farmyard)


def _set_resources(state, player_idx: int, **kwargs):
    """Convenience: replace one or more resource fields on the player."""
    res = state.players[player_idx].resources
    new_res = dataclasses.replace(res, **kwargs)
    return _set_player(state, player_idx, resources=new_res)


def _set_owner(state, idx: int, owner):
    """Set major_improvement_owners[idx] = owner (int or None)."""
    owners = list(state.board.major_improvement_owners)
    owners[idx] = owner
    new_board = dataclasses.replace(state.board, major_improvement_owners=tuple(owners))
    return dataclasses.replace(state, board=new_board)


def _enclose_cell(state, player_idx: int, r: int, c: int):
    """Return a new state with cell (r, c) fully enclosed by 4 fences.

    The cell forms a 1×1 single-cell pasture. Useful for testing helpers
    that need to distinguish empty vs. enclosed-empty cells.

    Fence index conventions (see state.py):
      horizontal_fences[r][c] sits between row r-1 and row r at column c.
      vertical_fences[r][c]  sits between column c-1 and column c at row r.
    Cell (r, c) is bordered by:
      top:    horizontal_fences[r][c]
      bottom: horizontal_fences[r+1][c]
      left:   vertical_fences[r][c]
      right:  vertical_fences[r][c+1]
    """
    farmyard = state.players[player_idx].farmyard
    h = [list(row) for row in farmyard.horizontal_fences]
    v = [list(row) for row in farmyard.vertical_fences]
    h[r][c] = True       # top
    h[r + 1][c] = True   # bottom
    v[r][c] = True       # left
    v[r][c + 1] = True   # right
    new_h = tuple(tuple(row) for row in h)
    new_v = tuple(tuple(row) for row in v)
    new_farmyard = dataclasses.replace(
        farmyard,
        horizontal_fences=new_h,
        vertical_fences=new_v,
        pastures=compute_pastures_from_arrays(farmyard.grid, new_h, new_v),
    )
    return _set_player(state, player_idx, farmyard=new_farmyard)


def _enclose_rect(state, player_idx: int,
                  r0: int, c0: int, r1: int, c1: int):
    """Return a new state with the rectangle [r0..r1] × [c0..c1] enclosed by fences.

    Fences are placed only on the outer boundary of the rectangle so the
    interior cells form one connected pasture.
    """
    farmyard = state.players[player_idx].farmyard
    h = [list(row) for row in farmyard.horizontal_fences]
    v = [list(row) for row in farmyard.vertical_fences]
    # Top and bottom edges of the rectangle.
    for c in range(c0, c1 + 1):
        h[r0][c] = True       # top edge
        h[r1 + 1][c] = True   # bottom edge
    # Left and right edges of the rectangle.
    for r in range(r0, r1 + 1):
        v[r][c0] = True       # left edge
        v[r][c1 + 1] = True   # right edge
    new_h = tuple(tuple(row) for row in h)
    new_v = tuple(tuple(row) for row in v)
    new_farmyard = dataclasses.replace(
        farmyard,
        horizontal_fences=new_h,
        vertical_fences=new_v,
        pastures=compute_pastures_from_arrays(farmyard.grid, new_h, new_v),
    )
    return _set_player(state, player_idx, farmyard=new_farmyard)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def state():
    return setup(seed=0)


@pytest.fixture
def active(state):
    return state.current_player


# ---------------------------------------------------------------------------
# _can_bake_bread
# ---------------------------------------------------------------------------

def test_can_bake_bread_with_fireplace_and_grain(state, active):
    state = _set_owner(state, 0, active)  # Fireplace at index 0
    state = _set_resources(state, active, grain=1)
    p = state.players[active]
    assert _can_bake_bread(state, p) is True


def test_can_bake_bread_no_improvement(state, active):
    state = _set_resources(state, active, grain=5)
    p = state.players[active]
    # No improvement owned → False even with plenty of grain.
    assert _can_bake_bread(state, p) is False


def test_can_bake_bread_no_grain(state, active):
    state = _set_owner(state, 0, active)
    p = state.players[active]
    # Owns Fireplace but 0 grain.
    assert p.resources.grain == 0
    assert _can_bake_bread(state, p) is False


# ---------------------------------------------------------------------------
# _can_sow
# ---------------------------------------------------------------------------

def test_can_sow_grain_on_empty_field(state, active):
    state = _set_grid(state, active, {(0, 0): Cell(cell_type=CellType.FIELD)})
    state = _set_resources(state, active, grain=1)
    p = state.players[active]
    assert _can_sow(p) is True


def test_can_sow_no_empty_field(state, active):
    # All field cells are planted (grain=2 or veg=1).
    state = _set_grid(state, active, {(0, 0): Cell(cell_type=CellType.FIELD, grain=2)})
    state = _set_resources(state, active, grain=1)
    p = state.players[active]
    assert _can_sow(p) is False


def test_can_sow_no_seeds(state, active):
    state = _set_grid(state, active, {(0, 0): Cell(cell_type=CellType.FIELD)})
    p = state.players[active]
    # No grain, no veg in supply.
    assert p.resources.grain == 0 and p.resources.veg == 0
    assert _can_sow(p) is False


# ---------------------------------------------------------------------------
# _can_plow
# ---------------------------------------------------------------------------

def test_can_plow_first_field(state, active):
    # Fresh state: 2 rooms at (1,0) and (2,0); 13 empty cells; no fields.
    p = state.players[active]
    assert _can_plow(p) is True


def test_can_plow_adjacent(state, active):
    state = _set_grid(state, active, {(0, 0): Cell(cell_type=CellType.FIELD)})
    p = state.players[active]
    # (0, 1) is empty and adjacent to (0, 0).
    assert _can_plow(p) is True


def test_can_plow_no_adjacent(state, active):
    # Field at (0, 0). All neighbors of (0, 0) — namely (0, 1) and (1, 0) — must be non-EMPTY.
    # (1, 0) is already a ROOM. Make (0, 1) a ROOM too. Then no adjacent EMPTY exists.
    state = _set_grid(state, active, {
        (0, 0): Cell(cell_type=CellType.FIELD),
        (0, 1): Cell(cell_type=CellType.ROOM),
    })
    p = state.players[active]
    assert _can_plow(p) is False


def test_can_plow_excludes_enclosed_cell(state, active):
    # Single empty cell at (0, 4) is enclosed by a single-cell pasture; all other
    # non-room cells are FIELDs. Without the enclosed-cell filter, _can_plow would
    # return True (the empty (0, 4) is adjacent to fields). With the filter it
    # returns False — enclosed empty cells cannot be converted to fields.
    cells = {}
    for r in range(3):
        for c in range(5):
            if (r, c) not in {(1, 0), (2, 0), (0, 4)}:
                cells[(r, c)] = Cell(cell_type=CellType.FIELD)
    state = _set_grid(state, active, cells)
    state = _enclose_cell(state, active, 0, 4)
    p = state.players[active]
    # Sanity: the only EMPTY cell is (0, 4) and it is enclosed.
    enclosed = {cell for past in p.farmyard.pastures for cell in past.cells}
    assert (0, 4) in enclosed
    assert all(
        p.farmyard.grid[r][c].cell_type != CellType.EMPTY
        for r in range(3) for c in range(5)
        if (r, c) != (0, 4)
    )
    assert _can_plow(p) is False


def test_can_plow_first_field_excludes_enclosed_cells(state, active):
    # Exercises the first-field branch (no fields exist) under the enclosed filter:
    # 3×2 pasture covers cols 3 and 4 (6 enclosed empty cells); all other 9 cells
    # are ROOMs. There are no fields, but every EMPTY cell is enclosed → the
    # first-field branch must return False (it would erroneously return True
    # without the enclosed-cell filter).
    cells = {}
    for r in range(3):
        for c in range(3):  # cols 0..2 → 9 cells, all rooms
            cells[(r, c)] = Cell(cell_type=CellType.ROOM)
    state = _set_grid(state, active, cells)
    state = _enclose_rect(state, active, 0, 3, 2, 4)
    p = state.players[active]
    # Sanity: cols 3 and 4 are all EMPTY and all enclosed; no FIELD cells exist;
    # cols 0..2 are all ROOM.
    enclosed = {cell for past in p.farmyard.pastures for cell in past.cells}
    assert enclosed == {(r, c) for r in range(3) for c in (3, 4)}
    assert all(
        p.farmyard.grid[r][c].cell_type == CellType.EMPTY
        for r in range(3) for c in (3, 4)
    )
    assert all(
        p.farmyard.grid[r][c].cell_type != CellType.FIELD
        for r in range(3) for c in range(5)
    )
    assert _can_plow(p) is False


# ---------------------------------------------------------------------------
# _can_build_stable (parameterized: combines empty-cell + supply + affordability)
# ---------------------------------------------------------------------------

def test_can_build_stable_legal_with_wood(state, active):
    # Fresh state: 13 empty cells, all 4 stables in supply. Add wood for Side Job cost.
    state = _set_resources(state, active, wood=1)
    p = state.players[active]
    assert _can_build_stable(p, Resources(wood=1)) is True


def test_can_build_stable_no_supply(state, active):
    # Convert 4 cells to STABLE so 0 stables remain in supply.
    state = _set_grid(state, active, {
        (0, 0): Cell(cell_type=CellType.STABLE),
        (0, 1): Cell(cell_type=CellType.STABLE),
        (0, 2): Cell(cell_type=CellType.STABLE),
        (0, 3): Cell(cell_type=CellType.STABLE),
    })
    state = _set_resources(state, active, wood=10)
    p = state.players[active]
    assert _can_build_stable(p, Resources(wood=1)) is False


def test_can_build_stable_no_empty_cell(state, active):
    # Fill every empty cell with a FIELD; then there are no EMPTY cells left.
    cells = {}
    for r in range(3):
        for c in range(5):
            if (r, c) not in {(1, 0), (2, 0)}:  # leave the 2 starting rooms
                cells[(r, c)] = Cell(cell_type=CellType.FIELD)
    state = _set_grid(state, active, cells)
    state = _set_resources(state, active, wood=10)
    p = state.players[active]
    assert _can_build_stable(p, Resources(wood=1)) is False


def test_can_build_stable_insufficient_wood(state, active):
    # 13 empty cells + supply, but no wood — cost check fails.
    p = state.players[active]  # fresh state has 0 wood
    assert _can_build_stable(p, Resources(wood=1)) is False


def test_can_build_stable_farm_expansion_cost(state, active):
    # Farm Expansion uses 2 wood per stable, distinct from Side Job's 1 wood.
    state = _set_resources(state, active, wood=1)
    p = state.players[active]
    assert _can_build_stable(p, Resources(wood=2)) is False
    state = _set_resources(state, active, wood=2)
    p = state.players[active]
    assert _can_build_stable(p, Resources(wood=2)) is True


# ---------------------------------------------------------------------------
# _can_afford_room  /  _has_room_placement  /  _can_build_room
# ---------------------------------------------------------------------------

def test_can_afford_room_legal(state, active):
    # Wood house at fresh setup needs 5 wood + 2 reed.
    state = _set_resources(state, active, wood=5, reed=2)
    p = state.players[active]
    assert _can_afford_room(p) is True


def test_can_afford_room_insufficient(state, active):
    # 4 wood < 5 required, with reed satisfied.
    state = _set_resources(state, active, wood=4, reed=2)
    p = state.players[active]
    assert _can_afford_room(p) is False


def test_has_room_placement_legal(state, active):
    # Fresh farmyard: starting rooms at (1,0) and (2,0); their adjacent EMPTY cells
    # (0,0), (1,1), (2,1) are all unoccupied and non-enclosed.
    p = state.players[active]
    assert _has_room_placement(p) is True


def test_has_room_placement_no_adjacent_empty(state, active):
    # Surround the starting rooms with non-EMPTY cells. Adjacent to (1,0) and (2,0)
    # are (0,0), (1,1), (2,1). Make all three FIELDs.
    state = _set_grid(state, active, {
        (0, 0): Cell(cell_type=CellType.FIELD),
        (1, 1): Cell(cell_type=CellType.FIELD),
        (2, 1): Cell(cell_type=CellType.FIELD),
    })
    p = state.players[active]
    assert _has_room_placement(p) is False


def test_has_room_placement_excludes_enclosed_cell(state, active):
    # Make (1,1) and (2,1) FIELDs — non-EMPTY. Leave (0,0) EMPTY but enclose it
    # with fences. The only room-adjacent empty cell is enclosed; without the
    # filter the helper would return True. With the filter it returns False.
    state = _set_grid(state, active, {
        (1, 1): Cell(cell_type=CellType.FIELD),
        (2, 1): Cell(cell_type=CellType.FIELD),
    })
    state = _enclose_cell(state, active, 0, 0)
    p = state.players[active]
    # Sanity: (0,0) is EMPTY and enclosed; (1,1) and (2,1) are FIELDs.
    assert p.farmyard.grid[0][0].cell_type == CellType.EMPTY
    enclosed = {cell for past in p.farmyard.pastures for cell in past.cells}
    assert (0, 0) in enclosed
    assert _has_room_placement(p) is False


def test_can_build_room_legal(state, active):
    # Fresh state: house is WOOD; 5 wood + 2 reed needed; (0,0) etc. are empty
    # and adjacent to the existing rooms at (1,0) and (2,0).
    state = _set_resources(state, active, wood=5, reed=2)
    p = state.players[active]
    assert _can_build_room(p) is True


def test_can_build_room_no_resources(state, active):
    # 4 wood < 5 required.
    state = _set_resources(state, active, wood=4, reed=2)
    p = state.players[active]
    assert _can_build_room(p) is False


def test_can_build_room_no_adjacent_empty(state, active):
    # Affordability OK; placement geometry blocked by FIELDs surrounding the rooms.
    state = _set_resources(state, active, wood=5, reed=2)
    state = _set_grid(state, active, {
        (0, 0): Cell(cell_type=CellType.FIELD),
        (1, 1): Cell(cell_type=CellType.FIELD),
        (2, 1): Cell(cell_type=CellType.FIELD),
    })
    p = state.players[active]
    assert _can_build_room(p) is False


# ---------------------------------------------------------------------------
# _can_renovate
# ---------------------------------------------------------------------------

def test_can_renovate_wood_to_clay(state, active):
    # Fresh state: 2-room wood house. 2 clay + 1 reed required.
    state = _set_resources(state, active, clay=2, reed=1)
    p = state.players[active]
    assert _can_renovate(p) is True


def test_can_renovate_already_stone(state, active):
    state = _set_player(state, active, house_material=HouseMaterial.STONE)
    state = _set_resources(state, active, stone=99, reed=99)
    p = state.players[active]
    assert _can_renovate(p) is False


def test_can_renovate_insufficient_resources(state, active):
    # Wood house, 2 rooms; 1 clay (< 2 needed).
    state = _set_resources(state, active, clay=1, reed=1)
    p = state.players[active]
    assert _can_renovate(p) is False


# ---------------------------------------------------------------------------
# _can_afford_any_major_improvement
# ---------------------------------------------------------------------------

def test_can_afford_major_improvement_basic(state, active):
    # Fresh state: all 10 unowned. 2 clay → can afford index 0 (Fireplace, 2 clay).
    state = _set_resources(state, active, clay=2)
    p = state.players[active]
    assert _can_afford_any_major_improvement(state, p) is True


def test_can_afford_major_improvement_return_fireplace(state, active):
    # Owns Fireplace at index 0; 0 clay; Cooking Hearth (idx 2) is unowned.
    # Can buy Cooking Hearth by returning the Fireplace.
    state = _set_owner(state, 0, active)
    p = state.players[active]
    # Sanity: the player has 0 clay and there are plenty of unaffordable indices.
    assert p.resources.clay == 0
    assert _can_afford_any_major_improvement(state, p) is True


def test_can_afford_major_improvement_all_owned(state, active):
    # Mark all 10 owned (by either player); nothing left to buy.
    other = 1 - active
    for i in range(10):
        state = _set_owner(state, i, other if i % 2 == 0 else active)
    state = _set_resources(state, active, wood=99, clay=99, reed=99, stone=99)
    p = state.players[active]
    assert _can_afford_any_major_improvement(state, p) is False


# ---------------------------------------------------------------------------
# Per-space: legal when conditions met
# ---------------------------------------------------------------------------

def test_farm_expansion_legal_can_build_room(state, active):
    state = _set_resources(state, active, wood=5, reed=2)
    assert PlaceWorker(space="farm_expansion") in legal_placements(state)


def test_farm_expansion_legal_can_build_stable(state, active):
    # 2 wood + an empty cell + stables in supply = stable-only path is legal.
    # No reed → cannot build a room. Must rely on stable path.
    state = _set_resources(state, active, wood=2, reed=0)
    assert PlaceWorker(space="farm_expansion") in legal_placements(state)


def test_farmland_legal(state):
    # Fresh setup: no fields, plenty of empty cells. First plow is legal.
    assert PlaceWorker(space="farmland") in legal_placements(state)


def test_side_job_legal_can_build_stable(state, active):
    # 1 wood + empty cell + stables in supply.
    state = _set_resources(state, active, wood=1)
    assert PlaceWorker(space="side_job") in legal_placements(state)


def test_side_job_legal_can_bake_bread(state, active):
    # No wood. Owns Fireplace and 1 grain.
    state = _set_owner(state, 0, active)
    state = _set_resources(state, active, grain=1, wood=0)
    assert PlaceWorker(space="side_job") in legal_placements(state)


def test_grain_utilization_legal_can_sow(state, active):
    state = _reveal_space(state, "grain_utilization")
    state = _set_grid(state, active, {(0, 0): Cell(cell_type=CellType.FIELD)})
    state = _set_resources(state, active, grain=1)
    assert PlaceWorker(space="grain_utilization") in legal_placements(state)


def test_grain_utilization_legal_can_bake_bread(state, active):
    state = _reveal_space(state, "grain_utilization")
    state = _set_owner(state, 0, active)
    state = _set_resources(state, active, grain=1)
    assert PlaceWorker(space="grain_utilization") in legal_placements(state)


def test_sheep_market_legal(state):
    state = _set_space(state, "sheep_market",
                       revealed=True,
                       accumulated_amount=1)
    assert PlaceWorker(space="sheep_market") in legal_placements(state)


def test_pig_market_legal(state):
    state = _set_space(state, "pig_market",
                       revealed=True,
                       accumulated_amount=1)
    assert PlaceWorker(space="pig_market") in legal_placements(state)


def test_cattle_market_legal(state):
    state = _set_space(state, "cattle_market",
                       revealed=True,
                       accumulated_amount=1)
    assert PlaceWorker(space="cattle_market") in legal_placements(state)


def test_major_improvement_legal(state, active):
    state = _reveal_space(state, "major_improvement")
    state = _set_resources(state, active, clay=2)
    assert PlaceWorker(space="major_improvement") in legal_placements(state)


def test_house_redevelopment_legal(state, active):
    state = _reveal_space(state, "house_redevelopment")
    state = _set_resources(state, active, clay=2, reed=1)
    assert PlaceWorker(space="house_redevelopment") in legal_placements(state)


def test_cultivation_legal_can_plow(state):
    # Fresh state: no fields, can plow first field anywhere.
    state = _reveal_space(state, "cultivation")
    assert PlaceWorker(space="cultivation") in legal_placements(state)


def test_cultivation_legal_can_sow(state, active):
    # Block plow: fill all empty cells. Allow sow: one cell becomes a planted-empty FIELD.
    state = _reveal_space(state, "cultivation")
    cells = {}
    for r in range(3):
        for c in range(5):
            if (r, c) not in {(1, 0), (2, 0)}:  # keep starting rooms
                cells[(r, c)] = Cell(cell_type=CellType.STABLE)
    # Replace one stable with an empty FIELD to enable sow.
    cells[(0, 0)] = Cell(cell_type=CellType.FIELD)
    state = _set_grid(state, active, cells)
    state = _set_resources(state, active, grain=1)
    # Sanity: cannot plow (no EMPTY cells), but can sow.
    p = state.players[active]
    assert _can_plow(p) is False
    assert _can_sow(p) is True
    assert PlaceWorker(space="cultivation") in legal_placements(state)


def test_farm_redevelopment_legal(state, active):
    state = _reveal_space(state, "farm_redevelopment")
    state = _set_resources(state, active, clay=2, reed=1)
    assert PlaceWorker(space="farm_redevelopment") in legal_placements(state)


# ---------------------------------------------------------------------------
# Per-space: illegal when conditions fail
# ---------------------------------------------------------------------------

def test_farm_expansion_illegal_cannot_build_anything(state, active):
    # No wood, no reed, all 4 stables already built (consumes 4 of the 13 empty cells).
    state = _set_resources(state, active, wood=0, reed=0)
    state = _set_grid(state, active, {
        (0, 0): Cell(cell_type=CellType.STABLE),
        (0, 1): Cell(cell_type=CellType.STABLE),
        (0, 2): Cell(cell_type=CellType.STABLE),
        (0, 3): Cell(cell_type=CellType.STABLE),
    })
    assert PlaceWorker(space="farm_expansion") not in legal_placements(state)


def test_farmland_illegal_no_valid_cell(state, active):
    # Fill every cell that is currently EMPTY with a STABLE. Two starting rooms remain.
    cells = {}
    for r in range(3):
        for c in range(5):
            if (r, c) not in {(1, 0), (2, 0)}:
                cells[(r, c)] = Cell(cell_type=CellType.STABLE)
    state = _set_grid(state, active, cells)
    assert PlaceWorker(space="farmland") not in legal_placements(state)


def test_side_job_illegal_neither_option(state, active):
    # No wood, no baking improvement.
    state = _set_resources(state, active, wood=0, grain=0)
    assert PlaceWorker(space="side_job") not in legal_placements(state)


def test_grain_utilization_illegal_neither_option(state, active):
    # Reveal the space; player has no empty field (no fields at all) and no baking improvement.
    state = _reveal_space(state, "grain_utilization")
    # Sanity: fresh state has no fields and no baking improvement.
    assert PlaceWorker(space="grain_utilization") not in legal_placements(state)


def test_sheep_market_illegal_zero_accumulation(state):
    state = _set_space(state, "sheep_market",
                       revealed=True,
                       accumulated_amount=0)
    assert PlaceWorker(space="sheep_market") not in legal_placements(state)


def test_pig_market_illegal_zero_accumulation(state):
    state = _set_space(state, "pig_market",
                       revealed=True,
                       accumulated_amount=0)
    assert PlaceWorker(space="pig_market") not in legal_placements(state)


def test_cattle_market_illegal_zero_accumulation(state):
    state = _set_space(state, "cattle_market",
                       revealed=True,
                       accumulated_amount=0)
    assert PlaceWorker(space="cattle_market") not in legal_placements(state)


def test_major_improvement_illegal_cannot_afford_any(state):
    # Reveal the space; fresh player has 0 of every resource → no major is affordable
    # and no Fireplace is owned (which would otherwise enable Cooking Hearth).
    state = _reveal_space(state, "major_improvement")
    assert PlaceWorker(space="major_improvement") not in legal_placements(state)


def test_house_redevelopment_illegal_already_stone(state, active):
    state = _reveal_space(state, "house_redevelopment")
    state = _set_player(state, active, house_material=HouseMaterial.STONE)
    state = _set_resources(state, active, stone=99, reed=99)
    assert PlaceWorker(space="house_redevelopment") not in legal_placements(state)


def test_farm_redevelopment_illegal_already_stone(state, active):
    state = _reveal_space(state, "farm_redevelopment")
    state = _set_player(state, active, house_material=HouseMaterial.STONE)
    state = _set_resources(state, active, stone=99, reed=99)
    assert PlaceWorker(space="farm_redevelopment") not in legal_placements(state)


def test_cultivation_illegal_neither_option(state, active):
    # No empty cells at all → cannot plow. No fields → cannot sow.
    state = _reveal_space(state, "cultivation")
    cells = {}
    for r in range(3):
        for c in range(5):
            if (r, c) not in {(1, 0), (2, 0)}:
                cells[(r, c)] = Cell(cell_type=CellType.STABLE)
    state = _set_grid(state, active, cells)
    # Sanity: no fields, all non-room cells are STABLE.
    p = state.players[active]
    assert _can_plow(p) is False
    assert _can_sow(p) is False
    assert PlaceWorker(space="cultivation") not in legal_placements(state)


# ---------------------------------------------------------------------------
# Cross-cutting: fencing now legal post-TASK_6; lessons remains illegal
# ---------------------------------------------------------------------------

def test_fencing_present_in_legal_placements_with_resources(state):
    # TASK_6: Fencing is now implemented. Reveal the space and give the
    # player wood + fences supply; fencing should appear in legal_placements
    # because at least one legal pasture commit exists (e.g., a 1×1 at (0, 0)
    # or any other ENCLOSABLE cell).
    state = _reveal_space(state, "fencing")
    state = _set_resources(state, state.current_player, wood=99, clay=99, reed=99, stone=99)
    assert "fencing" in _spaces(legal_placements(state))


def test_lessons_absent_from_legal_placements(state):
    # Lessons is always illegal in the Family game; it never appears.
    assert "lessons" not in _spaces(legal_placements(state))
