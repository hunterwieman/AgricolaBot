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
from agricola.resources import Animals, Cost, Resources

if TYPE_CHECKING:
    from agricola.actions import Action
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

    @property
    def subaction_started(self) -> bool:
        """Proceed-host before-window signal (SPACE_HOST_REFACTOR.md §5.1): True once
        any base sub-action has been chosen. `before_action_space` triggers are offered
        only while this is False — taking the space's work closes the before-window."""
        return self.sow_chosen or self.bake_chosen


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
    # Card-only: a granted PARTIAL sow ("for each newborn, you can sow crops in
    # exactly 1 field" — Fodder Planter pushes max_fields = newborn count) caps
    # the commit at grain+veg <= max_fields. 0 = uncapped — every Family sow and
    # the full granted "Sow" action (Slurry Spreader C71) — so it is a
    # Family-constant default → canonical-skip field, no C++ change.
    # With card-fields, a card consumes exactly ONE field-unit of the cap
    # however many stacks the commit fills on it (user ruling 48, 2026-07-12).
    max_fields: int = 0
    # Card-only (user ruling 48, 2026-07-12 — the sow-grant lexicon): True for
    # a CROPS-EXPLICIT grant ("sow crops" — Fodder Planter; officially may NOT
    # plant onto Wood Field), excluding wood/stone card-field sows from the
    # enumeration. False (generic) for the action-space sows and every bare
    # "Sow" grant, capped or not (Chief Forester's clarification permits wood).
    # Family-constant False → canonical-skip field, no C++ change.
    crops_only: bool = False
    # Work-complete signal for the DEFERRED after-flip (user ruling 2026-07-14:
    # "after you [do X]" effects fire after X's FULL effect, pushed frames
    # included). The commit executor sets this instead of flipping inline;
    # _advance_until_decision flips the host to its after-phase (firing the
    # after-autos) once the host is back on top — i.e. after every frame the
    # effect pushed has resolved. Cleared at the flip, so True only survives a
    # step while effect-pushed children are up. Family-REACHABLE there (the
    # ovens' free bake on PendingBuildMajor), so it is emitted when True
    # (canonical-skipped at the default False) and mirrored by the C++ engine.
    # Carried by every commit-terminated host (this comment is the reference).
    effect_initiated: bool = False


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
    effect_initiated: bool = False      # deferred after-flip signal (see PendingSow)


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
    # Card-only: a granted plow that precedes a mandatory base plow (e.g. Moldboard Plow
    # on Farmland) sets this so its cell choice is restricted to cells that leave the base
    # plow legal (legality.safe_plow_cells). Always False in the Family game (base plows
    # and Cultivation plows), so it is a default canonical-skip field — no C++ change.
    must_preserve_base: bool = False
    # Card-only: a granted MULTI-SHOT plow (Swing/Turnwrest/Wheel Plow's "plow up to N
    # fields") commits up to `max_plows` cells from one grant, one CommitPlow each, before
    # flipping to the after-phase / popping. `num_plowed` counts commits so far. The
    # default (max_plows=1, num_plowed=0) is the single-shot plow — every Family plow and
    # the single-grant plow cards — so the granted plow flips to after on its first commit,
    # byte-identical to before. Both are Family-constant defaults → canonical-skip fields,
    # no C++ change.
    max_plows: int = 1
    num_plowed: int = 0
    effect_initiated: bool = False      # deferred after-flip signal (see PendingSow)


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

    @property
    def space_id(self) -> str:
        return self.initiated_by_id.split(":", 1)[1]

    @property
    def subaction_started(self) -> bool:
        """Proceed-host before-window signal (SPACE_HOST_REFACTOR.md §5.1): True once
        any base sub-action has been chosen; `before_action_space` triggers are offered
        only while this is False."""
        return self.room_chosen or self.stable_chosen


@dataclass(frozen=True)
class PendingBuildStables:
    """Multi-shot sub-action HOST for stable construction.

    Pushed by `_choose_subaction_*` handlers when the player enters the
    build-stables category. Holds the per-commit `cost: Resources` and a
    caller-imposed cap `max_builds: int | None` (None = no cap; Side Job
    sets 1; Farm Expansion sets None). `num_built` increments on each commit.

    A uniform before/after host (SUBACTION_HOOK_REFACTOR.md), like the
    single-commit sub-actions but with the work-complete signal made explicit:
    in the `before` phase the player commits stables (and before-triggers may
    fire), then `Proceed` (legal once num_built >= 1) flips to `after` — firing
    `after_build_stables` automatic effects — where after-triggers + `Stop` are
    legal and `Stop` pops. Multi-shot has no single commit to flip on (unlike
    Sow/Bake/Plow, which flip on their commit), so `Proceed` is that explicit
    signal, exactly as for the and/or space hosts. `triggers_resolved` tracks
    fired triggers per the host family. (NN: Proceed is relabeled to Stop and the
    trailing Stop is a singleton, so the policy/MCTS view is unchanged — §9.)
    """
    PENDING_ID: ClassVar[str] = "build_stables"
    player_idx: int
    initiated_by_id: str
    cost: Resources
    max_builds: int | None
    num_built: int = 0
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()
    build_stables_action: bool = True   # literal Build Stables action vs a card effect that builds (§9.6); default-True canonical skip-field → Family byte-identical, no C++


@dataclass(frozen=True)
class PendingBuildRooms:
    """Multi-shot sub-action HOST for room construction.

    Same shape and uniform before/after host lifecycle as PendingBuildStables
    (see there): `before`-phase room commits + before-triggers, then `Proceed`
    (num_built >= 1) flips to `after` firing `after_build_rooms` autos, then
    after-triggers + `Stop` pops. `max_builds=None` from Farm Expansion.

    The room cost is NOT stored on this frame — it is resolved per room through the
    cost-modifier chokepoint `effective_payments` (base `ROOM_COSTS[house_material]`),
    so a cost card can reduce / convert / discount the Nth room without a stale cache
    (COST_MODIFIER_DESIGN.md §3.3). `_execute_build_room` debits the singleton frontier
    point directly, or — when a card offers >1 payment — pushes `PendingChooseCost`.
    """
    PENDING_ID: ClassVar[str] = "build_rooms"
    player_idx: int
    initiated_by_id: str
    max_builds: int | None
    num_built: int = 0
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()
    build_rooms_action: bool = True     # literal Build Rooms action vs a card effect that builds (§9.6); default-True canonical skip-field → Family byte-identical, no C++


@dataclass(frozen=True)
class PendingBuildMajor:
    """Sub-action pending for Major Improvement purchase.

    A uniform commit-terminated sub-action HOST (SUBACTION_HOOK_REFACTOR.md):
    the commit sets `effect_initiated` and the DEFERRED flip (user ruling
    2026-07-14) fires in _advance_until_decision once this frame is back on top
    — so for an oven major the free-bake wrapper fully resolves BEFORE the flip
    (and its `after_build_major` autos); the frame then offers its after-phase
    triggers + Stop. For a non-oven major nothing is pushed, so the flip lands
    within the same step. `phase=="after"` replaces the old `build_chosen` flag
    (they were exactly redundant). Event derived `<phase>_build_major` — no
    per-frame TRIGGER_EVENT.

    Cost is NOT on this pending — it's keyed off `commit.major_idx` and
    looked up in `MAJOR_IMPROVEMENT_COSTS`.
    """
    PENDING_ID: ClassVar[str] = "build_major"
    player_idx: int
    initiated_by_id: str
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()
    effect_initiated: bool = False      # deferred after-flip signal (see PendingSow)


@dataclass(frozen=True)
class PendingRenovate:
    """Sub-action pending for house renovation.

    The renovation cost is NOT stored on this frame. It is derived on demand from
    the player (one of the next material per room + 1 reed) and resolved through the
    cost-modifier chokepoint `effective_payments`; the chosen `PaymentOption` rides
    on `CommitRenovate.payment`, which `_execute_renovate` debits
    (COST_MODIFIER_DESIGN.md §3.3 — the old stored `cost` was a cache of a derived
    value that goes stale once cost cards make it depend on owned cards).

    A uniform commit-terminated sub-action HOST (SUBACTION_HOOK_REFACTOR.md):
    `phase` flips "before"->"after" at CommitRenovate (no auto-pop), firing
    `after_renovate` automatic effects; the after-phase offers `after_renovate`
    triggers (e.g. Mining Hammer's free stable) + Stop. Event derived
    `<phase>_renovate` — no per-frame TRIGGER_EVENT.
    """
    PENDING_ID: ClassVar[str] = "renovate"
    player_idx: int
    initiated_by_id: str
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()
    effect_initiated: bool = False      # deferred after-flip signal (see PendingSow)


@dataclass(frozen=True)
class PendingChooseCost:
    """Payment-selection frame for a two-step build (card game only).

    Pushed on top of a build host (`PendingBuildRooms` / `PendingBuildStables`) by
    that build's effect when the cost-modifier chokepoint surfaces MORE THAN ONE
    payment for the geometry just committed — the cell is already placed, so the only
    remaining decision is which payment to make. Its enumerator offers one
    `CommitChooseCost` per entry of `payments`; that commit debits the chosen payment
    and pops this frame, returning to the build host for the next build / Stop.
    Singleton frontiers skip this frame entirely (the build debits its one payment
    inline), so it never arises in the Family game (COST_MODIFIER_DESIGN.md §3.7).

    Not a host: no card triggers fire on "choosing a cost", so there is no
    before/after phase or `triggers_resolved` — just the frozen `payments` frontier.
    `initiated_by_id` is the build host's PENDING_ID, for provenance. `action_kind` is the
    cost-modifier action kind of the underlying build (e.g. "build_room"), so the commit
    can record per-action conversion-budget usage (Millwright) against the right cards.
    """
    PENDING_ID: ClassVar[str] = "choose_cost"
    player_idx: int
    initiated_by_id: str
    payments: tuple                      # tuple[PaymentOption, ...], frozen at push
    action_kind: str                     # cost-modifier action kind, e.g. "build_room"


@dataclass(frozen=True)
class PendingSubActionSpace:
    """Generic action-space host for a space with exactly ONE mandatory
    sub-action — a Delegating host (SPACE_HOST_REFACTOR.md §4.2/§5). Replaces the
    old per-space PendingFarmland / PendingFencing classes; the specific child is
    dispatched by `space_id` (read off `initiated_by_id`):
      farmland          -> PendingPlow
      fencing           -> PendingBuildFences
      major_improvement -> PendingMajorMinorImprovement
      lessons           -> PendingPlayOccupation   (card-only)

    Lifecycle: pushed in the before-phase (firing before_action_space autos). The
    before-phase offers any before_action_space triggers + the single
    `ChooseSubAction(name=…)`, which sets `subaction_complete=True` and pushes the
    child. When the child pops, `_advance_until_decision`'s Delegating auto-advance
    (keyed on the DELEGATING marker + `subaction_complete && phase=="before"`)
    flips this frame to its after-phase and fires after_action_space autos; the
    after-phase offers after-triggers + Stop, and Stop pops. There is no Proceed —
    the single mandatory sub-action's completion is the work-complete boundary,
    detected by the engine (an auto-advance, never a player decision).

    Shares `PENDING_ID = "action_space"` and the action_space event with
    PendingActionSpace (both are in ACTION_SPACE_PENDING_IDS); the class is the
    dispatch key, so sharing the id is safe.
    """
    PENDING_ID: ClassVar[str] = "action_space"
    DELEGATING: ClassVar[bool] = True   # opt into the auto-advance (§5)
    player_idx: int
    initiated_by_id: str                       # "space:<id>"
    subaction_complete: bool = False
    phase: str = "before"               # "before" | "after"
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

    @property
    def subaction_started(self) -> bool:
        """Proceed-host before-window signal (SPACE_HOST_REFACTOR.md §5.1): True once
        any base sub-action has been chosen; `before_action_space` triggers are offered
        only while this is False."""
        return self.plow_chosen or self.sow_chosen


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
    effect_initiated: bool = False      # deferred after-flip signal (see PendingSow)

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
    effect_initiated: bool = False      # deferred after-flip signal (see PendingSow)

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
    effect_initiated: bool = False      # deferred after-flip signal (see PendingSow)

    @property
    def space_id(self) -> str:
        return self.initiated_by_id.split(":", 1)[1]


@dataclass(frozen=True)
class PendingMajorMinorImprovement:
    """The composite "build a major OR play a minor" action — a Delegating host
    (SPACE_HOST_REFACTOR.md §4.2/§6). Pushed by the Major Improvement space (via
    PendingSubActionSpace's `improvement` choose) AND reused as House
    Redevelopment's optional second step, so its hook lives on a frame shared
    across those entry points.

    It fires the `major_minor_improvement` event (NOT `action_space`), so it is
    deliberately OUT of ACTION_SPACE_PENDING_IDS — under House Redevelopment that
    keeps it from firing a second after_action_space on top of House
    Redevelopment's own.

    Lifecycle: its single `ChooseSubAction("build_major" | "play_minor")` sets the
    matching `*_chosen` flag and pushes the child primitive. The three-way
    distinction (renovate-then-no / minor / major) is load-bearing for future
    cards (Cabbage Buyer), so the flags are kept; `subaction_complete` is derived
    as `major_chosen or minor_chosen`. When the child pops, the Delegating
    auto-advance flips `phase` to "after" (firing after_major_minor_improvement
    autos); the after-phase offers after-triggers + Stop, and Stop pops.
    """
    PENDING_ID: ClassVar[str] = "major_minor_improvement"
    DELEGATING: ClassVar[bool] = True   # opt into the auto-advance (§5)
    player_idx: int
    initiated_by_id: str
    major_chosen: bool = False
    minor_chosen: bool = False
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()

    @property
    def subaction_complete(self) -> bool:
        """The Delegating work-complete signal (§5.2): the composite action ran
        iff a major was built or a minor was played."""
        return self.major_chosen or self.minor_chosen


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

    @property
    def space_id(self) -> str:
        return self.initiated_by_id.split(":", 1)[1]

    @property
    def subaction_started(self) -> bool:
        """Proceed-host before-window signal (SPACE_HOST_REFACTOR.md §5.1): True once
        any base sub-action has been chosen; `before_action_space` triggers are offered
        only while this is False."""
        return self.renovate_chosen or self.improvement_chosen


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
class FenceRestrictions:
    """A restricted-grant geometry descriptor on PendingBuildFences (COST_MODIFIER_DESIGN.md
    §9.8). A small, hashable, serializable structure (NOT a callback — that would break the
    frame's hash / canonical JSON) the legal-pasture enumerator filters by. Default (all
    None/False) = unrestricted = a normal Build Fences action.

    Mini Pasture = `FenceRestrictions(exact_size=1, forbid_subdivision=True, max_pastures=1)`
    (a new 1×1 enclosure, never a subdivision, exactly one). "Adjacent to an existing pasture"
    needs no field — `_check_entry_legal`'s adjacency rule already requires a non-subdivision
    new pasture to touch an existing one when any exist (owner ruling, §9.8)."""
    max_pastures: int | None = None       # cap the action's commit count (Mini Pasture = 1)
    exact_size:   int | None = None       # require this many cells per pasture (Mini Pasture = 1)
    forbid_subdivision: bool = False      # only NEW enclosures, never a split of an existing pasture


@dataclass(frozen=True)
class PendingBuildFences:
    """Multi-shot sub-action HOST for fence building.

    Pushed when the player enters the build_fences category — Fencing (via the
    generic delegating space host) and Farm Redevelopment — and by future card
    effects. Each `CommitBuildPasture` names one pasture cell-set; the effect
    function debits wood for the new fence edges and increments the counters below.

    A uniform before/after host (SUBACTION_HOOK_REFACTOR.md), like the other
    multi-shot builders `PendingBuildStables` / `PendingBuildRooms`: in the
    `before` phase the player commits pastures (and `before_build_fences` triggers
    may fire), then `Proceed` (legal once `pastures_built >= 1`) flips to `after` —
    firing `after_build_fences` automatic effects via `_enter_after_phase` — where
    after-triggers + `Stop` are legal and `Stop` pops. Multi-shot has no single
    commit to flip on (unlike Sow/Bake/Plow, which flip on their commit), so
    `Proceed` is that explicit signal, exactly as for the and/or space hosts.
    (NN: Proceed is relabeled to Stop for the `fencing` head + combiners and the
    trailing Stop is a singleton, so the policy/MCTS view is unchanged.)

    State fields:
      - `pastures_built`: number of CommitBuildPasture commits landed so far.
        Proceed-legality requires `pastures_built >= 1`.
      - `fences_built`: total fence-edges placed across all commits. Carries
        forward for card patterns like "each time you build N fences ≥ current
        round, get 1 vegetable".
      - `subdivision_started`: flips True the first time a subdivision commit
        lands. Implements the builds-before-subdivisions ordering rule
        (TASK_6.md Part 2.3): once a subdivision has happened, new-pasture
        commits are no longer offered in the enumerator.

    The matching `CommitBuildPasture` handler never pops: each commit replaces
    the top with updated counters and leaves the pending in the before-phase;
    `Proceed` flips to after, `Stop` pops.

    Deferred-tally fields (COST_MODIFIER_DESIGN.md §9.2 — the Cards-only payment
    model). In the Family game these always hold their defaults (Family debits
    per-commit, never accruing), so they are default canonical skip-fields and the
    Family JSON / C++ engine are untouched:
      - `accrued_cost`: in CARDS mode, the running wood owed (after per-action
        frees) across all this action's pasture commits — debited once at the
        Proceed settle through `effective_payments`. Family never sets it.
      - `free_fence_budget`: the generic per-action free-fence allowance (§9.4
        source 2), seeded at the `before_build_fences` host (e.g. Hedge Keeper +3)
        and decremented as it covers paid edges. Dies with the frame. Family
        never seeds it.
    """
    PENDING_ID: ClassVar[str] = "build_fences"
    player_idx: int
    initiated_by_id: str
    pastures_built: int = 0
    fences_built: int = 0
    subdivision_started: bool = False
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()
    build_fences_action: bool = True    # literal Build Fences action (Fencing / Farm Redev) vs a card effect that fences (§9.6); default-True canonical skip-field → Family byte-identical, no C++
    accrued_cost: Resources = Resources()  # Cards deferred-tally: running wood owed, settled at Proceed (§9.2); default → Family byte-identical skip-field, no C++
    free_fence_budget: int = 0          # Cards per-action free-fence allowance (Hedge Keeper +3, §9.4); default → Family byte-identical skip-field, no C++
    restrictions: "FenceRestrictions" = FenceRestrictions()  # restricted-grant geometry (Mini Pasture, §9.8); default unrestricted → Family byte-identical skip-field, no C++


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

    @property
    def space_id(self) -> str:
        return self.initiated_by_id.split(":", 1)[1]

    @property
    def subaction_started(self) -> bool:
        """Proceed-host before-window signal (SPACE_HOST_REFACTOR.md §5.1): True once
        any base sub-action has been chosen; `before_action_space` triggers are offered
        only while this is False."""
        return self.renovate_chosen or self.build_fences_chosen


@dataclass(frozen=True)
class PendingPlayOccupation:
    """Play one occupation from hand into the tableau (card game only).

    Pushed by Lessons (and later Scholar / card grants). It is its own host —
    there is no separate sub-action below it: one `CommitPlayOccupation` plays
    exactly one occupation, then this frame pops. `cost` is the food cost of THIS
    play, set at push time (route-dependent — Lessons: `occupation_cost(...)`;
    Scholar: 1 food); `_execute_play_occupation` reads it and debits.

    A uniform commit-terminated sub-action HOST (SUBACTION_HOOK_REFACTOR.md):
    the commit sets `effect_initiated` and the DEFERRED flip (user ruling
    2026-07-14) fires in _advance_until_decision once this frame is back on top
    — so the `after_play_occupation` autos fire only after the occupation's
    on-play (and anything it pushed) has fully resolved; the after-phase then
    offers `after_play_occupation` triggers (e.g. Bread Paddle's free bake) +
    Stop. Card-only frame: never reaches the C++ (Family) engine. Event derived
    `<phase>_play_occupation`.
    """
    PENDING_ID: ClassVar[str] = "play_occupation"
    player_idx: int
    initiated_by_id: str
    cost: Resources = Resources()
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()
    # The card just played — stamped by the executor at the commit, BEFORE the
    # flip, so after_play_occupation autos/triggers can read WHICH card landed
    # (Clutterer's text-filtered count). None during the before-phase. Card-only
    # frame, so no canonical/C++ concern.
    played_card_id: str | None = None
    effect_initiated: bool = False      # deferred after-flip signal (see PendingSow)


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
    the commit sets `effect_initiated` and the DEFERRED flip (user ruling
    2026-07-14) fires in _advance_until_decision once this frame is back on top
    — so the `after_play_minor` autos (and the coarse `after_build_improvement`)
    fire only after the minor's on-play (and anything it pushed) has fully
    resolved; the after-phase then offers `after_play_minor` triggers + Stop.
    Card-only frame: never reaches the C++ (Family) engine. Event derived
    `<phase>_play_minor`.
    """
    PENDING_ID: ClassVar[str] = "play_minor"
    player_idx: int
    initiated_by_id: str
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()
    # The card just played — stamped by the executor at the commit, BEFORE the
    # flip, so after_play_minor autos/triggers can read WHICH card landed
    # (Clutterer's text-filtered count; a traveling minor is stamped too, though
    # it has already been passed on). None during the before-phase. Card-only
    # frame, so no canonical/C++ concern.
    played_card_id: str | None = None
    effect_initiated: bool = False      # deferred after-flip signal (see PendingSow)


@dataclass(frozen=True)
class PendingBasicWishForChildren:
    """Card-game parent frame for Basic Wish for Children — mirrors
    PendingHouseRedevelopment: a mandatory primary sub-action (family growth) then
    an optional follow-up (play 1 minor).

    A Proceed-host action-space frame (and-then; SPACE_HOST_REFACTOR.md §4.3):
    family growth is the mandatory first sub-action (no Proceed until it has run),
    then the optional minor, then Proceed. Proceed flips `phase` to "after" (firing
    after_action_space autos), the after-phase hosts after-triggers + Stop. Event
    derives via the action_space bucket (legality.trigger_event) — no per-frame
    TRIGGER_EVENT. `basic_wish_for_children` is in ACTION_SPACE_PENDING_IDS.

    The Family game keeps the atomic resolver and never pushes this frame.
    Card-only: never reaches the C++ (Family) engine.
    See CARD_IMPLEMENTATION_PLAN.md.
    """
    PENDING_ID: ClassVar[str] = "basic_wish_for_children"
    player_idx: int
    initiated_by_id: str
    family_growth_done: bool = False
    minor_chosen: bool = False
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()

    @property
    def space_id(self) -> str:
        return self.initiated_by_id.split(":", 1)[1]

    @property
    def subaction_started(self) -> bool:
        """Proceed-host before-window signal (SPACE_HOST_REFACTOR.md §5.1): True once
        any base sub-action has been chosen (the mandatory growth or the optional
        minor); `before_action_space` triggers are offered only while this is False."""
        return self.family_growth_done or self.minor_chosen


@dataclass(frozen=True)
class PendingMeetingPlace:
    """Card-game Meeting Place follow-up — a single-optional Proceed-host
    (SPACE_HOST_REFACTOR.md §7). Become starting player is an IMMEDIATE effect
    (applied in the resolver, no frame — it always happens and triggers no cards),
    so this frame hosts only the ONE OPTIONAL minor.

    A Proceed-host action-space frame: the before-phase offers any
    before_action_space triggers + ChooseSubAction("play_minor") (while not yet
    played) + `Proceed` — and `Proceed` is legal FROM THE START (it *is* the
    decline, since the SP token was already taken). Proceed flips `phase` to
    "after" (firing after_action_space autos), the after-phase hosts after-triggers
    + Stop, and Stop pops. `meeting_place` is in ACTION_SPACE_PENDING_IDS, so the
    event derives via the action_space bucket (legality.trigger_event).

    Pushed (card mode only) right after become-SP, and ALWAYS pushed — even when no
    minor is playable (the before-phase is then just before-triggers + Proceed), so
    that cards hooking the space via before_/after_action_space still fire. This is
    the SOLE host for card-mode Meeting Place: `engine._apply_place_worker` dispatches
    the space directly to its handler ahead of the generic atomic-host wrapper, so it
    is never double-hosted (a redundant PendingActionSpace wrapper over this pushing
    handler soft-locks the turn). Card-only: the Family Meeting Place is the atomic
    food/SP resolver and never pushes this, so it never reaches the C++ engine.
    See CARD_IMPLEMENTATION_PLAN.md I.3.
    """
    PENDING_ID: ClassVar[str] = "meeting_place"
    player_idx: int
    initiated_by_id: str
    minor_chosen: bool = False
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()

    @property
    def space_id(self) -> str:
        return self.initiated_by_id.split(":", 1)[1]

    @property
    def subaction_started(self) -> bool:
        """Proceed-host before-window signal (SPACE_HOST_REFACTOR.md §5.1): True once
        the one optional base sub-action (the minor) has been chosen. Become-SP happens
        at push (before this frame exists), so the minor is the only orderable work;
        `before_action_space` triggers are offered only while this is False."""
        return self.minor_chosen


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
    C++ (Family) engine. Event derived `<phase>_family_growth`.

    `place_on_space=False` is the CARD-GRANTED growth (user ruling, recorded in
    CARD_DEFERRED_PLANS.md Group A1): a growth granted by a card places the
    newborn on NO action space — the commit increments people_total/newborns for
    the frame's `player_idx` without touching the board (there is no valid space
    id a "card:<id>" grant could name; a real one would falsely plant a meeple
    visible to worker-scanning cards). The room gate (people_total < 5 and
    < rooms) is the CALLER's eligibility check, not the primitive's — exactly as
    for the space path. Default True (the wish-space behavior) — every existing
    pusher is unchanged."""
    PENDING_ID: ClassVar[str] = "family_growth"
    player_idx: int
    initiated_by_id: str
    phase: str = "before"               # "before" | "after"
    triggers_resolved: frozenset = frozenset()
    place_on_space: bool = True
    effect_initiated: bool = False      # deferred after-flip signal (see PendingSow)


@dataclass(frozen=True)
class PendingFoodPayment:
    """Raise food to cover a card-game food cost, then resume the action it serves
    (FOOD_PAYMENT_DESIGN.md §3). Pushed at execution when a chosen cost needs more food than
    is on hand; its enumerator offers the `food_payment_frontier` of crops/animals-to-food
    conversion bundles (one CommitFoodPayment each), and `_execute_food_payment` applies the
    chosen bundle, pops this frame, and dispatches the resume.

    **Raise-only, not raise-and-debit.** The frame only *produces* food (banking any overshoot)
    until supply covers `food_needed`; it does NOT debit. The resumed action debits the full
    cost itself, from the now-sufficient supply — so one uniform mechanism serves both a
    re-run of a cost-paying commit (the resumed executor debits) and a card grant (its resume
    debits). `owe = food_needed - p.resources.food` is recomputed live, never stored (CLAUDE.md
    Foundations, Derived data not cached).

    **`reserved`** names the goods the conversion must NOT consume — the convertible part of
    the cost the resumed action will itself debit (a minor's grain/veg/animal cost; a major's
    building resources). Without it the frame could cook a good the cost still needs and
    double-spend it (FOOD_PAYMENT_DESIGN.md §5). The enumerator runs the frontier over
    `(player goods − reserved)`, so a reserved good is never offered as fuel. (This is the
    execution-time twin of the affordability gate's `reserved_animals`.)

    **Resume as DATA** (a frozen / hashable / JSON-serializable frame can't hold a closure):
    `resume_kind == "rerun"` re-dispatches the stored `action` (a `Commit*`) through the normal
    handler table — the unified path for play-minor / play-occupation / build-major and future
    food-bearing builds; any other `resume_kind` is a card id with a registered grant
    continuation (Ox Goad → plow). Card-only frame: never reaches the C++ (Family) engine."""
    PENDING_ID: ClassVar[str] = "food_payment"
    player_idx: int
    food_needed: int
    resume_kind: str
    reserved: Cost = Cost()
    action: "Action | None" = None


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

    The frame hosts card triggers in BOTH of its stretches (card game only;
    `breed_chosen` is the phase discriminator):

    - **Before CommitBreed — event `"breeding"`** (user ruling 20,
      2026-07-05): in-breeding-phase card effects that do not depend on the
      breeding outcome (Stone Importer's priced stone buy) are offered
      BEFORE the breed decision, never after. Firing one leaves the frame up
      (CommitBreed still to come).
    - **After CommitBreed, before Stop — event `"breeding_outcome"`**:
      effects that react to WHICH newborns were just placed (Fodder Planter
      / Slurry Spreader C71's sow grants). The outcome payload travels as a
      round-keyed CardStore latch written by the card's own
      `register_breeding_outcome_auto` handler at the commit — the frame
      carries no payload field. Stop declines whatever is unfired.

    `triggers_resolved` is stamped by the generic FireTrigger dispatch and is
    shared across both events (card ids are unique). Family games push this
    frame every harvest but no card ever stamps it, so the field is
    Family-constant-default — canonical-skipped via the qualified entry
    "PendingHarvestBreed.triggers_resolved" (no C++ change).
    """
    PENDING_ID: ClassVar[str] = "harvest_breed"
    player_idx:      int
    initiated_by_id: str            # always "phase:harvest_breed"
    breed_chosen:    bool = False
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class PendingAccommodate:
    """Reconciliation frame: player `player_idx` holds more animals than their farm can
    house, because a DECISION-FREE grant (round-start collection, an on-play card gain)
    added animals past capacity via helpers.grant_animals.

    Pushed by engine._reconcile_accommodation — the accommodation barrier run at every
    decision boundary in _advance_until_decision — when a flagged player's animals do
    NOT fit. Hosts exactly one CommitAccommodate: the player chooses which animals to
    KEEP (one option per housable Pareto-frontier config over their current animals),
    and the excess is cooked to food at their cooking rates. Unlike the animal-market
    frames (PendingSheepMarket/…), this has NO before/after action-space lifecycle — it
    is a bare reconciliation, so CommitAccommodate POPS it (resolution._execute_accommodate
    branches on the frame type: markets pivot to their after-phase, this pops).

    Card-only: the Family game never grants animals decision-free, so this frame is never
    constructed and the Family trace / C++ engine never see it. No `triggers_resolved` /
    `TRIGGER_EVENT` yet (harvest-frame precedent) — it hosts no card hooks today.

    `min_keep` — a componentwise LOWER BOUND on the offered keep-configs: the enumerator
    drops every frontier point that keeps fewer than `min_keep` of any type. The default
    `Animals()` (no bound) is the barrier's unfiltered frame. A card that must house a
    specific just-gained animal (Automatic Water Trough's "If you can accommodate the
    animal, you can buy…") pushes this frame directly with `min_keep=<the purchase>`, so
    the choice can never discard the animal the purchase was conditioned on housing.
    Filtering the frontier is loss-less: dominance is over kept animal counts only, so
    a point satisfying the bound can only be dominated by another point that also
    satisfies it.
    """
    PENDING_ID: ClassVar[str] = "accommodate"
    player_idx:      int
    initiated_by_id: str = "reconcile:accommodate"
    min_keep:        Animals = Animals()


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
class PendingHarvestWindow:
    """Per-player choice host for one simple harvest timing window (card game only).

    The harvest is threaded with an ordered ladder of timing windows
    (`agricola/cards/harvest_windows.py`; design: HARVEST_WINDOWS_DESIGN.md) —
    "at the start of each harvest", "after the field phase", "at the end of each
    harvest", …. When the walk (`engine._advance_harvest`) reaches a simple window,
    its automatic effects fire mechanically (no frame); THIS frame is pushed only
    for a player with an eligible registered TRIGGER in that window, one frame per
    such player, starting player on top (the FEED/BREED push order).

    `window_id` names the window and doubles as the trigger event string — the
    enumerator surfaces the player's eligible, unfired triggers for that event
    (variant-expanded) plus `Proceed`, the decline / work-complete boundary that
    pops (a phase host with no before/after flip). Serves the harvest, round-end,
    AND preparation ladders — a window frame is this class with the ladder's
    window id.
    Mandatory-with-choice
    triggers gate Proceed off until fired, as everywhere else.

    Default-inert: no card registered on a window → the frame is never
    constructed; a Family (or windowless-card) harvest is byte-identical to the
    pre-ladder engine.
    """
    PENDING_ID: ClassVar[str] = "harvest_window"
    window_id: str
    player_idx: int
    initiated_by_id: str = "phase:harvest_window"
    triggers_resolved: frozenset = frozenset()


@dataclass(frozen=True)
class HarvestEntry:
    """One (source, crop) line of a harvest occasion's manifest: this harvesting
    event removed `amount` of `crop` from `source`. `emptied` records that it took
    the source's LAST crop — the fact per-emptied consequence cards (Slurry
    Spreader, Food Merchant's discount) key on. Sources are board fields today
    ("cell:r,c"); card-fields ("card:<id>") ride the same shape when they land
    (HARVEST_WINDOWS_DESIGN.md §6)."""
    source: str          # "cell:r,c" | "card:<id>"
    crop: str            # "grain" | "veg" (card-fields add e.g. "wood")
    amount: int
    emptied: bool


@dataclass(frozen=True)
class BreedingOutcome:
    """The payload of one player's breeding resolution: which newborns were
    actually PLACED (0/1 per type — a type breeds at most once). Computed at
    `resolution._execute_breed` with the engine's own kept-newborn indicator
    (pre >= 2 and post >= 3, the `breeding_food_gained` test) and handed to
    the `register_breeding_outcome_auto` consumers (Fodder Planter, Slurry
    Spreader C71, Champion Breeder [3+]). The clarification both consumer
    cards print — "You must be able to accommodate each newborn in order to
    get it" — is inherent here: an unaccommodated newborn is never placed, so
    it never appears in the outcome. NOT for Dung Collector ("each time you
    get 2+ newborn animals" counts ANY-source gains, markets included — the
    deliberately-out-of-scope wider event, HARVEST_HANDOFF.md §12)."""
    sheep: int
    boar: int
    cattle: int

    @property
    def total(self) -> int:
        return self.sheep + self.boar + self.cattle

    @property
    def types(self) -> int:
        return (self.sheep > 0) + (self.boar > 0) + (self.cattle > 0)


@dataclass(frozen=True)
class HarvestOccasion:
    """One harvesting OCCASION — the manifest of what a single harvesting event
    took, and from where (HARVEST_WINDOWS_DESIGN.md §4d).

    The field-phase take is one occasion (`source="take"` — it harvests every
    planted field simultaneously, user ruling 5); each fired card-granted
    additional harvest (Stable Manure, Scythe E73) is its own occasion
    (`source="card:<id>"`). Consequence cards read the manifest at the
    granularity their text names: "each time you harvest…" counts occasions,
    "for each X…" counts units within one (rulings 5-6). The occasion registries
    that consume this live in `agricola/cards/harvest_windows.py`."""
    source: str                            # "take" | "card:<id>"
    entries: tuple[HarvestEntry, ...]


@dataclass(frozen=True)
class PendingHarvestOccasion:
    """Per-occasion choice host (card game only): the player owns a card with
    an eligible OPTIONAL reaction to one just-emitted harvesting occasion
    (Potato Ridger's 3-veg exchange, Food Merchant's per-grain vegetable buys
    — HARVEST_WINDOWS_DESIGN.md §4d, the trigger half of the occasion
    registries).

    Pushed by `apply_harvest_occasion_autos` right after the occasion's
    automatic consequences fire — wherever the occasion was emitted: the
    walk's inline take, a `CommitFieldTake` at the FIELD during-frame (this
    frame then sits on top of that host), or a bare card-driven `field_take`
    (Bumper Crop, mid-WORK — the frame stacks above the firing frame like any
    card sub-decision). The `occasion` payload rides the frame so trigger
    eligibility/variants/apply read exactly the event they react to; Proceed
    declines whatever is unfired and pops.

    `autos_fired` records which per-occasion AUTOMATIC effects fired for this
    same occasion, so a two-tier card can keep its optional tier from
    double-reacting (user ruling 2026-07-05, Potato Ridger: at 4+ vegetables
    the exchange is AUTOMATIC — no player input — and having fired, the
    optional at-3 offer must not appear for the same occasion; "exactly 1
    vegetable" is once per occasion). A fact about this occasion's
    resolution, carried on the host — no card_state latch, nothing to go
    stale.

    Default-inert: no occasion trigger registered (the Family game, and every
    card game before the first member) → never constructed."""
    PENDING_ID: ClassVar[str] = "harvest_occasion"
    player_idx: int
    occasion: HarvestOccasion
    initiated_by_id: str = "phase:harvest_occasion"
    triggers_resolved: frozenset = frozenset()
    autos_fired: frozenset = frozenset()


@dataclass(frozen=True)
class PendingFieldPhase:
    """Per-player choice host for the FIELD during-window — harvest window #5,
    "field_phase" (card game only; HARVEST_WINDOWS_DESIGN.md §4).

    Pushed by the harvest walk's per-player FIELD band for a player with an
    eligible trigger registered on the "field_phase" event (Cube Cutter's
    exchange, Treegardener's buy, the additional-harvest grants). Unlike the
    simple-window host, this frame also OWNS the phase's mechanical work: the
    crop take rides it as a mandatory commit —

    - `CommitFieldTake` is legal while `take_fired` is False; it applies the
      shared take (`resolution.field_take`), records the take occasion here,
      and fires the per-occasion automatic effects. It does NOT pop — the
      window's free-order triggers stay available after the take.
    - `Proceed` (the exit) is withheld until `take_fired` — the take is
      mandatory — and by unfired mandatory triggers as everywhere else.
    - Triggers surface as ordinary FireTriggers in ANY order around the take
      (the during-window's free-order rule); take-MODIFIERS (Grain Thief's
      replacement, Scythe Worker's fold-in) gate on `take_fired` being False —
      firing the take implicitly declines every unfired modifier (§4b's
      one-way gate).

    `occasions` is the frame-scoped manifest log: the take occasion plus one
    per fired additional-harvest trigger, appended by `emit_harvest_occasion`.
    Per-occasion OPTIONAL triggers (Potato Ridger) will read it when they land;
    per-occasion autos consume each occasion at emit time and need no field.

    Default-inert: pushed only when a "field_phase" trigger is eligible — a
    Family game (or a card game with none owned) takes inline in the walk and
    never constructs this frame."""
    PENDING_ID: ClassVar[str] = "field_phase"
    player_idx: int
    take_fired: bool = False
    occasions: tuple[HarvestOccasion, ...] = ()
    initiated_by_id: str = "phase:field_phase"
    triggers_resolved: frozenset = frozenset()


# (PendingPreparation is GONE — the preparation ladder, ruling 54, 2026-07-14:
# start-of-round decisions now ride per-window PendingHarvestWindow choice hosts
# pushed by engine._advance_preparation, exactly like the harvest and round-end
# ladders; see agricola/cards/preparation.py.)


@dataclass(frozen=True)
class PendingCardChoice:
    """The forced-choice decision frame a mandatory-with-choice trigger pushes to
    surface its decision (card game only) — Seasonal Worker's grain/veg, Childless's
    crop, and any future "you must pick one of N" effect.

    Its legal actions are exactly the options (a `CommitCardChoice(index)` per
    option) with NO `Stop`/decline, so the player must pick one; a single-option
    frame auto-resolves via singleton-skip. The pushing card's resolver — keyed on
    the card id parsed off `initiated_by_id` ("card:<id>") in CARD_CHOICE_RESOLVERS
    — applies the chosen option and pops this frame.

    Card-only: never reaches the C++ (Family) engine. See CARD_IMPLEMENTATION_PLAN.md
    II.6.
    """
    PENDING_ID: ClassVar[str] = "card_choice"
    player_idx: int
    initiated_by_id: str                  # "card:<id>" — which card pushed it
    options: tuple = ()                   # tuple[Hashable, ...], e.g. ("grain", "veg")


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


@dataclass(frozen=True)
class PendingDraftPick:
    """Draft-pick decision: the active player selects one card from their pool.

    Pushed by engine._advance_until_decision during Phase.DRAFT when the
    stack is empty, once per card type per player per round. `player_idx`
    is who is picking; `card_type` is 'occupation' or 'minor'. The matching
    CommitDraftPick moves the card from the pool into the player's hand and
    pops this frame.

    No triggers_resolved — draft picks have no card hooks.
    Card-only: never reaches the C++ (Family) engine.
    """
    PENDING_ID: ClassVar[str] = "draft_pick"
    player_idx: int
    card_type: str   # "occupation" or "minor"


@dataclass(frozen=True)
class PendingGrantedSubAction:
    """An OPTIONAL granted sub-action (a card grant — Field Fences / Trellis grant a
    Build Fences; Dwelling Plan grants a Renovate).

    "You CAN take a '<sub-action>' action" — the optionality. This thin, generic PARENT host
    offers the choice (`ChooseSubAction(<subaction>)`) OR a decline (`Stop`), instead of forcing
    the sub-action (CARD_AUTHORING_GUIDE: granted sub-actions are optional; optionality lives at
    the parent's choose+Stop, never a per-frame flag on the inner host — so the inner
    primitive keeps its mandatory shape, and this wrapper is where declining lives). Choosing
    pushes the real primitive frame (`PendingBuildFences` / `PendingRenovate`) carrying THIS
    frame's `initiated_by_id`, so the grant's provenance — and any positional discount / seeded
    free-fence budget — applies. `Stop` pops: declining if nothing was taken, or finishing after
    the inner primitive has popped.

    This is the generic form of the pattern the delegating hosts already use — one frame with a
    discriminator (`PendingSubActionSpace` dispatches its child by `space_id`); here the
    discriminator is `subaction`, and the per-primitive eligibility + push live in the
    enumerator / choose-handler dispatch (legality/resolution), NOT in bespoke per-primitive
    frame classes. All primitive-specific STATE lives on the pushed child frame, so this wrapper
    stays field-free beyond the discriminator.

    - `subaction`: the granted primitive's id (`"build_fences"` | `"renovate"`), matched by the
      offered `ChooseSubAction(name=subaction)`.
    - `initiated_by_id`: the grant's provenance (e.g. `"card:field_fences"`).
    - `chosen`: flips True when the sub-action is entered, so it is offered at most once (after
      the inner primitive pops, only Stop remains).

    Card-only: never reaches the C++ (Family) engine.
    """
    PENDING_ID: ClassVar[str] = "granted_subaction"
    player_idx: int
    initiated_by_id: str
    subaction: str
    chosen: bool = False


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
    PendingChooseCost,
    PendingFarmExpansion,
    PendingSubActionSpace,
    PendingCultivation,
    PendingSideJob,
    PendingSheepMarket,
    PendingPigMarket,
    PendingCattleMarket,
    PendingMajorMinorImprovement,
    PendingHouseRedevelopment,
    PendingClayOven,
    PendingStoneOven,
    PendingBuildFences,
    PendingFarmRedevelopment,
    PendingGrantedSubAction,
    PendingPlayOccupation,
    PendingPlayMinor,
    PendingBasicWishForChildren,
    PendingMeetingPlace,
    PendingFamilyGrowth,
    PendingFoodPayment,
    PendingHarvestFeed,
    PendingHarvestBreed,
    PendingAccommodate,
    PendingReveal,
    PendingHarvestWindow,
    PendingFieldPhase,
    PendingCardChoice,
    PendingActionSpace,
    PendingDraftPick,
]


# PENDING_IDs (frame ids, NOT space ids) of the action-space HOST frames — the
# generic atomic/delegating host (PendingActionSpace + PendingSubActionSpace both
# share id "action_space") plus every non-atomic per-space parent. They share the
# coarse before_/after_action_space event (legality.trigger_event) and fire
# after_action_space automatic effects at their work-complete boundary
# (SPACE_HOST_REFACTOR.md §11). Multi-shot sub-action frames
# (build_stables/_rooms/_fences) are deliberately NOT here — their Proceed/Stop
# ends a sub-action, not the space. `major_minor_improvement` is deliberately NOT here
# either — it is the composite-action host firing its OWN
# major_minor_improvement event, not action_space (§6). `farmland` / `fencing`
# are gone — those spaces are now PendingSubActionSpace ("action_space").
# `side_job` is deliberately NOT here — Side Job is a Family-only, Stop-terminated
# non-host (PendingSideJob has no `phase` and carries its own bespoke
# `before_side_job` TRIGGER_EVENT); it is never a Proceed/atomic host, so it never
# reaches the bucket-keyed trigger_event / _apply_proceed paths. Lives here (with
# the frames) so both legality and engine import it.
ACTION_SPACE_PENDING_IDS: frozenset = frozenset({
    "action_space", "farm_expansion", "grain_utilization",
    "sheep_market", "pig_market", "cattle_market",
    "house_redevelopment", "cultivation", "farm_redevelopment",
    "meeting_place",           # card-only single-optional Proceed-host (§7)
    "basic_wish_for_children", # card-only and-then Proceed-host (follow-up to B1-B3)
})


# PENDING_IDs of the commit-terminated / multi-shot sub-action HOST frames — the
# hosts that carry a before/after `phase` and surface before/after triggers
# (SUBACTION_HOOK_REFACTOR.md). The before-automatic-effect firing at push gates
# on this set (engine._fire_subaction_before_auto): a frame whose just-pushed top
# has a PENDING_ID here fires its `before_<PENDING_ID>` autos (e.g. before_sow,
# before_renovate, before_build_rooms). It is DISJOINT from ACTION_SPACE_PENDING_IDS
# — those hosts fire `before_action_space` at push (engine._apply_place_worker) —
# and excludes `major_minor_improvement` (PendingMajorMinorImprovement is a
# composite host firing its own `before_major_minor_improvement`, not a sub-action
# leaf). The single-commit leaves flip to phase="after" on their commit; the
# multi-shot builders (`build_rooms`/`build_stables`/`build_fences`) flip on
# `Proceed` (no single commit to flip on; no Stop-terminated exception remains).
SUBACTION_PENDING_IDS: frozenset = frozenset({
    "sow", "bake_bread", "plow", "renovate", "build_major",
    "family_growth", "play_occupation", "play_minor",
    "build_rooms", "build_stables", "build_fences",
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
