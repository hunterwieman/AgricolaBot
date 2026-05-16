from __future__ import annotations

from dataclasses import dataclass

from agricola.constants import CellType, HouseMaterial
from agricola.state import GameState, PlayerState

# Points awarded for each major improvement (index 0–9).
MAJOR_IMPROVEMENT_POINTS = [1, 1, 1, 1, 4, 2, 3, 2, 2, 2]

# Craft building indices and their bonus thresholds.
# Each entry: (resource_attr, [(resource_cost, bonus_pts), ...]) highest to lowest
_CRAFT_BONUSES = {
    7: ("wood", [(7, 3), (5, 2), (3, 1)]),   # Joinery
    8: ("clay", [(7, 3), (5, 2), (3, 1)]),   # Pottery
    9: ("reed", [(5, 3), (4, 2), (2, 1)]),   # Basketmaker's
}


# ---------------------------------------------------------------------------
# Scoring tables (look-up helpers)
# ---------------------------------------------------------------------------

def _score_field_tiles(n: int) -> int:
    if n <= 1:  return -1
    if n == 2:  return 1
    if n == 3:  return 2
    if n == 4:  return 3
    return 4


def _score_pastures(n: int) -> int:
    if n == 0:  return -1
    return min(n, 4)


def _score_grain(n: int) -> int:
    if n == 0:  return -1
    if n <= 3:  return 1
    if n <= 5:  return 2
    if n <= 7:  return 3
    return 4


def _score_veg(n: int) -> int:
    if n == 0:  return -1
    return min(n, 4)


def _score_sheep(n: int) -> int:
    if n == 0:  return -1
    if n <= 3:  return 1
    if n <= 5:  return 2
    if n <= 7:  return 3
    return 4


def _score_boar(n: int) -> int:
    if n == 0:  return -1
    if n <= 2:  return 1
    if n <= 4:  return 2
    if n <= 6:  return 3
    return 4


def _score_cattle(n: int) -> int:
    if n == 0:  return -1
    if n == 1:  return 1
    if n <= 3:  return 2
    if n <= 5:  return 3
    return 4


# ---------------------------------------------------------------------------
# ScoreBreakdown dataclass
# ---------------------------------------------------------------------------

@dataclass
class ScoreBreakdown:
    field_tiles:              int
    pastures:                 int
    grain:                    int
    vegetables:               int
    sheep:                    int
    boar:                     int
    cattle:                   int
    unused_spaces:            int   # always ≤ 0
    fenced_stables:           int
    clay_rooms:               int
    stone_rooms:              int
    people:                   int
    begging_markers:          int   # always ≤ 0
    major_improvement_points: int
    bonus_points:             int   # craft building end-game bonuses
    total:                    int


# ---------------------------------------------------------------------------
# Craft bonus helper
# ---------------------------------------------------------------------------

def _craft_bonus_spending(state: GameState, player_idx: int) -> tuple[int, dict]:
    """Compute craft building bonus points and the resources consumed to earn them.

    Returns (bonus_points, spent) where spent is a dict with keys 'wood', 'clay',
    'reed' indicating how many of each resource are consumed.
    Players always take the maximum bonus they qualify for.
    Spent resources are consumed from personal supply and reduce the tiebreaker count.
    """
    res = state.players[player_idx].resources
    amounts = {"wood": res.wood, "clay": res.clay, "reed": res.reed}
    spent = {"wood": 0, "clay": 0, "reed": 0}
    bonus = 0
    for imp_idx, (attr, thresholds) in _CRAFT_BONUSES.items():
        if state.board.major_improvement_owners[imp_idx] == player_idx:
            for cost, pts in thresholds:  # highest threshold first
                if amounts[attr] >= cost:
                    bonus += pts
                    spent[attr] += cost
                    amounts[attr] -= cost  # consumed
                    break
    return bonus, spent


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def score(state: GameState, player_idx: int) -> tuple[int, ScoreBreakdown]:
    """Compute end-of-game score for player_idx.

    Returns (total_score, ScoreBreakdown).
    Resources spent on craft building bonuses are consumed and reduce the
    tiebreaker count. Use tiebreaker(state, player_idx) to get the tiebreaker value.
    """
    ps: PlayerState = state.players[player_idx]
    farmyard = ps.farmyard
    grid = farmyard.grid
    pastures = farmyard.pastures

    # Field tiles
    num_fields = sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
    )
    pts_fields = _score_field_tiles(num_fields)

    # Pastures
    pts_pastures = _score_pastures(len(pastures))

    # Grain: supply + all grain on field cells
    total_grain = ps.resources.grain + sum(
        grid[r][c].grain
        for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
    )
    pts_grain = _score_grain(total_grain)

    # Vegetables: supply + all veg on field cells
    total_veg = ps.resources.veg + sum(
        grid[r][c].veg
        for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
    )
    pts_veg = _score_veg(total_veg)

    # Animals
    pts_sheep  = _score_sheep(ps.animals.sheep)
    pts_boar   = _score_boar(ps.animals.boar)
    pts_cattle = _score_cattle(ps.animals.cattle)

    # Unused farmyard spaces
    enclosed_cells = {cell for p in pastures for cell in p.cells}
    unused = sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.EMPTY
        and (r, c) not in enclosed_cells
    )
    pts_unused = -unused

    # Fenced stables: stables inside any pasture
    fenced_stables = sum(
        1 for p in pastures
        for (r, c) in p.cells
        if grid[r][c].cell_type == CellType.STABLE
    )
    pts_fenced_stables = min(fenced_stables, 4)

    # Clay rooms and stone rooms — all rooms share one material (ps.house_material)
    num_rooms = sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.ROOM
    )
    clay_rooms  = num_rooms if ps.house_material == HouseMaterial.CLAY  else 0
    stone_rooms = num_rooms if ps.house_material == HouseMaterial.STONE else 0
    pts_clay_rooms  = clay_rooms * 1
    pts_stone_rooms = stone_rooms * 2

    # People
    pts_people = ps.people_total * 3

    # Begging markers
    pts_begging = ps.begging_markers * -3

    # Major improvement points
    pts_major = sum(
        MAJOR_IMPROVEMENT_POINTS[i]
        for i, owner in enumerate(state.board.major_improvement_owners)
        if owner == player_idx
    )

    # Craft building bonus points (award maximum the player qualifies for)
    bonus, _ = _craft_bonus_spending(state, player_idx)

    total = (
        pts_fields + pts_pastures + pts_grain + pts_veg
        + pts_sheep + pts_boar + pts_cattle
        + pts_unused + pts_fenced_stables
        + pts_clay_rooms + pts_stone_rooms
        + pts_people + pts_begging
        + pts_major + bonus
    )

    breakdown = ScoreBreakdown(
        field_tiles=pts_fields,
        pastures=pts_pastures,
        grain=pts_grain,
        vegetables=pts_veg,
        sheep=pts_sheep,
        boar=pts_boar,
        cattle=pts_cattle,
        unused_spaces=pts_unused,
        fenced_stables=pts_fenced_stables,
        clay_rooms=pts_clay_rooms,
        stone_rooms=pts_stone_rooms,
        people=pts_people,
        begging_markers=pts_begging,
        major_improvement_points=pts_major,
        bonus_points=bonus,
        total=total,
    )

    return total, breakdown


def tiebreaker(state: GameState, player_idx: int) -> int:
    """Return total building resources (wood + clay + reed + stone) in personal supply.

    Resources spent on craft building bonuses (Joinery, Pottery, Basketmaker's)
    are consumed and subtracted before computing this value.
    """
    res = state.players[player_idx].resources
    _, spent = _craft_bonus_spending(state, player_idx)
    return (
        (res.wood  - spent["wood"])
        + (res.clay  - spent["clay"])
        + (res.reed  - spent["reed"])
        + res.stone
    )
