"""Tests for the Farm Redevelopment action space (TASK_6).

Renovate-then-optionally-Build-Fences. Mirrors test_house_redevelopment.py
structurally, with Build Fences replacing the optional improvement step.

Tests cover:
  - basic walks (renovate-only, renovate-then-build-fences)
  - mandatory-renovate-first ordering
  - Stop legality
  - WOOD → CLAY → STONE progression; STONE blocks
  - renovation cost on PendingRenovate
  - inner PendingBuildFences.initiated_by_id provenance (distinct from Fencing space)
  - Build Fences engine reuse (subdivision_started ordering rule still works)
  - _legal_farm_redevelopment predicate
  - Build Fences optional, gated on at-least-one-legal-pasture-commit
  - Stack invariants and flag semantics
"""
from __future__ import annotations

import dataclasses

import pytest

from agricola.actions import (
    ChooseSubAction,
    CommitBuildPasture,
    CommitRenovate,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.constants import HouseMaterial
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingBuildFences,
    PendingFarmRedevelopment,
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
from tests.test_utils import run_actions


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _fr_setup(*, material=HouseMaterial.WOOD, resources=None, current_player=0):
    """Setup: Farm Redevelopment revealed, given house + resources."""
    state = setup(seed=0)
    state = with_current_player(state, current_player)
    state = with_house(state, current_player, material)
    if resources:
        state = with_resources(state, current_player, **resources)
    state = with_space(state, "farm_redevelopment", revealed=True)
    return state


# ---------------------------------------------------------------------------
# Basic walks
# ---------------------------------------------------------------------------

def test_renovate_only_walk():
    """WOOD-house player: renovate only, skip optional Build Fences."""
    # 2 rooms → 2 clay + 1 reed.
    state = _fr_setup(resources={"clay": 2, "reed": 1})
    state = run_actions(state, [
        PlaceWorker(space="farm_redevelopment"),
        ChooseSubAction(name="renovate"),
        CommitRenovate(),
        Stop(),      # pop PendingRenovate's after-phase
        Proceed(),   # flip the parent to its after-phase
        Stop(),      # pop the parent
    ])
    assert state.pending_stack == ()
    assert state.players[0].house_material == HouseMaterial.CLAY
    assert state.players[0].resources.clay == 0
    assert state.players[0].resources.reed == 0


def test_renovate_then_build_fences_walk():
    """WOOD player: renovate then build a 1×1 pasture."""
    state = _fr_setup(resources={"clay": 2, "reed": 1, "wood": 4})
    state = run_actions(state, [
        PlaceWorker(space="farm_redevelopment"),
        ChooseSubAction(name="renovate"),
        CommitRenovate(),
        Stop(),                                 # pop PendingRenovate's after-phase
        ChooseSubAction(name="build_fences"),
        CommitBuildPasture(cells=frozenset({(0, 1)})),
        Stop(),                                 # pops PendingBuildFences
        Proceed(),                              # flip PendingFarmRedevelopment to after-phase
        Stop(),                                 # pops PendingFarmRedevelopment
    ])
    assert state.pending_stack == ()
    assert state.players[0].house_material == HouseMaterial.CLAY
    assert state.players[0].resources.wood == 0       # 4 wood debited
    fy = state.players[0].farmyard
    assert len(fy.pastures) == 1
    assert fy.pastures[0].cells == frozenset({(0, 1)})


# ---------------------------------------------------------------------------
# Mandatory-renovate-first + Stop legality
# ---------------------------------------------------------------------------

def test_build_fences_requires_renovate_first():
    """ChooseSubAction("build_fences") is not in legal_actions before renovate."""
    state = _fr_setup(resources={"clay": 2, "reed": 1, "wood": 4})
    state = step(state, PlaceWorker(space="farm_redevelopment"))
    legal = legal_actions(state)
    assert ChooseSubAction(name="build_fences") not in legal
    assert ChooseSubAction(name="renovate") in legal


def test_stop_illegal_before_renovate():
    """Stop is illegal on PendingFarmRedevelopment before renovate_chosen."""
    state = _fr_setup(resources={"clay": 2, "reed": 1})
    state = step(state, PlaceWorker(space="farm_redevelopment"))
    legal = legal_actions(state)
    assert Stop() not in legal


def test_stop_legal_after_renovate_skip_build_fences():
    """Stop legal at PendingFarmRedevelopment once renovate_chosen=True."""
    state = _fr_setup(resources={"clay": 2, "reed": 1})
    state = run_actions(state, [
        PlaceWorker(space="farm_redevelopment"),
        ChooseSubAction(name="renovate"),
        CommitRenovate(),
    ])
    legal = legal_actions(state)
    assert Stop() in legal


# ---------------------------------------------------------------------------
# Material progression
# ---------------------------------------------------------------------------

def test_material_progression_wood_to_clay():
    state = _fr_setup(material=HouseMaterial.WOOD, resources={"clay": 2, "reed": 1})
    state = run_actions(state, [
        PlaceWorker(space="farm_redevelopment"),
        ChooseSubAction(name="renovate"),
        CommitRenovate(),
        Stop(),
    ])
    assert state.players[0].house_material == HouseMaterial.CLAY


def test_material_progression_clay_to_stone():
    state = _fr_setup(material=HouseMaterial.CLAY, resources={"stone": 2, "reed": 1})
    state = run_actions(state, [
        PlaceWorker(space="farm_redevelopment"),
        ChooseSubAction(name="renovate"),
        CommitRenovate(),
        Stop(),
    ])
    assert state.players[0].house_material == HouseMaterial.STONE


def test_stone_house_cannot_start_farm_redevelopment():
    state = _fr_setup(material=HouseMaterial.STONE)
    assert PlaceWorker(space="farm_redevelopment") not in legal_actions(state)


# ---------------------------------------------------------------------------
# Renovation cost on pending
# ---------------------------------------------------------------------------

def test_renovation_cost_wood_to_clay():
    """Wood → Clay: num_rooms clay + 1 reed total (not per-room)."""
    state = _fr_setup(resources={"clay": 2, "reed": 1})
    state = run_actions(state, [
        PlaceWorker(space="farm_redevelopment"),
        ChooseSubAction(name="renovate"),
    ])
    pending = state.pending_stack[-1]
    assert isinstance(pending, PendingRenovate)
    assert pending.cost == Resources(clay=2, reed=1)


def test_renovation_cost_clay_to_stone():
    state = _fr_setup(material=HouseMaterial.CLAY, resources={"stone": 2, "reed": 1})
    state = run_actions(state, [
        PlaceWorker(space="farm_redevelopment"),
        ChooseSubAction(name="renovate"),
    ])
    pending = state.pending_stack[-1]
    assert isinstance(pending, PendingRenovate)
    assert pending.cost == Resources(stone=2, reed=1)


# ---------------------------------------------------------------------------
# Provenance: inner PendingBuildFences from Farm Redev
# ---------------------------------------------------------------------------

def test_inner_build_fences_provenance():
    """Inner PendingBuildFences.initiated_by_id reflects Farm Redev (not Fencing)."""
    state = _fr_setup(resources={"clay": 2, "reed": 1, "wood": 4})
    state = run_actions(state, [
        PlaceWorker(space="farm_redevelopment"),
        ChooseSubAction(name="renovate"),
        CommitRenovate(),
        Stop(),   # pop PendingRenovate's after-phase
        ChooseSubAction(name="build_fences"),
    ])
    inner = state.pending_stack[-1]
    assert isinstance(inner, PendingBuildFences)
    assert inner.initiated_by_id == "farm_redevelopment"
    # Distinct from the Fencing-space path which uses "fencing".
    assert inner.initiated_by_id != "fencing"
    assert inner.initiated_by_id != "space:farm_redevelopment"


# ---------------------------------------------------------------------------
# Build Fences engine reuse — same machinery as Fencing space
# ---------------------------------------------------------------------------

def test_build_fences_subdivision_started_flag_works_via_farm_redev():
    """The ordering rule (builds before subdivisions) applies just as much when
    Build Fences is reached via Farm Redev as via Fencing."""
    state = _fr_setup(resources={"clay": 2, "reed": 1, "wood": 20})
    state = run_actions(state, [
        PlaceWorker(space="farm_redevelopment"),
        ChooseSubAction(name="renovate"),
        CommitRenovate(),
        Stop(),   # pop PendingRenovate's after-phase
        ChooseSubAction(name="build_fences"),
        CommitBuildPasture(cells=frozenset({(0, 1)})),     # new pasture, 4 fences
        CommitBuildPasture(cells=frozenset({(0, 2)})),     # adjacent new pasture, 3 fences
    ])
    pending = state.pending_stack[-1]
    assert isinstance(pending, PendingBuildFences)
    assert pending.pastures_built == 2
    assert pending.fences_built == 7
    assert pending.subdivision_started is False


# ---------------------------------------------------------------------------
# _legal_farm_redevelopment predicate
# ---------------------------------------------------------------------------

def test_legal_baseline_true():
    state = _fr_setup(resources={"clay": 2, "reed": 1})
    assert PlaceWorker(space="farm_redevelopment") in legal_actions(state)


def test_legal_false_when_stone_house():
    state = _fr_setup(material=HouseMaterial.STONE)
    assert PlaceWorker(space="farm_redevelopment") not in legal_actions(state)


def test_legal_false_when_missing_reed():
    state = _fr_setup(resources={"clay": 2})        # no reed
    assert PlaceWorker(space="farm_redevelopment") not in legal_actions(state)


def test_legal_false_when_missing_clay_wood_house():
    state = _fr_setup(resources={"reed": 1})        # no clay
    assert PlaceWorker(space="farm_redevelopment") not in legal_actions(state)


def test_legal_false_when_missing_stone_clay_house():
    state = _fr_setup(material=HouseMaterial.CLAY, resources={"reed": 1})
    assert PlaceWorker(space="farm_redevelopment") not in legal_actions(state)


# ---------------------------------------------------------------------------
# Build Fences optional, gated on legality
# ---------------------------------------------------------------------------

def test_build_fences_not_offered_when_no_legal_commit():
    """When post-renovate state has no legal pasture commit, build_fences is
    not in legal_actions — only Stop."""
    # Renovate cost (2 clay + 1 reed) exactly drains resources; no wood for fences.
    state = _fr_setup(resources={"clay": 2, "reed": 1})
    state = run_actions(state, [
        PlaceWorker(space="farm_redevelopment"),
        ChooseSubAction(name="renovate"),
        CommitRenovate(),
    ])
    legal = legal_actions(state)
    assert ChooseSubAction(name="build_fences") not in legal
    assert Stop() in legal


def test_build_fences_offered_when_legal_commit_exists():
    """With enough wood post-renovate, build_fences appears as an option."""
    state = _fr_setup(resources={"clay": 2, "reed": 1, "wood": 4})
    state = run_actions(state, [
        PlaceWorker(space="farm_redevelopment"),
        ChooseSubAction(name="renovate"),
        CommitRenovate(),
        Stop(),   # pop PendingRenovate's after-phase -> back at the parent
    ])
    legal = legal_actions(state)
    assert ChooseSubAction(name="build_fences") in legal


# ---------------------------------------------------------------------------
# Stack invariants
# ---------------------------------------------------------------------------

def test_stack_invariants_full_walk():
    """Walk through all stack transitions and verify pendings + flags."""
    state = _fr_setup(resources={"clay": 2, "reed": 1, "wood": 4})

    # PlaceWorker → PendingFarmRedevelopment.
    state = step(state, PlaceWorker(space="farm_redevelopment"))
    assert len(state.pending_stack) == 1
    parent = state.pending_stack[-1]
    assert isinstance(parent, PendingFarmRedevelopment)
    assert parent.initiated_by_id == "space:farm_redevelopment"
    assert parent.renovate_chosen is False
    assert parent.build_fences_chosen is False

    # ChooseSubAction("renovate") sets renovate_chosen + pushes PendingRenovate.
    state = step(state, ChooseSubAction(name="renovate"))
    assert len(state.pending_stack) == 2
    assert state.pending_stack[0].renovate_chosen is True
    inner = state.pending_stack[-1]
    assert isinstance(inner, PendingRenovate)
    assert inner.initiated_by_id == "farm_redevelopment"

    # CommitRenovate flips PendingRenovate to after-phase (no auto-pop).
    state = step(state, CommitRenovate())
    assert len(state.pending_stack) == 2
    assert isinstance(state.pending_stack[-1], PendingRenovate)
    assert state.pending_stack[-1].phase == "after"
    assert isinstance(state.pending_stack[-2], PendingFarmRedevelopment)

    # Stop pops PendingRenovate's after-phase → back at parent.
    state = step(state, Stop())
    assert len(state.pending_stack) == 1
    assert isinstance(state.pending_stack[-1], PendingFarmRedevelopment)

    # ChooseSubAction("build_fences") sets the flag + pushes PendingBuildFences.
    state = step(state, ChooseSubAction(name="build_fences"))
    assert len(state.pending_stack) == 2
    assert state.pending_stack[0].build_fences_chosen is True
    bf = state.pending_stack[-1]
    assert isinstance(bf, PendingBuildFences)
    assert bf.initiated_by_id == "farm_redevelopment"

    # CommitBuildPasture leaves PendingBuildFences on top (the dispatcher never pops).
    state = step(state, CommitBuildPasture(cells=frozenset({(0, 1)})))
    assert len(state.pending_stack) == 2

    # Stop pops PendingBuildFences.
    state = step(state, Stop())
    assert len(state.pending_stack) == 1
    assert isinstance(state.pending_stack[-1], PendingFarmRedevelopment)

    # Proceed flips PendingFarmRedevelopment to its after-phase.
    state = step(state, Proceed())
    assert len(state.pending_stack) == 1
    assert isinstance(state.pending_stack[-1], PendingFarmRedevelopment)

    # Stop pops PendingFarmRedevelopment.
    state = step(state, Stop())
    assert state.pending_stack == ()
