"""Tests for agricola/scoring.py."""

import dataclasses

import pytest

from agricola.constants import CellType, HouseMaterial
from agricola.pasture import compute_pastures_from_arrays
from agricola.scoring import ScoreBreakdown, score, tiebreaker
from agricola.setup import setup
from agricola.resources import Animals, Resources
from agricola.state import (
    BoardState,
    Cell,
    Farmyard,
    GameState,
    PlayerState,
)


# ---------------------------------------------------------------------------
# Helpers shared with test_helpers.py (duplicated to keep tests self-contained)
# ---------------------------------------------------------------------------

def _empty_grid():
    return tuple(tuple(Cell() for _ in range(5)) for _ in range(3))


def _no_fences_h():
    return tuple(tuple(False for _ in range(5)) for _ in range(4))


def _no_fences_v():
    return tuple(tuple(False for _ in range(6)) for _ in range(3))


def _set_h(base, r, c, val=True):
    rows = [list(row) for row in base]
    rows[r][c] = val
    return tuple(tuple(row) for row in rows)


def _set_v(base, r, c, val=True):
    rows = [list(row) for row in base]
    rows[r][c] = val
    return tuple(tuple(row) for row in rows)


def _set_grid_cell(base_grid, r, c, cell: Cell):
    rows = [list(row) for row in base_grid]
    rows[r][c] = cell
    return tuple(tuple(row) for row in rows)


def _enclose_cell(r, c, hf, vf):
    hf = _set_h(hf, r,     c)
    hf = _set_h(hf, r + 1, c)
    vf = _set_v(vf, r, c)
    vf = _set_v(vf, r, c + 1)
    return hf, vf


def _make_farmyard(hf=None, vf=None, grid=None):
    grid = grid if grid is not None else _empty_grid()
    hf = hf if hf is not None else _no_fences_h()
    vf = vf if vf is not None else _no_fences_v()
    return Farmyard(
        grid=grid,
        horizontal_fences=hf,
        vertical_fences=vf,
        pastures=compute_pastures_from_arrays(grid, hf, vf),
    )


def _replace_player(state: GameState, player_idx: int, new_ps: PlayerState) -> GameState:
    players = list(state.players)
    players[player_idx] = new_ps
    return dataclasses.replace(state, players=tuple(players))


def _replace_board(state: GameState, new_board: BoardState) -> GameState:
    return dataclasses.replace(state, board=new_board)




def _set_major_owner(state: GameState, imp_idx: int, owner: int) -> GameState:
    owners = list(state.board.major_improvement_owners)
    owners[imp_idx] = owner
    new_board = BoardState(
        action_spaces=state.board.action_spaces,
        major_improvement_owners=tuple(owners),
        round_card_order=state.board.round_card_order,
    )
    return _replace_board(state, new_board)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_score_empty_farm_two_people():
    # Starting state: 2 wood rooms at (1,0) and (2,0), 13 empty cells, 2 people.
    # field_tiles=0→−1, pastures=0→−1, grain=0→−1, veg=0→−1,
    # sheep=0→−1, boar=0→−1, cattle=0→−1  (−7 total)
    # unused=13→−13, people=2→+6
    # All other categories: 0
    # Total: −7 + −13 + 6 = −14
    state = setup(seed=0)
    total, bd = score(state, 0)
    assert total == -14
    assert bd.field_tiles == -1
    assert bd.pastures == -1
    assert bd.grain == -1
    assert bd.vegetables == -1
    assert bd.sheep == -1
    assert bd.boar == -1
    assert bd.cattle == -1
    assert bd.unused_spaces == -13
    assert bd.people == 6
    assert bd.total == total


def test_field_tile_scoring():
    state = setup(seed=0)
    ps = state.players[0]
    # Place 3 field tiles
    grid = _empty_grid()
    grid = _set_grid_cell(grid, 0, 0, Cell(cell_type=CellType.FIELD))
    grid = _set_grid_cell(grid, 0, 1, Cell(cell_type=CellType.FIELD))
    grid = _set_grid_cell(grid, 0, 2, Cell(cell_type=CellType.FIELD))
    # Keep rooms at (1,0) and (2,0)
    grid = _set_grid_cell(grid, 1, 0, Cell(cell_type=CellType.ROOM))
    grid = _set_grid_cell(grid, 2, 0, Cell(cell_type=CellType.ROOM))
    new_ps = PlayerState(
        resources=ps.resources,
        animals=ps.animals,
        farmyard=_make_farmyard(grid=grid),
        house_material=ps.house_material,
        people_total=ps.people_total,
        people_home=ps.people_home,
    )
    state2 = _replace_player(state, 0, new_ps)
    total, bd = score(state2, 0)
    assert bd.field_tiles == 2  # 3 fields → 2 pts


def test_animal_scoring():
    state = setup(seed=0)
    ps = state.players[0]
    new_ps = PlayerState(
        resources=ps.resources,
        animals=Animals(sheep=4, boar=3, cattle=2),
        farmyard=ps.farmyard,
        house_material=ps.house_material,
        people_total=ps.people_total,
        people_home=ps.people_home,
    )
    state2 = _replace_player(state, 0, new_ps)
    _, bd = score(state2, 0)
    assert bd.sheep == 2    # 4–5 → 2 pts
    assert bd.boar == 2     # 3–4 → 2 pts
    assert bd.cattle == 2   # 2–3 → 2 pts


def test_begging_markers():
    state = setup(seed=0)
    ps = state.players[0]
    new_ps = PlayerState(
        resources=ps.resources,
        animals=ps.animals,
        farmyard=ps.farmyard,
        house_material=ps.house_material,
        people_total=ps.people_total,
        people_home=ps.people_home,
        begging_markers=2,
    )
    state2 = _replace_player(state, 0, new_ps)
    _, bd = score(state2, 0)
    assert bd.begging_markers == -6


def test_fenced_stable_scoring():
    # Stable inside a 1×1 pasture → 1 pt fenced stable
    state = setup(seed=0)
    ps = state.players[0]
    hf, vf = _enclose_cell(0, 2, _no_fences_h(), _no_fences_v())
    grid = _empty_grid()
    grid = _set_grid_cell(grid, 1, 0, Cell(cell_type=CellType.ROOM))
    grid = _set_grid_cell(grid, 2, 0, Cell(cell_type=CellType.ROOM))
    grid = _set_grid_cell(grid, 0, 2, Cell(cell_type=CellType.STABLE))
    new_ps = PlayerState(
        resources=ps.resources,
        animals=ps.animals,
        farmyard=_make_farmyard(hf=hf, vf=vf, grid=grid),
        house_material=ps.house_material,
        people_total=ps.people_total,
        people_home=ps.people_home,
    )
    state2 = _replace_player(state, 0, new_ps)
    _, bd = score(state2, 0)
    assert bd.fenced_stables == 1


def test_craft_building_bonus():
    # Player owns Joinery (index 7) and has 7 wood → 3 bonus pts
    state = setup(seed=0)
    ps = state.players[0]
    new_ps = PlayerState(
        resources=Resources(wood=7),
        animals=ps.animals,
        farmyard=ps.farmyard,
        house_material=ps.house_material,
        people_total=ps.people_total,
        people_home=ps.people_home,
    )
    state2 = _replace_player(state, 0, new_ps)
    state2 = _set_major_owner(state2, 7, 0)  # player 0 owns Joinery
    _, bd = score(state2, 0)
    assert bd.bonus_points == 3


def test_tiebreaker():
    state = setup(seed=0)
    ps = state.players[0]
    new_ps = PlayerState(
        resources=Resources(wood=3, clay=2, reed=1, stone=4, food=10),
        animals=ps.animals,
        farmyard=ps.farmyard,
        house_material=ps.house_material,
        people_total=ps.people_total,
        people_home=ps.people_home,
    )
    state2 = _replace_player(state, 0, new_ps)
    # No craft buildings owned: wood+clay+reed+stone = 3+2+1+4 = 10; food excluded
    assert tiebreaker(state2, 0) == 10


def test_tiebreaker_subtracts_craft_bonus_spending():
    # Player owns Joinery (idx 7) and has 7 wood — qualifies for 3 bonus pts,
    # spending 7 wood. Tiebreaker must subtract those 7 wood.
    # wood=7, clay=2, reed=1, stone=4 → raw total = 14
    # After spending 7 wood for Joinery bonus → 14 - 7 = 7
    state = setup(seed=0)
    ps = state.players[0]
    new_ps = PlayerState(
        resources=Resources(wood=7, clay=2, reed=1, stone=4),
        animals=ps.animals,
        farmyard=ps.farmyard,
        house_material=ps.house_material,
        people_total=ps.people_total,
        people_home=ps.people_home,
    )
    state2 = _replace_player(state, 0, new_ps)
    state2 = _set_major_owner(state2, 7, 0)
    assert tiebreaker(state2, 0) == 7
