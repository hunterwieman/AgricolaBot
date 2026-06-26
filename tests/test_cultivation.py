"""Tests for the Cultivation action space.

Validates the Cultivation non-atomic resolution: PlaceWorker pushes
PendingCultivation, ChooseSubAction("plow") and ChooseSubAction("sow") are
both optional sub-actions, Stop is legal once at least one has been
chosen, and plowing-then-sowing on the new field works in a single action.
"""
from __future__ import annotations

from agricola.actions import (
    ChooseSubAction,
    CommitPlow,
    CommitSow,
    PlaceWorker,
    Stop,
)
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingCultivation
from agricola.setup import setup

from tests.factories import (
    with_current_player,
    with_grid,
    with_resources,
    with_space,
)
from tests.test_utils import run_actions


def _cult_setup(*, grain=0, veg=0, prefab_fields=()):
    """Construct a player-0 state suitable for Cultivation tests.

    Cultivation is a stage-5 card; expose it as revealed for testing.
    """
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, grain=grain, veg=veg)
    state = with_space(state, "cultivation", revealed=True)
    if prefab_fields:
        from agricola.state import Cell
        state = with_grid(state, 0, {(r, c): Cell(cell_type=CellType.FIELD) for (r, c) in prefab_fields})
    return state


def test_cultivation_plow_only():
    """Cultivation can be used to plow only (no sow)."""
    state = _cult_setup()
    state = run_actions(state, [
        PlaceWorker(space="cultivation"),
        ChooseSubAction(name="plow"),
        CommitPlow(row=0, col=2),
        Stop(),   # pop PendingPlow's after-phase
        Stop(),   # pop the parent
    ])
    assert state.pending_stack == ()
    assert state.players[0].farmyard.grid[0][2].cell_type == CellType.FIELD


def test_cultivation_sow_only():
    """Cultivation can be used to sow only (player has existing field + grain)."""
    state = _cult_setup(grain=1, prefab_fields=[(0, 2)])
    state = run_actions(state, [
        PlaceWorker(space="cultivation"),
        ChooseSubAction(name="sow"),
        CommitSow(grain=1, veg=0),
        Stop(),   # pop PendingSow's after-phase
        Stop(),   # pop the parent
    ])
    assert state.pending_stack == ()
    assert state.players[0].farmyard.grid[0][2].grain == 3
    assert state.players[0].resources.grain == 0


def test_cultivation_plow_then_sow_on_new_field():
    """Plow first creates a new field that can then be sown in the same action."""
    state = _cult_setup(grain=1)
    state = run_actions(state, [
        PlaceWorker(space="cultivation"),
        ChooseSubAction(name="plow"),
        CommitPlow(row=0, col=2),
        Stop(),   # pop PendingPlow's after-phase
        ChooseSubAction(name="sow"),
        CommitSow(grain=1, veg=0),
        Stop(),   # pop PendingSow's after-phase
        Stop(),   # pop the parent
    ])
    assert state.players[0].farmyard.grid[0][2].cell_type == CellType.FIELD
    assert state.players[0].farmyard.grid[0][2].grain == 3


def test_cultivation_sow_then_plow():
    """Sow first then plow — works (different order from RULES note but valid)."""
    state = _cult_setup(grain=1, prefab_fields=[(0, 2)])
    state = run_actions(state, [
        PlaceWorker(space="cultivation"),
        ChooseSubAction(name="sow"),
        CommitSow(grain=1, veg=0),
        Stop(),   # pop PendingSow's after-phase
        ChooseSubAction(name="plow"),
        CommitPlow(row=0, col=3),
        Stop(),   # pop PendingPlow's after-phase
        Stop(),   # pop the parent
    ])
    assert state.players[0].farmyard.grid[0][2].grain == 3
    assert state.players[0].farmyard.grid[0][3].cell_type == CellType.FIELD


def test_cultivation_stop_illegal_before_any_subaction():
    """Stop is illegal until at least one of plow/sow has been chosen."""
    state = _cult_setup(grain=1)
    state = step(state, PlaceWorker(space="cultivation"))
    actions = legal_actions(state)
    assert Stop() not in actions


def test_cultivation_stop_legal_after_plow():
    """Stop is legal once plow has been chosen."""
    state = _cult_setup()
    state = run_actions(state, [
        PlaceWorker(space="cultivation"),
        ChooseSubAction(name="plow"),
        CommitPlow(row=0, col=2),
    ])
    actions = legal_actions(state)
    assert Stop() in actions


def test_cultivation_choose_flag_invariants():
    """ChooseSubAction sets the corresponding _chosen flag on the parent."""
    state = _cult_setup(grain=1)
    state = step(state, PlaceWorker(space="cultivation"))
    parent = state.pending_stack[-1]
    assert isinstance(parent, PendingCultivation)
    assert parent.plow_chosen is False
    assert parent.sow_chosen is False

    state = step(state, ChooseSubAction(name="plow"))
    parent = state.pending_stack[-2]
    assert parent.plow_chosen is True
    assert parent.sow_chosen is False
