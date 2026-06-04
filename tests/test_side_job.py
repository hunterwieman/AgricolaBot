"""Tests for the Side Job action space.

Validates the Side Job non-atomic resolution: build 1 stable for 1 wood
and/or Bake Bread. Tests cost-on-pending pattern (PendingBuildStables.cost
== Resources(wood=1), max_builds=1) and Potter Ceramics integration.

Post-Task-5D: stable build uses the multi-shot PendingBuildStables with
max_builds=1; trace shape is CommitBuildStable -> Stop -> Stop (one Stop
to pop PendingBuildStables, a second to pop PendingSideJob).
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
from agricola.pending import PendingBuildStables, PendingSideJob
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
    """Build 1 stable for 1 wood, no bake.

    Multi-shot trace: ChooseSubAction pushes PendingBuildStables(max_builds=1);
    CommitBuildStable leaves it on top (num_built=1); first Stop pops
    PendingBuildStables; second Stop pops PendingSideJob.
    """
    state = _sj_setup(wood=1)
    state = run_actions(state, [
        PlaceWorker(space="side_job"),
        ChooseSubAction(name="build_stables"),
        CommitBuildStable(row=0, col=2),
        Stop(),
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
    """Build stable AND bake bread in one action.

    Trace: build_stable (commit + Stop to exit the multi-shot frame),
    then bake_bread (commit auto-pops PendingBakeBread), then Stop to
    pop PendingSideJob.
    """
    state = _sj_setup(wood=1, grain=1, with_fireplace=True)
    pre_food = state.players[0].resources.food
    state = run_actions(state, [
        PlaceWorker(space="side_job"),
        ChooseSubAction(name="build_stables"),
        CommitBuildStable(row=0, col=2),
        Stop(),
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
        ChooseSubAction(name="build_stables"),
        CommitBuildStable(row=0, col=2),
    ])
    assert state.players[0].resources.wood == 4  # 5 - 1 = 4


def test_side_job_pending_build_stables_cost_field():
    """PendingBuildStables.cost is Resources(wood=1) and max_builds=1 when pushed by Side Job."""
    state = _sj_setup(wood=1)
    state = run_actions(state, [
        PlaceWorker(space="side_job"),
        ChooseSubAction(name="build_stables"),
    ])
    pending = state.pending_stack[-1]
    assert isinstance(pending, PendingBuildStables)
    assert pending.cost == Resources(wood=1)
    assert pending.max_builds == 1
    assert pending.num_built == 0


def test_side_job_stable_singleton_stop_after_commit():
    """After the single CommitBuildStable, Stop is the only legal action
    (max_builds=1 saturates the cap)."""
    state = _sj_setup(wood=5)  # ample resources, only cap should bind
    state = run_actions(state, [
        PlaceWorker(space="side_job"),
        ChooseSubAction(name="build_stables"),
        CommitBuildStable(row=0, col=2),
    ])
    # PendingBuildStables(num_built=1, max_builds=1) is on top; only Stop legal.
    actions = legal_actions(state)
    assert actions == [Stop()]


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
