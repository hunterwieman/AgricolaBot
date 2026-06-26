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
    rule "must take at least one effect" is enforced via the Proceed-legality
    predicate: Proceed is legal iff sow_chosen or bake_chosen.

    A Proceed-host action-space frame (and/or; SPACE_HOST_REFACTOR.md §4.3):
    the before-phase hosts the legal ChooseSubActions + (once a sub-action has
    run) Proceed; Proceed flips `phase` to "after" (firing after_action_space
    autos), the after-phase hosts after-triggers + Stop, and Stop pops. The
    event derives via the action_space bucket (legality.trigger_event).
    """
    PENDING_ID: ClassVar[str] = "grain_utilization"
    player_idx: int
    initiated_by_id: str   # mandatory; identifies what pushed this frame
    sow_chosen: bool = False
    bake_chosen: bool = False
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()

    @property
    def space_id(self) -> str:
        return self.initiated_by_id.split(":", 1)[1]


@dataclass(frozen=True)
class PendingSow:
    """Inner pending pushed by ChooseSubAction("sow") at Grain Utilization.

    A uniform commit-terminated sub-action HOST (SUBACTION_HOOK_REFACTOR.md):
    it carries a before/after `phase` and a `triggers_resolved` set, does NOT
    auto-pop on CommitSow, and pivots to `phase="after"` at the commit (firing
    `after_sow` automatic effects there). The after-phase enumerator then offers
    any `after_sow` triggers + Stop, and Stop pops. The derived trigger event is
    `<phase>_sow` (legality.trigger_event), so no per-frame TRIGGER_EVENT.

    Stack invariant: when this frame finally pops (at Stop), the new top is the
    parent pending. Trigger frames always push on top of PendingSow, never
    between it and its parent.
    """
    PENDING_ID: ClassVar[str] = "sow"
    player_idx: int
    initiated_by_id: str   # mandatory
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingBakeBread:
    """Inner pending pushed by ChooseSubAction("bake_bread").

    `triggers_resolved` records which before-/after-bake-bread card triggers
    have already fired during THIS Bake Bread action. The set is scoped to this
    frame's lifetime — when the frame pops, the set goes with it, and a
    new Bake Bread action starts with an empty set.

    A uniform commit-terminated sub-action HOST (SUBACTION_HOOK_REFACTOR.md):
    `phase` flips "before"->"after" at CommitBake (no auto-pop), firing
    `after_bake_bread` automatic effects; the after-phase offers `after_bake_bread`
    triggers + Stop. The before-phase still hosts Potter (`before_bake_bread`).
    The event is derived `<phase>_bake_bread` (legality.trigger_event) — no
    per-frame TRIGGER_EVENT.
    """
    PENDING_ID: ClassVar[str] = "bake_bread"
    player_idx: int
    initiated_by_id: str   # mandatory
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()  # frozenset[str], card_ids


@dataclass(frozen=True)
class PendingPlow:
    """Sub-action pending pushed by ChooseSubAction("plow") at a parent.

    Consumed by Farmland and Cultivation; cards may also push this with
    `initiated_by_id="card:<card_id>"`.

    A uniform commit-terminated sub-action HOST (SUBACTION_HOOK_REFACTOR.md):
    `phase` flips "before"->"after" at CommitPlow (no auto-pop), firing
    `after_plow` automatic effects; the after-phase offers `after_plow` triggers
    + Stop. Event derived `<phase>_plow` — no per-frame TRIGGER_EVENT.
    """
    PENDING_ID: ClassVar[str] = "plow"
    player_idx: int
    initiated_by_id: str
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingFarmExpansion:
    """Top-level parent pending for the Farm Expansion action space.

    Mirrors the Side Job parent's shape — two boolean `*_chosen` flags
    enforcing the "once per category" rule (you cannot build rooms,
    switch to stables, then return to rooms).

    A Proceed-host action-space frame (and/or; SPACE_HOST_REFACTOR.md §4.3):
    the before-phase hosts the legal ChooseSubActions + (once a sub-action has
    run) Proceed; Proceed flips `phase` to "after" (firing after_action_space
    autos), the after-phase hosts after-triggers + Stop. Event derives via the
    action_space bucket (legality.trigger_event).
    """
    PENDING_ID: ClassVar[str] = "farm_expansion"
    player_idx: int
    initiated_by_id: str
    room_chosen: bool = False
    stable_chosen: bool = False
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()


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

    A uniform commit-terminated sub-action HOST (SUBACTION_HOOK_REFACTOR.md):
    `phase` flips "before"->"after" at CommitBuildMajor (no auto-pop). For an
    oven major the flip happens BEFORE the oven wrapper is pushed, so when the
    free-bake wrapper pops back, this frame is already in its after-phase
    (offering `after_build_major` triggers + Stop). For a non-oven major the
    effect flips and leaves the frame for its trailing Stop. `phase=="after"`
    therefore replaces the old `build_chosen` flag (they were exactly
    redundant). Event derived `<phase>_build_major` — no per-frame TRIGGER_EVENT.

    Cost is NOT on this pending — it's keyed off `commit.major_idx` and
    looked up in `MAJOR_IMPROVEMENT_COSTS`.
    """
    PENDING_ID: ClassVar[str] = "build_major"
    player_idx: int
    initiated_by_id: str
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingRenovate:
    """Sub-action pending for house renovation.

    `cost: Resources` is set at push time by the choose handler.
    `_execute_renovate` reads `pending.cost` and debits.

    A uniform commit-terminated sub-action HOST (SUBACTION_HOOK_REFACTOR.md):
    `phase` flips "before"->"after" at CommitRenovate (no auto-pop), firing
    `after_renovate` automatic effects; the after-phase offers `after_renovate`
    triggers (e.g. Mining Hammer's free stable) + Stop. Event derived
    `<phase>_renovate` — no per-frame TRIGGER_EVENT.
    """
    PENDING_ID: ClassVar[str] = "renovate"
    player_idx: int
    initiated_by_id: str
    cost: Resources
    phase: str = "before"               # "before" | "after"
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

    @property
    def space_id(self) -> str:
        return self.initiated_by_id.split(":", 1)[1]


@dataclass(frozen=True)
class PendingCultivation:
    """Top-level parent pending for the Cultivation action space.

    A Proceed-host action-space frame (and/or; SPACE_HOST_REFACTOR.md §4.3):
    before-phase hosts the legal ChooseSubActions + (once a sub-action has run)
    Proceed; Proceed flips `phase` to "after" (firing after_action_space autos),
    the after-phase hosts after-triggers + Stop. Event derives via the
    action_space bucket (legality.trigger_event) — no per-frame TRIGGER_EVENT.
    """
    PENDING_ID: ClassVar[str] = "cultivation"
    player_idx: int
    initiated_by_id: str
    plow_chosen: bool = False
    sow_chosen: bool = False
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()

    @property
    def space_id(self) -> str:
        return self.initiated_by_id.split(":", 1)[1]


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

    A space-host frame (CARD_IMPLEMENTATION_PLAN.md II.2/4b): it carries the
    before/after `phase` and fires the coarse `before_/after_action_space` event
    (routed via legality.trigger_event's bucket — no per-frame TRIGGER_EVENT).
    Unlike the old auto-popping model, CommitAccommodate now flips `phase` to
    "after" and `Stop` pops — the uniform non-atomic lifecycle.
    """
    PENDING_ID: ClassVar[str] = "sheep_market"
    player_idx: int
    initiated_by_id: str
    gained: int
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()

    @property
    def space_id(self) -> str:
        return self.initiated_by_id.split(":", 1)[1]


@dataclass(frozen=True)
class PendingPigMarket:
    """Top-level parent pending for the Pig Market action space (see PendingSheepMarket)."""
    PENDING_ID: ClassVar[str] = "pig_market"
    player_idx: int
    initiated_by_id: str
    gained: int
    phase: str = "before"
    triggers_resolved: frozenset = frozenset()

    @property
    def space_id(self) -> str:
        return self.initiated_by_id.split(":", 1)[1]


@dataclass(frozen=True)
class PendingCattleMarket:
    """Top-level parent pending for the Cattle Market action space (see PendingSheepMarket)."""
    PENDING_ID: ClassVar[str] = "cattle_market"
    player_idx: int
    initiated_by_id: str
    gained: int
    phase: str = "before"
    triggers_resolved: frozenset = frozenset()

    @property
    def space_id(self) -> str:
        return self.initiated_by_id.split(":", 1)[1]


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
    """Top-level parent pending for the House Redevelopment action space.

    A Proceed-host action-space frame (and-then; SPACE_HOST_REFACTOR.md §4.3):
    a mandatory renovate, then an optional improvement, then Proceed. While
    renovate is unchosen only it is offered (no Proceed); once renovate has run,
    the optional improvement + Proceed are offered. Proceed flips `phase` to
    "after" (firing after_action_space autos), the after-phase hosts
    after-triggers + Stop. Event derives via the action_space bucket — no
    per-frame TRIGGER_EVENT.
    """
    PENDING_ID: ClassVar[str] = "house_redevelopment"
    player_idx: int
    initiated_by_id: str
    renovate_chosen: bool = False
    improvement_chosen: bool = False
    phase: str = "before"               # "before" | "after"
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

    A Proceed-host action-space frame (and-then; SPACE_HOST_REFACTOR.md §4.3):
    a mandatory renovate, then an optional Build Fences, then Proceed; Proceed
    flips `phase` to "after" (firing after_action_space autos), the after-phase
    hosts after-triggers + Stop. Event derives via the action_space bucket — no
    per-frame TRIGGER_EVENT.
    """
    PENDING_ID: ClassVar[str] = "farm_redevelopment"
    player_idx: int
    initiated_by_id: str
    renovate_chosen: bool = False
    build_fences_chosen: bool = False
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingPlayOccupation:
    """Play one occupation from hand into the tableau (card game only).

    Pushed by Lessons (and later Scholar / card grants). It is its own host —
    there is no separate sub-action below it: one `CommitPlayOccupation` plays
    exactly one occupation, then this frame pops. `cost` is the food cost of THIS
    play, set at push time (route-dependent — Lessons: `occupation_cost(...)`;
    Scholar: 1 food); `_execute_play_occupation` reads it and debits.

    A uniform commit-terminated sub-action HOST (SUBACTION_HOOK_REFACTOR.md):
    `phase` flips "before"->"after" at CommitPlayOccupation (no auto-pop), firing
    `after_play_occupation` automatic effects; the after-phase offers
    `after_play_occupation` triggers (e.g. Bread Paddle's free bake) + Stop. The
    flip happens BEFORE the occupation's on-play runs (which may itself push a
    sub-decision), mirroring the granted-sub-action record-before-apply rule.
    Card-only frame: never reaches the C++ (Family) engine. Event derived
    `<phase>_play_occupation`.
    """
    PENDING_ID: ClassVar[str] = "play_occupation"
    player_idx: int
    initiated_by_id: str
    cost: Resources = Resources()
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingPlayMinor:
    """Play (optionally) one minor improvement from hand (card game only).

    Pushed by the card Meeting Place / the improvement spaces / card grants. Its
    enumerator offers a CommitPlayMinor per playable hand minor PLUS Stop —
    declining is allowed (Meeting Place's minor is optional). No cost field: a
    minor pays its own printed cost, read from its MinorSpec at resolution.

    Always plays exactly one minor: its enumerator offers a CommitPlayMinor per
    playable hand minor and nothing else. It is pushed ONLY after the player has
    committed to the minor branch (mirroring how PendingSow is pushed only after
    `sow` is chosen), so >=1 minor is always playable and there is no decline
    here. Whether playing a minor was *optional* is the PARENT frame's concern —
    the parent offers the `play_minor` choice alongside its own Stop — so this
    frame needs no optionality of its own.

    A uniform commit-terminated sub-action HOST (SUBACTION_HOOK_REFACTOR.md):
    `phase` flips "before"->"after" at CommitPlayMinor (no auto-pop), firing
    `after_play_minor` automatic effects; the after-phase offers
    `after_play_minor` triggers + Stop. The flip happens BEFORE the minor's
    on-play runs (which may push a sub-decision). Card-only frame: never reaches
    the C++ (Family) engine. Event derived `<phase>_play_minor`.
    """
    PENDING_ID: ClassVar[str] = "play_minor"
    player_idx: int
    initiated_by_id: str
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingBasicWishForChildren:
    """Card-game parent frame for Basic Wish for Children — mirrors
    PendingHouseRedevelopment: a mandatory primary sub-action (family growth) then
    an optional follow-up (play 1 minor).

    Lifecycle: pushed at placement (card mode only). While `family_growth_done` is
    False the enumerator offers only ChooseSubAction("family_growth") — a mandatory
    singleton that pushes PendingFamilyGrowth; once growth has run, it offers
    ChooseSubAction("play_minor") (if a minor is playable) plus Stop. The OR-style
    once-only restriction lives in the enumerator. The Family game keeps the atomic
    resolver and never pushes this frame. See CARD_IMPLEMENTATION_PLAN.md.
    """
    PENDING_ID: ClassVar[str] = "basic_wish_for_children"
    player_idx: int
    initiated_by_id: str
    family_growth_done: bool = False
    minor_chosen: bool = False


@dataclass(frozen=True)
class PendingMeetingPlaceCards:
    """Card-game Meeting Place follow-up. Become starting player is an IMMEDIATE
    effect (applied in the resolver, no frame — it always happens and triggers no
    cards), so this frame hosts only the OPTIONAL minor: its enumerator offers
    ChooseSubAction("play_minor") (while not yet played and a minor is playable)
    plus Stop — the decline, since the SP token was already taken. Pushed (card
    mode only) right after become-SP, and only when a minor is playable. The
    Family Meeting Place is the atomic food/SP resolver and never pushes this.
    See CARD_IMPLEMENTATION_PLAN.md I.3.
    """
    PENDING_ID: ClassVar[str] = "meeting_place"
    player_idx: int
    initiated_by_id: str
    minor_chosen: bool = False


@dataclass(frozen=True)
class PendingFamilyGrowth:
    """The family-growth sub-action primitive: add one newborn on the space named
    by `initiated_by_id` (RULES: the newborn is placed next to the parent on the
    action space). Parameter-free — its only action is CommitFamilyGrowth. Pushed
    today by PendingBasicWishForChildren; reusable by any future space/card that
    grants family growth. Mirrors PendingRenovate (a single-commit primitive).

    A uniform commit-terminated sub-action HOST (SUBACTION_HOOK_REFACTOR.md):
    `phase` flips "before"->"after" at CommitFamilyGrowth (no auto-pop), firing
    `after_family_growth` automatic effects; the after-phase offers
    `after_family_growth` triggers + Stop. Card-only frame: never reaches the
    C++ (Family) engine. Event derived `<phase>_family_growth`."""
    PENDING_ID: ClassVar[str] = "family_growth"
    player_idx: int
    initiated_by_id: str
    phase: str = "before"               # "before" | "after"
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
      - Each CommitHarvestConversion fires a craft: pays input_cost and adds
        food_out to supply (no food_owed bookkeeping). Declining a craft is
        implicit — commit CommitConvert without firing it.
      - CommitConvert is the sole payment site: pays `min(need, food_in_supply
        + food_produced)` to feeding; surplus stays in supply; any shortfall
        becomes begging markers. Sets `conversion_done=True`.
      - Stop is legal only after `conversion_done=True`.

    "Fired" conversion ids live on PlayerState.harvest_conversions_used,
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


@dataclass(frozen=True)
class PendingActionSpace:
    """Generic action-space host frame for ATOMIC spaces (card game only).

    An atomic space (Forest, Clay Pit, Grain Seeds, …) stays atomic — no frame
    pushed — until a card may fire on it; then `_apply_place_worker` pushes THIS
    frame instead of running the atomic effect directly. Non-atomic spaces are
    already host frames (PendingCattleMarket, …) and do NOT use this class.

    Lifecycle (CARD_IMPLEMENTATION_PLAN.md II.2): pushed in the "before" phase
    (before-automatic-effects fire at push, before-triggers are surfaced as
    FireTrigger) → Proceed applies ATOMIC_HANDLERS[space_id] and flips to "after"
    (after-automatic-effects fire, after-triggers are surfaced) → Stop pops.

    `space_id` is read off `initiated_by_id` ("space:forest" → "forest"), the
    same uniform accessor the non-atomic host frames will gain, so a card's
    eligibility reads `top.space_id` without an isinstance check. The trigger
    event derives via the action_space bucket (legality.trigger_event), so this
    frame carries no per-instance TRIGGER_EVENT.

    Default empty/inert: only constructed in card games with a hooking card, so
    the Family game never produces it and the C++ Family engine never sees it.
    """
    PENDING_ID: ClassVar[str] = "action_space"
    player_idx: int
    initiated_by_id: str                       # "space:<id>"
    phase: str = "before"                      # "before" | "after"
    triggers_resolved: frozenset = frozenset()  # frozenset[str], card_ids fired this host-visit

    @property
    def space_id(self) -> str:
        return self.initiated_by_id.split(":", 1)[1]


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
    PendingActionSpace,
]


# PENDING_IDs (frame ids, NOT space ids) of the action-space HOST frames — the
# generic atomic host plus every non-atomic per-space parent. They share the
# coarse before_/after_action_space event (legality.trigger_event) and are the
# frames at whose Stop the engine fires after_action_space automatic effects
# (CARD_IMPLEMENTATION_PLAN.md II.2 / 4b). Multi-shot sub-action frames
# (build_stables/_rooms/_fences) are deliberately NOT here — their Stop pops a
# sub-action, not the space. Lives here (with the frames) so both legality and
# engine import it.
ACTION_SPACE_PENDING_IDS: frozenset = frozenset({
    "action_space", "farm_expansion", "farmland", "side_job", "grain_utilization",
    "sheep_market", "pig_market", "cattle_market", "major_minor_improvement",
    "house_redevelopment", "cultivation", "farm_redevelopment", "fencing",
})


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
