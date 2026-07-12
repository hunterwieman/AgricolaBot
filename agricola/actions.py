from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from agricola.constants import HouseMaterial
from agricola.cost import PaymentOption


# ---------------------------------------------------------------------------
# Action types
# ---------------------------------------------------------------------------
#
# Flat tagged union: every action is its own frozen dataclass under the
# `Action` alias. Dispatched by `isinstance` in agricola/engine.py's
# `_apply_action`. See ENGINE_IMPLEMENTATION.md §1 (Engine structure &
# dispatch) for the design rationale.


@dataclass(frozen=True)
class PlaceWorker:
    """Place the active player's worker on an action space.

    For atomic spaces this is the entire action.
    For non-atomic spaces this initiates a chain of pending sub-decisions.
    """
    space: str   # action space ID, e.g. "forest", "grain_utilization"


@dataclass(frozen=True)
class ChooseSubAction:
    """Pick a sub-action category at a non-atomic space's pending decision.

    Categories are space-specific strings: e.g. "sow", "bake_bread" at
    Grain Utilization. The handler pushes the corresponding Pending* onto
    the stack.
    """
    name: str


@dataclass(frozen=True)
class CommitSubAction:
    """Marker base for all Commit* sub-action types.

    Empty by design — concrete commit dataclasses (CommitSow, CommitBake, …)
    inherit from this so `_apply_commit_subaction` in engine.py can dispatch
    them uniformly through the `COMMIT_SUBACTION_HANDLERS` table.
    """


@dataclass(frozen=True)
class CommitSow(CommitSubAction):
    """Commit a sow with specific grain and veg counts.

    `grain`/`veg` are the BOARD-field counts (cells are filled in canonical
    order — the fields are interchangeable, so counts suffice). `card_sows`
    is the card-field part (user rulings 45-48, 2026-07-12): a sorted tuple
    of (card_id, good) pairs, one per card-field stack sown this commit —
    goods include "wood"/"stone" on the cards that grow them. Family-constant
    `()` (no card-fields exist there), so it is skipped from the wire
    encoding at default (trace_replay.action_to_params) and the C++ engine
    is untouched."""
    grain: int
    veg: int
    card_sows: tuple = ()


@dataclass(frozen=True)
class CommitBake(CommitSubAction):
    """Commit a Bake Bread with the chosen grain amount."""
    grain: int


@dataclass(frozen=True)
class CommitPlow(CommitSubAction):
    """Commit a Plow at the chosen (row, col) cell."""
    row: int
    col: int


@dataclass(frozen=True)
class CommitBuildStable(CommitSubAction):
    """Commit a Build Stable at the chosen (row, col) cell.

    The cost paid is read from the host pending's `cost` field, not from
    this commit (the cost is determined by the caller that pushed
    `PendingBuildStables`, not by the agent at commit time).
    """
    row: int
    col: int


@dataclass(frozen=True)
class CommitBuildRoom(CommitSubAction):
    """Commit a Build Room at the chosen (row, col) cell.

    The cost paid is read from the host PendingBuildRooms' `cost` field
    (set at push time from `ROOM_COSTS[p.house_material]`). Each commit
    builds one room; the multi-shot session continues until the player
    explicitly Stops (the pending does not auto-pop).
    """
    row: int
    col: int


@dataclass(frozen=True)
class CommitBuildMajor(CommitSubAction):
    """Commit a Major Improvement purchase.

    A *wide* commit (COST_MODIFIER_DESIGN.md §3.4): `payment` is the chosen
    `PaymentOption` from the cost-modifier frontier `effective_payments` — either a
    `Resources` vector (the printed clay/etc. cost, or a card-reduced/converted
    variant) or, for Cooking Hearth (major_idx 2 or 3), a `ReturnImprovement(fp)`
    route that pays by returning a Fireplace (idx 0 or 1) you own instead of paying
    clay (§4.5). Replaces the old `return_fireplace_idx` field — a route is now just a
    `ReturnImprovement` payment.

    Dispatched via the generic commit dispatcher (registered in
    `COMMIT_SUBACTION_HANDLERS`), which never pops — the effect function
    `_execute_build_major` owns the stack manipulation: pop
    `PendingBuildMajor` for non-oven majors, or push
    `PendingClayOven` / `PendingStoneOven` for Clay/Stone Oven.
    """
    major_idx: int
    payment: PaymentOption


@dataclass(frozen=True)
class CommitRenovate(CommitSubAction):
    """Commit a renovation (all rooms at once), paying `payment`.

    `payment` is the chosen `PaymentOption` from the renovate frontier produced by
    `effective_payments` (COST_MODIFIER_DESIGN.md §3.2). Renovate is a *wide* action
    — its only degree of freedom is which payment to make — so the payment rides
    directly on the commit (no separate cost frame). In the Family game (no
    cost-modifier cards) the frontier is the singleton printed cost, so `payment` is
    that cost. `_execute_renovate` debits it. Renovate has no non-resource routes, so
    in practice `payment` is always a `Resources`, but the field is typed over the full
    `PaymentOption` union for uniformity with the other wide commits.

    `to_material` is the target tier of this renovation. Normally it is just the next
    tier (WOOD→CLAY, CLAY→STONE), but a card can make additional targets legal — e.g.
    Conservator lets a wood house renovate directly to STONE — so the *target* is a
    degree of freedom carried on the commit, and `_execute_renovate` upgrades to exactly
    `to_material` (rather than deriving the next tier). `payment` is the cost of reaching
    that target (COST_MODIFIER_DESIGN.md §3.2; the renovate-target model).
    """
    payment: PaymentOption
    to_material: HouseMaterial


@dataclass(frozen=True)
class CommitChooseCost(CommitSubAction):
    """Pick which payment to make for an in-progress build, at a `PendingChooseCost`
    frame — the two-step payment path for build-room / build-stable (card game only).

    Used when a cost-modifier card surfaces MORE THAN ONE payment for the same build
    geometry (e.g. Frame Builder's "pay the clay, or convert 2 clay → 1 wood"): the
    cell is already placed by the preceding `CommitBuildRoom` / `CommitBuildStable`,
    so the only remaining decision is which `payment` to make (COST_MODIFIER_DESIGN.md
    §3.7). `_execute_choose_cost` debits `payment` and pops the frame, returning to the
    build host. In the Family game the frontier is always a singleton, so this frame
    never arises (the build debits its one payment inline).
    """
    payment: PaymentOption


@dataclass(frozen=True)
class CommitFamilyGrowth(CommitSubAction):
    """Commit the family-growth primitive (add one newborn). Parameter-free —
    lands on PendingFamilyGrowth, which names the newborn's space via
    initiated_by_id. `_execute_family_growth` runs the growth and the dispatcher
    auto-pops the frame."""


@dataclass(frozen=True)
class CommitFieldTake(CommitSubAction):
    """Commit the field-phase crop take at a PendingFieldPhase host (card game
    only; HARVEST_WINDOWS_DESIGN.md §4b/§4c).

    The take is the FIELD during-window's own mandatory work — one singular
    event harvesting 1 crop from every planted field simultaneously (user
    ruling 5), WITH every take-modifier's contribution folded into that same
    event (user ruling 11: all field-phase harvesting is simultaneous — there
    is no separate during-phase harvesting occasion). It surfaces as an action
    only when the during-window is hosted (an eligible "field_phase" trigger,
    or a choice-bearing take-modifier); a frameless field phase takes inline
    in the harvest walk and never enumerates this.

    `modifiers` carries the player's chosen uses of their choice-bearing
    take-modifiers as (card_id, variant) pairs (Stable Manure's which-fields
    count vector; Grain Thief's replacement joins later) — the enumerator
    expands one CommitFieldTake per legal combination, the bare `()` being
    "use none of them" (each modifier is a "you can"). Auto fold-ins (Scythe
    Worker) need no pair — they apply to every real-harvest take.
    `_execute_field_take` applies the combined take, records the one take
    occasion on the frame (`take_fired=True`), and fires the per-occasion
    autos; the frame stays up (Proceed exits)."""
    modifiers: tuple = ()   # tuple[(card_id, variant), ...], enumeration-ordered


@dataclass(frozen=True)
class CommitPlayOccupation(CommitSubAction):
    """Play the named occupation from hand (card game).

    Lands on PendingPlayOccupation. The play cost is read from that frame's
    `cost` field (route-dependent), not from this commit. `_execute_play_occupation`
    moves the card hand->tableau, debits the cost, and runs the card's on-play
    effect; the dispatcher then auto-pops the frame.

    `variant` selects an on-play play-variant for occupations that register one
    (Roof Ballaster's pay-or-not choice; see specs.PLAY_OCCUPATION_VARIANTS). It is
    None for every ordinary occupation — the common, variant-less play — so two
    CommitPlayOccupations for the same card with different variants are distinct
    actions only when the card opts into the variant mechanism.
    """
    card_id: str
    variant: str | None = None


@dataclass(frozen=True)
class CommitPlayMinor(CommitSubAction):
    """Play the named minor improvement from hand (card game).

    Lands on PendingPlayMinor. This is a *wide* commit (COST_MODIFIER_DESIGN.md §3.4):
    `payment` is the chosen `PaymentOption` for the card's RESOURCE cost, from the
    cost-modifier frontier `effective_payments` — the printed cost when no cost card
    applies, or a reduced / converted variant otherwise. A minor's *animal* cost (if
    any) is not card-modifiable (the `PaymentOption` union is resource-only), so it is
    debited as printed, separately.

    `cost` names the chosen ALTERNATIVE for a "/"-cost minor (Chophouse "2 Wood / 2
    Clay"; MinorSpec.alt_costs): the full set of ways to pay is `(spec.cost,) +
    spec.alt_costs`, and each alternative is enumerated as its own CommitPlayMinor.
    `payment` (a Resources vector) already distinguishes the alternatives by their
    resource cost, so `cost` is only load-bearing for the alternative's ANIMAL portion,
    which `payment` cannot carry. `cost is None` (the default) means "use `spec.cost`" —
    the ordinary single-cost card. Because it defaults to None and minors are card-mode
    only, a Family state never carries a non-default value (byte-identity preserved).

    `_execute_play_minor` debits `payment` (resources) + the chosen alternative's animal
    cost, moves the card hand->tableau (or, for a traveling minor, passes it to the
    opponent), and runs its on-play effect; the dispatcher then auto-pops the frame.

    `variant` names the chosen route of a play-variant minor (specs.
    PLAY_MINOR_VARIANTS — the minor analog of Roof Ballaster/Baker's occupation
    mechanism, built for Facades Carving's on-play food-for-points choice, user
    ruling 2026-07-06): the variant's SURCHARGE is already folded into `payment`
    (so the debit and the food-shortfall guard need no special handling), and its
    BENEFIT is granted by the card's variant-aware on_play. None (the default) =
    an ordinary minor; minors are card-mode only, so a Family state never carries
    this action at all.
    """
    card_id: str
    payment: PaymentOption
    cost: object | None = None  # chosen alternative Cost (animal portion); None -> spec.cost
    variant: str | None = None  # chosen play-variant route (PLAY_MINOR_VARIANTS)


@dataclass(frozen=True)
class CommitAccommodate(CommitSubAction):
    """Commit a final animal configuration after taking from an animal market.

    Lands directly on the parent market pending (PendingSheepMarket /
    PendingPigMarket / PendingCattleMarket) — there is no separate
    sub-action pending pushed by the markets. The dispatcher's
    expected_pending_type entry uses a tuple of the three market types.
    """
    sheep: int
    boar: int
    cattle: int


@dataclass(frozen=True)
class CommitBuildPasture(CommitSubAction):
    """Commit one pasture build at PendingBuildFences.

    `cells` is the cell-set of the pasture being committed — same shape as
    one entry in the active fence universe (UNIVERSE_RESTRICTED by default).
    `frozenset` gives content-based equality and hashing, so two
    CommitBuildPasture objects naming the same cell-set compare equal
    regardless of construction order. By convention, callers iterating
    `cells` for display or logging sort by (row, col) lexicographic order.

    Cost is NOT a field on this commit — it is a pure function of
    (state, commit.cells) computed by `compute_new_fence_edges` in
    `agricola.fences`. This is the 4th sub-action cost-handling bucket
    (ENGINE_IMPLEMENTATION.md §3 — sub-action cost handling).

    The dispatcher never pops: the effect function leaves PendingBuildFences on
    top with updated counters; Stop pops it.
    """
    cells: frozenset                          # frozenset[tuple[int, int]]


@dataclass(frozen=True)
class CommitHarvestConversion(CommitSubAction):
    """Commit a once-per-harvest goods-to-food conversion at PendingHarvestFeed.

    `conversion_id` is a key in HARVEST_CONVERSIONS (e.g. "joinery", "pottery",
    "basketmaker", or a future card-registered id).

    Firing the conversion pays input_cost and adds the full food_out to the
    player's supply (which will be paid out, or kept as surplus, at the final
    CommitConvert), and adds the conversion_id to
    `player.harvest_conversions_used` so the enumerator no longer offers it for
    the remainder of this harvest's FEED. There is no "decline" variant:
    declining a craft is simply not firing it before `CommitConvert`, which
    forfeits every still-undecided craft. The dispatcher never pops — the
    pending stays on top to host further craft decisions and the final
    CommitConvert.

    `variant` names the chosen route of a VARIANT-bearing conversion
    (HarvestConversionSpec.variants_fn — built 2026-07-06 for Craft Brewery's
    "which grain field" choice, encoded by field height per the user's ruling):
    one commit per currently-legal variant; the spec's side_effect_fn receives
    it. None (the default) = an ordinary conversion. The three Family builtin
    crafts never set it, and the action wire encoding (trace_replay.
    action_to_params) skips a None variant, so the Family action contract and
    the C++ gates are untouched.
    """
    conversion_id: str
    variant: str | None = None


@dataclass(frozen=True)
class CommitConvert(CommitSubAction):
    """Commit the player's chosen goods-to-food conversion configuration at
    PendingHarvestFeed AND pay the feeding cost.

    Fields hold CONSUMED amounts — values subtracted from the player's supply
    at commit time (contrast with CommitAccommodate / CommitBreed, which hold
    post-event-state counts). The CONSUMED convention fits CommitConvert because
    the values are bounded by per-good caps in food_payment_frontier, and
    (0,0,0,0,0) means "consume nothing" regardless of player state.

    The legality enumerator constructs CommitConvert by inverting the
    REMAINING-goods tuples returned by harvest_feed_frontier (consumed =
    player_max - remaining).

    The dispatcher never pops. After this commit, only Stop is legal
    on the pending — `conversion_done` is set True. `_execute_convert` is
    the sole food-payment site: it adds food_produced to supply, then pays
    `min(need, supply + food_produced)` from the combined pool, leaves any
    surplus in supply, and assigns the shortfall as begging markers
    (assigned by _execute_convert, not Stop, preserving the Stop-only-pops
    convention).
    """
    grain:  int
    veg:    int
    sheep:  int
    boar:   int
    cattle: int


@dataclass(frozen=True)
class CommitBreed(CommitSubAction):
    """Commit the final post-breed animal configuration at PendingHarvestBreed.

    Fields hold POST-BREED animal counts (matches the convention of
    CommitAccommodate). The triple must match a Pareto-optimal point from
    `breeding_frontier(player_state, rates[:3])`; the legality enumerator
    only emits frontier points.

    The dispatcher never pops: the effect sets the chosen counts and
    adds the frontier's `food_gained` to supply; Stop is the explicit exit.
    """
    sheep:  int
    boar:   int
    cattle: int


@dataclass(frozen=True)
class CommitCardChoice(CommitSubAction):
    """Pick option `index` at a PendingCardChoice frame (card game).

    Lands on PendingCardChoice (a mandatory-with-choice trigger's pushed decision —
    Seasonal Worker's grain/veg, Childless's crop). `index` selects
    `pending.options[index]`; the pushing card's resolver (keyed on the frame's
    `initiated_by_id` card id in CARD_CHOICE_RESOLVERS) applies the option and pops
    the frame. No decline — the frame offers exactly its options.
    """
    index: int


@dataclass(frozen=True)
class FireTrigger:
    """Fire a specific card trigger that's currently eligible at the top pending.

    Declining a trigger is implicit (player picks a commit or another trigger
    instead) — there is no SkipTrigger action.

    `variant` distinguishes play-route variants of one trigger that the enumerator
    surfaces as separate FireTriggers (Scholar's "occupation" vs "minor" route): two
    FireTriggers with the same card_id but different variants are distinct actions,
    and `_apply_fire_trigger` threads the variant into the trigger's apply_fn. Plain
    triggers leave it None (backward-compatible) and their apply_fn takes
    `(state, idx)`.
    """
    card_id: str
    variant: str | None = None


@dataclass(frozen=True)
class Stop:
    """End the current non-atomic action (pop the top pending frame).

    Legal only at certain pending frames (currently: outer space pendings
    where at least one sub-action has been committed). Future cards may
    enable Stop at inner frames; in that case it still pops only the top.
    """


@dataclass(frozen=True)
class Proceed:
    """Apply an action-space host frame's primary effect and flip it to the
    after-phase (card game only).

    Surfaced by a PendingActionSpace (an atomic space hosted because a card may
    fire on it) while in its "before" phase, after any before-triggers. Applying
    it runs the space's normal atomic effect (ATOMIC_HANDLERS[space_id]) and
    flips the frame to "after", where after-triggers/effects fire and Stop pops.
    Treated like any other singleton step (auto-skipped when it's the only legal
    action). See CARD_IMPLEMENTATION_PLAN.md II.2.
    """


@dataclass(frozen=True)
class RevealCard:
    """Nature's action: turn up `card` as the round's stage card.

    A top-level transition like PlaceWorker (NOT a CommitSubAction). Supplied
    by the Environment (real games) or enumerated by the MCTS chance node;
    dispatched in engine._apply_action. See HIDDEN_INFO_DESIGN.md §4.1.
    """
    card: str   # a stage-card space id


@dataclass(frozen=True)
class CommitFoodPayment(CommitSubAction):
    """Commit a crops/animals-to-food conversion bundle to pay a card-game food cost
    (FOOD_PAYMENT_DESIGN.md §3.1). Lands on a PendingFoodPayment frame.

    Fields hold CONSUMED amounts — values subtracted from supply at commit time, the same
    convention as CommitConvert. `_execute_food_payment` adds the produced food (each good at
    its `cooking_rates` rate) — RAISE-ONLY, banking any overshoot; it does NOT debit the cost
    (the resumed action debits it from the now-sufficient supply) — then pops the frame and
    resumes the action the food was for.

    The legality enumerator constructs these by inverting the REMAINING-goods tuples from
    `food_payment_frontier`, run over the player's goods MINUS the frame's `reserved` cost
    goods (consumed = reduced_max - remaining).
    """
    grain:  int
    veg:    int
    sheep:  int
    boar:   int
    cattle: int


@dataclass(frozen=True)
class CommitDraftPick:
    """Draft one card from the current player's pool.

    A top-level action like RevealCard (NOT a CommitSubAction). The card
    is moved from the player's draft pool into their hand. Dispatched in
    engine._apply_draft_pick during Phase.DRAFT when PendingDraftPick is
    on the stack.
    """
    card_id: str


# The Action union. Dispatch in `_apply_action` is by `isinstance`.
# Concrete commit subclasses are listed individually (CommitSubAction base
# itself is intentionally not in the union — only concrete options are
# what an agent can pick).
Action = Union[
    PlaceWorker,
    ChooseSubAction,
    CommitSow,
    CommitBake,
    CommitPlow,
    CommitBuildStable,
    CommitBuildRoom,
    CommitBuildMajor,
    CommitRenovate,
    CommitChooseCost,
    CommitFamilyGrowth,
    CommitPlayOccupation,
    CommitPlayMinor,
    CommitAccommodate,
    CommitBuildPasture,
    CommitHarvestConversion,
    CommitConvert,
    CommitBreed,
    CommitCardChoice,
    CommitFoodPayment,
    FireTrigger,
    Stop,
    Proceed,
    RevealCard,
    CommitDraftPick,
]
