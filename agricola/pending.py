"""Pending decision types — frozen dataclasses representing in-progress
sub-decisions during a non-atomic action.

The pending stack on GameState (`pending_stack: tuple[PendingDecision, ...]`)
holds these frames bottom-to-top. The top frame identifies the next decision
the agent must make.

Each pending dataclass carries `player_idx: int`. This is usually equal to
`state.current_player` (the active player). Out-of-turn trigger frames
(not implemented in Task 5) would set `player_idx` to a non-active player,
enabling opponent decisions mid-resolution.

See CLAUDE.md "The pending-decision stack" for the full architecture and
design philosophies.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import ClassVar, TYPE_CHECKING, Union

from agricola.resources import Resources

if TYPE_CHECKING:
    from agricola.state import GameState


@dataclass(frozen=True)
class PendingGrainUtilization:
    """Outer pending for Grain Utilization.

    Tracks which sub-action categories have been chosen. The Family-game
    rule "must take at least one effect" is enforced via the Stop-legality
    predicate: Stop is legal iff sow_chosen or bake_chosen.
    """
    PENDING_ID: ClassVar[str] = "grain_utilization"
    player_idx: int
    initiated_by_id: str   # mandatory; identifies what pushed this frame
    sow_chosen: bool = False
    bake_chosen: bool = False


@dataclass(frozen=True)
class PendingSow:
    """Inner pending pushed by ChooseSubAction("sow") at Grain Utilization.

    Stack invariant: when CommitSow pops this frame, the new top is the
    parent pending (PendingGrainUtilization in Task 5). Trigger frames
    always push on top of PendingSow, never between it and its parent.
    """
    PENDING_ID: ClassVar[str] = "sow"
    player_idx: int
    initiated_by_id: str   # mandatory


@dataclass(frozen=True)
class PendingBakeBread:
    """Inner pending pushed by ChooseSubAction("bake_bread").

    `triggers_resolved` records which before-bake-bread card triggers have
    already fired during THIS Bake Bread action. The set is scoped to this
    frame's lifetime — when the frame pops, the set goes with it, and a
    new Bake Bread action starts with an empty set.

    TRIGGER_EVENT identifies the registry event this pending handles.
    """
    PENDING_ID: ClassVar[str] = "bake_bread"
    TRIGGER_EVENT: ClassVar[str] = "before_bake_bread"
    player_idx: int
    initiated_by_id: str   # mandatory
    triggers_resolved: frozenset = frozenset()  # frozenset[str], card_ids


@dataclass(frozen=True)
class PendingPlow:
    """Sub-action pending pushed by ChooseSubAction("plow") at a parent.

    Consumed by Farmland and Cultivation; cards may also push this with
    `initiated_by_id="card:<card_id>"`.
    """
    PENDING_ID: ClassVar[str] = "plow"
    TRIGGER_EVENT: ClassVar[str] = "before_plow"
    player_idx: int
    initiated_by_id: str
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingBuildStable:
    """Sub-action pending for stable construction.

    `cost: Resources` is set at push time by the choose handler (1 wood
    for Side Job; future spaces/cards specify their own). `_execute_build_stable`
    reads `pending.cost` and debits via `p.resources - pending.cost`.
    """
    PENDING_ID: ClassVar[str] = "build_stable"
    TRIGGER_EVENT: ClassVar[str] = "before_build_stable"
    player_idx: int
    initiated_by_id: str
    cost: Resources
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingBuildMajor:
    """Sub-action pending for Major Improvement purchase.

    `build_chosen` is set by `_execute_build_major` when the build commits
    (matters only for oven majors: PendingBuildMajor lingers below the
    oven wrapper while the optional free bake resolves; on return, only
    Stop is legal). For non-oven majors the pending is popped immediately
    by `_execute_build_major`, so the flag is never observed externally.

    Cost is NOT on this pending — it's keyed off `commit.major_idx` and
    looked up in `MAJOR_IMPROVEMENT_COSTS`.
    """
    PENDING_ID: ClassVar[str] = "build_major"
    TRIGGER_EVENT: ClassVar[str] = "before_build_major"
    player_idx: int
    initiated_by_id: str
    build_chosen: bool = False
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingRenovate:
    """Sub-action pending for house renovation.

    `cost: Resources` is set at push time by the choose handler.
    `_execute_renovate` reads `pending.cost` and debits.
    """
    PENDING_ID: ClassVar[str] = "renovate"
    TRIGGER_EVENT: ClassVar[str] = "before_renovate"
    player_idx: int
    initiated_by_id: str
    cost: Resources
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingFarmland:
    """Top-level parent pending for the Farmland action space."""
    PENDING_ID: ClassVar[str] = "farmland"
    TRIGGER_EVENT: ClassVar[str] = "before_farmland"
    player_idx: int
    initiated_by_id: str
    plow_chosen: bool = False
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingCultivation:
    """Top-level parent pending for the Cultivation action space."""
    PENDING_ID: ClassVar[str] = "cultivation"
    TRIGGER_EVENT: ClassVar[str] = "before_cultivation"
    player_idx: int
    initiated_by_id: str
    plow_chosen: bool = False
    sow_chosen: bool = False
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingSideJob:
    """Top-level parent pending for the Side Job action space."""
    PENDING_ID: ClassVar[str] = "side_job"
    TRIGGER_EVENT: ClassVar[str] = "before_side_job"
    player_idx: int
    initiated_by_id: str
    stable_chosen: bool = False
    bake_chosen: bool = False
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingSheepMarket:
    """Top-level parent pending for the Sheep Market action space.

    `gained` stages the animals taken from the space — they are not yet
    on the player. The player is in a transient pre-accommodation state
    until CommitAccommodate fires and sets the final animal counts.
    """
    PENDING_ID: ClassVar[str] = "sheep_market"
    TRIGGER_EVENT: ClassVar[str] = "before_sheep_market"
    player_idx: int
    initiated_by_id: str
    gained: int
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingPigMarket:
    """Top-level parent pending for the Pig Market action space."""
    PENDING_ID: ClassVar[str] = "pig_market"
    TRIGGER_EVENT: ClassVar[str] = "before_pig_market"
    player_idx: int
    initiated_by_id: str
    gained: int
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingCattleMarket:
    """Top-level parent pending for the Cattle Market action space."""
    PENDING_ID: ClassVar[str] = "cattle_market"
    TRIGGER_EVENT: ClassVar[str] = "before_cattle_market"
    player_idx: int
    initiated_by_id: str
    gained: int
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingMajorMinorImprovement:
    """Top-level parent pending for the Major/Minor Improvement action space."""
    PENDING_ID: ClassVar[str] = "major_minor_improvement"
    TRIGGER_EVENT: ClassVar[str] = "before_major_minor_improvement"
    player_idx: int
    initiated_by_id: str
    major_chosen: bool = False
    minor_chosen: bool = False
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingHouseRedevelopment:
    """Top-level parent pending for the House Redevelopment action space."""
    PENDING_ID: ClassVar[str] = "house_redevelopment"
    TRIGGER_EVENT: ClassVar[str] = "before_house_redevelopment"
    player_idx: int
    initiated_by_id: str
    renovate_chosen: bool = False
    improvement_chosen: bool = False
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingClayOven:
    """Non-top-level parent pending hosting the optional free Bake Bread
    after Clay Oven purchase.

    Pushed by `_execute_build_major` when `major_idx == 5`. Offers
    `ChooseSubAction("bake_bread")` (if legal) and `Stop`. `bake_chosen`
    becomes True when the player picks the bake; after the bake commits
    and PendingClayOven returns to top, only Stop is legal.
    """
    PENDING_ID: ClassVar[str] = "clay_oven"
    player_idx: int
    initiated_by_id: str
    bake_chosen: bool = False


@dataclass(frozen=True)
class PendingStoneOven:
    """Non-top-level parent pending hosting the optional free Bake Bread
    after Stone Oven purchase. Mirror of PendingClayOven.
    """
    PENDING_ID: ClassVar[str] = "stone_oven"
    player_idx: int
    initiated_by_id: str
    bake_chosen: bool = False


# The PendingDecision union. New pending types are added here as the
# non-atomic resolution surface grows.
PendingDecision = Union[
    PendingGrainUtilization,
    PendingSow,
    PendingBakeBread,
    PendingPlow,
    PendingBuildStable,
    PendingBuildMajor,
    PendingRenovate,
    PendingFarmland,
    PendingCultivation,
    PendingSideJob,
    PendingSheepMarket,
    PendingPigMarket,
    PendingCattleMarket,
    PendingMajorMinorImprovement,
    PendingHouseRedevelopment,
    PendingClayOven,
    PendingStoneOven,
]


# ---------------------------------------------------------------------------
# Stack operations
# ---------------------------------------------------------------------------
#
# Pure functions; all return new GameState objects (never mutate).
# Imported by agricola.engine and agricola.resolution.

def push(state: "GameState", frame: PendingDecision) -> "GameState":
    """Push a pending frame onto the top of state.pending_stack."""
    return dataclasses.replace(
        state, pending_stack=state.pending_stack + (frame,),
    )


def pop(state: "GameState") -> "GameState":
    """Drop the top frame from state.pending_stack."""
    return dataclasses.replace(
        state, pending_stack=state.pending_stack[:-1],
    )


def replace_top(state: "GameState", new_top: PendingDecision) -> "GameState":
    """Replace the top frame of state.pending_stack with new_top."""
    return dataclasses.replace(
        state,
        pending_stack=state.pending_stack[:-1] + (new_top,),
    )
