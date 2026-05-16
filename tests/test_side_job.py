"""Tests for the Side Job action space.

Validates the Side Job non-atomic resolution: build 1 stable for 1 wood
and/or Bake Bread. Tests cost-on-pending pattern (PendingBuildStable.cost
== Resources(wood=1)) and Potter Ceramics integration.
"""
from __future__ import annotations

from agricola.actions import (
    ChooseSubAction,
    CommitBake,
    CommitBuildStable,
    PlaceWorker,
    Stop,
)
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingBuildStable, PendingSideJob
from agricola.resources import Resources
from agricola.setup import setup

from tests.factories import (
    with_current_player,
    with_majors,
    with_minors,
    with_resources,
)
from tests.test_utils import run_actions


def _sj_setup(*, wood=0, grain=0, clay=0, with_fireplace=False, with_potter=False):
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, wood=wood, grain=grain, clay=clay)
    if with_fireplace:
        state = with_majors(state, owner_by_idx={0: 0})
    if with_potter:
        state = with_minors(state, 0, frozenset({"potter_ceramics"}))
    return state


def test_side_job_build_stable_only():
    """Build 1 stable for 1 wood, no bake."""
    state = _sj_setup(wood=1)
    state = run_actions(state, [
        PlaceWorker(space="side_job"),
        ChooseSubAction(name="build_stable"),
        CommitBuildStable(row=0, col=2),
        Stop(),
    ])
    assert state.pending_stack == ()
    assert state.players[0].farmyard.grid[0][2].cell_type == CellType.STABLE
    assert state.players[0].resources.wood == 0  # 1 wood spent


def test_side_job_bake_only():
    """Bake bread only, no stable."""
    state = _sj_setup(grain=1, with_fireplace=True)
    pre_food = state.players[0].resources.food
    state = run_actions(state, [
        PlaceWorker(space="side_job"),
        ChooseSubAction(name="bake_bread"),
        CommitBake(grain=1),
        Stop(),
    ])
    assert state.pending_stack == ()
    assert state.players[0].resources.food == pre_food + 2  # Fireplace: 2 food/grain
    assert state.players[0].resources.grain == 0


def test_side_job_both():
    """Build stable AND bake bread in one action."""
    state = _sj_setup(wood=1, grain=1, with_fireplace=True)
    pre_food = state.players[0].resources.food
    state = run_actions(state, [
        PlaceWorker(space="side_job"),
        ChooseSubAction(name="build_stable"),
        CommitBuildStable(row=0, col=2),
        ChooseSubAction(name="bake_bread"),
        CommitBake(grain=1),
        Stop(),
    ])
    assert state.pending_stack == ()
    assert state.players[0].farmyard.grid[0][2].cell_type == CellType.STABLE
    assert state.players[0].resources.wood == 0
    assert state.players[0].resources.food == pre_food + 2


def test_side_job_stable_costs_1_wood():
    """Building a stable via Side Job costs exactly 1 wood (not 2)."""
    state = _sj_setup(wood=5)
    state = run_actions(state, [
        PlaceWorker(space="side_job"),
        ChooseSubAction(name="build_stable"),
        CommitBuildStable(row=0, col=2),
    ])
    assert state.players[0].resources.wood == 4  # 5 - 1 = 4


def test_side_job_pending_build_stable_cost_field():
    """PendingBuildStable.cost is set to Resources(wood=1) when pushed by Side Job."""
    state = _sj_setup(wood=1)
    state = run_actions(state, [
        PlaceWorker(space="side_job"),
        ChooseSubAction(name="build_stable"),
    ])
    pending = state.pending_stack[-1]
    assert isinstance(pending, PendingBuildStable)
    assert pending.cost == Resources(wood=1)


def test_side_job_potter_ceramics_integration():
    """Side Job's bake integrates with Potter Ceramics trigger."""
    state = _sj_setup(clay=1, grain=0, with_fireplace=True, with_potter=True)
    pre_food = state.players[0].resources.food
    from agricola.actions import FireTrigger
    state = run_actions(state, [
        PlaceWorker(space="side_job"),
        ChooseSubAction(name="bake_bread"),
        FireTrigger(card_id="potter_ceramics"),
        CommitBake(grain=1),
        Stop(),
    ])
    # Potter swaps 1 clay -> 1 grain; Fireplace bakes 1 grain -> 2 food.
    assert state.players[0].resources.clay == 0
    assert state.players[0].resources.grain == 0
    assert state.players[0].resources.food == pre_food + 2


def test_side_job_stop_illegal_before_any_subaction():
    """Stop is illegal at PendingSideJob until at least one sub-action is chosen."""
    state = _sj_setup(wood=1, grain=1, with_fireplace=True)
    state = step(state, PlaceWorker(space="side_job"))
    actions = legal_actions(state)
    assert Stop() not in actions


def test_side_job_placement_illegal_when_neither_possible():
    """PlaceWorker(side_job) illegal when player can't build stable AND can't bake."""
    # No wood, no grain, no baker.
    state = _sj_setup(wood=0, grain=0)
    actions = legal_actions(state)
    assert PlaceWorker(space="side_job") not in actions
