"""Tests for atomic action-space resolution via step().

Migrated from resolve_atomic (removed in Task 5) to step. step does
additional auto-advance work (current_player alternation), so tests that
relied on current_player being preserved after resolution may need
adjustment.
"""
from __future__ import annotations

import dataclasses

import pytest

from agricola.actions import PlaceWorker
from agricola.constants import SPACE_IDS, CellType, HouseMaterial
from agricola.engine import step
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import ActionSpaceState, Cell, Farmyard, PlayerState, get_space, with_space


# ---------------------------------------------------------------------------
# Helpers (mirrors the pattern from test_legality_atomic.py)
# ---------------------------------------------------------------------------

def _set_space(state, space_id: str, **kwargs):
    """Return a new state with the given fields replaced on the named action space."""
    new_space = dataclasses.replace(get_space(state.board, space_id), **kwargs)
    new_board = with_space(state.board, space_id, new_space)
    return dataclasses.replace(state, board=new_board)


def _reveal_space(state, space_id: str, accumulated=None):
    """Return a new state with the named stage card revealed at the current round.

    accumulated: Resources for building-resource spaces, int for food/animal spaces,
    or None to leave accumulation at default.
    """
    if isinstance(accumulated, Resources):
        return _set_space(state, space_id, round_revealed=state.round_number, accumulated=accumulated)
    elif isinstance(accumulated, int):
        return _set_space(state, space_id, round_revealed=state.round_number, accumulated_amount=accumulated)
    else:
        return _set_space(state, space_id, round_revealed=state.round_number)


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
    """Return a new state with num_extra_rooms extra ROOM cells added."""
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
def ap(state):
    """Index of the active player."""
    return state.current_player


# ---------------------------------------------------------------------------
# Per-space happy-path tests
# ---------------------------------------------------------------------------

def test_day_laborer_resolution(state, ap):
    pre_food = state.players[ap].resources.food
    pre_resources = state.players[ap].resources

    new_state = step(state, PlaceWorker(space="day_laborer"))
    p = new_state.players[ap]

    # food up by 2
    assert p.resources.food == pre_food + 2
    # all other resources unchanged
    assert p.resources.wood == pre_resources.wood
    assert p.resources.clay == pre_resources.clay
    assert p.resources.reed == pre_resources.reed
    assert p.resources.stone == pre_resources.stone
    assert p.resources.grain == pre_resources.grain
    assert p.resources.veg == pre_resources.veg


def test_fishing_resolution(state, ap):
    accum = get_space(state.board, "fishing").accumulated_amount
    assert accum > 0  # precondition: setup pre-loads 1 food

    pre_food = state.players[ap].resources.food
    new_state = step(state, PlaceWorker(space="fishing"))
    p = new_state.players[ap]

    # food up by accumulated amount
    assert p.resources.food == pre_food + accum
    # accumulated_amount reset to 0
    assert get_space(new_state.board, "fishing").accumulated_amount == 0
    # no other resource changes
    assert p.resources.wood == state.players[ap].resources.wood
    assert p.resources.clay == state.players[ap].resources.clay
    assert p.resources.reed == state.players[ap].resources.reed
    assert p.resources.stone == state.players[ap].resources.stone
    assert p.resources.grain == state.players[ap].resources.grain
    assert p.resources.veg == state.players[ap].resources.veg


def test_forest_resolution(state, ap):
    accum = get_space(state.board, "forest").accumulated
    assert bool(accum)  # setup pre-loads Resources(wood=3)

    pre_wood = state.players[ap].resources.wood
    new_state = step(state, PlaceWorker(space="forest"))
    p = new_state.players[ap]

    assert p.resources.wood == pre_wood + accum.wood
    assert get_space(new_state.board, "forest").accumulated == Resources()
    # no other resource changes
    assert p.resources.clay == state.players[ap].resources.clay
    assert p.resources.reed == state.players[ap].resources.reed
    assert p.resources.stone == state.players[ap].resources.stone
    assert p.resources.food == state.players[ap].resources.food
    assert p.resources.grain == state.players[ap].resources.grain
    assert p.resources.veg == state.players[ap].resources.veg


def test_clay_pit_resolution(state, ap):
    accum = get_space(state.board, "clay_pit").accumulated
    assert bool(accum)

    pre_clay = state.players[ap].resources.clay
    new_state = step(state, PlaceWorker(space="clay_pit"))
    p = new_state.players[ap]

    assert p.resources.clay == pre_clay + accum.clay
    assert get_space(new_state.board, "clay_pit").accumulated == Resources()


def test_reed_bank_resolution(state, ap):
    accum = get_space(state.board, "reed_bank").accumulated
    assert bool(accum)

    pre_reed = state.players[ap].resources.reed
    new_state = step(state, PlaceWorker(space="reed_bank"))
    p = new_state.players[ap]

    assert p.resources.reed == pre_reed + accum.reed
    assert get_space(new_state.board, "reed_bank").accumulated == Resources()


def test_grain_seeds_resolution(state, ap):
    pre_grain = state.players[ap].resources.grain
    pre_resources = state.players[ap].resources

    new_state = step(state, PlaceWorker(space="grain_seeds"))
    p = new_state.players[ap]

    assert p.resources.grain == pre_grain + 1
    # no other resource changes
    assert p.resources.wood == pre_resources.wood
    assert p.resources.clay == pre_resources.clay
    assert p.resources.reed == pre_resources.reed
    assert p.resources.stone == pre_resources.stone
    assert p.resources.food == pre_resources.food
    assert p.resources.veg == pre_resources.veg


def test_meeting_place_resolution(state, ap):
    accum = get_space(state.board, "meeting_place").accumulated_amount
    pre_food = state.players[ap].resources.food

    new_state = step(state, PlaceWorker(space="meeting_place"))
    p = new_state.players[ap]

    # food up by accumulated amount
    assert p.resources.food == pre_food + accum
    # accumulated_amount reset to 0
    assert get_space(new_state.board, "meeting_place").accumulated_amount == 0
    # starting_player updated immediately to ap
    assert new_state.starting_player == ap


def test_western_quarry_resolution(state, ap):
    state2 = _reveal_space(state, "western_quarry", accumulated=Resources(stone=2))
    accum = get_space(state2.board, "western_quarry").accumulated

    pre_stone = state2.players[ap].resources.stone
    new_state = step(state2, PlaceWorker(space="western_quarry"))
    p = new_state.players[ap]

    assert p.resources.stone == pre_stone + accum.stone
    assert get_space(new_state.board, "western_quarry").accumulated == Resources()


def test_vegetable_seeds_resolution(state, ap):
    state2 = _reveal_space(state, "vegetable_seeds")
    pre_veg = state2.players[ap].resources.veg
    pre_resources = state2.players[ap].resources

    new_state = step(state2, PlaceWorker(space="vegetable_seeds"))
    p = new_state.players[ap]

    assert p.resources.veg == pre_veg + 1
    # no other resource changes
    assert p.resources.wood == pre_resources.wood
    assert p.resources.clay == pre_resources.clay
    assert p.resources.reed == pre_resources.reed
    assert p.resources.stone == pre_resources.stone
    assert p.resources.food == pre_resources.food
    assert p.resources.grain == pre_resources.grain


def test_eastern_quarry_resolution(state, ap):
    state2 = _reveal_space(state, "eastern_quarry", accumulated=Resources(stone=3))
    accum = get_space(state2.board, "eastern_quarry").accumulated

    pre_stone = state2.players[ap].resources.stone
    new_state = step(state2, PlaceWorker(space="eastern_quarry"))
    p = new_state.players[ap]

    assert p.resources.stone == pre_stone + accum.stone
    assert get_space(new_state.board, "eastern_quarry").accumulated == Resources()


def test_basic_wish_resolution(state, ap):
    # Add a spare room so the space is legal (people_total < num_rooms).
    state2 = _add_rooms(state, ap, num_extra_rooms=1)
    state2 = _reveal_space(state2, "basic_wish_for_children")

    pre_people_total = state2.players[ap].people_total
    pre_people_home = state2.players[ap].people_home

    new_state = step(state2, PlaceWorker(space="basic_wish_for_children"))
    p = new_state.players[ap]

    # people_total up by 1 (newborn)
    assert p.people_total == pre_people_total + 1
    # newborns incremented
    assert p.newborns == 1
    # parent placed (people_home decremented by 1), newborn NOT added to people_home
    assert p.people_home == pre_people_home - 1
    # workers[ap] == 2 (parent + newborn on space)
    assert get_space(new_state.board, "basic_wish_for_children").workers[ap] == 2


def test_urgent_wish_resolution(state, ap):
    state2 = _reveal_space(state, "urgent_wish_for_children")

    pre_people_total = state2.players[ap].people_total
    pre_people_home = state2.players[ap].people_home

    new_state = step(state2, PlaceWorker(space="urgent_wish_for_children"))
    p = new_state.players[ap]

    # Same assertions as basic wish
    assert p.people_total == pre_people_total + 1
    assert p.newborns == 1
    assert p.people_home == pre_people_home - 1
    assert get_space(new_state.board, "urgent_wish_for_children").workers[ap] == 2


# ---------------------------------------------------------------------------
# Cross-cutting invariants (using Day Laborer as representative)
# ---------------------------------------------------------------------------

def test_resolution_marks_space_occupied(state, ap):
    new_state = step(state, PlaceWorker(space="day_laborer"))
    assert get_space(new_state.board, "day_laborer").workers[ap] == 1


def test_resolution_decrements_people_home(state, ap):
    pre_home = state.players[ap].people_home
    new_state = step(state, PlaceWorker(space="day_laborer"))
    assert new_state.players[ap].people_home == pre_home - 1


def test_step_advances_current_player_after_atomic(state, ap):
    """After an atomic placement, step rotates current_player.

    This is the inverse of the old (pre-Task-5) behavior of `resolve_atomic`,
    which left current_player unchanged. The work-phase alternation now
    happens inside step, immediately after the action is applied.
    """
    new_state = step(state, PlaceWorker(space="day_laborer"))
    assert new_state.current_player == 1 - ap


def test_step_atomic_leaves_empty_stack(state):
    """Atomic placements never push a pending frame."""
    new_state = step(state, PlaceWorker(space="day_laborer"))
    assert new_state.pending_stack == ()


def test_resolution_doesnt_advance_phase_when_workers_remain(state):
    """As long as some player has workers, phase stays in WORK."""
    pre_phase = state.phase
    new_state = step(state, PlaceWorker(space="day_laborer"))
    assert new_state.phase == pre_phase


def test_resolution_other_player_unchanged(state, ap):
    other = 1 - ap
    pre_other = state.players[other]
    new_state = step(state, PlaceWorker(space="day_laborer"))
    assert new_state.players[other] == pre_other


def test_resolution_other_spaces_unchanged(state):
    ap = state.current_player
    new_state = step(state, PlaceWorker(space="day_laborer"))
    for space_id, old_space in zip(SPACE_IDS, state.board.action_spaces):
        if space_id == "day_laborer":
            continue
        new_space = get_space(new_state.board, space_id)
        assert new_space.workers == old_space.workers, (
            f"{space_id}: workers changed from {old_space.workers} to {new_space.workers}"
        )
        assert new_space.accumulated == old_space.accumulated, (
            f"{space_id}: accumulated changed"
        )
        assert new_space.accumulated_amount == old_space.accumulated_amount, (
            f"{space_id}: accumulated_amount changed"
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_meeting_place_zero_accumulation(state, ap):
    # Set meeting_place accumulated_amount to 0 before placement.
    state2 = _set_space(state, "meeting_place", accumulated_amount=0)
    pre_food = state2.players[ap].resources.food

    new_state = step(state2, PlaceWorker(space="meeting_place"))
    p = new_state.players[ap]

    # Food unchanged (0 accumulated)
    assert p.resources.food == pre_food
    # starting_player still updated even with zero food
    assert new_state.starting_player == ap


def test_accumulation_zero_after_take(state, ap):
    # Forest is always legal at setup (accumulated=Resources(wood=3)).
    new_state = step(state, PlaceWorker(space="forest"))
    assert get_space(new_state.board, "forest").accumulated == Resources()


def test_resolution_returns_new_state(state, ap):
    # Day Laborer changes resources, so the resources object must be a new object.
    new_state = step(state, PlaceWorker(space="day_laborer"))
    assert state.players[ap].resources is not new_state.players[ap].resources


# ---------------------------------------------------------------------------
# Wish-specific tests
# ---------------------------------------------------------------------------

def test_basic_wish_workers_are_two(state, ap):
    state2 = _add_rooms(state, ap, num_extra_rooms=1)
    state2 = _reveal_space(state2, "basic_wish_for_children")

    new_state = step(state2, PlaceWorker(space="basic_wish_for_children"))
    assert get_space(new_state.board, "basic_wish_for_children").workers[ap] == 2


def test_basic_wish_other_player_workers_zero(state, ap):
    other = 1 - ap
    state2 = _add_rooms(state, ap, num_extra_rooms=1)
    state2 = _reveal_space(state2, "basic_wish_for_children")

    new_state = step(state2, PlaceWorker(space="basic_wish_for_children"))
    assert get_space(new_state.board, "basic_wish_for_children").workers[other] == 0


def test_wish_increments_newborns(state, ap):
    state2 = _add_rooms(state, ap, num_extra_rooms=1)
    state2 = _reveal_space(state2, "basic_wish_for_children")

    new_state = step(state2, PlaceWorker(space="basic_wish_for_children"))
    # Exactly 1 newborn, not 0 or 2
    assert new_state.players[ap].newborns == 1
