"""Tests for legal_placements — atomic action space legality.

The non-atomic-space tests live in test_legality_non_atomic.py. This file
covers only the 12 atomic spaces, but uses the unified `legal_placements`
function (which now handles both atomic and non-atomic spaces).
"""
from __future__ import annotations

import dataclasses

import pytest

from agricola.actions import PlaceWorker
from agricola.constants import CellType, HouseMaterial
from agricola.legality import legal_placements
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import ActionSpaceState, Cell, Farmyard, PlayerState, get_space, with_space


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spaces(result: list[PlaceWorker]) -> set[str]:
    return {pw.space for pw in result}


def _set_space(state, space_id: str, **kwargs):
    """Return a new state with the given fields replaced on the named action space."""
    new_space = dataclasses.replace(get_space(state.board, space_id), **kwargs)
    new_board = with_space(state.board, space_id, new_space)
    return dataclasses.replace(state, board=new_board)


def _reveal_space(state, space_id: str, accumulated=None):
    """Return a new state with the named stage card revealed at the current round.

    accumulated: Resources for building-resource spaces, int for food/animal spaces,
    or None to leave the accumulation field at its default (empty).
    """
    if isinstance(accumulated, Resources):
        return _set_space(state, space_id, revealed=True, accumulated=accumulated)
    elif isinstance(accumulated, int):
        return _set_space(state, space_id, revealed=True, accumulated_amount=accumulated)
    else:
        return _set_space(state, space_id, revealed=True)


def _reveal_space_no_goods(state, space_id: str):
    """Return a new state with the named stage card revealed but no accumulated goods."""
    return _set_space(state, space_id, revealed=True)


def _set_player(state, player_idx: int, **kwargs):
    """Return a new state with the given fields replaced on the named player."""
    old = state.players[player_idx]
    new_player = dataclasses.replace(old, **kwargs)
    new_players = (
        new_player if player_idx == 0 else state.players[0],
        new_player if player_idx == 1 else state.players[1],
    )
    return dataclasses.replace(state, players=new_players)


def _add_rooms(state, player_idx: int, num_extra_rooms: int):
    """Return a new state with num_extra_rooms extra ROOM cells added at columns 1..N.

    Adds rooms at (0, 1), (0, 2), etc. — adjacent to each other and valid for testing.
    Assumes the base farmyard has rooms only at (1,0) and (2,0).
    """
    player = state.players[player_idx]
    grid = [list(row) for row in player.farmyard.grid]
    room_cell = Cell(cell_type=CellType.ROOM)
    positions = [(0, c) for c in range(1, 1 + num_extra_rooms)]
    for r, c in positions:
        grid[r][c] = room_cell
    new_grid = tuple(tuple(row) for row in grid)
    new_farmyard = dataclasses.replace(player.farmyard, grid=new_grid)
    new_player = dataclasses.replace(player, farmyard=new_farmyard)
    new_players = (
        new_player if player_idx == 0 else state.players[0],
        new_player if player_idx == 1 else state.players[1],
    )
    return dataclasses.replace(state, players=new_players)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def state():
    return setup(seed=0)


@pytest.fixture
def active(state):
    """The index of the active player at setup."""
    return state.current_player


# ---------------------------------------------------------------------------
# Per-space: legal when conditions met
# ---------------------------------------------------------------------------

def test_day_laborer_legal_at_setup(state):
    # Day Laborer has no accumulation precondition; it is always available from round 1.
    assert PlaceWorker(space="day_laborer") in legal_placements(state)


def test_fishing_legal_with_accumulation(state):
    # At setup fishing already has accumulated_amount=1 (round-1 pre-load).
    assert get_space(state.board, "fishing").accumulated_amount == 1
    assert PlaceWorker(space="fishing") in legal_placements(state)


def test_forest_legal_with_accumulation(state):
    # At setup forest already has accumulated=Resources(wood=3).
    assert get_space(state.board, "forest").accumulated == Resources(wood=3)
    assert PlaceWorker(space="forest") in legal_placements(state)


def test_clay_pit_legal_with_accumulation(state):
    assert get_space(state.board, "clay_pit").accumulated == Resources(clay=1)
    assert PlaceWorker(space="clay_pit") in legal_placements(state)


def test_reed_bank_legal_with_accumulation(state):
    assert get_space(state.board, "reed_bank").accumulated == Resources(reed=1)
    assert PlaceWorker(space="reed_bank") in legal_placements(state)


def test_grain_seeds_legal_at_setup(state):
    assert PlaceWorker(space="grain_seeds") in legal_placements(state)


def test_meeting_place_legal_at_setup(state):
    assert PlaceWorker(space="meeting_place") in legal_placements(state)


def test_meeting_place_legal_with_zero_accumulation(state):
    # Zero food on Meeting Place must not block it — taking the SP token is itself an effect.
    state2 = _set_space(state, "meeting_place", accumulated_amount=0)
    assert PlaceWorker(space="meeting_place") in legal_placements(state2)


def test_western_quarry_legal_when_revealed_with_accumulation(state):
    state2 = _reveal_space(state, "western_quarry", accumulated=Resources(stone=1))
    assert PlaceWorker(space="western_quarry") in legal_placements(state2)


def test_vegetable_seeds_legal_when_revealed(state):
    state2 = _reveal_space_no_goods(state, "vegetable_seeds")
    assert PlaceWorker(space="vegetable_seeds") in legal_placements(state2)


def test_eastern_quarry_legal_when_revealed_with_accumulation(state):
    state2 = _reveal_space(state, "eastern_quarry", accumulated=Resources(stone=1))
    assert PlaceWorker(space="eastern_quarry") in legal_placements(state2)


def test_basic_wish_legal_when_revealed_with_room(state, active):
    # Basic Wish requires more rooms than people. Starting state: 2 people, 2 rooms.
    # Add 1 extra room so rooms (3) > people (2).
    state2 = _reveal_space_no_goods(state, "basic_wish_for_children")
    state2 = _add_rooms(state2, active, num_extra_rooms=1)
    assert PlaceWorker(space="basic_wish_for_children") in legal_placements(state2)


def test_urgent_wish_legal_when_revealed(state):
    # Urgent Wish only requires people_total < 5. Starting state has 2.
    state2 = _reveal_space_no_goods(state, "urgent_wish_for_children")
    assert PlaceWorker(space="urgent_wish_for_children") in legal_placements(state2)


# ---------------------------------------------------------------------------
# Per-space: illegal when conditions fail
# ---------------------------------------------------------------------------

def test_fishing_illegal_with_zero_accumulation(state):
    state2 = _set_space(state, "fishing", accumulated_amount=0)
    assert PlaceWorker(space="fishing") not in legal_placements(state2)


def test_forest_illegal_with_zero_accumulation(state):
    state2 = _set_space(state, "forest", accumulated=Resources())
    assert PlaceWorker(space="forest") not in legal_placements(state2)


def test_clay_pit_illegal_with_zero_accumulation(state):
    state2 = _set_space(state, "clay_pit", accumulated=Resources())
    assert PlaceWorker(space="clay_pit") not in legal_placements(state2)


def test_reed_bank_illegal_with_zero_accumulation(state):
    state2 = _set_space(state, "reed_bank", accumulated=Resources())
    assert PlaceWorker(space="reed_bank") not in legal_placements(state2)


def test_western_quarry_illegal_with_zero_accumulation(state):
    # Reveal the space but give it empty Resources — should be blocked.
    state2 = _reveal_space(state, "western_quarry", accumulated=Resources())
    assert PlaceWorker(space="western_quarry") not in legal_placements(state2)


def test_eastern_quarry_illegal_with_zero_accumulation(state):
    state2 = _reveal_space(state, "eastern_quarry", accumulated=Resources())
    assert PlaceWorker(space="eastern_quarry") not in legal_placements(state2)


def test_basic_wish_illegal_at_max_family(state, active):
    # people_total == 5 means the family is at maximum size.
    state2 = _reveal_space_no_goods(state, "basic_wish_for_children")
    state2 = _add_rooms(state2, active, num_extra_rooms=4)   # ensure plenty of rooms
    state2 = _set_player(state2, active, people_total=5, people_home=5)
    assert PlaceWorker(space="basic_wish_for_children") not in legal_placements(state2)


def test_basic_wish_illegal_without_room(state, active):
    # people_total == num_rooms means every room is occupied; no room for a newborn.
    # Starting state: 2 people, 2 rooms → blocked.
    state2 = _reveal_space_no_goods(state, "basic_wish_for_children")
    assert PlaceWorker(space="basic_wish_for_children") not in legal_placements(state2)


def test_urgent_wish_illegal_at_max_family(state, active):
    state2 = _reveal_space_no_goods(state, "urgent_wish_for_children")
    state2 = _set_player(state2, active, people_total=5, people_home=5)
    assert PlaceWorker(space="urgent_wish_for_children") not in legal_placements(state2)


# ---------------------------------------------------------------------------
# Cross-cutting
# ---------------------------------------------------------------------------

def test_occupied_space_illegal(state):
    # Mark Day Laborer as occupied by player 0; it must be absent from results.
    state2 = _set_space(state, "day_laborer", workers=(1, 0))
    assert PlaceWorker(space="day_laborer") not in legal_placements(state2)


def test_unrevealed_stage_space_illegal(state):
    # At round 1, western_quarry (a stage-2 card) is unrevealed. Even with goods it is illegal.
    assert not get_space(state.board, "western_quarry").revealed
    state2 = _set_space(state, "western_quarry", accumulated=Resources(stone=3))
    # `revealed` is unchanged (still False), so it remains unrevealed.
    assert PlaceWorker(space="western_quarry") not in legal_placements(state2)


def test_no_workers_returns_empty(state, active):
    state2 = _set_player(state, active, people_home=0)
    assert legal_placements(state2) == []


def test_setup_legal_set(state):
    # At fresh setup (round 1) the legal spaces are exactly:
    #   "day_laborer"  — no precondition
    #   "grain_seeds"  — no precondition
    #   "meeting_place"— no precondition (legal even at 0 food, and setup pre-loads 1 food anyway)
    #   "forest"       — accumulated=Resources(wood=3) (pre-loaded by setup)
    #   "clay_pit"     — accumulated=Resources(clay=1) (pre-loaded by setup)
    #   "reed_bank"    — accumulated=Resources(reed=1) (pre-loaded by setup)
    #   "fishing"      — accumulated_amount=1 (pre-loaded by setup, scalar)
    #   "farmland"     — non-atomic; first plow is always legal at fresh setup
    # Excluded: farm_expansion (no wood/reed) and side_job (no wood, no baking improvement).
    # All stage cards are unrevealed at round 1. Lessons is omitted from the dispatch entirely.
    # Fencing is deferred and excluded from legal_placements.
    expected = {
        "day_laborer",
        "grain_seeds",
        "meeting_place",
        "forest",
        "clay_pit",
        "reed_bank",
        "fishing",
        "farmland",
    }
    assert _spaces(legal_placements(state)) == expected


# ---------------------------------------------------------------------------
# Per-player: current_player determines legality
# ---------------------------------------------------------------------------

def test_current_player_determines_legality(state):
    # Set current_player to 1. Give player 1 exactly as many rooms as people
    # (blocking Basic Wish). Give player 0 a spare room (would allow Basic Wish).
    # Verify Basic Wish is absent — we check player 1's farm, not player 0's.
    state2 = dataclasses.replace(state, current_player=1)
    # Player 1: 2 people, 2 rooms — rooms not > people, blocked.
    # (Default starting state already has this configuration; no change needed for player 1.)
    # Player 0: add a spare room so it would be legal if we were checking player 0.
    state2 = _add_rooms(state2, 0, num_extra_rooms=1)
    state2 = _reveal_space_no_goods(state2, "basic_wish_for_children")
    # Also ensure player 1 has workers to place.
    state2 = _set_player(state2, 1, people_home=2)
    assert PlaceWorker(space="basic_wish_for_children") not in legal_placements(state2)
