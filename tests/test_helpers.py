"""Tests for agricola/helpers.py."""

import dataclasses

import pytest

from agricola.constants import CellType, HouseMaterial
from agricola.helpers import (
    breeding_frontier,
    can_accommodate,
    cooking_rates,
    enclosed_cells,
    extract_slots,
    fences_in_supply,
    pareto_frontier,
    stables_in_supply,
)
from agricola.pasture import compute_pastures_from_arrays
from agricola.setup import setup
from agricola.resources import Animals, Resources
from agricola.state import BoardState, Cell, Farmyard, GameState, PlayerState


# ---------------------------------------------------------------------------
# Farmyard / PlayerState construction helpers
# ---------------------------------------------------------------------------

def _empty_grid():
    return tuple(tuple(Cell() for _ in range(5)) for _ in range(3))


def _no_fences_h():
    return tuple(tuple(False for _ in range(5)) for _ in range(4))


def _no_fences_v():
    return tuple(tuple(False for _ in range(6)) for _ in range(3))


def _set_h(base, r, c, val=True):
    """Return new horizontal_fences with [r][c] set to val."""
    rows = [list(row) for row in base]
    rows[r][c] = val
    return tuple(tuple(row) for row in rows)


def _set_v(base, r, c, val=True):
    """Return new vertical_fences with [r][c] set to val."""
    rows = [list(row) for row in base]
    rows[r][c] = val
    return tuple(tuple(row) for row in rows)


def _set_grid_cell(base_grid, r, c, cell: Cell):
    rows = [list(row) for row in base_grid]
    rows[r][c] = cell
    return tuple(tuple(row) for row in rows)


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


def _make_player(farmyard: Farmyard, animals: Animals = None) -> PlayerState:
    return PlayerState(
        resources=Resources(),
        animals=animals or Animals(),
        farmyard=farmyard,
        house_material=HouseMaterial.WOOD,
        people_total=2,
        people_home=2,
    )


# ---------------------------------------------------------------------------
# Fence helper: enclose a single cell (r, c) with 4 explicit fence pieces
# ---------------------------------------------------------------------------

def _enclose_cell(r: int, c: int, hf, vf):
    """Add the 4 fence segments that enclose cell (r, c)."""
    hf = _set_h(hf, r,     c)   # top edge
    hf = _set_h(hf, r + 1, c)   # bottom edge
    vf = _set_v(vf, r, c)       # left edge
    vf = _set_v(vf, r, c + 1)   # right edge
    return hf, vf


# ---------------------------------------------------------------------------
# Pasture decomposition tests (farmyard.pastures populated by the
# `_make_farmyard` helper, which calls `compute_pastures_from_arrays`).
# ---------------------------------------------------------------------------

def test_no_fences_no_pastures():
    farmyard = _make_farmyard()
    assert farmyard.pastures == ()


def test_single_1x1_pasture():
    hf, vf = _enclose_cell(0, 0, _no_fences_h(), _no_fences_v())
    farmyard = _make_farmyard(hf=hf, vf=vf)
    pastures = farmyard.pastures
    assert len(pastures) == 1
    p = pastures[0]
    assert p.cells == frozenset([(0, 0)])
    assert p.num_stables == 0
    assert p.capacity == 2  # 2 * 1 * (2^0) = 2


def test_2x1_pasture():
    # Enclose cells (0,0) and (0,1) — a 1-row × 2-col pasture
    hf = _no_fences_h()
    vf = _no_fences_v()
    # Top edge for both columns
    hf = _set_h(hf, 0, 0)
    hf = _set_h(hf, 0, 1)
    # Bottom edge for both columns
    hf = _set_h(hf, 1, 0)
    hf = _set_h(hf, 1, 1)
    # Left outer edge
    vf = _set_v(vf, 0, 0)
    # Right outer edge
    vf = _set_v(vf, 0, 2)
    # No fence between (0,0) and (0,1) — they're in the same pasture
    farmyard = _make_farmyard(hf=hf, vf=vf)
    pastures = farmyard.pastures
    assert len(pastures) == 1
    p = pastures[0]
    assert p.cells == frozenset([(0, 0), (0, 1)])
    assert p.num_stables == 0
    assert p.capacity == 4  # 2 * 2 * (2^0) = 4


def test_stable_in_pasture():
    hf, vf = _enclose_cell(0, 0, _no_fences_h(), _no_fences_v())
    grid = _set_grid_cell(_empty_grid(), 0, 0, Cell(cell_type=CellType.STABLE))
    farmyard = _make_farmyard(hf=hf, vf=vf, grid=grid)
    pastures = farmyard.pastures
    assert len(pastures) == 1
    p = pastures[0]
    assert p.num_stables == 1
    assert p.capacity == 4  # 2 * 1 * (2^1) = 4


def test_two_stables_in_2x1():
    # 2-cell pasture, both cells are STABLE
    hf = _no_fences_h()
    vf = _no_fences_v()
    hf = _set_h(hf, 0, 0); hf = _set_h(hf, 0, 1)
    hf = _set_h(hf, 1, 0); hf = _set_h(hf, 1, 1)
    vf = _set_v(vf, 0, 0); vf = _set_v(vf, 0, 2)
    grid = _empty_grid()
    grid = _set_grid_cell(grid, 0, 0, Cell(cell_type=CellType.STABLE))
    grid = _set_grid_cell(grid, 0, 1, Cell(cell_type=CellType.STABLE))
    farmyard = _make_farmyard(hf=hf, vf=vf, grid=grid)
    pastures = farmyard.pastures
    assert len(pastures) == 1
    p = pastures[0]
    assert p.num_stables == 2
    assert p.capacity == 16  # 2 * 2 * (2^2) = 16


def test_two_adjacent_pastures():
    # Subdivide a 2×1 area into two 1×1 pastures with an internal fence
    hf = _no_fences_h()
    vf = _no_fences_v()
    hf = _set_h(hf, 0, 0); hf = _set_h(hf, 0, 1)
    hf = _set_h(hf, 1, 0); hf = _set_h(hf, 1, 1)
    vf = _set_v(vf, 0, 0)
    vf = _set_v(vf, 0, 1)   # internal fence between (0,0) and (0,1)
    vf = _set_v(vf, 0, 2)
    farmyard = _make_farmyard(hf=hf, vf=vf)
    pastures = farmyard.pastures
    assert len(pastures) == 2
    cells = {frozenset(p.cells) for p in pastures}
    assert frozenset([(0, 0)]) in cells
    assert frozenset([(0, 1)]) in cells
    for p in pastures:
        assert p.capacity == 2


def test_unfenced_cell_not_pasture():
    # Cell (1, 2) with no surrounding fences — not enclosed
    farmyard = _make_farmyard()
    pastures = farmyard.pastures
    enclosed = {cell for p in pastures for cell in p.cells}
    assert (1, 2) not in enclosed


# ---------------------------------------------------------------------------
# Cache structural-property tests
# (auto-fill was removed in CHANGES.md Change 3; these tests exercise the
# pasture decomposition produced by `_make_farmyard`, which calls
# `compute_pastures_from_arrays` explicitly. They check canonical ordering
# and equivalence, which MCTS subtree sharing depends on.)
# ---------------------------------------------------------------------------

def test_pastures_canonical_order():
    # Two single-cell enclosures at (0, 0) and (1, 3). Canonical order sorts
    # by min(cells) lexicographically, so (0, 0) must come before (1, 3).
    hf, vf = _enclose_cell(0, 0, _no_fences_h(), _no_fences_v())
    hf, vf = _enclose_cell(1, 3, hf, vf)
    farmyard = _make_farmyard(hf=hf, vf=vf)

    assert len(farmyard.pastures) == 2
    assert min(farmyard.pastures[0].cells) == (0, 0)
    assert min(farmyard.pastures[1].cells) == (1, 3)

    # Build a logically-equivalent farmyard the same way; the pastures tuples
    # must compare equal (canonical ordering => deterministic equality).
    hf2, vf2 = _enclose_cell(1, 3, _no_fences_h(), _no_fences_v())
    hf2, vf2 = _enclose_cell(0, 0, hf2, vf2)
    farmyard2 = _make_farmyard(hf=hf2, vf=vf2)
    assert farmyard.pastures == farmyard2.pastures


def test_equivalent_farmyards_compare_equal_and_hash_equal():
    # Two farmyards built by adding the same enclosures in different orders
    # must compare equal and hash equal. This is the structural guarantee
    # MCTS relies on for subtree sharing.
    hf1, vf1 = _enclose_cell(0, 0, _no_fences_h(), _no_fences_v())
    hf1, vf1 = _enclose_cell(2, 4, hf1, vf1)
    farmyard1 = _make_farmyard(hf=hf1, vf=vf1)

    hf2, vf2 = _enclose_cell(2, 4, _no_fences_h(), _no_fences_v())
    hf2, vf2 = _enclose_cell(0, 0, hf2, vf2)
    farmyard2 = _make_farmyard(hf=hf2, vf=vf2)

    assert farmyard1 == farmyard2
    assert hash(farmyard1) == hash(farmyard2)


def test_enclosed_cells_helper():
    # Fresh farmyard: empty set.
    fresh = _make_farmyard()
    assert enclosed_cells(fresh) == frozenset()

    # Two enclosures: union of all enclosed cells.
    hf, vf = _enclose_cell(0, 0, _no_fences_h(), _no_fences_v())
    hf, vf = _enclose_cell(2, 4, hf, vf)
    farmyard = _make_farmyard(hf=hf, vf=vf)
    assert enclosed_cells(farmyard) == frozenset([(0, 0), (2, 4)])


# ---------------------------------------------------------------------------
# extract_slots tests
# ---------------------------------------------------------------------------

def test_extract_slots_standalone_stable():
    # 1 standalone stable (not in any pasture) → num_flexible = 2 (stable + house)
    grid = _set_grid_cell(_empty_grid(), 1, 3, Cell(cell_type=CellType.STABLE))
    farmyard = _make_farmyard(grid=grid)
    player = _make_player(farmyard)
    caps, flex = extract_slots(player)
    assert caps == []
    assert flex == 2


# ---------------------------------------------------------------------------
# can_accommodate tests
# ---------------------------------------------------------------------------

def test_empty_farm_no_animals():
    assert can_accommodate([], 1, 0, 0, 0) is True


def test_fits_in_one_pasture():
    assert can_accommodate([4], 0, 4, 0, 0) is True


def test_overflow_to_flexible():
    # 4 sheep in pasture, 1 boar in house
    assert can_accommodate([4], 1, 4, 1, 0) is True


def test_overflow_exceeds_flexible():
    # 4 sheep fill the pasture; 2 boar need flexible slots but only 1 exists
    assert can_accommodate([4], 1, 4, 2, 0) is False


def test_two_types_two_pastures():
    # pasture 0 (cap 4) → sheep; pasture 1 (cap 2) → boar; 1 boar overflow → house
    assert can_accommodate([4, 2], 1, 4, 3, 0) is True


# ---------------------------------------------------------------------------
# pareto_frontier tests
# ---------------------------------------------------------------------------

def _fresh_player_no_stables(animals: Animals = None) -> PlayerState:
    """Player with no fences, no stables — only the house pet slot."""
    farmyard = _make_farmyard()
    return _make_player(farmyard, animals=animals or Animals())


def _player_with_1x1_pasture(animals: Animals = None) -> PlayerState:
    hf, vf = _enclose_cell(0, 0, _no_fences_h(), _no_fences_v())
    farmyard = _make_farmyard(hf=hf, vf=vf)
    return _make_player(farmyard, animals=animals or Animals())


def _player_with_two_pastures(animals: Animals = None) -> PlayerState:
    """2-cell pasture (cap 4) + 1-cell pasture (cap 2), no stables, house pet."""
    hf = _no_fences_h()
    vf = _no_fences_v()
    # Pasture 1: cells (0,0)+(0,1), cap 4
    hf = _set_h(hf, 0, 0); hf = _set_h(hf, 0, 1)
    hf = _set_h(hf, 1, 0); hf = _set_h(hf, 1, 1)
    vf = _set_v(vf, 0, 0); vf = _set_v(vf, 0, 2)
    # Pasture 2: cell (1,3), cap 2
    hf = _set_h(hf, 1, 3); hf = _set_h(hf, 2, 3)
    vf = _set_v(vf, 1, 3); vf = _set_v(vf, 1, 4)
    farmyard = _make_farmyard(hf=hf, vf=vf)
    return _make_player(farmyard, animals=animals or Animals())



def test_empty_farm():
    # No fences, no stables → only house pet slot (num_flexible=1)
    player = _fresh_player_no_stables()
    gained = Animals(sheep=1, boar=1, cattle=1)
    frontier = pareto_frontier(player, gained)
    frontier_set = set((a.sheep, a.boar, a.cattle) for a, _ in frontier)
    # Can keep exactly 1 animal total (one flexible slot); all single-animal configs are Pareto
    assert (1, 0, 0) in frontier_set
    assert (0, 1, 0) in frontier_set
    assert (0, 0, 1) in frontier_set
    # Cannot keep 2 or more
    assert not any(a.sheep + a.boar + a.cattle > 1 for a, _ in frontier)
    # Default rates (0,0,0) → food always 0
    assert all(food == 0 for _, food in frontier)


def test_worked_example():
    # pasture_capacities=[4, 2], num_flexible=1
    # current=(0, 4, 0), gained=(4, 0, 0) → s_max=4, b_max=4, c_max=0
    player = _player_with_two_pastures(animals=Animals(boar=4))
    gained = Animals(sheep=4)
    frontier = pareto_frontier(player, gained)
    frontier_set = set((a.sheep, a.boar, a.cattle) for a, _ in frontier)
    assert (4, 3, 0) in frontier_set
    assert (3, 4, 0) in frontier_set
    # (4, 4, 0) must NOT be in frontier (cannot accommodate)
    assert (4, 4, 0) not in frontier_set


def test_inventory_constraint():
    # b_max = 4, so (2, 5, 0) can never be returned
    player = _player_with_two_pastures(animals=Animals(boar=4))
    gained = Animals(sheep=4)
    frontier = pareto_frontier(player, gained)
    assert all(a.boar <= 4 for a, _ in frontier)


def test_discard_to_gain():
    # Player has 4 boar. Gains 4 sheep. Can discard boar to keep more sheep.
    player = _player_with_two_pastures(animals=Animals(boar=4))
    gained = Animals(sheep=4)
    frontier = pareto_frontier(player, gained)
    frontier_set = set((a.sheep, a.boar, a.cattle) for a, _ in frontier)
    assert (4, 0, 0) not in frontier_set  # dominated by (4, 3, 0)
    assert (4, 3, 0) in frontier_set


def test_no_gained_no_change():
    # Player has 1 sheep, gains nothing → frontier contains only (1, 0, 0)
    player = _player_with_1x1_pasture(animals=Animals(sheep=1))
    gained = Animals()
    frontier = pareto_frontier(player, gained)
    assert len(frontier) == 1
    animals, food = frontier[0]
    assert animals == Animals(sheep=1)
    assert food == 0


# ---------------------------------------------------------------------------
# cooking_rates tests
# ---------------------------------------------------------------------------

def _make_state_with_owners(owners: tuple) -> GameState:
    state = setup(seed=0)
    new_board = dataclasses.replace(state.board, major_improvement_owners=owners)
    return dataclasses.replace(state, board=new_board)


def test_no_cooking_improvement():
    state = _make_state_with_owners(tuple(None for _ in range(10)))
    assert cooking_rates(state, 0) == (0, 0, 0)


def test_fireplace_owned():
    owners = [None] * 10
    owners[0] = 0  # Fireplace (idx 0)
    state = _make_state_with_owners(tuple(owners))
    assert cooking_rates(state, 0) == (2, 2, 3)


def test_cooking_hearth_owned():
    owners = [None] * 10
    owners[2] = 0  # Cooking Hearth (idx 2)
    state = _make_state_with_owners(tuple(owners))
    assert cooking_rates(state, 0) == (2, 3, 4)


def test_hearth_beats_fireplace():
    owners = [None] * 10
    owners[1] = 0  # Fireplace (idx 1)
    owners[3] = 0  # Cooking Hearth (idx 3)
    state = _make_state_with_owners(tuple(owners))
    assert cooking_rates(state, 0) == (2, 3, 4)


# ---------------------------------------------------------------------------
# New pareto_frontier tests (with rates)
# ---------------------------------------------------------------------------

def test_pareto_food_no_improvement():
    # rates (0,0,0) → food always 0 regardless of what's discarded
    player = _player_with_1x1_pasture()
    gained = Animals(sheep=4)
    frontier = pareto_frontier(player, gained, rates=(0, 0, 0))
    assert all(food == 0 for _, food in frontier)


def test_pareto_food_with_fireplace():
    # 2×1 pasture (cap 4), gained 4 sheep, current 0 → can keep all 4
    # rates (2,2,3): keeping all 4 sheep → food = 0
    player = _player_with_two_pastures()  # has cap-4 and cap-2 pastures + house
    gained = Animals(sheep=4)
    frontier = pareto_frontier(player, gained, rates=(2, 2, 3))
    frontier_dict = {(a.sheep, a.boar, a.cattle): food for a, food in frontier}
    assert (4, 0, 0) in frontier_dict
    assert frontier_dict[(4, 0, 0)] == 0  # kept all 4, nothing cooked


def test_pareto_food_partial_keep():
    # 1×1 pasture (cap 2) only, gained 4 sheep, current 0
    # max keepable sheep = 2 (pasture cap 2, house holds 1 more → actually 3)
    # Use fresh player (house only, cap 1) to force max=1... use 1x1 pasture (cap 2)
    # With 1×1 pasture + house: can keep up to 3 sheep (2 in pasture, 1 in house)
    # To get exactly cap=2: use 1×1 pasture, no flexible beyond house.
    # Actually 1×1 pasture gives cap=2 + 1 house = 3 total. Use no-stables fresh player (house only):
    # num_flexible=1, no pastures → max=1 sheep.
    player = _fresh_player_no_stables()
    gained = Animals(sheep=4)
    frontier = pareto_frontier(player, gained, rates=(2, 2, 3))
    frontier_dict = {(a.sheep, a.boar, a.cattle): food for a, food in frontier}
    # Can keep at most 1 sheep (house pet slot only); 3 sheep cooked at rate 2
    assert (1, 0, 0) in frontier_dict
    assert frontier_dict[(1, 0, 0)] == 6  # (4-1)*2 = 6


def test_pareto_food_existing_animals_eaten():
    # Player has 2 boar (in 1×1 pasture cap 2). Gains 2 sheep.
    # House slot is the only flexible slot. With rates (2,2,3):
    # To keep (2 sheep, 2 boar): needs cap for both types. 1×1 pasture holds 1 type.
    # Best: sheep in pasture (2), boar in house (1) → (2,1,0), food=(2-1)*2=2 from boar
    # or: boar in pasture (2), sheep in house (1) → (1,2,0), food=(2-1)*2=2 from sheep
    player = _player_with_1x1_pasture(animals=Animals(boar=2))
    gained = Animals(sheep=2)
    frontier = pareto_frontier(player, gained, rates=(2, 2, 3))
    frontier_dict = {(a.sheep, a.boar, a.cattle): food for a, food in frontier}
    # (2,1,0): kept 2 sheep + 1 boar, cooked 1 boar → food = 1*2 = 2
    assert (2, 1, 0) in frontier_dict
    assert frontier_dict[(2, 1, 0)] == 2
    # (1,2,0): kept 1 sheep + 2 boar, cooked 1 sheep → food = 1*2 = 2
    assert (1, 2, 0) in frontier_dict
    assert frontier_dict[(1, 2, 0)] == 2


# ---------------------------------------------------------------------------
# breeding_frontier tests
# ---------------------------------------------------------------------------

def test_breeding_no_animals():
    player = _fresh_player_no_stables()
    frontier = breeding_frontier(player)
    assert len(frontier) == 1
    animals, food = frontier[0]
    assert animals == Animals()
    assert food == 0


def test_breeding_one_of_each():
    # 1 sheep, 1 boar, 1 cattle → no type has ≥ 2, so no breeding
    player = _fresh_player_no_stables(animals=Animals(sheep=1, boar=1, cattle=1))
    frontier = breeding_frontier(player)
    # Only the house slot (1 flexible) → can only keep 1 animal total
    # So frontier has single-animal configs; current state (1,1,1) doesn't fit
    frontier_set = {(a.sheep, a.boar, a.cattle) for a, _ in frontier}
    # No breeding occurred, food=0 for all
    assert all(food == 0 for _, food in frontier)
    # None can have total > 1
    assert not any(a.sheep + a.boar + a.cattle > 1 for a, _ in frontier)


def test_breeding_sheep_only_breeds():
    # s=2, house only (1 flexible). s_desired=3, max fit=1.
    # Feasible: sF in {0,1}. (1,0,0) dominates (0,0,0).
    # sF=1 < 3 → food_s = (s-sF)*sR = (2-1)*0 = 0.
    # Frontier is exactly {(1,0,0): 0}.
    player = _fresh_player_no_stables(animals=Animals(sheep=2))
    frontier = breeding_frontier(player)
    frontier_dict = {(a.sheep, a.boar, a.cattle): food for a, food in frontier}
    assert frontier_dict == {(1, 0, 0): 0}


def test_breeding_sheep_breeds_with_room():
    # s=2, two-pasture farm (cap 4 + cap 2 + house). s_desired=3, all of 0..3 fit.
    # (3,0,0) dominates everything. sF=3>=3 and s=2>=2 → food=(2+1-3)*0=0.
    # Frontier is exactly {(3,0,0): 0}.
    player = _player_with_two_pastures(animals=Animals(sheep=2))
    frontier = breeding_frontier(player)
    frontier_dict = {(a.sheep, a.boar, a.cattle): food for a, food in frontier}
    assert frontier_dict == {(3, 0, 0): 0}


def test_breeding_food_from_excess():
    # Farm: 2x1 pasture (cap 4) + house (1 flexible, no standalone stable).
    # Animals: sheep=4 (fits in pasture ✓), cattle=1 (fits in house ✓).
    # s=4, s_desired=5; c=1, c_desired=1 (no cattle breeding).
    # Frontier is exactly {(5,0,0), (4,0,1)} — neither dominates the other:
    #   (5,0,0): 5 sheep in pasture+house, no cattle. sF=5>=3, s=4>=2
    #            food_s = (4+1-5)*2 = 0; food_c = (1-0)*0 = 0 → total food=0
    #   (4,0,1): 4 sheep in pasture, 1 cattle in house. sF=4>=3, s=4>=2
    #            food_s = (4+1-4)*2 = 2; food_c = 0 → total food=2
    hf = _no_fences_h()
    vf = _no_fences_v()
    hf = _set_h(hf, 0, 0); hf = _set_h(hf, 0, 1)
    hf = _set_h(hf, 1, 0); hf = _set_h(hf, 1, 1)
    vf = _set_v(vf, 0, 0); vf = _set_v(vf, 0, 2)
    farmyard = _make_farmyard(hf=hf, vf=vf)
    player = PlayerState(
        resources=Resources(),
        animals=Animals(sheep=4, cattle=1),
        farmyard=farmyard,
        house_material=HouseMaterial.WOOD,
        people_total=2,
        people_home=2,
    )
    frontier = breeding_frontier(player, rates=(2, 0, 0))
    frontier_dict = {(a.sheep, a.boar, a.cattle): food for a, food in frontier}
    assert frontier_dict == {
        (5, 0, 0): 0,   # kept newborn sheep, cooked 1 cattle
        (4, 0, 1): 2,   # kept cattle, cooked 1 sheep pre-breed; newborn sheep kept
    }


def test_breeding_worked_example():
    # b=4, farm: 2x1 (cap 4) + 1x1 (cap 2) + house (1 flexible). rates (2,2,3).
    # b_desired=5. 5 boar fit: 4 in cap-4 pasture + 1 in house.
    # (0,5,0) is the unique maximum; all lower boar counts are dominated.
    # bF=5>=3 and b=4>=2 → food_b = (4+1-5)*2 = 0.
    # Frontier is exactly {(0,5,0): 0}.
    player = _player_with_two_pastures(animals=Animals(boar=4))
    frontier = breeding_frontier(player, rates=(2, 2, 3))
    frontier_dict = {(a.sheep, a.boar, a.cattle): food for a, food in frontier}
    assert frontier_dict == {(0, 5, 0): 0}


def test_breeding_formula_sF_ge_3():
    # s=3, 1x1 pasture (cap 2) + house (1 flexible) → max 3 sheep fit.
    # s_desired=4; sF=4 doesn't fit, so best achievable is sF=3.
    # (3,0,0) dominates all lower configs. sF=3>=3 and s=3>=2 → food=(3+1-3)*2=2.
    # Frontier is exactly {(3,0,0): 2}.
    player = _player_with_1x1_pasture(animals=Animals(sheep=3))
    frontier = breeding_frontier(player, rates=(2, 0, 0))
    frontier_dict = {(a.sheep, a.boar, a.cattle): food for a, food in frontier}
    assert frontier_dict == {(3, 0, 0): 2}


def test_breeding_formula_sF_lt_3():
    # s=3, house only (1 flexible, no pastures) → max sheep=1.
    # s_desired=4. (1,0,0) dominates (0,0,0). sF=1<3 → food=(3-1)*2=4.
    # Frontier is exactly {(1,0,0): 4}.
    player = _fresh_player_no_stables(animals=Animals(sheep=3))
    frontier = breeding_frontier(player, rates=(2, 0, 0))
    frontier_dict = {(a.sheep, a.boar, a.cattle): food for a, food in frontier}
    assert frontier_dict == {(1, 0, 0): 4}
