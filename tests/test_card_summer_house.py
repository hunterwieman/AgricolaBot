"""Tests for Summer House (minor improvement, D #33) — a pure end-game scoring
minor.

"During scoring, if you live in a stone house, you get 2 bonus points for each
unused farmyard space orthogonally adjacent to your house." Play prereq: you live
in a WOOD house. The two house-material conditions are opposite (WOOD to play,
STONE to score). "Unused" = EMPTY and not inside a pasture; "adjacent to your
house" = orthogonally adjacent to a ROOM cell.
"""
import agricola.cards.summer_house  # noqa: F401  (registers the card)

import dataclasses

from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.summer_house import CARD_ID, _score
from agricola.constants import CellType, HouseMaterial
from agricola.pasture import Pasture
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import SCORING_TERMS
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_grid, with_house


def _blank_grid(state, idx):
    """Reset player idx's whole 3x5 grid to EMPTY (the starting grid has default
    rooms at (1,0)/(2,0) that would otherwise skew the adjacency counts; we place
    every ROOM explicitly per test)."""
    return with_grid(
        state, idx, {(r, c): Cell() for r in range(3) for c in range(5)}
    )


def _room(state, idx, cells):
    """Mark the given cells as ROOM cells in player idx's grid."""
    return with_grid(state, idx, {c: Cell(cell_type=CellType.ROOM) for c in cells})


def _field(state, idx, cells):
    return with_grid(state, idx, {c: Cell(cell_type=CellType.FIELD) for c in cells})


def _add_pasture(state, idx, cells):
    """Enclose `cells` in a single pasture (fences, no stables)."""
    p = state.players[idx]
    fy = p.farmyard
    pasture = Pasture(cells=frozenset(cells), num_stables=0, capacity=2 * len(cells))
    fy = fast_replace(fy, pastures=(pasture,))
    new_p = fast_replace(p, farmyard=fy)
    return dataclasses.replace(
        state, players=tuple(new_p if i == idx else state.players[i] for i in range(2))
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_minor_with_cost_and_prereq():
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(wood=3, stone=1)
    assert spec.prereq is not None
    assert spec.vps == 0
    assert spec.passing_left is False


def test_registered_as_scoring_term():
    assert any(card_id == CARD_ID for card_id, _ in SCORING_TERMS)


# ---------------------------------------------------------------------------
# Play prerequisite — "Still in Wooden House" (WOOD at play time)
# ---------------------------------------------------------------------------

def test_prereq_requires_wood_house():
    state = setup(seed=0)
    spec = MINORS[CARD_ID]

    wood = with_house(state, 0, HouseMaterial.WOOD)
    assert prereq_met(spec, wood, 0) is True

    clay = with_house(state, 0, HouseMaterial.CLAY)
    assert prereq_met(spec, clay, 0) is False

    stone = with_house(state, 0, HouseMaterial.STONE)
    assert prereq_met(spec, stone, 0) is False


# ---------------------------------------------------------------------------
# Scoring — gated on STONE house at game end
# ---------------------------------------------------------------------------

def test_no_bonus_unless_stone_house():
    """Even with a qualifying layout, a non-stone house scores 0."""
    state = setup(seed=0)
    state = _blank_grid(state, 0)
    # Room at (0,0); an unused EMPTY cell at (0,1) adjacent to it.
    state = _room(state, 0, [(0, 0)])

    wood = with_house(state, 0, HouseMaterial.WOOD)
    assert _score(wood, 0) == 0

    clay = with_house(state, 0, HouseMaterial.CLAY)
    assert _score(clay, 0) == 0


def test_bonus_two_points_per_adjacent_unused_cell():
    """Stone house: +2 per unused cell orthogonally adjacent to a room."""
    state = setup(seed=0)
    state = _blank_grid(state, 0)
    state = with_house(state, 0, HouseMaterial.STONE)
    # Room at (1,1). Its four orthogonal neighbours (0,1),(2,1),(1,0),(1,2) are
    # all EMPTY and unenclosed -> 4 qualifying cells -> 8 points.
    state = _room(state, 0, [(1, 1)])
    assert _score(state, 0) == 8


def test_only_orthogonal_adjacency_counts():
    """A diagonal-only EMPTY cell does NOT qualify."""
    state = setup(seed=0)
    state = _blank_grid(state, 0)
    state = with_house(state, 0, HouseMaterial.STONE)
    # Single room at (0,0). (1,1) is diagonal (not orthogonal) -> excluded.
    # (0,1) and (1,0) are orthogonal -> 2 qualifying -> 4 points.
    state = _room(state, 0, [(0, 0)])
    assert _score(state, 0) == 4


def test_non_empty_adjacent_cells_do_not_count():
    """An adjacent cell that is a FIELD (not EMPTY) is not 'unused'."""
    state = setup(seed=0)
    state = _blank_grid(state, 0)
    state = with_house(state, 0, HouseMaterial.STONE)
    state = _room(state, 0, [(0, 0)])
    # Make both orthogonal neighbours non-empty: (0,1) FIELD, (1,0) FIELD.
    state = _field(state, 0, [(0, 1), (1, 0)])
    assert _score(state, 0) == 0


def test_room_cells_themselves_never_count():
    """ROOM cells are not EMPTY, so they never qualify even if adjacent to rooms."""
    state = setup(seed=0)
    state = _blank_grid(state, 0)
    state = with_house(state, 0, HouseMaterial.STONE)
    # A 2x1 block of rooms.
    state = _room(state, 0, [(0, 0), (0, 1)])
    # Orthogonal EMPTY neighbours: (1,0) [under (0,0)], (1,1) [under (0,1)],
    # (0,2) [right of (0,1)] -> 3 qualifying -> 6 points. The ROOM cells
    # themselves are not EMPTY, so they never count.
    assert _score(state, 0) == 6


def test_fenced_but_empty_adjacent_cell_is_used_not_unused():
    """A fenced (pasture) cell reads EMPTY but is USED, so it does NOT qualify —
    matching the base-scoring 'unused' definition (EMPTY and not enclosed)."""
    state = setup(seed=0)
    state = _blank_grid(state, 0)
    state = with_house(state, 0, HouseMaterial.STONE)
    state = _room(state, 0, [(0, 0)])
    # Without fences, (0,1) and (1,0) are unused-adjacent -> 4 points.
    assert _score(state, 0) == 4
    # Now enclose (0,1) and (1,0) in a pasture: they become USED -> 0 points.
    fenced = _add_pasture(state, 0, [(0, 1), (1, 0)])
    assert _score(fenced, 0) == 0


def test_no_rooms_adjacent_means_no_bonus():
    """An unused cell with no orthogonally-adjacent room scores nothing."""
    state = setup(seed=0)
    state = _blank_grid(state, 0)
    state = with_house(state, 0, HouseMaterial.STONE)
    # Room far away at (0,0); the isolated empty cell at (2,4) has neighbours
    # (1,4),(2,3) which are empty, none a room -> no bonus from it.
    state = _room(state, 0, [(0, 0)])
    # Only the room's own orthogonal empties qualify: (0,1) and (1,0) -> 4 points.
    assert _score(state, 0) == 4


def test_scoring_is_per_player_scoped():
    """The bonus reads only the scored player's farmyard/house, not the opponent's."""
    state = setup(seed=0)
    # Player 0: blanked grid, stone house, room at (1,1) -> 4 adjacent empties.
    state = _blank_grid(state, 0)
    state = with_house(state, 0, HouseMaterial.STONE)
    state = _room(state, 0, [(1, 1)])
    # Player 1: WOOD house (so its own term would be 0) with its own layout —
    # scoring player 0 must read only player 0's farmyard/house.
    state = with_house(state, 1, HouseMaterial.WOOD)
    state = _room(state, 1, [(0, 0)])
    assert _score(state, 0) == 8
    # Player 1 lives in a wood house -> its own Summer House term is 0,
    # confirming the term is per-player scoped, not a shared read.
    assert _score(state, 1) == 0
