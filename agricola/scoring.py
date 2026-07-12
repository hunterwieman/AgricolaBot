from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from agricola.constants import CellType, HouseMaterial
from agricola.state import GameState, PlayerState

# Points awarded for each major improvement (index 0–9).
MAJOR_IMPROVEMENT_POINTS = [1, 1, 1, 1, 4, 2, 3, 2, 2, 2]


# ---------------------------------------------------------------------------
# Card scoring-term registry (CARD_IMPLEMENTATION_PLAN.md Category 1)
# ---------------------------------------------------------------------------
# Each entry is (card_id, fn) with fn(state, player_idx) -> int bonus points.
# Populated at import of `agricola.cards`; `score` sums the terms a player OWNS.
# Empty in the Family game (no cards), so the per-player card_points is 0 there
# and the family total — the value the C++ differential checks — is unchanged.
SCORING_TERMS: list[tuple[str, Callable]] = []


def register_scoring(card_id: str, fn: Callable) -> None:
    """Register a card's end-game scoring term (called at card-module import)."""
    SCORING_TERMS.append((card_id, fn))


# ---------------------------------------------------------------------------
# Mutually-exclusive scoring GROUPS
# ---------------------------------------------------------------------------
# Some cards carry a rule like "you can only use one card to get bonus points
# for your stone house": a player who owns several members of such a group may
# only benefit from ONE of them — the best-scoring — not the sum.
#
# Members are keyed by group_id. For each group a player owns >=1 member of,
# scoring adds `max(fn(state, idx) for each owned member)` exactly once. A group
# member is registered ONLY here (never also via register_scoring), so it is not
# double-counted through the plain SCORING_TERMS sum path.
#
# SCORING_GROUPS maps group_id -> list of (card_id, fn). Empty in the Family
# game (no cards), so grouped card_points is 0 there and the family total — the
# value the C++ differential checks — is unchanged.
SCORING_GROUPS: dict[str, list[tuple[str, Callable]]] = {}


def register_scoring_group(group_id: str, card_id: str, fn: Callable) -> None:
    """Register a card into a mutually-exclusive scoring group.

    Only the highest-scoring OWNED member of each group counts (the game rule
    "you can only use one card to get bonus points ..."). Members go here and
    NOT into SCORING_TERMS, so there is no double-count.
    """
    SCORING_GROUPS.setdefault(group_id, []).append((card_id, fn))


def _owns(ps: PlayerState, card_id: str) -> bool:
    return card_id in ps.occupations or card_id in ps.minor_improvements

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
    card_points:              int   # occupation/minor card scoring terms (0 in the Family game)
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

    # Card-fields (user ruling 45, 2026-07-12): "this card is a field" cards
    # count in the Fields category (1 per card, however many stacks — ruling
    # 47), and their planted crops join the grain/veg totals. Family players
    # own no card-fields, so both terms are 0 there and the C++ score gates
    # are untouched.
    from agricola.cards.card_fields import (   # local import: load-order safe
        card_field_count,
        planted_card_crops,
    )
    card_grain, card_veg = planted_card_crops(ps)

    # Fields (the scoring category counts every field the player has — grid
    # tiles plus card-fields, per ruling 45)
    num_fields = sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
    ) + card_field_count(ps)
    pts_fields = _score_field_tiles(num_fields)

    # Pastures
    pts_pastures = _score_pastures(len(pastures))

    # Grain: supply + all grain on field cells + grain planted on card-fields
    total_grain = ps.resources.grain + sum(
        grid[r][c].grain
        for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
    ) + card_grain
    pts_grain = _score_grain(total_grain)

    # Vegetables: supply + all veg on field cells + veg planted on card-fields
    total_veg = ps.resources.veg + sum(
        grid[r][c].veg
        for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
    ) + card_veg
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

    # Card scoring terms (occupations / minors the player owns). Empty in the
    # Family game → 0. See CARD_IMPLEMENTATION_PLAN.md Category 1.
    card_points = sum(
        fn(state, player_idx) for card_id, fn in SCORING_TERMS
        if _owns(ps, card_id)
    )
    # Mutually-exclusive scoring groups: for each group the player owns >=1
    # member of, count only the single best-scoring owned member (the "you can
    # only use one card ..." rule). Empty in the Family game → 0.
    for members in SCORING_GROUPS.values():
        owned = [fn(state, player_idx) for cid, fn in members if _owns(ps, cid)]
        if owned:
            card_points += max(owned)
    # Plus each kept minor improvement's printed victory points (the yellow
    # circle). Passing minors are never kept, so they never reach here; the
    # Family game has no minors, so this is 0 (C++ family-score gate undisturbed).
    if ps.minor_improvements:
        from agricola.cards.specs import MINORS  # local import: load-order safe
        card_points += sum(
            MINORS[cid].vps for cid in ps.minor_improvements if cid in MINORS
        )

    total = (
        pts_fields + pts_pastures + pts_grain + pts_veg
        + pts_sheep + pts_boar + pts_cattle
        + pts_unused + pts_fenced_stables
        + pts_clay_rooms + pts_stone_rooms
        + pts_people + pts_begging
        + pts_major + bonus + card_points
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
        card_points=card_points,
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
