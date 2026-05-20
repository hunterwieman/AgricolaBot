"""Tests for the Major Improvement action space.

Integration tests for the full purchase-then-bake chain.
Unit-level bake bread coverage lives in tests/test_bake_bread.py.
"""
from __future__ import annotations

from agricola.actions import (
    ChooseSubAction,
    CommitBake,
    CommitBuildMajor,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingBuildMajor,
    PendingClayOven,
    PendingMajorMinorImprovement,
    PendingStoneOven,
)
from agricola.resources import Resources
from agricola.setup import setup

from tests.factories import (
    with_current_player,
    with_majors,
    with_minors,
    with_resources,
    with_space,
)
from tests.test_utils import run_actions


def _mi_setup(*, resources=None, owner_by_idx=None, minors=None):
    state = setup(seed=0)
    state = with_current_player(state, 0)
    if resources:
        state = with_resources(state, 0, **resources)
    if owner_by_idx:
        state = with_majors(state, owner_by_idx=owner_by_idx)
    if minors:
        state = with_minors(state, 0, frozenset(minors))
    state = with_space(state, "major_improvement", round_revealed=1)
    return state


def test_build_fireplace_idx0():
    """Build cheap Fireplace (idx 0, cost 2 clay)."""
    state = _mi_setup(resources={"clay": 2})
    state = run_actions(state, [
        PlaceWorker(space="major_improvement"),
        ChooseSubAction(name="build_major"),
        CommitBuildMajor(major_idx=0, return_fireplace_idx=None),
        Stop(),
    ])
    assert state.pending_stack == ()
    assert state.board.major_improvement_owners[0] == 0
    assert state.players[0].resources.clay == 0


def test_build_cooking_hearth_pay_clay():
    """Build cheap Cooking Hearth (idx 2) by paying 4 clay."""
    state = _mi_setup(resources={"clay": 4})
    state = run_actions(state, [
        PlaceWorker(space="major_improvement"),
        ChooseSubAction(name="build_major"),
        CommitBuildMajor(major_idx=2, return_fireplace_idx=None),
        Stop(),
    ])
    assert state.board.major_improvement_owners[2] == 0
    assert state.players[0].resources.clay == 0


def test_build_cooking_hearth_return_fireplace():
    """Build Cooking Hearth by returning a Fireplace (no clay spent)."""
    state = _mi_setup(owner_by_idx={0: 0})  # Player owns Fireplace at idx 0
    state = run_actions(state, [
        PlaceWorker(space="major_improvement"),
        ChooseSubAction(name="build_major"),
        CommitBuildMajor(major_idx=2, return_fireplace_idx=0),
        Stop(),
    ])
    # Cooking Hearth owned by player 0; Fireplace at idx 0 reverted to unowned.
    assert state.board.major_improvement_owners[2] == 0
    assert state.board.major_improvement_owners[0] is None


def test_cooking_hearth_both_payment_modes_offered():
    """When player has both Fireplaces, both return options appear in legal actions."""
    state = _mi_setup(resources={"clay": 4}, owner_by_idx={0: 0, 1: 0})
    state = run_actions(state, [
        PlaceWorker(space="major_improvement"),
        ChooseSubAction(name="build_major"),
    ])
    legal = legal_actions(state)
    # Cooking Hearth idx 2: clay pay + return fp 0 + return fp 1.
    options_for_hearth2 = [
        a for a in legal
        if isinstance(a, CommitBuildMajor) and a.major_idx == 2
    ]
    return_fp_options = {a.return_fireplace_idx for a in options_for_hearth2}
    assert None in return_fp_options       # pay clay
    assert 0 in return_fp_options          # return Fireplace 0
    assert 1 in return_fp_options          # return Fireplace 1


def test_cooking_hearth_standard_payment_gated_on_clay_not_on_fireplace():
    """Regression test for the negative-clay leak surfaced by random play.

    Player owns Fireplace (idx 0) but has 0 clay. Two legal actions should
    appear for Cooking Hearth (idx 2): the Fireplace-return option only.
    The standard-clay-payment option (`return_fireplace_idx=None`) must be
    EXCLUDED — paying the 4-clay cost from 0 clay would silently produce
    negative clay.

    Before the fix, `_can_afford_major(state, p, 2)` returned True via the
    `OR owns_fireplace` branch and the enumerator emitted both options.
    `CommitBuildMajor(major_idx=2, return_fireplace_idx=None)` then
    committed, driving clay to -4. The non-negative invariant in
    `engine.step` now catches this case at the assertion boundary; this
    test verifies the enumerator never emits the bad option in the first
    place.
    """
    state = _mi_setup(resources={"clay": 0}, owner_by_idx={0: 0})  # Fireplace, 0 clay
    state = run_actions(state, [
        PlaceWorker(space="major_improvement"),
        ChooseSubAction(name="build_major"),
    ])
    legal = legal_actions(state)
    options_for_hearth2 = [
        a for a in legal
        if isinstance(a, CommitBuildMajor) and a.major_idx == 2
    ]
    return_fp_options = {a.return_fireplace_idx for a in options_for_hearth2}
    assert None not in return_fp_options    # standard payment EXCLUDED
    assert 0 in return_fp_options           # Fireplace-return INCLUDED


def test_clay_oven_standard_payment_gated_on_full_cost():
    """Sibling regression: Clay Oven (idx 5) costs 3 clay + 1 stone. Owning
    a Fireplace is irrelevant — Clay Oven has no alternative-payment path.
    A player with 0 clay should see no Clay Oven option at all, regardless
    of Fireplace ownership.
    """
    state = _mi_setup(resources={"clay": 0, "stone": 1}, owner_by_idx={0: 0})
    state = run_actions(state, [
        PlaceWorker(space="major_improvement"),
        ChooseSubAction(name="build_major"),
    ])
    legal = legal_actions(state)
    options_for_clay_oven = [
        a for a in legal
        if isinstance(a, CommitBuildMajor) and a.major_idx == 5
    ]
    assert options_for_clay_oven == []


def test_build_well_writes_future_resources():
    """Building the Well writes +1 food into the next 5 round entries of future_resources."""
    state = _mi_setup(resources={"stone": 3, "wood": 1})
    pre_round = state.round_number
    state = run_actions(state, [
        PlaceWorker(space="major_improvement"),
        ChooseSubAction(name="build_major"),
        CommitBuildMajor(major_idx=4, return_fireplace_idx=None),
        Stop(),
    ])
    fr = state.players[0].future_resources
    # Indices [round_number .. min(round_number+5, 14)) have +1 food.
    for r in range(pre_round, min(pre_round + 5, 14)):
        assert fr[r].food == 1


def test_clay_oven_purchase_plus_free_bake():
    """Clay Oven purchase pushes PendingClayOven; bake consumes 1 grain -> 5 food."""
    state = _mi_setup(resources={"clay": 3, "stone": 1, "grain": 1})
    pre_food = state.players[0].resources.food
    state = run_actions(state, [
        PlaceWorker(space="major_improvement"),
        ChooseSubAction(name="build_major"),
        CommitBuildMajor(major_idx=5, return_fireplace_idx=None),
    ])
    # After commit: PendingClayOven on top of PendingBuildMajor.
    assert isinstance(state.pending_stack[-1], PendingClayOven)
    assert isinstance(state.pending_stack[-2], PendingBuildMajor)
    assert state.pending_stack[-2].build_chosen is True

    # Continue with the optional free bake.
    state = run_actions(state, [
        ChooseSubAction(name="bake_bread"),
        CommitBake(grain=1),
        Stop(),  # pop PendingClayOven
        Stop(),  # pop PendingBuildMajor
        Stop(),  # pop PendingMajorMinorImprovement
    ])
    assert state.pending_stack == ()
    assert state.players[0].resources.food == pre_food + 5  # Clay Oven: 5 food/grain
    assert state.players[0].resources.grain == 0
    assert state.board.major_improvement_owners[5] == 0


def test_clay_oven_purchase_skip_bake():
    """Clay Oven purchase + decline free bake: only Stop legal at PendingClayOven."""
    state = _mi_setup(resources={"clay": 3, "stone": 1})
    pre_food = state.players[0].resources.food
    state = run_actions(state, [
        PlaceWorker(space="major_improvement"),
        ChooseSubAction(name="build_major"),
        CommitBuildMajor(major_idx=5, return_fireplace_idx=None),
        Stop(),  # decline bake (pop PendingClayOven)
        Stop(),  # pop PendingBuildMajor
        Stop(),  # pop PendingMajorMinorImprovement
    ])
    assert state.pending_stack == ()
    assert state.players[0].resources.food == pre_food  # no bake, no food
    assert state.board.major_improvement_owners[5] == 0


def test_stone_oven_purchase_plus_free_bake_2_grain():
    """Stone Oven (cap 2 grain × 4 food/grain) bakes 2 grain for 8 food."""
    state = _mi_setup(resources={"clay": 1, "stone": 3, "grain": 2})
    pre_food = state.players[0].resources.food
    state = run_actions(state, [
        PlaceWorker(space="major_improvement"),
        ChooseSubAction(name="build_major"),
        CommitBuildMajor(major_idx=6, return_fireplace_idx=None),
    ])
    assert isinstance(state.pending_stack[-1], PendingStoneOven)
    state = run_actions(state, [
        ChooseSubAction(name="bake_bread"),
        CommitBake(grain=2),
        Stop(), Stop(), Stop(),
    ])
    assert state.players[0].resources.food == pre_food + 8
    assert state.players[0].resources.grain == 0


def test_clay_oven_with_potter_ceramics_0_grain():
    """Clay Oven purchase + Potter Ceramics: 0 grain + 1 clay -> Potter swaps -> bake."""
    state = _mi_setup(
        resources={"clay": 4, "stone": 1, "grain": 0},  # clay: 3 for purchase + 1 for Potter
        minors=["potter_ceramics"],
    )
    pre_food = state.players[0].resources.food
    state = run_actions(state, [
        PlaceWorker(space="major_improvement"),
        ChooseSubAction(name="build_major"),
        CommitBuildMajor(major_idx=5, return_fireplace_idx=None),
        ChooseSubAction(name="bake_bread"),
        FireTrigger(card_id="potter_ceramics"),  # swaps 1 clay -> 1 grain
        CommitBake(grain=1),
        Stop(), Stop(), Stop(),
    ])
    # Clay: started 4, paid 3 for purchase, swapped 1 via Potter -> 0.
    # Grain: gained 1 via Potter, baked 1 -> 0.
    # Food: +5 from Clay Oven.
    assert state.players[0].resources.clay == 0
    assert state.players[0].resources.grain == 0
    assert state.players[0].resources.food == pre_food + 5
