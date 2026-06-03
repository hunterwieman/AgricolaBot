"""Pending decision types — frozen dataclasses representing in-progress
sub-decisions during a non-atomic action.

The pending stack on GameState (`pending_stack: tuple[PendingDecision, ...]`)
holds these frames bottom-to-top. The top frame identifies the next decision
the agent must make.

Each pending dataclass carries `player_idx: int`. This is usually equal to
`state.current_player` (the active player). Out-of-turn trigger frames
(not implemented in Task 5) would set `player_idx` to a non-active player,
enabling opponent decisions mid-resolution.

See ENGINE_IMPLEMENTATION.md §2 (The pending-decision stack) for the full
architecture and design philosophies.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import ClassVar, TYPE_CHECKING, Union

from agricola.replace import fast_replace
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
class PendingFarmExpansion:
    """Top-level parent pending for the Farm Expansion action space.

    Mirrors the Side Job parent's shape — two boolean `*_chosen` flags
    enforcing the "once per category" rule (you cannot build rooms,
    switch to stables, then return to rooms).

    No `triggers_resolved` field and no `TRIGGER_EVENT` classvar — card
    machinery for the farm_expansion event is deferred until the first
    such card lands.
    """
    PENDING_ID: ClassVar[str] = "farm_expansion"
    player_idx: int
    initiated_by_id: str
    room_chosen: bool = False
    stable_chosen: bool = False


@dataclass(frozen=True)
class PendingBuildStables:
    """Multi-shot sub-action pending for stable construction.

    Pushed by `_choose_subaction_*` handlers when the player enters the
    build-stables category. Holds the per-commit `cost: Resources` and a
    caller-imposed cap `max_builds: int | None` (None = no cap; Side Job
    sets 1; Farm Expansion sets None). `num_built` increments on each
    commit; when no commit is legal but num_built >= 1, only Stop is
    legal and the player explicitly Stops to pop the pending.

    No card-trigger fields yet — `triggers_resolved` / `TRIGGER_EVENT`
    will be added when the first card needs them (per the deferred
    "card-trigger machinery on the new pendings" note in TASK_5D
    Appendix A).
    """
    PENDING_ID: ClassVar[str] = "build_stables"
    player_idx: int
    initiated_by_id: str
    cost: Resources
    max_builds: int | None
    num_built: int = 0


@dataclass(frozen=True)
class PendingBuildRooms:
    """Multi-shot sub-action pending for room construction.

    Same shape as PendingBuildStables. `cost` is `ROOM_COSTS[house_material]`;
    `max_builds=None` from Farm Expansion (the only caller in Task 5D).
    """
    PENDING_ID: ClassVar[str] = "build_rooms"
    player_idx: int
    initiated_by_id: str
    cost: Resources
    max_builds: int | None
    num_built: int = 0


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


@dataclass(frozen=True)
class PendingFencing:
    """Top-level parent pending for the Fencing action space.

    A thin wrapper above PendingBuildFences. Without cards it carries one
    boolean (`build_fences_chosen`) used by Stop-legality (Stop is illegal
    until the build_fences sub-action has been entered). With cards it
    hosts the space-specific `before_fencing` trigger event — distinct
    from `before_build_fences`, which fires at the sub-action layer when
    Build Fences is reached via Fencing, Farm Redevelopment, or card
    effects.
    """
    PENDING_ID: ClassVar[str] = "fencing"
    TRIGGER_EVENT: ClassVar[str] = "before_fencing"
    player_idx: int
    initiated_by_id: str
    build_fences_chosen: bool = False
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingBuildFences:
    """Multi-shot sub-action pending for fence building.

    Pushed by `_choose_subaction_fencing` and by `_choose_subaction_farm_redevelopment`
    (and by future card effects). Each `CommitBuildPasture` names one pasture
    cell-set; the effect function debits wood for the new fence edges and
    increments the counters below.

    State fields:
      - `pastures_built`: number of CommitBuildPasture commits landed so far.
        Stop-legality requires `pastures_built >= 1`.
      - `fences_built`: total fence-edges placed across all commits. Carries
        forward for card patterns like "each time you build N fences ≥ current
        round, get 1 vegetable".
      - `subdivision_started`: flips True the first time a subdivision commit
        lands. Implements the builds-before-subdivisions ordering rule
        (TASK_6.md Part 2.3): once a subdivision has happened, new-pasture
        commits are no longer offered in the enumerator.

    `auto_pop=False` for the matching `CommitBuildPasture` handler: each
    commit replaces the top with updated counters and leaves the pending
    on the stack; Stop pops it.
    """
    PENDING_ID: ClassVar[str] = "build_fences"
    TRIGGER_EVENT: ClassVar[str] = "before_build_fences"
    player_idx: int
    initiated_by_id: str
    pastures_built: int = 0
    fences_built: int = 0
    subdivision_started: bool = False
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingFarmRedevelopment:
    """Top-level parent pending for the Farm Redevelopment action space.

    Two-step structure (mirrors PendingHouseRedevelopment from TASK_5C §3.6):
      - Renovate is mandatory. Stop-legality requires renovate_chosen=True.
      - Build Fences is optional ("renovate **then** optionally Build Fences"),
        offered only after renovate has been entered AND at least one legal
        pasture commit exists in the post-renovate state.

    Reuses PendingRenovate (from TASK_5C) for the renovate step and
    PendingBuildFences (above) for the build_fences step. Provenance:
    inner PendingBuildFences carries `initiated_by_id="farm_redevelopment"`
    (the parent's PENDING_ID, no prefix) — distinct from the Fencing-space
    path which pushes with `initiated_by_id="fencing"`. Future cards may
    gate on entry point via this provenance.
    """
    PENDING_ID: ClassVar[str] = "farm_redevelopment"
    TRIGGER_EVENT: ClassVar[str] = "before_farm_redevelopment"
    player_idx: int
    initiated_by_id: str
    renovate_chosen: bool = False
    build_fences_chosen: bool = False
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingHarvestFeed:
    """Phase-driven pending for the HARVEST_FEED sub-phase, one per player.

    Pushed by `_initiate_harvest_feed` (in engine.py) at the start of FEED,
    with `initiated_by_id="phase:harvest_feed"` — the third namespace in the
    provenance scheme alongside `"space:..."` and `"card:..."`.

    Hosts trigger-style opt-in sub-decisions (the three craft majors, via
    CommitHarvestConversion) plus one main `CommitConvert`. After cards
    land, additional card-triggered conversions register into the same
    HARVEST_CONVERSIONS registry and appear alongside the crafts.

    State semantics:
      - Food payment is deferred to `CommitConvert`. No food is debited
        when this pending is pushed; `p.resources.food` is the player's
        live supply throughout the feed sub-phase.
      - `food_owed` is a derived value, recomputed wherever needed as
        `max(0, need - p.resources.food)` with `need = 2*people_total - newborns`.
        It is not stored on this pending — see CLAUDE.md Foundations
        (Derived data, not cached data). Recomputing on each
        legality call lets future cards that mutate food during feeding
        (e.g. food↔resource exchanges that chain into Pottery) be reflected
        immediately in the next legal-actions call.
      - Each CommitHarvestConversion(use=True) pays input_cost and adds
        food_out to supply (no food_owed bookkeeping).
      - CommitConvert is the sole payment site: pays `min(need, food_in_supply
        + food_produced)` to feeding; surplus stays in supply; any shortfall
        becomes begging markers. Sets `conversion_done=True`.
      - Stop is legal only after `conversion_done=True`.

    "Decided" conversion ids live on PlayerState.harvest_conversions_used,
    not on this pending — per the "per-card budgets that span multiple
    events live on PlayerState" convention.

    No `triggers_resolved` / `TRIGGER_EVENT` fields yet — added per Task 5D
    precedent only when the first card needing them lands. Natural future
    events: `before_harvest_feed`, `after_harvest_feed`.
    """
    PENDING_ID: ClassVar[str] = "harvest_feed"
    player_idx:      int
    initiated_by_id: str            # always "phase:harvest_feed"
    conversion_done: bool = False


@dataclass(frozen=True)
class PendingHarvestBreed:
    """Phase-driven pending for the HARVEST_BREED sub-phase, one per player.

    Pushed by `_initiate_harvest_breed` at the start of BREED with
    `initiated_by_id="phase:harvest_breed"`. Simpler shape than FEED — one
    CommitBreed (chosen from `breeding_frontier`) followed by Stop. No
    food pre-debit; CommitBreed adds the frontier's food_gained to supply.

    No `triggers_resolved` / `TRIGGER_EVENT` yet (Task 5D precedent).
    Natural future events: `before_harvest_breed`, `after_harvest_breed`.
    """
    PENDING_ID: ClassVar[str] = "harvest_breed"
    player_idx:      int
    initiated_by_id: str            # always "phase:harvest_breed"
    breed_chosen:    bool = False


@dataclass(frozen=True)
class PendingReveal:
    """Nature's pending decision: which stage card is revealed for the round
    being entered. Pushed by the PREPARATION phase walk (the two-state Case 2
    in engine._advance_until_decision) when the next round's card is not up yet.

    `player_idx` is None — the nature sentinel — so `decider_of` returns None
    and the driver routes the decision to the dealer (the Environment), never
    to a strategic agent. Hosts exactly one RevealCard, then pops. See
    HIDDEN_INFO_DESIGN.md §4.2.
    """
    PENDING_ID: ClassVar[str] = "reveal"
    player_idx: None = None               # nature: no owning player
    initiated_by_id: str = "phase:reveal"


# The PendingDecision union. New pending types are added here as the
# non-atomic resolution surface grows.
PendingDecision = Union[
    PendingGrainUtilization,
    PendingSow,
    PendingBakeBread,
    PendingPlow,
    PendingBuildStables,
    PendingBuildRooms,
    PendingBuildMajor,
    PendingRenovate,
    PendingFarmExpansion,
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
    PendingFencing,
    PendingBuildFences,
    PendingFarmRedevelopment,
    PendingHarvestFeed,
    PendingHarvestBreed,
    PendingReveal,
]


# ---------------------------------------------------------------------------
# Stack operations
# ---------------------------------------------------------------------------
#
# Pure functions; all return new GameState objects (never mutate).
# Imported by agricola.engine and agricola.resolution.

def push(state: "GameState", frame: PendingDecision) -> "GameState":
    """Push a pending frame onto the top of state.pending_stack."""
    return fast_replace(
        state, pending_stack=state.pending_stack + (frame,),
    )


def pop(state: "GameState") -> "GameState":
    """Drop the top frame from state.pending_stack."""
    return fast_replace(
        state, pending_stack=state.pending_stack[:-1],
    )


def replace_top(state: "GameState", new_top: PendingDecision) -> "GameState":
    """Replace the top frame of state.pending_stack with new_top."""
    return fast_replace(
        state,
        pending_stack=state.pending_stack[:-1] + (new_top,),
    )
