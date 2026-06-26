"""Tests for the Farmland action space.

Validates the Farmland non-atomic resolution: PlaceWorker pushes
PendingSubActionSpace(space_id="farmland"), ChooseSubAction("plow") pushes
PendingPlow and flips subaction_complete on the parent, CommitPlow places a
FIELD cell, Stop pops the parent.
"""
from __future__ import annotations

from agricola.actions import (
    ChooseSubAction,
    CommitPlow,
    PlaceWorker,
    Stop,
)
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingSubActionSpace, PendingPlow
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import (
    with_current_player,
    with_grid,
    with_pending_stack,
)
from tests.test_utils import run_actions


def test_farmland_basic_walk():
    """PlaceWorker(farmland) -> ChooseSubAction(plow) -> CommitPlow -> Stop (after-phase) -> Stop (parent)."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = run_actions(state, [
        PlaceWorker(space="farmland"),
        ChooseSubAction(name="plow"),
        CommitPlow(row=0, col=2),
        Stop(),   # pop PendingPlow's after-phase
        Stop(),   # pop the parent
    ])
    # Stack empty after Stop.
    assert state.pending_stack == ()
    # Cell at (0, 2) is now a FIELD.
    assert state.players[0].farmyard.grid[0][2].cell_type == CellType.FIELD


def test_farmland_stop_illegal_before_plow_chosen():
    """Stop is not legal at PendingSubActionSpace until plow has been chosen."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = step(state, PlaceWorker(space="farmland"))
    actions = legal_actions(state)
    assert Stop() not in actions


def test_farmland_stop_legal_after_plow_chosen():
    """Once plow has been chosen (and committed), Stop is the only legal action."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = run_actions(state, [
        PlaceWorker(space="farmland"),
        ChooseSubAction(name="plow"),
        CommitPlow(row=0, col=2),
    ])
    actions = legal_actions(state)
    assert actions == [Stop()]


def test_farmland_choose_plow_marks_parent():
    """ChooseSubAction("plow") sets subaction_complete=True on the host AND pushes PendingPlow."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = step(state, PlaceWorker(space="farmland"))
    parent = state.pending_stack[-1]
    assert isinstance(parent, PendingSubActionSpace)
    assert parent.space_id == "farmland"
    assert parent.subaction_complete is False

    state = step(state, ChooseSubAction(name="plow"))
    assert len(state.pending_stack) == 2
    assert isinstance(state.pending_stack[-1], PendingPlow)
    new_parent = state.pending_stack[-2]
    assert isinstance(new_parent, PendingSubActionSpace)
    assert new_parent.space_id == "farmland"
    assert new_parent.subaction_complete is True


def test_farmland_commit_plow_flips_pending_plow_after_without_modifying_parent():
    """CommitPlow pivots PendingPlow to its after-phase (no auto-pop) and does NOT
    touch the parent's flag; the trailing Stop pops PendingPlow."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = run_actions(state, [
        PlaceWorker(space="farmland"),
        ChooseSubAction(name="plow"),
    ])
    # Parent has subaction_complete=True (set at choose time).
    pre_parent = state.pending_stack[-2]
    assert isinstance(pre_parent, PendingSubActionSpace)
    assert pre_parent.subaction_complete is True

    state = step(state, CommitPlow(row=0, col=2))
    # PendingPlow stays on top in its after-phase; parent untouched.
    assert len(state.pending_stack) == 2
    assert isinstance(state.pending_stack[-1], PendingPlow)
    assert state.pending_stack[-1].phase == "after"
    post_parent = state.pending_stack[-2]
    assert isinstance(post_parent, PendingSubActionSpace)
    # Same flag value — commit didn't modify it.
    assert post_parent.subaction_complete == pre_parent.subaction_complete

    # The trailing Stop pops PendingPlow; back at the parent.
    state = step(state, Stop())
    assert len(state.pending_stack) == 1
    assert isinstance(state.pending_stack[-1], PendingSubActionSpace)


def test_farmland_plow_cell_enumeration_excludes_non_empty():
    """CommitPlow options exclude non-empty cells."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = step(state, PlaceWorker(space="farmland"))
    state = step(state, ChooseSubAction(name="plow"))
    options = legal_actions(state)
    # Wood-house rooms are at (1, 0) and (2, 0); those should not be plow targets.
    for opt in options:
        assert (opt.row, opt.col) not in {(1, 0), (2, 0)}


def test_farmland_plow_adjacency_after_first_field():
    """After the first field, subsequent plows must be adjacent to existing fields."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    # Pre-plow a field at (0, 2).
    state = with_grid(state, 0, {(0, 2): Cell(cell_type=CellType.FIELD)})
    state = step(state, PlaceWorker(space="farmland"))
    state = step(state, ChooseSubAction(name="plow"))
    options = legal_actions(state)
    # (0, 1) and (0, 3) and (1, 2) are adjacent — legal.
    cells = {(opt.row, opt.col) for opt in options}
    assert (0, 1) in cells
    assert (0, 3) in cells
    assert (1, 2) in cells
    # (0, 4) is not adjacent to (0, 2) — illegal.
    assert (0, 4) not in cells


def test_farmland_placement_illegal_when_no_plow_target():
    """PlaceWorker(farmland) is illegal when the farmyard has no empty cells."""
    from agricola.constants import CellType
    state = setup(seed=0)
    state = with_current_player(state, 0)
    # Fill every non-room cell with a stable. Rooms remain at (1, 0) and (2, 0).
    overrides = {
        (r, c): Cell(cell_type=CellType.STABLE)
        for r in range(3) for c in range(5)
        if (r, c) not in {(1, 0), (2, 0)}
    }
    state = with_grid(state, 0, overrides)
    actions = legal_actions(state)
    assert PlaceWorker(space="farmland") not in actions
