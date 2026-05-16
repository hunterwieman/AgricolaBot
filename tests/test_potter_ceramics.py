"""Tests for Potter Ceramics — the one card implemented in Task 5.

All tests use prefabricated states from tests/factories.py. The card cannot
be acquired through Task 5 gameplay (no action space plays minor
improvements), so every test starts by directly setting
PlayerState.minor_improvements.
"""
from __future__ import annotations

import dataclasses

import pytest

from agricola.actions import (
    ChooseSubAction,
    CommitBake,
    CommitSow,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.engine import step
from agricola.legality import _can_bake_bread, legal_actions
from agricola.pending import PendingBakeBread, PendingGrainUtilization
from agricola.setup import setup

from tests.factories import (
    with_current_player,
    with_fields,
    with_majors,
    with_minors,
    with_pending_stack,
    with_resources,
)
from tests.test_utils import run_actions


CARD_ID = "potter_ceramics"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _potter_setup(*, grain=0, clay=1, veg=0,
                   with_fireplace=True, with_hearth=False,
                   empty_fields=0, with_card=True,
                   seed=0, current_player=0):
    """Build a prefabricated state where the active player optionally has
    Potter Ceramics played and the specified resources / improvements.
    """
    state = setup(seed=seed)
    state = with_current_player(state, current_player)
    state = with_resources(state, current_player, grain=grain, veg=veg, clay=clay)
    if with_card:
        state = with_minors(state, current_player, frozenset({CARD_ID}))
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
# _can_bake_bread predicate tests (the headline behavior change)
# ---------------------------------------------------------------------------

def test_can_bake_bread_potter_clay_no_grain():
    """The headline case: 0 grain + 1 clay + Potter + Fireplace → True via extension."""
    state = _potter_setup(grain=0, clay=1, with_fireplace=True)
    ap = state.current_player
    p = state.players[ap]
    assert _can_bake_bread(state, p) is True


def test_can_bake_bread_potter_no_clay():
    """0 clay + Potter + Fireplace → False (extension requires clay >= 1)."""
    state = _potter_setup(grain=0, clay=0, with_fireplace=True)
    p = state.players[state.current_player]
    assert _can_bake_bread(state, p) is False


def test_can_bake_bread_potter_no_baker():
    """No baking improvement → False even with Potter and clay."""
    state = _potter_setup(grain=0, clay=1, with_fireplace=False)
    p = state.players[state.current_player]
    assert _can_bake_bread(state, p) is False


def test_can_bake_bread_no_potter():
    """No Potter (and no grain) → False even with Fireplace and clay."""
    state = _potter_setup(grain=0, clay=1, with_fireplace=True, with_card=False)
    p = state.players[state.current_player]
    assert _can_bake_bread(state, p) is False


def test_can_bake_bread_potter_with_grain_already():
    """1 grain (no clay needed) + Fireplace + Potter → True via base check."""
    state = _potter_setup(grain=1, clay=0, with_fireplace=True)
    p = state.players[state.current_player]
    assert _can_bake_bread(state, p) is True


# ---------------------------------------------------------------------------
# Full Grain Utilization walk-through with the trigger
# ---------------------------------------------------------------------------

def test_grain_utilization_potter_zero_grain_full_walk():
    """0 grain, 1 clay, Potter, Fireplace, no fields. Fire trigger, then bake."""
    state = _potter_setup(
        grain=0, clay=1, with_fireplace=True, empty_fields=0,
    )
    ap = state.current_player
    pre_food = state.players[ap].resources.food

    # Step 1: PlaceWorker
    state = step(state, PlaceWorker(space="grain_utilization"))
    assert len(state.pending_stack) == 1
    assert isinstance(state.pending_stack[-1], PendingGrainUtilization)

    # Step 2: legal_actions should offer only ChooseSubAction("bake_bread")
    # (sow is impossible: no fields).
    actions = legal_actions(state)
    assert ChooseSubAction(name="bake_bread") in actions
    assert ChooseSubAction(name="sow") not in actions

    # Step 3: choose bake
    state = step(state, ChooseSubAction(name="bake_bread"))
    assert isinstance(state.pending_stack[-1], PendingBakeBread)
    assert state.pending_stack[-1].triggers_resolved == frozenset()

    # Step 4: legal_actions at PendingBakeBread.
    # 0 grain → no CommitBake; Potter eligible → FireTrigger present.
    actions = legal_actions(state)
    assert actions == [FireTrigger(card_id=CARD_ID)]

    # Step 5: fire Potter Ceramics.
    state = step(state, FireTrigger(card_id=CARD_ID))
    # Resources: -1 clay, +1 grain.
    assert state.players[ap].resources.clay == 0
    assert state.players[ap].resources.grain == 1
    # triggers_resolved updated.
    assert state.pending_stack[-1].triggers_resolved == frozenset({CARD_ID})

    # Step 6: now CommitBake(1) is the only commit, trigger already resolved.
    actions = legal_actions(state)
    assert actions == [CommitBake(grain=1)]

    # Step 7: commit the bake.
    state = step(state, CommitBake(grain=1))
    # Pop PendingBakeBread; bake_chosen=True on parent.
    assert len(state.pending_stack) == 1
    assert isinstance(state.pending_stack[-1], PendingGrainUtilization)
    assert state.pending_stack[-1].bake_chosen is True
    # Resources: -1 grain, +2 food (Fireplace).
    assert state.players[ap].resources.grain == 0
    assert state.players[ap].resources.food == pre_food + 2

    # Step 8: only Stop is legal.
    actions = legal_actions(state)
    assert actions == [Stop()]

    state = step(state, Stop())
    assert state.pending_stack == ()
    # current_player has alternated.
    assert state.current_player != ap


# ---------------------------------------------------------------------------
# Single-fire-per-action invariant
# ---------------------------------------------------------------------------

def test_potter_fires_at_most_once_per_action():
    """With 2 clay, Potter still only offered once per Bake Bread action."""
    state = _potter_setup(grain=0, clay=2, with_fireplace=True, empty_fields=0)

    state = run_actions(state, [
        PlaceWorker(space="grain_utilization"),
        ChooseSubAction(name="bake_bread"),
        FireTrigger(card_id=CARD_ID),
    ])
    # After firing once: clay=1, grain=1, triggers_resolved={potter}.
    # Even though clay >= 1 still holds, FireTrigger is no longer offered.
    actions = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) not in actions
    # Only CommitBake(1) is legal now.
    assert actions == [CommitBake(grain=1)]


# ---------------------------------------------------------------------------
# Re-eligibility on a new bake action
# ---------------------------------------------------------------------------

def test_potter_re_eligible_in_new_pending_bake_bread():
    """A fresh PendingBakeBread has empty triggers_resolved — Potter
    becomes eligible again.

    Demonstrates that triggers_resolved is scoped to the pending frame's
    lifetime, not persistent player state.
    """
    state = _potter_setup(grain=0, clay=2, with_fireplace=True, empty_fields=0)
    ap = state.current_player

    # Take one Grain Utilization, fire Potter, bake, stop.
    state = run_actions(state, [
        PlaceWorker(space="grain_utilization"),
        ChooseSubAction(name="bake_bread"),
        FireTrigger(card_id=CARD_ID),
        CommitBake(grain=1),
        Stop(),
    ])
    # Now player has 1 clay, 0 grain, +2 food, no active pending.
    assert state.players[ap].resources.clay == 1
    assert state.players[ap].resources.grain == 0
    assert state.pending_stack == ()

    # Construct a fresh PendingBakeBread directly (testing the trigger
    # re-eligibility property, not gameplay).
    state = with_current_player(state, ap)
    state = with_pending_stack(state, [
        PendingGrainUtilization(player_idx=ap, initiated_by_id="space:grain_utilization"),
        PendingBakeBread(player_idx=ap, initiated_by_id="grain_utilization"),
    ])
    actions = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) in actions


# ---------------------------------------------------------------------------
# Implicit-skip behavior (no SkipTrigger action)
# ---------------------------------------------------------------------------

def test_potter_implicitly_declined_via_commit():
    """With 1 clay AND 1 grain, the player can decline Potter by committing directly."""
    state = _potter_setup(grain=1, clay=1, with_fireplace=True, empty_fields=0)
    ap = state.current_player
    pre_clay = state.players[ap].resources.clay
    pre_food = state.players[ap].resources.food

    state = run_actions(state, [
        PlaceWorker(space="grain_utilization"),
        ChooseSubAction(name="bake_bread"),
        # Skip Fire — go straight to commit.
        CommitBake(grain=1),
        Stop(),
    ])
    # Clay unchanged (trigger didn't fire), +2 food.
    assert state.players[ap].resources.clay == pre_clay
    assert state.players[ap].resources.food == pre_food + 2


def test_potter_listed_alongside_commit_when_both_legal():
    """At PendingBakeBread with 1 clay + 1 grain, both Fire and Commit appear."""
    state = _potter_setup(grain=1, clay=1, with_fireplace=True, empty_fields=0)

    state = run_actions(state, [
        PlaceWorker(space="grain_utilization"),
        ChooseSubAction(name="bake_bread"),
    ])
    actions = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) in actions
    assert CommitBake(grain=1) in actions


def test_only_fire_legal_when_no_commit_possible():
    """0 grain + 1 clay + Potter + Fireplace: only FireTrigger is legal at PendingBakeBread."""
    state = _potter_setup(grain=0, clay=1, with_fireplace=True, empty_fields=0)

    state = run_actions(state, [
        PlaceWorker(space="grain_utilization"),
        ChooseSubAction(name="bake_bread"),
    ])
    actions = legal_actions(state)
    # No SkipTrigger exists in this architecture. The only legal action is to fire.
    assert actions == [FireTrigger(card_id=CARD_ID)]
