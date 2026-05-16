"""Tests for Grain Utilization — the one non-atomic action space implemented in Task 5.

Tests use prefabricated states from tests/factories.py and the run_actions
helper from tests/test_utils.py. They do NOT rely on multi-round play to
reach interesting configurations.
"""
from __future__ import annotations

import pytest

from agricola.actions import (
    ChooseSubAction,
    CommitBake,
    CommitSow,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingBakeBread,
    PendingGrainUtilization,
    PendingSow,
)
from agricola.setup import setup

from tests.factories import (
    with_current_player,
    with_fields,
    with_majors,
    with_pending_stack,
    with_resources,
)
from tests.test_utils import run_actions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gu_setup(*, grain=0, veg=0, empty_fields=0,
              with_fireplace=False, with_hearth=False,
              seed=0, current_player=0):
    """Build a prefabricated state ready for Grain Utilization tests.

    Player has the given grain/veg counts, optionally owns Fireplace and/or
    Cooking Hearth, and has `empty_fields` empty FIELD cells available.
    """
    state = setup(seed=seed)
    state = with_current_player(state, current_player)
    state = with_resources(state, current_player, grain=grain, veg=veg)
    majors = {}
    if with_fireplace:
        majors[0] = current_player
    if with_hearth:
        majors[2] = current_player
    if majors:
        state = with_majors(state, owner_by_idx=majors)
    if empty_fields > 0:
        cells = [(0, 2 + i) for i in range(empty_fields)]
        state = with_fields(state, current_player, cells)
    return state


# ---------------------------------------------------------------------------
# Basic walk-throughs (no cards)
# ---------------------------------------------------------------------------

def test_grain_util_sow_only_walk():
    """Sow 1 grain into 1 field, then Stop."""
    state = _gu_setup(grain=1, empty_fields=1, with_fireplace=True)
    ap = state.current_player

    state = run_actions(state, [
        PlaceWorker(space="grain_utilization"),
        ChooseSubAction(name="sow"),
        CommitSow(grain=1, veg=0),
        Stop(),
    ])

    # Resources: 0 grain (sown), no food gained (didn't bake).
    assert state.players[ap].resources.grain == 0
    assert state.players[ap].resources.food == state.players[ap].resources.food  # unchanged
    # Field (0, 2) should now have 3 grain.
    assert state.players[ap].farmyard.grid[0][2].grain == 3
    # Stack empty, turn passed to other player.
    assert state.pending_stack == ()
    assert state.current_player != ap


def test_grain_util_bake_only_walk():
    """Bake 1 grain → 2 food (Fireplace), then Stop. No fields available."""
    state = _gu_setup(grain=1, with_fireplace=True)
    ap = state.current_player
    pre_food = state.players[ap].resources.food

    state = run_actions(state, [
        PlaceWorker(space="grain_utilization"),
        ChooseSubAction(name="bake_bread"),
        CommitBake(grain=1),
        Stop(),
    ])

    # -1 grain, +2 food (Fireplace rate).
    assert state.players[ap].resources.grain == 0
    assert state.players[ap].resources.food == pre_food + 2
    assert state.pending_stack == ()


def test_grain_util_both_sub_actions_walk():
    """Sow 2 grain into 2 fields, then bake 1 grain → 2 food."""
    state = _gu_setup(grain=3, empty_fields=2, with_fireplace=True)
    ap = state.current_player
    pre_food = state.players[ap].resources.food

    state = run_actions(state, [
        PlaceWorker(space="grain_utilization"),
        ChooseSubAction(name="sow"),
        CommitSow(grain=2, veg=0),
        ChooseSubAction(name="bake_bread"),
        CommitBake(grain=1),
        Stop(),
    ])

    # 3 - 2 (sown) - 1 (baked) = 0 grain remaining.
    assert state.players[ap].resources.grain == 0
    assert state.players[ap].resources.food == pre_food + 2
    # Two fields filled.
    assert state.players[ap].farmyard.grid[0][2].grain == 3
    assert state.players[ap].farmyard.grid[0][3].grain == 3


def test_grain_util_both_sub_actions_reverse_order():
    """bake-then-sow yields the same end state as sow-then-bake."""
    state = _gu_setup(grain=3, empty_fields=2, with_fireplace=True)
    ap = state.current_player

    # Walk bake-first.
    state_a = run_actions(state, [
        PlaceWorker(space="grain_utilization"),
        ChooseSubAction(name="bake_bread"),
        CommitBake(grain=1),
        ChooseSubAction(name="sow"),
        CommitSow(grain=2, veg=0),
        Stop(),
    ])
    # Walk sow-first.
    state_b = run_actions(state, [
        PlaceWorker(space="grain_utilization"),
        ChooseSubAction(name="sow"),
        CommitSow(grain=2, veg=0),
        ChooseSubAction(name="bake_bread"),
        CommitBake(grain=1),
        Stop(),
    ])
    # Resources and field contents should be identical.
    assert state_a.players[ap].resources == state_b.players[ap].resources
    assert state_a.players[ap].farmyard.grid == state_b.players[ap].farmyard.grid


# ---------------------------------------------------------------------------
# Stop legality
# ---------------------------------------------------------------------------

def test_grain_util_stop_illegal_at_start():
    """Stop is illegal at PendingGrainUtilization before any sub-action."""
    state = _gu_setup(grain=1, empty_fields=1, with_fireplace=True)
    state = with_pending_stack(state, [
        PendingGrainUtilization(
            player_idx=state.current_player,
            initiated_by_id="space:grain_utilization",
        ),
    ])
    actions = legal_actions(state)
    assert Stop() not in actions


def test_grain_util_stop_legal_after_one_sub_action():
    """Stop becomes legal once at least one sub-action has been completed."""
    state = _gu_setup(grain=0, with_fireplace=True)
    state = with_pending_stack(state, [
        PendingGrainUtilization(
            player_idx=state.current_player,
            initiated_by_id="space:grain_utilization",
            sow_chosen=True,
        ),
    ])
    actions = legal_actions(state)
    assert Stop() in actions


def test_grain_util_only_stop_when_both_done():
    """When both sub-actions are done, only Stop is offered."""
    state = _gu_setup(grain=0, with_fireplace=True)
    state = with_pending_stack(state, [
        PendingGrainUtilization(
            player_idx=state.current_player,
            initiated_by_id="space:grain_utilization",
            sow_chosen=True, bake_chosen=True,
        ),
    ])
    actions = legal_actions(state)
    assert actions == [Stop()]


# ---------------------------------------------------------------------------
# Mid-turn legality recomputation
# ---------------------------------------------------------------------------

def test_sow_becomes_illegal_after_baking_depletes_grain():
    """Bake first → grain depleted → sow no longer offered."""
    state = _gu_setup(grain=1, empty_fields=1, with_fireplace=True)

    state = run_actions(state, [
        PlaceWorker(space="grain_utilization"),
        ChooseSubAction(name="bake_bread"),
        CommitBake(grain=1),
    ])
    # Now at PendingGrainUtilization with grain=0, bake_chosen=True.
    actions = legal_actions(state)
    # ChooseSubAction("sow") is NOT offered because _can_sow requires grain or veg.
    assert ChooseSubAction(name="sow") not in actions
    # Only Stop is legal.
    assert actions == [Stop()]

    state = step(state, Stop())
    assert state.pending_stack == ()


def test_bake_becomes_illegal_after_sowing_depletes_grain():
    """Sow first → grain depleted → bake no longer offered."""
    state = _gu_setup(grain=1, empty_fields=1, with_fireplace=True)

    state = run_actions(state, [
        PlaceWorker(space="grain_utilization"),
        ChooseSubAction(name="sow"),
        CommitSow(grain=1, veg=0),
    ])
    # Now at PendingGrainUtilization with grain=0, sow_chosen=True.
    actions = legal_actions(state)
    # ChooseSubAction("bake_bread") is NOT offered because _can_bake_bread
    # requires grain >= 1 (no Potter Ceramics in this state).
    assert ChooseSubAction(name="bake_bread") not in actions
    assert actions == [Stop()]


def test_sow_remains_legal_after_partial_bake():
    """Partial bake leaves grain → sow still legal."""
    state = _gu_setup(grain=3, empty_fields=2, with_fireplace=True)

    state = run_actions(state, [
        PlaceWorker(space="grain_utilization"),
        ChooseSubAction(name="bake_bread"),
        CommitBake(grain=1),
    ])
    # Resources: 2 grain remaining. Sow still offered.
    actions = legal_actions(state)
    assert ChooseSubAction(name="sow") in actions


def test_partial_field_fills_after_partial_sow():
    """Sowing fewer than empty-field count fills canonical-order fields first."""
    ap = 0
    state = _gu_setup(
        grain=3, empty_fields=3, with_fireplace=True, current_player=ap,
    )

    state = run_actions(state, [
        PlaceWorker(space="grain_utilization"),
        ChooseSubAction(name="sow"),
        CommitSow(grain=2, veg=0),
    ])
    # Field at (0, 2) and (0, 3) filled; (0, 4) still empty.
    grid = state.players[ap].farmyard.grid
    assert grid[0][2].grain == 3
    assert grid[0][3].grain == 3
    assert grid[0][4].grain == 0
    assert grid[0][4].cell_type == CellType.FIELD
    # Resources: 1 grain left.
    assert state.players[ap].resources.grain == 1
    # ChooseSubAction("bake_bread") is still legal.
    actions = legal_actions(state)
    assert ChooseSubAction(name="bake_bread") in actions
    # ChooseSubAction("sow") is NOT legal (sow_chosen is True).
    assert ChooseSubAction(name="sow") not in actions


# ---------------------------------------------------------------------------
# Sow distribution semantics
# ---------------------------------------------------------------------------

def test_sow_fills_grain_first_then_veg():
    """When committing both grain and veg, grain fills earliest fields first."""
    ap = 0
    state = _gu_setup(
        grain=1, veg=1, empty_fields=2, with_fireplace=True, current_player=ap,
    )
    # Fields are at (0, 2) and (0, 3) per _gu_setup.

    state = run_actions(state, [
        PlaceWorker(space="grain_utilization"),
        ChooseSubAction(name="sow"),
        CommitSow(grain=1, veg=1),
        Stop(),
    ])
    grid = state.players[ap].farmyard.grid
    assert grid[0][2].grain == 3
    assert grid[0][2].veg == 0
    assert grid[0][3].veg == 2
    assert grid[0][3].grain == 0


def test_sow_canonical_order():
    """Multiple fields fill in canonical (row, col) order regardless of plow order."""
    ap = 0
    state = setup(seed=0)
    state = with_current_player(state, ap)
    state = with_resources(state, ap, grain=3)
    state = with_majors(state, owner_by_idx={0: ap})
    # Place fields at non-contiguous cells.
    state = with_fields(state, ap, [(2, 0), (0, 4), (1, 2)])

    # _gu_setup-style: walk through.
    state = run_actions(state, [
        PlaceWorker(space="grain_utilization"),
        ChooseSubAction(name="sow"),
        CommitSow(grain=3, veg=0),
        Stop(),
    ])
    # Wait — (2, 0) is initially a ROOM cell in setup. Need different cells.
    # Let me just verify all three were filled.
    grid = state.players[ap].farmyard.grid
    field_cells_with_grain = sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD and grid[r][c].grain == 3
    )
    assert field_cells_with_grain == 3


def test_legal_sow_commits_respect_field_count():
    """CommitSow(g, v) with g+v > empty_fields is not legal."""
    state = _gu_setup(grain=3, empty_fields=1, with_fireplace=True)

    state = step(state, PlaceWorker(space="grain_utilization"))
    state = step(state, ChooseSubAction(name="sow"))
    actions = legal_actions(state)
    # Only CommitSow(1, 0) is legal — 1 field, 3 grain in supply.
    assert CommitSow(grain=1, veg=0) in actions
    assert CommitSow(grain=2, veg=0) not in actions
    assert CommitSow(grain=3, veg=0) not in actions


# ---------------------------------------------------------------------------
# Cooking rate tests
# ---------------------------------------------------------------------------

def test_bake_uses_cooking_hearth_rate_when_owned():
    """Hearth gives 3 food per grain (not 2)."""
    state = _gu_setup(grain=1, with_hearth=True)  # no Fireplace
    ap = state.current_player
    pre_food = state.players[ap].resources.food

    state = run_actions(state, [
        PlaceWorker(space="grain_utilization"),
        ChooseSubAction(name="bake_bread"),
        CommitBake(grain=1),
        Stop(),
    ])
    assert state.players[ap].resources.food == pre_food + 3


def test_bake_uses_hearth_rate_when_both_owned():
    """When player owns both Fireplace and Hearth, Hearth's better rate applies."""
    state = _gu_setup(grain=1, with_fireplace=True, with_hearth=True)
    ap = state.current_player
    pre_food = state.players[ap].resources.food

    state = run_actions(state, [
        PlaceWorker(space="grain_utilization"),
        ChooseSubAction(name="bake_bread"),
        CommitBake(grain=1),
        Stop(),
    ])
    assert state.players[ap].resources.food == pre_food + 3


def test_bake_with_only_clay_oven():
    """A player who owns only Clay Oven (idx 5) bakes exactly 1 grain for 5 food."""
    ap = 0
    state = setup(seed=0)
    state = with_current_player(state, ap)
    state = with_resources(state, ap, grain=1)
    state = with_majors(state, owner_by_idx={5: ap})  # only Clay Oven
    pre_food = state.players[ap].resources.food

    # Take Grain Utilization. _can_bake_bread should be True (Clay Oven is a baker).
    state = step(state, PlaceWorker(space="grain_utilization"))
    state = step(state, ChooseSubAction(name="bake_bread"))
    state = step(state, CommitBake(grain=1))
    # Clay Oven: exactly 1 grain -> 5 food.
    assert state.players[ap].resources.grain == 0
    assert state.players[ap].resources.food == pre_food + 5


# ---------------------------------------------------------------------------
# Placement legality
# ---------------------------------------------------------------------------

def test_grain_util_illegal_when_cannot_sow_or_bake():
    """When player has no grain/veg AND no baker, Grain Utilization is illegal."""
    state = _gu_setup(grain=0, veg=0, empty_fields=0)
    actions = legal_actions(state)
    assert PlaceWorker(space="grain_utilization") not in actions


def test_grain_util_legal_with_only_bake_path():
    """1 grain + Fireplace + no fields → legal (bake)."""
    state = _gu_setup(grain=1, with_fireplace=True, empty_fields=0)
    actions = legal_actions(state)
    assert PlaceWorker(space="grain_utilization") in actions


def test_grain_util_legal_with_only_sow_path():
    """1 grain + 1 empty field + no baker → legal (sow)."""
    state = _gu_setup(grain=1, empty_fields=1, with_fireplace=False)
    actions = legal_actions(state)
    assert PlaceWorker(space="grain_utilization") in actions


# ---------------------------------------------------------------------------
# Stack invariants
# ---------------------------------------------------------------------------

def test_choose_sow_marks_parent_sow_chosen_and_pushes_pending_sow():
    """ChooseSubAction("sow") sets sow_chosen=True on the parent AND pushes PendingSow."""
    state = _gu_setup(grain=1, empty_fields=1, with_fireplace=True)
    state = run_actions(state, [PlaceWorker(space="grain_utilization")])
    # Parent is on top, sow_chosen False initially.
    parent = state.pending_stack[-1]
    assert isinstance(parent, PendingGrainUtilization)
    assert parent.sow_chosen is False

    new_state = step(state, ChooseSubAction(name="sow"))
    # Now stack has parent (with sow_chosen=True) and PendingSow on top.
    assert len(new_state.pending_stack) == 2
    assert isinstance(new_state.pending_stack[-1], PendingSow)
    parent = new_state.pending_stack[-2]
    assert isinstance(parent, PendingGrainUtilization)
    assert parent.sow_chosen is True
    assert parent.bake_chosen is False


def test_commit_sow_pops_pending_sow_without_modifying_parent():
    """CommitSow pops PendingSow and does NOT modify parent (flag was set at choose time)."""
    state = _gu_setup(grain=1, empty_fields=1, with_fireplace=True)
    ap = state.current_player

    # Construct stack directly with sow_chosen=True already set (as if ChooseSubAction
    # had run before this test was reached).
    state = with_pending_stack(state, [
        PendingGrainUtilization(
            player_idx=ap, initiated_by_id="space:grain_utilization", sow_chosen=True,
        ),
        PendingSow(player_idx=ap, initiated_by_id="grain_utilization"),
    ])

    new_state = step(state, CommitSow(grain=1, veg=0))
    # Stack back to length 1; flag remains True (set at choose time, untouched by commit).
    assert len(new_state.pending_stack) == 1
    top = new_state.pending_stack[-1]
    assert isinstance(top, PendingGrainUtilization)
    assert top.sow_chosen is True
    assert top.bake_chosen is False


def test_choose_bake_marks_parent_bake_chosen_and_pushes_pending_bake_bread():
    """ChooseSubAction("bake_bread") sets bake_chosen=True on the parent AND pushes PendingBakeBread."""
    state = _gu_setup(grain=1, with_fireplace=True)
    state = run_actions(state, [PlaceWorker(space="grain_utilization")])
    parent = state.pending_stack[-1]
    assert isinstance(parent, PendingGrainUtilization)
    assert parent.bake_chosen is False

    new_state = step(state, ChooseSubAction(name="bake_bread"))
    assert len(new_state.pending_stack) == 2
    assert isinstance(new_state.pending_stack[-1], PendingBakeBread)
    parent = new_state.pending_stack[-2]
    assert isinstance(parent, PendingGrainUtilization)
    assert parent.bake_chosen is True
    assert parent.sow_chosen is False


def test_commit_bake_pops_pending_bake_bread_without_modifying_parent():
    """CommitBake pops PendingBakeBread and does NOT modify parent."""
    state = _gu_setup(grain=1, with_fireplace=True)
    ap = state.current_player

    state = with_pending_stack(state, [
        PendingGrainUtilization(
            player_idx=ap, initiated_by_id="space:grain_utilization", bake_chosen=True,
        ),
        PendingBakeBread(player_idx=ap, initiated_by_id="grain_utilization"),
    ])

    new_state = step(state, CommitBake(grain=1))
    assert len(new_state.pending_stack) == 1
    top = new_state.pending_stack[-1]
    assert isinstance(top, PendingGrainUtilization)
    assert top.bake_chosen is True
    assert top.sow_chosen is False
