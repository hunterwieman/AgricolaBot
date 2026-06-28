"""Tests for the House Redevelopment action space.

PlaceWorker pushes PendingHouseRedevelopment; renovate is mandatory first;
optional major-improvement step afterward; both Stop and improvement
choice are legal after renovate.
"""
from __future__ import annotations

from agricola.actions import (
    ChooseSubAction,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.constants import HouseMaterial
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingHouseRedevelopment,
    PendingMajorMinorImprovement,
    PendingRenovate,
)
from agricola.resources import Resources
from agricola.setup import setup

from tests.factories import (
    with_current_player,
    with_house,
    with_resources,
    with_space,
)
from tests.test_utils import build_major, run_actions, sole_renovate


def _hr_setup(*, material=HouseMaterial.WOOD, resources=None):
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_house(state, 0, material)
    if resources:
        state = with_resources(state, 0, **resources)
    state = with_space(state, "house_redevelopment", revealed=True)
    return state


def test_house_redev_renovate_only():
    """Renovate only (skip optional improvement)."""
    # 2 rooms -> cost 2 clay + 1 reed.
    state = _hr_setup(resources={"clay": 2, "reed": 1})
    state = run_actions(state, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        sole_renovate,
        Stop(),      # pop PendingRenovate's after-phase
        Proceed(),   # flip the parent to its after-phase
        Stop(),      # pop the parent
    ])
    assert state.pending_stack == ()
    assert state.players[0].house_material == HouseMaterial.CLAY
    assert state.players[0].resources.clay == 0
    assert state.players[0].resources.reed == 0


def test_house_redev_renovate_then_improvement():
    """Renovate first, then build a major improvement."""
    # 2 clay + 1 reed for renovate, 2 more clay for Fireplace.
    state = _hr_setup(resources={"clay": 4, "reed": 1})
    state = run_actions(state, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        sole_renovate,
        Stop(),  # pop PendingRenovate's after-phase
        ChooseSubAction(name="improvement"),
        ChooseSubAction(name="build_major"),
        build_major(0),
        Stop(),     # pop PendingBuildMajor's after-phase
        Stop(),     # pop PendingMajorMinorImprovement
        Proceed(),  # flip PendingHouseRedevelopment to its after-phase
        Stop(),     # pop PendingHouseRedevelopment
    ])
    assert state.pending_stack == ()
    assert state.players[0].house_material == HouseMaterial.CLAY
    assert state.board.major_improvement_owners[0] == 0


def test_house_redev_improvement_requires_renovate_first():
    """ChooseSubAction("improvement") is not legal until renovate is chosen."""
    state = _hr_setup(resources={"clay": 4, "reed": 1})
    state = step(state, PlaceWorker(space="house_redevelopment"))
    legal = legal_actions(state)
    assert ChooseSubAction(name="improvement") not in legal


def test_house_redev_stop_illegal_before_renovate():
    """Stop is illegal at PendingHouseRedevelopment before renovate is chosen."""
    state = _hr_setup(resources={"clay": 2, "reed": 1})
    state = step(state, PlaceWorker(space="house_redevelopment"))
    legal = legal_actions(state)
    assert Stop() not in legal


def test_house_redev_stop_legal_after_renovate_skip_improvement():
    """Stop is legal after renovate even if improvement is skipped."""
    state = _hr_setup(resources={"clay": 2, "reed": 1})
    state = run_actions(state, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        sole_renovate,
    ])
    legal = legal_actions(state)
    assert Stop() in legal


def test_house_redev_proceed_legal_after_both_steps():
    """Proceed is the only action after BOTH renovate and improvement complete —
    the parent's before-phase turn-ending boundary (Proceed flips to the
    after-phase, where Stop pops)."""
    state = _hr_setup(resources={"clay": 4, "reed": 1})
    state = run_actions(state, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        sole_renovate,
        Stop(),  # pop PendingRenovate's after-phase
        ChooseSubAction(name="improvement"),
        ChooseSubAction(name="build_major"),
        build_major(0),
        Stop(),  # pop PendingBuildMajor's after-phase
        Stop(),  # pop PendingMajorMinorImprovement -> back at PendingHouseRedevelopment
    ])
    # Now both renovate_chosen and improvement_chosen are True; Proceed is the
    # only legal action at the parent's before-phase.
    parent = state.pending_stack[-1]
    assert isinstance(parent, PendingHouseRedevelopment)
    assert parent.renovate_chosen is True
    assert parent.improvement_chosen is True
    legal = legal_actions(state)
    assert legal == [Proceed()]


def test_house_redev_stone_house_cannot_renovate():
    """A player with a stone house cannot renovate (action space is illegal)."""
    state = _hr_setup(material=HouseMaterial.STONE)
    actions = legal_actions(state)
    assert PlaceWorker(space="house_redevelopment") not in actions


def test_house_redev_renovation_cost_wood_to_clay():
    """Wood->Clay: num_rooms clay + 1 reed (not num_rooms reed)."""
    # 2-room wood house should cost exactly 2 clay + 1 reed.
    state = _hr_setup(resources={"clay": 2, "reed": 1})
    state = run_actions(state, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
    ])
    # The cost lives on the renovate frontier now (a singleton in the Family game),
    # surfaced as the sole legal CommitRenovate's payment.
    assert isinstance(state.pending_stack[-1], PendingRenovate)
    assert sole_renovate(state).payment == Resources(clay=2, reed=1)


def test_house_redev_renovation_cost_clay_to_stone():
    """Clay->Stone: num_rooms stone + 1 reed."""
    state = _hr_setup(material=HouseMaterial.CLAY, resources={"stone": 2, "reed": 1})
    state = run_actions(state, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
    ])
    assert isinstance(state.pending_stack[-1], PendingRenovate)
    assert sole_renovate(state).payment == Resources(stone=2, reed=1)


def test_house_redev_inner_improvement_provenance():
    """Inner PendingMajorMinorImprovement.initiated_by_id is "house_redevelopment"."""
    state = _hr_setup(resources={"clay": 4, "reed": 1})
    state = run_actions(state, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        sole_renovate,
        Stop(),   # pop PendingRenovate's after-phase
        ChooseSubAction(name="improvement"),
    ])
    inner = state.pending_stack[-1]
    assert isinstance(inner, PendingMajorMinorImprovement)
    assert inner.initiated_by_id == "house_redevelopment"
