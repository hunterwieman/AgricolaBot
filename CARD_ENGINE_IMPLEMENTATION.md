# CARD_ENGINE_IMPLEMENTATION.md

Deep-mechanics companion to **`ENGINE_IMPLEMENTATION.md`**, for the **card system** (Phase 3).
That document describes the Family-game engine — `step` / `legal_actions`, the pending stack, the
sub-action primitives, the Fencing / accommodation / harvest subsystems. This one describes
everything the card game **adds**: the host/firing system that lets ~270 played cards hook engine
events, the registries a card registers into, the card-only state and pending frames, the
cost-modifier and food-payment layers, and the capacity modifiers.

It serves two purposes:

1. **The durable reference for the card machinery as built.** The design records
   (`CARD_SYSTEM_DESIGN.md`, `CARD_IMPLEMENTATION_PLAN.md`, `COST_MODIFIER_DESIGN.md`,
   `FOOD_PAYMENT_DESIGN.md`, `SPACE_HOST_REFACTOR.md`, `SUBACTION_HOOK_REFACTOR.md`) keep the
   rationale, red-teams, and superseded alternatives; this document describes the code that
   actually exists, verified against the working tree.
2. **The one document a card-implementation session reads first.** Machinery (§2–§5), rulings and
   idioms (§6), process (§7), and status (§1) in one place — instead of ten overlapping design
   docs of mixed freshness. Per-card practice (how to read a card, the pitfall checklist) stays in
   **`CARD_AUTHORING_GUIDE.md`**; per-card records stay in **`CARD_IMPLEMENTATION_PROGRESS.md`**.

**Read `ENGINE_IMPLEMENTATION.md` first.** This document assumes its vocabulary throughout —
pending frames, the decider rule, `_advance_until_decision`, enumerators, effect functions, the
commit dispatch table — and describes only the delta.

Contents:
0. Orientation — what cards add; the Family/C++ lockstep invariant
1. Status (updated per batch — the maintenance contract)
2. Hosts & firing — how card effects attach to engine events
3. The registries — every `register_*` seam
4. Card state & pending frames
5. Costs, food & capacity — the three resolution layers
6. Rulings & idioms
7. Implementing a card (process pointer)
8. Boundaries — what deliberately does not exist
9. Doc map

---

## 0. Orientation

### What the card game adds

The **card game** (`GameMode.CARDS`) is the full 2-player Agricola: on top of the Family game,
each player is dealt a private hand of 7 occupation + 7 minor-improvement cards
(`setup_env(seed, card_pool=CardPool(...))`, optionally via a competitive draft with
`draft=True`), and the board changes shape — Side Job is gone, Lessons becomes usable (play an
occupation), Meeting Place becomes "become starting player + optionally play a minor" (no food),
and the improvement spaces gain a play-minor branch. A played card sits face-up in the player's
tableau (`PlayerState.occupations` / `minor_improvements`) and from then on modifies the game:
granting goods or sub-actions when spaces are used, changing what builds cost, adding scoring
terms, scheduling future goods, raising animal capacity, and so on.

Mechanically, every card effect is one or more entries in a **registry** (§3), populated at
import of `agricola.cards` (one module per card under `agricola/cards/`). The engine consults the
registries at fixed seams — the **hooks** (§2). No card has bespoke engine code; a card that
doesn't fit the existing seams is *deferred*, not hacked in (§6, §8).

### The goal, and the invariant maintained alongside it

**The #1 goal of card work is a correct, working card game.** Running alongside it is an
invariant to *maintain* — not a goal that outranks the card design: the Family game is the
AI-training environment (CLAUDE.md Phase 2) with a native C++ twin validated against Python by
the differential gates (`tests/test_cpp_*.py`), so **the Family game and the C++ engine must
stay in lockstep** — Python is the oracle, and the gates stay green. Card work satisfies that
in two sanctioned ways:

**The default route: additive seams the Family game skips at O(1).** Most card machinery is
built so a Family game is **byte-identical** with or without the card code existing — no C++
change, no NN-encoder impact, nothing to re-validate. Four mechanisms deliver that:

- **Empty registries.** A registry consulted with no entries is a no-op (`AUTO_EFFECTS.get(event)`
  on an empty dict, an empty fold over `REDUCTIONS`, …). The Family game plays no cards, so every
  ownership-gated entry is dead even when registered.
- **Ownership indexes with O(1) guards.** Where a card would change *control flow* (push a host
  frame on an atomic space, host the harvest field phase, host round start), a
  `should_host_*` predicate consults a registration-time index of card ids and short-circuits on
  the empty set — the Family game never constructs the frame at all (§2, §3).
- **Default-skip canonical fields.** Every card-only field on `GameState` / `PlayerState` / the
  pending frames defaults to an inert value and is listed in `canonical._DEFAULT_SKIP_FIELDS`, so
  a Family state serializes without it — the canonical JSON (the C++ contract) is unchanged
  (§4).
- **Explicit mode branches.** Where the two games genuinely differ in rules (the board tables,
  Meeting Place, the fence-payment model), the code branches on `state.mode` — never inferred
  from empty hands. Family is a configured variant, not a degenerate card game.

**The other route: change the Family shape and re-port.** When the right card design wants a
Family-visible change, the Family engine is changed on its merits and the change is re-ported to
`cpp/` so the gates stay green. This has happened repeatedly and is normal — the host/Proceed
lifecycle, `CommitRenovate.to_material` + the wide-commit `payment`, the non-auto-popping
markets, the fence before/after phase, and the stored `fences_in_supply` are all Family-shape
changes the card work made and ported. (Port cost never constrains the Python design; the
invariant forbids *silent divergence*, not change.)

The C++ engine implements the **Family game only** — it has no card content, and its
`FireTrigger` path throws. Practical consequence per change: a **card-only** change must keep
`pytest tests/test_cpp_*.py` green *untouched*; a **Family-shape** change must be re-ported to
`cpp/` before those gates are green again — and until it is, the C++ path is stale and must be
flagged as such.

### Scope

Not covered here: the web UI's Cards mode (CLAUDE.md → Web UI & online deployment; `play_web.py` serializes hands under
hidden-info rules and renders card-play buttons), per-card entries
(`CARD_IMPLEMENTATION_PROGRESS.md` is the ledger; this document names specific cards only as
exemplars of a mechanism or as genuinely unique cases), and the batch-workflow tooling
(`CARD_AUTHORING_GUIDE.md` + `scripts/card_batch/`).

---

## 1. Status

> **Last updated: 2026-07-02, HEAD `ed20a52`.** A card batch is not integrated until this
> section is updated (§7's maintenance contract). Numbers move in both directions (batches land,
> cards get un/re-deferred) — **always re-census before trusting them**:
>
> ```bash
> ~/miniconda3/bin/python -c "from agricola.cards.specs import OCCUPATIONS, MINORS; \
> print(len(OCCUPATIONS), len(MINORS))"
> ```
> (Registries populate at `import agricola.cards`.) The **live registry is the truth**; the
> `status` fields in `agricola/cards/data/*.json` are a lagging tracker — two differing counts
> are expected, never reconcile them by hand.

- **Implemented & registered: 265 cards — 86 occupations + 179 minors**, spanning decks A–E
  (deck = 168 cards interleaving Base-Revised + one expansion: A=Artifex, B=Bubulcus,
  C=Corbarius, D=Dulcinaria, E=Ephipparius; catalog 420 + 420 total). All firing machinery of
  §2–§5 is live and exercised; the full pytest suite and the C++ Family differential gates are
  green as of the last integrated batch.
- **Per-card status + mechanics classification:** `CARD_IMPLEMENTATION_PROGRESS.md` (the
  adjudicated two-pass taxonomy). **Deferred cards:** clustered with build proposals in
  `CARD_DEFERRED_PLANS.md` (+ the C/D/E triage's defers in `CARD_TRIAGE_CDE.md`); deferred
  modules are archived under `archive/deferred_cards/`, never deleted.
- **Remaining implementation work** (per the batch records): the un-triaged deck-D remainder +
  deck E; revisiting decks A/B's deferred + never-triaged cards; and the shared-infra proposals
  (`CARD_DEFERRED_PLANS.md`) that would unblock whole defer clusters at once — those are
  user-decision-gated (§8).
- **Web UI:** Cards mode is playable (human-vs-random / human-vs-human) at the deployed app
  with all implemented cards in the deal pool (CLAUDE.md → Web UI & online deployment). **No trained card-game agent
  exists yet** — the Phase-2 agent loop for the card game starts after the card content
  stabilizes.

---

## 2. Hosts & firing

Card text is written against game *events*: "each time you use the Cattle Market…", "when you
renovate…", "at the start of each round…". The engine's answer has three parts, covered in order:
**hosts** (frames whose lifecycle defines a before- and an after-window for each action), **event
derivation** (a frame's kind + phase names the event), and the **three firing kinds** (how a
registered card effect actually runs). The section closes with the ordering rules that make the
firing correct: enforce-first, record-before-apply, and the firing-seam map.

### Terminology (from CARD_SYSTEM_DESIGN.md §0)

- A **hook** is an engine seam where card effects can attach — a (frame kind, phase) pair such as
  "before the Farmland space's work" or "after a renovate".
- A **trigger** is an *optional* card effect the agent chooses to fire: surfaced as a
  `FireTrigger(card_id)` action by the host's enumerator, declined implicitly by picking any other
  action (there is no SkipTrigger — ENGINE_IMPLEMENTATION.md §2 invariant 3).
- An **automatic effect** is a *mandatory, choice-free* card effect: applied directly by the
  engine at the hook (`apply_auto_effects`), never surfaced to the agent.
- A **mandatory-with-choice** effect must happen but requires a decision (Childless: "you must
  choose grain or a vegetable"): a `mandatory`-tagged trigger that gates its host's phase-exit
  until fired; firing pushes a `PendingCardChoice` (§4).

### Hosts: every action has a before/after lifecycle

In the Family engine some placements were atomic (no frame) and sub-action frames popped on their
commit. Cards need a stable frame to fire from *before* an action's work and *after* it, so two
refactors (SPACE_HOST_REFACTOR.md, SUBACTION_HOOK_REFACTOR.md — both landed, both live in the
Family game and the C++ port) made every action a **host**: a frame carrying
`phase: "before" | "after"` and `triggers_resolved: frozenset` whose lifecycle is

```
push (before-phase; before-autos fire, before-triggers offered)
  → the action's work
  → the work-complete flip to phase="after" (_enter_after_phase; after-autos fire)
  → after-triggers offered + Stop
  → Stop pops (a pure pop — _apply_stop does nothing else)
```

What differs between host kinds is only *what the work is* and *what signals work-complete*:

| Host kind | Frames | Work | Work-complete signal |
|---|---|---|---|
| **Atomic host** | `PendingActionSpace` (generic, card-only) | the space's `ATOMIC_HANDLERS` effect, run at `Proceed` | `Proceed` (runs the effect, then flips) |
| **Commit-terminated** | the sub-action leaves (`PendingSow`, `PendingBakeBread`, `PendingPlow`, `PendingRenovate`, `PendingBuildMajor`, `PendingPlayOccupation`, `PendingPlayMinor`, `PendingFamilyGrowth`) and the three animal markets | the single commit | the commit itself (its effect ends with `_enter_after_phase`) |
| **Multi-shot** | `PendingBuildRooms` / `PendingBuildStables` / `PendingBuildFences` (and a multi-plow `PendingPlow` grant, §4) | one commit per room/stable/pasture, `replace_top` each | `Proceed`, legal once counter ≥ 1 |
| **Delegating** | `PendingSubActionSpace` (Farmland, Fencing, Major Improvement, Lessons), `PendingMajorMinorImprovement` | exactly one mandatory child sub-action | the child's pop — detected by the engine (`DELEGATING` ClassVar + `subaction_complete`), flipped by an auto-advance in `_advance_until_decision`, never a player decision |
| **Proceed-host** | the and/or and and-then space parents (`PendingGrainUtilization`, `PendingCultivation`, `PendingFarmExpansion`, `PendingHouseRedevelopment`, `PendingFarmRedevelopment`, and the card-only `PendingBasicWishForChildren`, `PendingMeetingPlace`) | the player's chosen sub-actions | `Proceed`, legal once the mandatory work is done (Meeting Place: from the start — Proceed *is* the decline of its one optional minor) |

Two deliberate non-hosts: **`PendingSideJob`** (Family-only — the space doesn't exist in the card
game, so it keeps the old Stop-terminated shape and its bespoke `before_side_job` ClassVar), and
**`PendingChooseCost` / `PendingFoodPayment` / `PendingCardChoice` / `PendingDraftPick`** (closed
decision frames: no card fires on "choosing a payment", so no phase, no triggers, no Stop — §4).

**Atomic spaces are hosted conditionally.** An atomic space (Forest, Day Laborer, …) stays atomic
— placement runs `ATOMIC_HANDLERS[space_id]` directly, no frame — *unless a played card hooks it*.
`_apply_place_worker` asks `should_host_space(state, space_id, acting_player)` (§3), which
consults two registration-time indexes: `OWN_ACTION_HOOK_CARDS` (cards firing on the acting
player's own use) and `ANY_PLAYER_HOOK_CARDS` (cards firing on *either* player's use — Milk Jug on
the animal markets — which force the host on the opponent's turn too). Both empty → always False →
the Family fast path. The split exists so the both-players ownership scan runs only for the rare
any-player card. When hosting, the generic `PendingActionSpace` is pushed in its before-phase and
the space's effect runs later, at `Proceed` (`_apply_proceed`).

One special case: **card-mode Meeting Place is self-hosting**. Its handler
(`_initiate_meeting_place_cards`) applies become-SP immediately (no card fires on that) and pushes
`PendingMeetingPlace` — itself a full host. `_apply_place_worker` dispatches it *ahead of* the
generic atomic-host wrapper, because wrapping a pushing handler in a second `PendingActionSpace`
double-hosts the space and soft-locks the turn (an infinite Proceed↔Stop cycle).

### Event derivation: `trigger_event(frame)`

A host does not store which event it fires (the old per-frame `TRIGGER_EVENT` ClassVar is gone —
ENGINE_IMPLEMENTATION.md §2 invariant 9). The event is **derived** from the frame's kind and
phase by `legality.trigger_event`:

```python
pid = type(frame).PENDING_ID
base = "action_space" if pid in ACTION_SPACE_PENDING_IDS else pid
return f"{frame.phase}_{base}"
```

- **Space hosts share one coarse event.** Every frame whose `PENDING_ID` is in
  `ACTION_SPACE_PENDING_IDS` (`pending.py`: the generic `"action_space"` shared by
  `PendingActionSpace` + `PendingSubActionSpace`, plus the per-space parents
  `farm_expansion`, `grain_utilization`, the three markets, `house_redevelopment`, `cultivation`,
  `farm_redevelopment`, and the card-only `meeting_place`, `basic_wish_for_children`) fires
  `before_action_space` / `after_action_space`. A card hooking a *specific* space filters inside
  its eligibility function via the frame's uniform `space_id` property
  (`state.pending_stack[-1].space_id`, parsed off `initiated_by_id`).
- **Sub-action hosts fire `<phase>_<PENDING_ID>`** — `before_bake_bread`, `after_renovate`,
  `after_build_fences`, `after_play_minor`, ….
- **Routing on `PENDING_ID`, not `initiated_by_id`, is load-bearing:** a sub-action frame's
  `initiated_by_id` is its *parent's* id (or `"card:<id>"` for a grant), so keying the bucket on
  it would mis-route. `initiated_by_id` answers "who pushed me" (grant scoping, §4);
  `PENDING_ID` answers "what kind of frame am I" (event routing).

Three deliberate exclusions from the `action_space` bucket:
- **`PendingMajorMinorImprovement`** fires its own `major_minor_improvement` event. It is the
  composite "build a major OR play a minor" host, reached both from the Major Improvement space
  and as House Redevelopment's optional second step — bucketing it would fire a second
  `after_action_space` on top of House Redevelopment's own. (The Major Improvement *space* still
  gets an `action_space` surface: its `PendingSubActionSpace` wrapper is pushed above the
  composite, so a space-hooking card like Plumber and a composite-hooking card like Merchant each
  have their own layer.)
- **The multi-shot builders** (`build_rooms` / `build_stables` / `build_fences`) — their
  Proceed/Stop ends a *sub-action*, not the space.
- **`side_job`** — Family-only, never a host.

One override: **`PendingPreparation`** (the start-of-round phase host, §4) shares the bucket id
family but its enumerator uses the literal event `"start_of_round"` — it is a phase host, not a
worker-placement host, and has no before/after flip (Proceed pops it directly).

The full event vocabulary at HEAD (from the live registries; grow as cards need them):
triggers fire on `before_/after_action_space`, `before_bake_bread`, `before_plow`, `before_sow`,
`before_renovate`, `before_/after_build_fences`, `before_/after_play_occupation`,
`after_play_minor`, `start_of_round`; autos additionally on `after_plow`, `after_sow`,
`after_renovate`, `after_build_major`, `after_build_rooms`, `after_build_stables`,
`after_major_minor_improvement`, `before_play_minor`, `before_build_major`, `before_build_rooms`,
`harvest_field`, and the coarse `after_build_improvement` ("any improvement built" — fired by
`_execute_play_minor` and the major-build path for cards like Junk Room).

### The three firing kinds

**1. Optional triggers** (`triggers.register(event, card_id, eligibility_fn, apply_fn)`). The
host's enumerator calls `_eligible_fire_triggers(state, pending, event)`, which filters the
event's `TRIGGERS` entries by: owned (played, not in hand) → not already in the frame's
`triggers_resolved` → `eligibility_fn(state, player_idx, triggers_resolved)` — and surfaces one
`FireTrigger(card_id)` per survivor, alphabetically. `_apply_fire_trigger` then runs the card's
`apply_fn(state, player_idx)`. `triggers_resolved` scopes the once-per-event budget to the frame's
lifetime (invariant 10); eligibility receives it so a card can also express "at most N times per
action" internally.

**2. Automatic effects** (`triggers.register_auto(event, card_id, eligibility_fn, apply_fn, *,
any_player=False)`). Applied directly at the hook by `apply_auto_effects(state, event,
acting_player)`, in registration order, never surfaced to the agent. Note the **eligibility
signature differs from triggers**: an auto's is `(state, owner_idx)` — there is no
`triggers_resolved` because an auto fires exactly once, at its hook, with no budget to consult.
`any_player=True` routes the effect to *every owner* rather than the acting player (Milk Jug pays
its owner when the opponent uses the Cattle Market); the owner-routing loop lives in
`apply_auto_effects`, not on frames.

**3. Mandatory-with-choice** (`register(..., mandatory=True)`). Surfaced as a `FireTrigger` like
an optional trigger, but the host's phase-exit (`Proceed` in the before-phase, `Stop` in the
after-phase) is **withheld** while an owned, eligible, unfired mandatory trigger exists —
`has_unfired_mandatory_trigger(state, pending, event)` is the gate the enumerators consult. The
player cannot decline, only choose *how* to resolve: the trigger's `apply_fn` pushes a
`PendingCardChoice(options=...)`, whose `CommitCardChoice(index)` dispatches to the card's
registered resolver (`CARD_CHOICE_RESOLVERS`, keyed on the card id parsed off the frame's
`initiated_by_id`). Exemplars: Childless, Seasonal Worker (round 6+).

**Play-variant triggers.** A trigger offering alternative *routes* ("play an occupation OR a
minor" — Scholar; "build a room OR renovate" — Cottager) collapses the route choice into the
fire: `register_play_variant_trigger(card_id, variants_fn)` makes the enumerator expand the
card's one trigger into one `FireTrigger(card_id, variant=...)` per currently-legal route
(`_expand_variant_triggers`), and `_apply_fire_trigger` threads the variant into a 3-argument
`apply_fn(state, idx, variant)`. No intermediate decision frame.

### Enforce-first: the before-window closes at the work

The governing ruling (user-confirmed; CARD_AUTHORING_GUIDE.md): **"each time you use [space]"
fires *before* the space's work unless the text literally says after** — and taking the mandatory
work *closes* the before-window, implicitly declining any unfired before-trigger. Order is
load-bearing per the rules (Moldboard Plow's granted plow must precede the base Farmland plow;
Writing Desk before the Lessons play), so the window must not be re-openable "in either order".
Two mechanisms enforce it:

- **Delegating hosts: the auto-advance flip is unconditional.** The moment the single mandatory
  child pops with the host still in its before-phase, `_advance_until_decision` flips it to the
  after-phase within the same `step` — the `(subaction_complete && phase=="before")` state is
  purely transient and `legal_actions` never sees it. (A "held flip" that suppressed the
  auto-advance while a before-trigger was still eligible — commit 20b6b83 — re-offered
  before-triggers *after* the work; it was a regression and was reverted in c00812e, and the
  reverted mechanism's orphaned predicate `has_eligible_trigger` was later deleted.
  POST_COMPACTION_DETOUR.md §2 is the full story.)
- **Proceed-hosts: the `subaction_started` gate.** A Proceed-host lingers across multiple
  sub-actions, so it has no auto-advance to close the window. Every Proceed-host space parent —
  the five Family ones plus the card-only `PendingBasicWishForChildren` and
  `PendingMeetingPlace` — carries a derived `subaction_started` property (the OR of its
  `*_chosen` flags), and their enumerators offer `before_action_space` triggers **only while it
  is False**. (Meeting Place's become-SP happens at push, before the frame exists, so there its
  gate covers the one orderable sub-action — the optional minor.)

### Record-before-apply

`_apply_fire_trigger` stamps `triggers_resolved` on the host frame *first*, then runs the
`apply_fn`. The order matters for granted-sub-action triggers, whose `apply_fn` *pushes* a
primitive frame (Assistant Tiller → `PendingPlow`; Oven Firing Boy → `PendingBakeBread`):
recording after the push would `replace_top` the just-pushed child instead of the host. For a
non-pushing trigger the order is end-state-identical.

### The firing-seam map

Where each firing actually happens in the engine — the complete set of call sites:

| Seam | Fires | Where |
|---|---|---|
| Space-host push | `before_action_space` autos | `_apply_place_worker` (atomic host), every non-atomic `_initiate_*` resolver except Family-only Side Job, `_initiate_lessons`, `_initiate_meeting_place_cards`, `_resolve_basic_wish_for_children`'s cards branch |
| Sub-action-leaf push | `before_<PENDING_ID>` autos | `_fire_subaction_before_auto` (engine.py) — the single seam, called after a `_choose_subaction_*` handler runs, after a trigger's `apply_fn` runs, after a minor's or occupation's pushing `on_play`, and after a non-"rerun" food-payment resume; gated on `SUBACTION_PENDING_IDS` **and a depth guard** (fires only if the call actually pushed a new frame — a non-pushing trigger or goods-only `on_play` must not re-fire the leaf's before-autos) |
| Work-complete flip | `after_<derived event>` autos | `_enter_after_phase` (resolution.py) — called by every commit-terminated effect at its commit, by the markets, by `_apply_proceed` for atomic/Proceed/multi-shot hosts, and by the Delegating auto-advance |
| Composite host | `before_/after_major_minor_improvement` autos | its choose-handler push / the Delegating auto-advance |
| Any improvement built | `after_build_improvement` autos | `_execute_play_minor` / the major-build path |
| Round start | `start_of_round` autos | `_fire_preparation_hook` (at each `PendingPreparation` push); its triggers via the host's enumerator |
| Harvest field phase | `harvest_field` autos | `_fire_harvest_field_hook`, inside `_resolve_harvest_field` *before* the crop take (Scythe Worker reads unharvested fields), per player in starting-player-first order |
| Renovate / card play | the one-shot conditional sweep | `_fire_ready_one_shots` (§3), called after a renovate applies and after any card is played |
| Triggers (all events) | `FireTrigger` surfacing | each host enumerator via `_eligible_fire_triggers` + `_expand_variant_triggers` |

`Stop` fires nothing (`_apply_stop` is a pure pop). There is deliberately **no end-of-turn
event** — see §8.

---

## 3. The registries

Every seam a card can register into, by module. A card module calls one or more `register_*`
functions at the bottom of its body; importing `agricola.cards` (which `engine.py` does at load)
runs them all. **Every registry is empty — and every fold over it a no-op — in the Family game**;
that is stated once here, not repeated per entry. Ownership ("has this player *played* the card"
— a hand card never fires or modifies anything) is checked inside the consuming fold, via the
module-local `_owns(player_state, card_id)` helpers.

### `agricola/cards/specs.py` — playing cards

- **`register_occupation(card_id, on_play)`** → `OCCUPATIONS: dict[str, OccupationSpec]`.
  An occupation's on-play effect, `(state, owner_idx) -> state` (default no-op for pure-scoring /
  passive cards). Occupations carry no structured cost or prerequisite — the play cost is
  **route-supplied** (Lessons charges `occupation_cost(num_played)`: first free, then 1 food;
  Scholar's route charges a flat 1 food) and lives on `PendingPlayOccupation.cost`, not the spec.
  Exemplar: `consultant.py`.
- **`register_minor(card_id, *, cost=Cost(), alt_costs=(), cost_fn=None, min_occupations=0,
  max_occupations=None, prereq=None, passing_left=False, vps=0, on_play=_noop)`** →
  `MINORS: dict[str, MinorSpec]`. The pieces:
  - `cost: Cost` — the spendable price (Resources + Animals), paid at play.
  - `alt_costs: tuple[Cost, ...]` — the printed **"/"-alternatives** (Chophouse "2 Wood / 2
    Clay"): the ways to pay are `(cost,) + alt_costs` and the player pays exactly one; each
    alternative is enumerated as its own `CommitPlayMinor` (§5). Not combinable with `cost_fn`.
  - `cost_fn: (state, idx) -> Cost` — a state-*scaling* cost, overriding `cost` at play time
    (Bottles: per-person clay+food).
  - `min_occupations` / `max_occupations` — the dominant prerequisite shape ("at least/at most N
    occupations"); `prereq: (state, idx) -> bool` — every other prerequisite (geometry, house
    material, round, supply comparisons). A prerequisite is a HAVE-check, never spent —
    `prereq_met(spec, state, idx)` is the combined predicate.
  - `passing_left: bool` — a traveling minor: executed, then passed into the *opponent's hand*,
    never kept in the tableau. Exemplar: `market_stall.py`.
  - `vps: int` — printed victory points, summed at scoring for kept minors (the second scoring
    path beside `SCORING_TERMS` below).
- **`register_play_occupation_variant(card_id, variants_fn)`** → `PLAY_OCCUPATION_VARIANTS`.
  For an occupation whose play carries an optional all-or-nothing choice (Roof Ballaster: "you
  may pay 1 food to get 1 stone per room"): `variants_fn(state, idx) -> list[(variant_str,
  surcharge: Resources)]` (must be non-empty — include a zero-surcharge decline variant). The
  enumerator offers one `CommitPlayOccupation(card_id, variant=v)` per payable variant, the
  executor folds the chosen surcharge into the debited cost, and `on_play` becomes
  `(state, idx, variant)`. **The cost lives on the option that surfaces it**, not a side table —
  the "paid option" principle (FOOD_PAYMENT_DESIGN.md §8). *No minor equivalent exists* — a "/"
  play-variant *reward* on a minor is a defer (§8).
- **`register_occupation_food_source(card_id, source_fn)`** → `OCCUPATION_FOOD_SOURCES`.
  A card that can *produce* food usable toward an occupation's play cost (Paper Maker: pay 1 wood
  → 1 food per occupation). The card itself is an ordinary `before_play_occupation` trigger; this
  registry additionally lets the affordability **gate** (`_payable_occupation`, §5) simulate
  firing it — `source_fn(state, idx) -> (food_produced, inputs: Resources) | None` — so a play
  payable only via the source is still offered.
- **`register_food_payment_resume(resume_kind, apply_fn)`** → `FOOD_PAYMENT_RESUMES`.
  A card-specific continuation after a `PendingFoodPayment` commits (§5): `resume_kind` is the
  card id the frame carries, `apply_fn(state, owner_idx) -> state` debits the food and applies the
  grant (Ox Goad: pay 2 food → push a plow).

### `agricola/cards/triggers.py` — firing + hosting

- **`register(event, card_id, eligibility_fn, apply_fn, *, mandatory=False)`** →
  `TRIGGERS` (event-keyed, read by enumerators) + `CARDS` (id-keyed, read by
  `_apply_fire_trigger`) — both hold the same `TriggerEntry`. The optional-trigger kind (§2);
  `mandatory=True` is mandatory-with-choice. Eligibility signature
  `(state, player_idx, triggers_resolved)`.
- **`register_auto(event, card_id, eligibility_fn, apply_fn, *, any_player=False)`** →
  `AUTO_EFFECTS`. The automatic-effect kind (§2). Eligibility signature `(state, owner_idx)` —
  **note the difference from triggers**. Exemplars: `wood_cutter` (own-action goods),
  `milk_jug` (`any_player=True`, fires `before_action_space` on either player's Cattle Market
  use).
- **`register_action_space_hook(card_id, spaces, *, any_player=False)`** →
  `OWN_ACTION_HOOK_CARDS` / `ANY_PLAYER_HOOK_CARDS` (space_id → card ids). **Required for a card
  hooking a TRUE-ATOMIC space** — it is what makes `should_host_space` push the host frame at
  all. The non-atomic spaces are already hosts and need no hook entry. Forgetting this line is
  the classic silent failure: the trigger registers, the host never pushes, the card never
  fires. **Never register a hook for `meeting_place` or `basic_wish_for_children`**: in card
  mode both are *self-hosting* (their handlers push their own host frames, which fire
  `before_/after_action_space` without any hook entry). Meeting Place is hard-protected (its
  dispatch precedes the `should_host_space` check — §2), but Basic Wish is not: a registered
  hook would wrap its pushing handler in a generic `PendingActionSpace`, whose `Proceed` would
  then flip the *pushed child* instead of the host — a latent misfire guarded only by this
  convention.
- **`register_harvest_field_hook(card_id)`** → `HARVEST_FIELD_CARDS`, consulted by
  `should_host_harvest_field`. Pair with `register_auto("harvest_field", ...)`. The field-phase
  hook is **auto-only** today — the transient `PendingHarvestField` never surfaces a decision
  (§4), so an optional "you may…" harvest-field card is a defer (§8). Exemplars: `scythe_worker`,
  `loom`.
- **`register_start_of_round_hook(card_id)`** → `START_OF_ROUND_CARDS`, consulted by
  `should_host_preparation` (together with `has_scheduled_round_start_effect` — a
  `future_rewards` slot carrying effect-card ids drives hosting on its own, so a deferred grant
  like Handplow hosts only the round it comes due, §3 schedules). Pair with
  `register("start_of_round", ...)` (optional triggers ARE supported here, unlike the field
  phase) or `register_auto`. Exemplars: `scullery` (auto), `plow_driver` (trigger).
- **`register_conditional(card_id, condition_fn, apply_fn)`** → `CONDITIONAL_ONE_SHOTS`.
  The one-shot **level-triggered latch**: "once you live in a stone house, …" fires the first
  moment the standing condition holds — whether the condition changed under a played card or was
  already true when the card was played. The sweep, `engine._fire_ready_one_shots`, latches into
  `fired_once` *before* applying (idempotent under re-entry) and runs at exactly the two seams a
  house-material condition can change for the owner: **after a renovate applies and after any
  card is played**. A condition on anything else (a resource count — Hook Knife's "8 sheep")
  never gets swept and is a defer (§8). Exemplar: `manservant`.
- **`register_card_choice_resolver(card_id, resolver)`** → `CARD_CHOICE_RESOLVERS`.
  `resolver(state, player_idx, chosen_option) -> state` applies a `PendingCardChoice` pick and
  pops the frame itself. Pair with a `mandatory=True` trigger whose `apply_fn` pushes the frame.
- **`register_play_variant_trigger(card_id, variants_fn)`** → `PLAY_VARIANT_TRIGGERS`.
  `variants_fn(state, idx) -> list[str]` (empty = none legal now); expands the card's trigger
  into per-variant `FireTrigger`s (§2). Exemplars: `scholar`, `cottager`.

### `agricola/cards/cost_mods.py` — cost modifiers + free fences

The registries behind the `effective_payments` chokepoint (§5). All keyed by `action_kind`
(`"renovate" | "build_room" | "build_stable" | "build_major" | "play_minor" | "build_fence"`)
except the fence-specific three.

- **`register_formula(action_kind, card_id, applies, formula)`** — replaces the whole printed
  cost with a fixed alternative; each owned, applicable formula seeds its own base (the player
  uses at most one — bases never combine).
- **`register_reduction(action_kind, card_id, reduce)`** — `reduce(state, idx, ctx, cost) ->
  Resources`, a signed delta; the fold floors every component at 0 after each. Exemplar:
  `bricklayer`.
- **`register_conversion(action_kind, card_id, expand1, *, order=0, record=None)`** — an
  optional resource-for-resource substitution at payment time. `expand1(state, idx, ctx, cost) ->
  list[Resources]` is an internally-budgeted *generator*: it returns the unchanged input plus
  every legal substitution variant (its own 0..max budget encoded inside). `order` sequences
  chains — producers low, a consuming *sink* high — so `expand_conversions` can apply **each
  conversion exactly once, in order** and still let a later conversion consume an earlier one's
  output (§5). `record(state, idx, payment) -> state` serves a **per-action** budget across a
  multi-shot build (Millwright's "up to 2 grain per action"): `expand1` reads the running spend
  from the card's own CardStore, `record` is called at each debit
  (`record_conversion_usage`), and the card resets the counter at its `after_build_*` auto.
  Exemplars: `frame_builder` (stateless), `millwright` (recorded).
- **`register_base_route(action_kind, card_id_or_None, routes_fn)`** — a **non-resource** payment
  route: `routes_fn -> list[ReturnImprovement]`. `card_id=None` is a built-in: the one today is
  the core Family rule "build a Cooking Hearth by returning a Fireplace", registered at module
  load (so even the Family frontier can be a 2-element menu there — the one Family case where a
  wide commit carries a route).
- **The three free-fence sources** (§5 has the consumption order):
  `register_free_fence_edges(card_id, edge_fn)` → `FREE_FENCE_EDGES` — *positional*: `edge_fn`
  returns (h, v) bitmaps of the specific board edges the card frees (Briar Hedge: the perimeter;
  Field Fences: field-adjacent), unioned across owned cards then intersected with a pasture's new
  edges (`positional_free_edge_count`). `register_free_fence_seed(card_id, seed_fn)` →
  `FREE_FENCE_SEEDS` — a *per-action scalar budget*: `seed_fn(state, idx, *,
  build_fences_action, space_id) -> int` (Hedge Keeper: 3), summed by `free_fence_budget_for`
  and seeded onto the frame at the build's start; one function serving the three call sites that
  must agree (seed at push, placement-time anticipation, during-build enumeration).
  `register_free_fence_pool(card_id, store_key)` → `FREE_FENCE_POOLS` — a *persistent pool* of
  fence pieces held ON the card in CardStore (Ash Trees moved them from the 15-supply at play):
  counts toward `buildable_fences` AND waives wood, spent greedily by `spend_fence_pools`.

### `agricola/cards/capacity_mods.py` — animal capacity

Read by `helpers.extract_slots` (the accommodation decomposition every frontier consumes):

- **`register_house_capacity(card_id, capacity_fn)`** → `HOUSE_CAPACITY_MODS`. How many flexible
  (any-type, capacity-1) slots the *house* provides. Fold: **max over owned modifiers, starting
  from the default 1** (the house pet) — `house_pet_capacity`. Exemplar: `animal_tamer` (one per
  room). The max-fold cannot express a *negation* (Milking Place would force 0) — §8.
- **`register_pasture_capacity(card_id, bonus_fn)`** → `PASTURE_CAPACITY_MODS`. A flat additive
  bonus applied to **every pasture's** final capacity (after the stable doubling — the card adds
  to the finished pasture, not inside the `2·cells·2^stables` formula). Fold: **sum over owned
  modifiers, default 0** — `pasture_capacity_bonus`. Exemplar: `drinking_trough` (+2).

The two folds are the first mechanism to make pasture capacities non-canonical (dependent on
owned cards, not just geometry) — which is exactly the situation the frontier-cache
projection-key contract warns about; see §5's closing note.

### `agricola/scoring.py` — end-game points

- **`register_scoring(card_id, fn)`** → `SCORING_TERMS`. `fn(state, player_idx) -> int` bonus
  points; `score` sums the terms the player owns. Exemplar: `stable_architect` (+1 per unfenced
  stable).
- **`register_scoring_group(group_id, card_id, fn)`** → `SCORING_GROUPS`. For cards carrying
  "you can only use one card to get bonus points for X": per group, only the **max over owned
  members** counts. A group member registers here and *not* in `SCORING_TERMS` (no
  double-count).
- The third path needs no registration: a kept minor's printed **`MinorSpec.vps`** is summed
  directly by `score`.

Cards whose points are *banked during play* (Big Country, Tutor, Beer Keg…) store the bank in
CardStore and register a scoring term that reads it — see `agricola/cards/display.py` (§4) for
how the web UI surfaces those live.

### `agricola/cards/harvest_conversions.py` — feed-phase conversions

**`register_harvest_conversion(HarvestConversionSpec(conversion_id, input_cost, food_out,
is_owned_fn, side_effect_fn=None))`** — a discrete, optional, once-per-harvest
`CommitHarvestConversion` in HARVEST_FEED, alongside the three built-in craft majors
(ENGINE_IMPLEMENTATION.md §4.3). `is_owned_fn(state, idx)` gates it; the fired id lands in
`PlayerState.harvest_conversions_used` (per-harvest scope). Two card-era extensions of the
original shape:

- **`side_effect_fn(state, idx) -> state`** runs after the food/resource accounting — it supports
  VP-banking (Beer Keg: +VP into CardStore) and goods payouts, so "X → food *and* a point" fits.
- **Multi-variant conversions** ("convert 1/2/3 grain") register N entries whose shared
  once-per-harvest budget is a *prefix match*: each `is_owned_fn` returns
  `not any(cid.startswith("<card_id>") for cid in used)` — firing any variant blocks the rest.
  An *output* choice ("3 food OR 1 point") is likewise just two entries — not an unsupported
  cost-side "/".

### `agricola/cards/schedules.py` — deferred goods & effects

Cards that place goods/effects on future round spaces ("place 1 food on each of the next 3
round spaces"). Slot convention: 1-indexed round N → slot N−1, collected when round N is entered
(`_complete_preparation`); out-of-game rounds silently dropped ("each *remaining* round space");
repeated placers stack additively.

- **`schedule_resources(state, idx, rounds, goods: Resources)`** — onto
  `PlayerState.future_resources` (the Family-reachable structure the Well already uses; collected
  mechanically at round start).
- **`schedule_effect(state, idx, rounds, card_id)`** — a card id into
  `future_rewards[slot].effect_card_ids`. The schedule gates the card's **optional**
  `start_of_round` trigger AND drives preparation hosting for that round
  (`has_scheduled_round_start_effect`); the grant is the player's to take or decline, never
  auto-fired. Exemplar: `handplow` (a deferred plow).
- **`schedule_animals(state, idx, rounds, animals: Animals)`** — animals into
  `future_rewards[slot].animals`; collected at round start by `engine._collect_future_rewards`
  and **auto-accommodated** decision-free (the best `pareto_frontier` point by total kept — the
  one place immediate accommodation exists outside the markets/harvest, §6). Exemplar:
  `acorns_basket`.

### `agricola/legality.py` — legality extensions

These live in `legality.py` (not `cards/`) because they extend its predicates in place:

- **`register_bake_bread_extension(fn)`** → `BAKE_BREAD_ELIGIBILITY_EXTENSIONS`.
  `(state, p) -> bool`, OR-ed into `_can_bake_bread` (the original extension seam — Potter
  Ceramics can bake at 0 grain; Hand Truck likewise).
- **`register_baking_spec_extension(fn)`** → `BAKING_SPEC_EXTENSIONS`. `(state, idx) ->
  list[(max_grain_per_action, food_per_grain)]` — non-major baking sources, merged with the
  major-improvement specs by `baking_specs_for_player`, consumed source-agnostically by the bake
  enumerator + executor.
- **`register_occupancy_override(fn)`** → `OCCUPANCY_OVERRIDE_EXTENSIONS`. `(state, space_id) ->
  bool`, consulted by `_is_available` **only on the occupied branch** (the unoccupied common path
  pays nothing): lets a card permit placing on an occupied space. An override self-gates on its
  own ownership + space + the precise occupancy shape it relaxes. Exemplars: `sleeping_corner`
  (a wish space used by exactly one *other* player), `forest_school` (Lessons).
- **`register_renovate_target_extension(fn)`** → `RENOVATE_TARGET_EXTENSIONS`. `(state, idx,
  current_material) -> list[HouseMaterial]` — extra legal renovate *targets* beyond the next
  tier, consumed by `_legal_renovate_targets`; each target's cost then flows through the
  chokepoint normally (the renovate-target model, §5). Exemplar: `conservator` (wood → stone
  directly).

---

## 4. Card state & pending frames

### The state-placement rule (COST_MODIFIER_DESIGN.md §9.9 — guides every future card)

When a card needs state, it goes in one of three homes, split by **lifetime and meaning**:

- **`initiated_by_id`** = "which card/site caused *this exact frame*." An *identity*, used to gate
  frame-scoped behavior (grant scoping — Field Fences' positional discount applies only to a
  build pushed with `initiated_by_id="card:field_fences"`). Not a general state bag.
- **Dedicated frame fields** (`accrued_cost`, `free_fence_budget`, `must_preserve_base`, …) =
  **frame-scoped state/parameters** that live and die with one frame.
- **CardStore** = **card-owned state with its own lifecycle, spanning frames** (Ash Trees'
  game-long fence pool, Millwright's per-action conversion budget, Shepherd's Crook's
  before→after snapshot).

Corollary for the eventual card-game NN encoder: a frame-scoped fact the encoder needs ("Field
Fences' grant is live") is *derived from the frame at encode time*, not pre-materialized onto the
card — the engine stays clean, and the choice is reversible.

### `GameState` additions

Exactly two card-new fields (plus the frames below riding the existing `pending_stack`):

- **`mode: GameMode = GameMode.FAMILY`** — which variant this state belongs to. Read wherever the
  rules genuinely diverge: `legal_placements` picks `FAMILY_GAME_LEGALITY` vs
  `CARD_GAME_LEGALITY` (Side Job dropped; `lessons` → `_legal_lessons_cards`;
  `major_improvement` → the major-or-minor predicate), `_apply_place_worker`'s Meeting Place
  branch, `_complete_preparation`'s Meeting-Place-refill skip, and the fence-payment branch in
  `_execute_build_pasture` (§5).
- **`draft_pools: tuple | None = None`** — during **`Phase.DRAFT`** (card game with
  `setup_env(seed, card_pool=..., draft=True)`), the four pools
  `(p0_occ, p0_min, p1_occ, p1_min)`. The draft is ordinary engine flow:
  `_advance_until_decision` pushes one `PendingDraftPick(player_idx, card_type)` at a time (pick
  order P0-occ → P0-min → P1-occ → P1-min, driven by `_next_draft_pick`'s max-pool-size rule),
  the enumerator offers one `CommitDraftPick` per card in that pool, and `_apply_draft_pick`
  (a top-level action like `RevealCard`, not a `CommitSubAction`) moves the card into the
  player's hand — swapping the pools between players when all four sizes equalize (the
  pass-to-the-left round boundary). When all pools empty, `draft_pools` is set to `None` and the
  walk continues to PREPARATION → the round-1 reveal → WORK. Without `draft=True`, `setup_env`
  deals complete 7+7 hands directly (`_deal_hands`) and no DRAFT phase exists.

`starting_player` is **not** card-new — it is a Phase-1 field.

### `PlayerState` additions

- **`hand_occupations` / `hand_minors: frozenset[str]`** — the private hands. Hidden information
  is handled **above the engine**: `legal_actions` / `step` only ever read the *decider's own*
  hand (the only hand any decision needs), and a search agent hides the opponent's hand by
  determinization (dealing plausible replacement hands — ISMCTS), a search-layer concern
  (CARD_IMPLEMENTATION_PLAN.md I.5). There is **no `observe(state, env, i)` projection in the
  code** — CLAUDE.md / ENGINE_IMPLEMENTATION.md passages presenting one as built describe
  unimplemented design intent. The web UI applies its own reveal rules at serialization
  (CLAUDE.md → Web UI & online deployment).
- **The scoped used-sets** — `used_this_turn`, `used_this_round`, `fired_once: frozenset[str]` —
  the "have I fired this already?" latches for card budgets spanning events (which never live on
  frames — invariant 10's complement). Each is cleared *at its scope boundary* by
  `engine._clear(state, field)`, which resets **both players** (an off-turn card must see a fresh
  latch too) and is a no-op returning the same object when both sets are empty (the Family path):
  - `used_this_turn` — cleared in `_advance_current_player` (every turn boundary) **and** in
    `_complete_preparation` (the new round's first turn has no preceding alternation — the
    double-site).
  - `used_this_round` — cleared in `_complete_preparation`.
  - `fired_once` — per-game one-shots (the conditional-latch sweep, §3); never cleared.
  - `harvest_conversions_used` (Phase-1) is the per-harvest scope, reset in
    `_resolve_harvest_field`.
- **`card_state: CardStore`** — the persistent per-card state side-map. `CardStore` is a frozen
  dataclass over a **sorted tuple of `(card_id, value)` pairs**, so two stores with equal
  contents are structurally identical (equal + same hash — the MCTS transposition table needs
  `GameState` hashable and stable). `get(cid, default)` / `set(cid, value)` (returns a new,
  re-sorted store; one value per card). Values are heterogeneous — an `int` for the common case
  (Tutor's snapshot, Moldboard Plow's uses-left, banked VP), a `Resources` for goods held on a
  card (Interim Storage), a frozen payload dataclass for a rare complex card. Only cards that
  store something have an entry; the played-card frozensets stay plain id sets.
- **`future_rewards: tuple[FutureReward, ...]`** (length 14) — the card-only sibling of
  `future_resources`, **not** a generalization of it (design (b)): goods schedules stay on the
  Family-reachable `future_resources`; this carries only what a `Resources` slot cannot —
  **animals** (collected + auto-accommodated at round start, §3 schedules) and **effect-card
  ids** (round-start grant hooks). `FutureReward` is additive (`+` stacks animals and unions
  ids) and falsy when empty, which is what lets `_complete_preparation` skip the whole branch
  object-identically in Family.
- **`fences_in_supply: int = 15`** — stored, not derived; the one card field that is **not**
  default-skip (its value varies in Family too, where it equals `15 − fences_built`). See §5.

### The card-new pending frames

Grouped by role (full field lists in `pending.py`; all are frozen dataclasses carrying
`player_idx` + `initiated_by_id` per the Phase-1 conventions, with two exceptions —
`PendingFoodPayment` and `PendingDraftPick` carry no `initiated_by_id`: closed decision frames
whose pusher identity is either irrelevant (a draft pick) or already encoded in `resume_kind`):

**Playing cards.** `PendingPlayOccupation` (a commit-terminated host; `cost: Resources` is the
route-supplied play cost, set at push — Lessons computes `occupation_cost`, a granting card sets
its own; one `CommitPlayOccupation` per playable hand card, no decline — placement legality
guaranteed one) and `PendingPlayMinor` (one `CommitPlayMinor` per playable hand minor ×
"/"-alternative × payment-frontier point; also no decline — *optionality lives at the parent*:
the frame is pushed only after the player chose the minor branch, exactly as `PendingSow` is
pushed only after choosing sow). Minors reach `PendingPlayMinor` from four entry points: the
Major/Minor Improvement space, House Redevelopment's optional second step (both via
`PendingMajorMinorImprovement`), Basic Wish for Children's optional second step, and Meeting
Place.

Both executors flip their host to the after-phase (firing the `after_play_*` autos) **before
running the card's `on_play`** — load-bearing for an `on_play` that pushes a primitive frame
(Shifting Cultivation → `PendingPlow`): the host must be flipped while it is still on top, so
the pushed child lands on the already-"after" host. Because the hand→tableau move precedes the
flip, an occupation-counting after-auto (Education Bonus) sees the new card; because after-
*triggers* are surfaced later by the enumerator, they see the post-`on_play` state either way.

**Space hosts.** `PendingActionSpace` (the generic atomic host, §2), `PendingSubActionSpace`
(the generic Delegating host — replaced the deleted per-space `PendingFarmland` /
`PendingFencing` classes; its child is dispatched by `space_id`: farmland → plow, fencing →
build-fences, major_improvement → the composite, lessons → play-occupation),
`PendingMeetingPlace` (single-optional Proceed-host; always pushed in card mode — even with no
playable minor — so space-hooking cards still fire), `PendingBasicWishForChildren` (and-then
Proceed-host: mandatory family growth, then optional minor; the Family game keeps the atomic
resolver and never pushes it — urgent_wish stays atomic in both modes today).

**Primitives.** `PendingFamilyGrowth` — the family-growth sub-action extracted as a reusable
commit-terminated host (parameter-free `CommitFamilyGrowth`; the newborn's space comes from
`initiated_by_id`). Pushed by Basic Wish today; the card-granted-growth gap (§6) is about the
*placement*, not this frame.

**Cost & food.** `PendingChooseCost` (the two-step payment menu for builds where geometry ⟂
payment, §5; a closed frame — frozen `payments` tuple + the underlying `action_kind`, no
phase/triggers/Stop) and `PendingFoodPayment` (the raise-only food-raising frame, §5; also
closed — `food_needed`, `resume_kind`, `reserved: Cost`, and the stored commit `action` for the
"rerun" continuation).

**Phase hosts.** `PendingPreparation` (start-of-round host, one per *owning* player,
non-starting player pushed first so the starting player decides first; `start_of_round` autos
fire at its push, triggers via its enumerator, `Proceed` pops — no after-phase),
`PendingHarvestField` (transient field-phase host: pushed, autos fired per player, popped —
all inside `_resolve_harvest_field`, so it never reaches a returned state and never surfaces a
decision; `player_idx=None` like `PendingReveal`), `PendingDraftPick` (above), and
`PendingCardChoice` (the forced-pick frame of mandatory-with-choice, §2 — options only, no
decline; a single-option frame auto-resolves via singleton-skip).

**Grant wrappers.** `PendingGrantedBuildFences` — the choose-or-decline parent for an *optional*
granted Build Fences (Field Fences): offers `ChooseSubAction("build_fences")` or `Stop`
(declining), pushing the real multi-shot `PendingBuildFences` with the *card's* provenance so
its discounts scope correctly. This is the template for optional grants of a mandatory-shaped
primitive: the inner frame keeps its "must do ≥1" shape; **declining lives at the parent's
choose+Stop, never a per-frame flag** (ENGINE_IMPLEMENTATION.md §2 invariant 3's corollary).

### Card-only fields on Family frames

Where a card mechanism needed state on a frame the Family game also uses, the field defaults to
the Family-constant value and is canonical-skipped:

- **`PendingBuildFences`**: `build_fences_action: bool = True` (literal action vs a card-effect
  build — free-fence seeds read it), `accrued_cost: Resources` + `free_fence_budget: int` (the
  Cards deferred-tally, §5), `restrictions: FenceRestrictions` — a hashable *descriptor* (never a
  callback — that would break hash/serde) the pasture enumerator filters by: `max_pastures`,
  `exact_size`, `forbid_subdivision` (Mini Pasture: a mandatory free new 1×1,
  `FenceRestrictions(exact_size=1, forbid_subdivision=True, max_pastures=1)`).
- **`PendingBuildRooms` / `PendingBuildStables`**: `build_rooms_action` / `build_stables_action`
  flags (same purpose).
- **`PendingPlow`**: `must_preserve_base: bool = False` — a granted plow that precedes a
  mandatory base plow restricts its cells to `safe_plow_cells` (a per-cell two-plow simulation,
  not a count — plowing is adjacency-constrained and can open new targets; `_can_plow_twice` is
  the existence gate); `max_plows: int = 1` + `num_plowed: int = 0` — the bounded multi-shot
  granted plow ("plow up to 2 fields": commit per cell, `Proceed` to finish early), making
  `PendingPlow` the fourth multi-shot host.
- The seven Proceed-host space parents (five Family + Basic Wish + Meeting Place) carry the
  derived `subaction_started` property (§2 — not a field, so nothing to skip).

### The canonical default-skip mechanism

`canonical._DEFAULT_SKIP_FIELDS` lists every card-only field name; the serializer omits a listed
field **when it equals its dataclass default**. A Family state never sets any of them, so its
JSON is byte-identical to the pre-card engine — which is what the C++ differential gates
consume. A Cards state that sets one simply emits it. Current set: `mode`, `hand_occupations`,
`hand_minors`, `used_this_turn`, `used_this_round`, `fired_once`, `card_state`,
`future_rewards`, `draft_pools`, the three `build_*_action` flags, `accrued_cost`,
`free_fence_budget`, `restrictions`, `must_preserve_base`, `max_plows`, `num_plowed`.
**Adding a card-only field to a Family-reachable structure = default it to the Family-constant
value + add it here** — that is the whole checklist for staying byte-identical (plus the C++
port if the field can vary in Family, like `fences_in_supply`).

### UI-only card state: `agricola/cards/display.py`

The engine never reads this module. It surfaces CardStore state a human can't read off the
board, for `play_web.py`'s card serialization: live banked-VP emblems for the history-derived
scoring cards (`HISTORY_VP_CARDS` — the value reuses the card's own registered scoring term, so
it can never drift from what is scored) and plain state badges (Interim Storage's held goods,
Moldboard Plow's plows left). Cards whose bonus is derivable from public state (Loom) are
deliberately excluded.

---

## 5. Costs, food & capacity

Three layers, each answering a different question. The **cost-modifier chokepoint** answers
"what are the ways to pay this build/play cost, given the player's cost cards?"
(COST_MODIFIER_DESIGN.md). The **food-payment layer** sits above it and answers "can/how does the
player *raise* the food component by liquidating crops and animals mid-turn?"
(FOOD_PAYMENT_DESIGN.md). The **capacity modifiers** are a small third seam inside animal
accommodation. Build Fences gets its own subsection — it is the one action whose payment model is
mode-branched.

### 5.1 The cost-modifier chokepoint: `effective_payments` / `can_pay`

Without a chokepoint, cards that change what a build costs (Bricklayer, Frame Builder,
Millwright, …) would need edits at scattered cost sites in both legality and mechanics. Instead,
every cost-modifiable action resolves its payment through one function pair in `legality.py`:

- **`effective_payments(state, idx, ctx) -> list[PaymentOption]`** — the Pareto-minimal set of
  ways to pay. Consumed by enumerators (one commit per payment) and, transitively, by the debit.
- **`can_pay(state, idx, ctx) -> bool`** — the short-circuiting existence view, for legality
  predicates. It never builds the full frontier: base first (the Family fast path), then formula
  bases × conversion variants × reductions, then routes, stopping at the first affordable hit.

A **`PaymentOption`** (`agricola/cost.py`) is either a `Resources` vector (spend these goods) or
a **`ReturnImprovement(improvement_idx)`** — a non-resource route that pays by returning a major
you own (Cooking Hearth via Fireplace, the built-in). Routes carry no resource cost, so they skip
the pipeline and enter the frontier directly, Pareto-incomparable to every resource payment.

A **`CostCtx`** is everything the action contributes: `action_kind` (the registry key), `base`
(the printed cost, computed by the action's adapter), and the discriminators a modifier might
read — `to_material`, `num_rooms`, `major_idx`, `card_id`, `space_id`, `build_index`, and
`reserved_animals` (the cost's own animal portion, read only by the food layer — 5.3). One flat
type for every action; per-action adapters build it: `_renovate_ctx`, `_build_room_ctx`,
`_build_stable_ctx` (base caller-supplied — the one cost still stored on a frame,
`PendingBuildStables.cost`, because Side Job 1 wood vs Farm Expansion 2 wood vs card grants 0 is
push-time intent, not derivable), `_build_major_ctx`, `_play_minor_ctx`, `_build_fence_ctx`.

**The pipeline**, in `effective_payments`:

1. **Resource bases** — the printed `ctx.base` plus one alternative base per owned, applicable
   *formula* card. Bases never combine (the player uses at most one formula).
2. **Conversions** — each owned conversion's budgeted generator applied **exactly once, in
   `order` (producers before sinks)** to the growing candidate set (`expand_conversions`).
   Applying each once respects its own budget (its `expand1` already emits all 0..max variants),
   while the ordering still lets a sink consume a feeder's output (clay→wood→grain chains;
   Millwright is the unique sink today). A test-only guard asserts this equals the full
   budget-respecting closure (COST_MODIFIER_DESIGN.md §4.7) — the backstop for the
   decks-A–E-only verification of the chaining claim (§8).
3. **Reductions** — every owned reduction folded over each candidate as a signed delta, floored
   at 0 per component after each.
4. **Filter + frontier** — keep the payable candidates (payable, not merely affordable — see
   5.3's gate↔frontier agreement) plus the takeable routes, then
   **`pareto_min_over_goods`**: prune resource payments dominated component-wise over the seven
   goods *and nothing else* (never an attached reward, never the route tag), de-duplicate, keep
   all routes.

Stacking rules are **emergent**, not hand-coded: a reduction applies to every base and every
conversion variant (reductions dominate); two formulas never combine (separate bases); two
conversions' variants are typically Pareto-incomparable (each survives); conversions-before-
reductions is the order that makes "1 building resource less" apply to the post-substitution
vector, the ruling-consistent reading.

**Wide commits vs the two-step.** Where the payment is the action's only degree of freedom, the
chosen `payment` rides on the commit itself (a *wide* commit): `CommitRenovate(payment,
to_material)`, `CommitBuildMajor(major_idx, payment)`, `CommitPlayMinor(card_id, payment, cost)`.
Where geometry and payment are independent (rooms, stables), committing the cell resolves the
frontier and — only when a cost card makes it non-singleton — pushes **`PendingChooseCost`**
(the frozen payment menu; `CommitChooseCost(payment)` debits and pops back to the build host).
Singleton frontiers debit inline, so the frame never arises in Family. The Family game's one
multi-payment frontier is Cooking Hearth's clay-or-return-Fireplace, which predates cards and
rides the wide `CommitBuildMajor`.

**The renovate-target model.** `CommitRenovate.to_material` makes the renovation *target* a
commit parameter rather than "the next tier": `_legal_renovate_targets` yields the next tier
plus any `RENOVATE_TARGET_EXTENSIONS` additions (Conservator's wood→stone), `_renovate_ctx(p,
to_material)` prices each target, and `_execute_renovate` upgrades to exactly `to_material`.
The old stored `PendingRenovate.cost` and `PendingBuildRooms.cost` are **removed** — a stored
cost is a cache of a derived value that goes stale the moment a cost card makes it depend on
owned cards (ENGINE_IMPLEMENTATION.md §3's bucket-2 description predates this).

**Per-action conversion budgets.** A conversion capped *per build-action* rather than per build
(Millwright: "up to 2 grain per build-rooms/stables action") threads through three pieces: its
`expand1` reads the running spend from its own CardStore; `record_conversion_usage(action_kind,
state, idx, payment)` is called at each debit site (`_execute_build_room` / `_execute_build_stable`
/ `_execute_choose_cost`) to bank what the committed payment used; and the card's
`after_build_*` auto resets the counter. This is the CardStore per-action-state pattern (§4's
placement rule, third home).

### 5.2 Build Fences: the deferred tally — and the one mode branch

Fence cost is geometry-derived (1 wood per new edge, a function of the commits so far), the
action is multi-shot, and the free-fence cards discount *edges*, not a final bill — so fences
could not adopt the wide-commit or two-step shapes directly. The Cards model
(COST_MODIFIER_DESIGN.md §9):

- **Accrue, don't debit.** In CARDS mode `_execute_build_pasture` debits nothing per commit.
  For each commit it applies the free-fence sources **in fixed order** — (1) *positional* edges
  (`positional_free_edge_count`: owned cards' free-edge bitmaps ∪-ed, ∩ new edges — a positional
  edge never consumes budget), (2) the *per-action budget* on the frame (`free_fence_budget`,
  seeded at the build's start from `free_fence_budget_for`, decremented as used), (3) the
  *persistent pools* (`spend_fence_pools`, decrementing CardStore) — and accrues the still-paid
  wood onto `PendingBuildFences.accrued_cost`.
- **Settle → pay → grants at `Proceed`.** `_apply_proceed` calls `_settle_build_fences` before
  the after-flip: the whole-action bill (`accrued_cost.wood`) runs through `effective_payments`
  (`_build_fence_ctx`). A singleton frontier debits inline, zeroes the accrued bill (a
  re-entered flip cannot double-debit), and the caller fires the after-grants
  (`_enter_after_phase`). A multi-payment frontier (Millwright-on-fences) pushes
  `PendingChooseCost(action_kind="build_fence")` and defers — `_execute_choose_cost` then
  debits, zeroes, and *itself* resumes `_enter_after_phase`, preserving the settle→pay→grants
  order.
- **The running total keeps legality and settle in agreement.** During building, affordability is
  checked against `accrued_cost.wood + this_pasture_paid` — always a whole-action running total,
  never one pasture in isolation (`_build_fence_ctx`'s contract). That is what makes a
  per-action-capped conversion correct: Millwright's 2 grain counts once against the whole
  action at both points, with no during-building/settle divergence.
- **THE MODE BRANCH — the one place the cost refactor is not unconditional.** FAMILY mode keeps
  the old per-commit debit (the frontier is always a singleton there), branched explicitly on
  `state.mode` in `_execute_build_pasture`. Rationale (COST_MODIFIER_DESIGN.md §9.3): deferring
  Family's payment would change the mid-action states the trained Family NN encoder sees and
  force a semantic C++ change; the branch preserves Family byte-for-byte and keeps the C++ port
  mechanical. Every other cost-modified action resolves through the chokepoint *unconditionally*
  (in Family the chokepoint degenerates to the printed cost).
- **Placement-time anticipation.** `_legal_fencing` / Farm Redev's offer must know a wood-short
  build the budget would cover is available, before any frame exists: `_any_legal_pasture_commit`
  computes the budget the frame *would* seed and gates on the discounted cost. Consequently the
  **fence-scan cache serves only the Family game** — the projection key `(farmyard, wood,
  subdivision_started)` knows nothing of budgets or restrictions, so the cached path is guarded
  on `state.mode is GameMode.FAMILY` (+ default universe + no restrictions); Cards always
  computes fresh through the budget-aware `_check_entry_legal`.
- **The fence-piece supply is stored.** `PlayerState.fences_in_supply` tracks location 4 of the
  four places a fence piece can be (board / removed / on a card / supply). It is **stored, not
  derived** — the second accepted on-object deviation from "derived data, not cached data"
  (after `Farmyard.pastures`) — because Ash Trees moves pieces onto a card independently of
  building, so `15 − fences_built` is wrong once a card holds pieces. Decremented wherever a
  piece leaves supply (a wood-free edge still draws a supply piece — only pool pieces don't).
  In Family it always equals `15 − fences_built`, but its value *varies*, so it is serialized
  (not a skip-field) and the C++ `PlayerState` mirrors it — the one C++ touch of the fence
  slice. `helpers.buildable_fences` = `fences_in_supply + free_fence_pool_remaining` (pieces
  actually placeable); `stables_in_supply` stays derived.

### 5.3 Food payment: produce-then-pay above the pipeline

The card game has food costs (occupation plays, minors' food components, variant surcharges),
and Agricola lets a player convert goods/animals to food *at any time* — in practice, at the
moment food is owed. The design decision (FOOD_PAYMENT_DESIGN.md): liquidation is **not** a
conversion inside `effective_payments` — that pipeline is subtract-only and resource-only, so it
structurally cannot bank overshoot (a cooked boar yields 2–3 food against a 1-food debt) or
spend animals. Instead, a produce-then-pay layer sits above it:

**The affordability gate.** `_payable(state, idx, p, cost, reserved_animals)` = plain
`_can_afford` OR (`cost.food > 0` and `_liquidatable_to`). `_liquidatable_to` requires every
non-food component on hand outright (liquidation only produces food), sets the cost's own
animal portion (`reserved_animals`, from the `CostCtx`) aside before counting animals as fuel,
and checks max-producible food at the player's `cooking_rates` against the shortfall. A
`food == 0` cost takes the `_can_afford` fast path — every Family build cost, so Family never
touches this layer. `_payable_occupation` additionally simulates firing an owned
occupation-food-source (§3) before re-checking.

**The execution frame.** When a chosen cost's food exceeds food on hand, the executor
(`_execute_play_occupation` / `_execute_play_minor` / the build-major path) pushes
**`PendingFoodPayment(food_needed, resume_kind, reserved, action)`** instead of debiting. The
frame is **raise-only**: its enumerator offers the `food_payment_frontier` of conversion bundles
(one `CommitFoodPayment` per Pareto point, run over the player's goods MINUS `reserved` — the
cost's own convertible goods, so liquidation can never cook a good the cost still needs);
`_execute_food_payment` adds the produced food (banking any overshoot — "cannot make change" is
the rule, overshoot is the player's), **debits nothing**, pops, and resumes. The resumed action
debits the full cost itself from the now-sufficient supply. `owe` is derived live
(`food_needed − food`), never stored.

**Continuation as data.** A frozen frame can't hold a closure, so the continuation is
`resume_kind`: `"rerun"` re-dispatches the stored commit through `COMMIT_SUBACTION_HANDLERS`
(the unified path — the executor's own food guard now passes, so it debits and completes; this
is also why the guard is safely **re-entrant**); any other value is a card id with a registered
grant continuation in `FOOD_PAYMENT_RESUMES` (Ox Goad: debit the food, push the plow). A "rerun"
is *not* wrapped in `_fire_subaction_before_auto` (the re-dispatched executor owns its firing);
a grant resume *is* (it leaves a fresh sub-action leaf on top).

**The closed-frame rule.** `PendingFoodPayment` surfaces only its frontier commits — no
triggers, no Stop. Its enumerator **asserts the frontier non-empty**: the gate
(`_liquidatable_to`) guaranteed feasibility over the same reduced goods, so an empty frontier is
a gate↔frontier mismatch and must fail loud.

**Gate↔frontier agreement — the load-bearing correctness requirement.** Liquidation-awareness
must appear in *both* `can_pay`'s gate *and* `effective_payments`' affordability filter (both
call `_payable`), or a card the gate marks playable would surface zero payment buttons — a
playable-card-with-no-actions dead state. The same agreement runs one level up: the
play-occupation enumerator withholds a commit whose cost isn't currently payable (forcing a
food-source trigger like Paper Maker to fire first), so committing never pushes an
empty-frontier frame.

**Accepted incompleteness** (FOOD_PAYMENT_DESIGN.md §10): a food-*rich* player is never offered
"spend grain anyway to preserve food" — liquidation only surfaces when food is short. Judged a
non-issue strategically (food is the most liquid good), recorded so it isn't rediscovered as a
bug.

### 5.4 Capacity modifiers

`helpers.extract_slots` — the capacity decomposition under every accommodation frontier
(markets, breeding, harvest feed, scheduled-animal collection) — reads the two `capacity_mods`
folds (§3): `num_flexible = standalone_stables + house_pet_capacity(p)` (max-fold, Family
default 1) and each pasture's capacity + `pasture_capacity_bonus(p)` (sum-fold, Family
default 0, applied after the stable doubling). Every frontier consumer inherits card capacity
automatically.

**The projection-key contract (live, not hypothetical).** The Pareto/feeding/fence helpers have
default-on projection-keyed caches (ENGINE_IMPLEMENTATION.md §4-note / §5;
FRONTIER_OPT_DESIGN.md §2.1), correct only while the key is the complete input set. The two card
mechanisms that broadened what these helpers read each satisfied the contract differently — the
two available patterns:

- **Capacity mods: key on the post-fold values.** The accommodation caches
  (`_animal_points_cached`, `_phi_cached`) are keyed on `extract_slots`' *outputs*
  (`caps_tuple`, `num_flexible`) — computed downstream of the capacity folds — so a capacity
  card changes the key itself and staleness is impossible by construction.
- **The fence budget: gate the cache to Family.** The fence-scan key `(farmyard, wood,
  subdivision_started)` cannot see budgets or restrictions, so the cached path is guarded to
  Family mode (5.2) and Cards computes fresh.

**Any card that adds an input to a cached helper must do one of these** — re-key on post-fold
values, or gate the cache off where the new input can vary — and extend
`tests/test_frontier_opt.py`'s corpus to cover it.

---

## 6. Rulings & idioms

The rulings are *correctness decisions* — settled by the game's rules (the user is the
authority), never by implementation convenience. The idioms are recurring code patterns whose
naive alternative is a known bug. `CARD_AUTHORING_GUIDE.md` develops most of these with worked
examples; this is the reference list.

### Rulings

- **"Each time you use [space]" = the before-window** (`before_action_space`), unless the text
  literally says "after"/"immediately after". Taking the space's mandatory work closes the
  window and implicitly declines unfired before-triggers — the enforce-first rule (§2). Never
  resolve a textual *silence* about ordering with a convenience assumption: resolve it by the
  rules default, or defer and ask.
- **After-automatic effects fire once per action, at the work-complete flip** — never between
  the pieces of a multi-shot build. A per-action quantity ("1 food per room built this action")
  is computed snapshot-before / compute-after, with the snapshot in CardStore (Shepherd's
  Crook; Millwright's budget reset).
- **A granted sub-action is optional** unless the card says "you must" — even when worded like a
  command. Optional grants register as triggers (declinable); pure-goods "you can" grants with
  no downside may be autos. Optionality lives at the **parent's** choose+Stop
  (`PendingGrantedBuildFences`), never a per-frame skip flag on the primitive. Always gate a
  grant's eligibility on the action being legal *and affordable now* (`_can_plow`,
  `_can_build_stable(state, p, cost)`, `_can_renovate`, `_can_bake_bread`, …) so firing can
  never strand the player.
- **A granted plow before a mandatory base plow must not strand it**: restrict its cells to
  `safe_plow_cells` via `PendingPlow.must_preserve_base`, gate eligibility on
  `_can_plow_twice` (§4). Applied uniformly on Farmland *and* Cultivation — on Cultivation the
  restriction removes only strictly-dominated options (the grant spends a limited resource where
  the free base plow could take the cell), a dominance argument verified against the full card
  base (POST_COMPACTION_DETOUR.md §7).
- **Immediate animal grants have no accommodation path.** Only the markets, breeding, harvest
  feed, and the scheduled round-start collection (`_collect_future_rewards`) accommodate. To
  grant an animal at a market, bump the market pending's `gained` (routes through
  accommodation — Cowherd); never `p.animals + Animals(...)`. An immediate, un-accommodated
  grant is a defer. Scheduled animals (`schedule_animals`) are sound — same `pareto_frontier`
  machinery, decision-free best-kept.
- **Card-granted family growth: deferred on placement.** The user's ruling is that a
  card-granted newborn occupies *no action space*, but `_execute_family_growth` →
  `_resolve_wish_for_children` forces space placement — such cards wait for a
  `place_on_space=False` field. The room gate (`people_total < 5` and `< rooms`) is the
  caller's check, not the primitive's.
- **"X in supply" is a prerequisite, not a cost** — a HAVE-check (`MinorSpec.prereq` /
  `min_occupations`), never debited.
- **"/" in a cost: now supported for minors; "/" in a *reward* is not.** A printed
  alternative cost (Chophouse "2 Wood / 2 Clay") is `MinorSpec.alt_costs`; a state-scaling cost
  is `cost_fn`; an occupation's pay-on-play choice is a play-variant (§3). *(This supersedes the
  earlier batch-era ruling that any "/" cost is an automatic defer — commit a8e1ee2.)* Still
  unsupported: a minor whose "/" is in the *effect* (Canvas Sack's choose-a-reward) — no
  `PLAY_MINOR_VARIANTS` registry exists; defer (§8).
- **A conditional one-shot latch fires only at the two swept seams** (renovate, card play). A
  standing condition on anything else — a resource count (Hook Knife's "8 sheep") — never gets
  swept; defer rather than approximating with an action hook.
- **The harvest field-phase hook is auto-only** — `PendingHarvestField` never surfaces a
  decision, so a "you may…" field-phase card is a defer (§8).

### Idioms

- **Majors are not a `PlayerState` field**: owners live on
  `state.board.major_improvement_owners` (length 10, `None` or owner idx). Indices:
  Fireplaces (0, 1), Cooking Hearths (2, 3), Well 4, Clay Oven 5, Stone Oven 6, Joinery 7,
  Pottery 8, Basketmaker 9 (`agricola/constants.py`).
- **A pasture is not a `CellType`** — an empty fenced cell reads `EMPTY`. Use
  `helpers.enclosed_cells(farmyard)` / `farmyard.pastures`, never `cell_type` alone.
- **Space occupancy** = `get_space(state.board, sid).workers != (0, 0)` — *not*
  `not _is_available(...)`, which is also False for unrevealed spaces.
- **Accumulation reads**: `get_space(board, sid).accumulated` (a `Resources`, building spaces)
  vs `.accumulated_amount` (a scalar, food/animal spaces). `grain_seeds` = take 1 grain;
  `grain_utilization` = sow+bake (different spaces!); `day_laborer` = 2 food, not an
  accumulation space.
- **The player-edit idiom** (card modules can't import `_update_player` from `resolution.py` —
  module ordering; the accepted exception in ENGINE_IMPLEMENTATION.md §5):
  ```python
  p = state.players[idx]
  p = fast_replace(p, resources=p.resources + Resources(clay=2))
  return fast_replace(state, players=tuple(
      p if i == idx else state.players[i] for i in range(2)))
  ```
- **CardStore access**: `p.card_state.get(key, default)` / `p.card_state.set(key, value)`
  (immutable — `set` returns a new store).
- **Pushing a granted primitive**: `push(state, PendingPlow(player_idx=idx,
  initiated_by_id="card:<id>"))`; `PendingBuildStables(..., cost=Resources(), max_builds=1)`;
  `PendingPlayOccupation(player_idx, initiated_by_id, cost=Resources())` (a free occupation
  play — gate on `playable_occupations` non-empty). The engine seams fire the leaf's
  before-autos for you (§2's seam map).
- **"Nth person placed this round"** = `(people_total − newborns) − people_home` — subtract
  same-round newborns or the index inflates mid-round (the Catcher bug).
- **Round arithmetic**: harvest rounds {4, 7, 9, 11, 13, 14}; post-harvest rounds
  {5, 8, 10, 12, 14}. `_complete_preparation` order: refill → distribute `future_resources` →
  clear used-sets → collect `future_rewards` animals → push the start-of-round hosts.
- **Registry test assertions must be subset checks**, never exact-set — the next batch extends
  every registry (`HARVEST_FIELD_CARDS == {...}` breaks on unrelated work).

---

## 7. Implementing a card

The one-page process; the full how-to (reading a card, the pitfall checklist, the worked
example) is **`CARD_AUTHORING_GUIDE.md`**, and the batch-scale workflow tooling lives in
**`scripts/card_batch/`** (its README covers the triage/implement workflow generators).

**The loop:** enumerate (which cards of the target deck are unimplemented — a slug is
implemented iff it is in `OCCUPATIONS`/`MINORS`; `scripts/card_text.py "<name>"` prints
IMPLEMENTED / not) → triage (read the **verbatim** card text via `card_text.py` — never
paraphrase; classify timing → firing kind → primitives → template; decide implement or defer)
→ review (scrutinize ordering-sensitive cards, errata, "/"-costs) → implement → integrate.

**The cardinal rule: DEFER and ASK.** A card that doesn't clearly fit the machinery is deferred
to `CARD_DEFERRED_PLANS.md` (clustered by blocker, with a build proposal), not approximated. The
user understands the rules and interactions far better than a coding session; a deferred card
costs nothing, a plausible-but-wrong card costs trust. Defer indicators: ambiguous
timing/optionality; needs new shared infrastructure (§8's list); an immediate un-accommodated
animal grant; at-any-time effects; "/"-rewards; end-of-turn / return-home / after-harvest
timing; geometry beyond the fence universe; new shared action spaces; randomness inside `step`;
temporary workers; card-as-field / card-as-animal-holder.

**One module per card** (`agricola/cards/<id>.py`, registering at the bottom of its body) + one
test file (`tests/test_card_<id>.py`, whose **first line imports the module** —
`import agricola.cards.<id>  # noqa: F401` — so the test runs standalone before the card is
wired into `agricola/cards/__init__.py`). Wire into `__init__.py` at integration, not during a
parallel batch (a broken import breaks everything). Registry assertions: subset, never
exact-set (§6).

**Template catalog** — copy the existing module matching the card's shape:

| Shape | Exemplar module(s) |
|---|---|
| pure scoring term | `stable_architect` |
| on-play goods | `consultant` |
| passing (traveling) minor | `market_stall` |
| space-hook auto | `wood_cutter`, `geologist` |
| any-player auto | `milk_jug` |
| granted sub-action trigger | `assistant_tiller`; with route variants `cottager` |
| start-of-round | `scullery` (auto), `plow_driver` (trigger) |
| harvest-field auto | `scythe_worker`, `loom` |
| conditional one-shot latch | `manservant` |
| deferred goods / effect | `pond_hut` / `handplow` |
| CardStore state | `big_country`, `tutor`, `shepherds_crook` |
| mandatory-with-choice | `childless`, `seasonal_worker` |
| play-variant occupation | `roof_ballaster` |
| cost modifier | `bricklayer`, `frame_builder`, `millwright` |
| free fences | `briar_hedge` (positional), `hedge_keeper`-shape seed, `ash_trees` (pool) |
| restricted / optional fence grant | `mini_pasture` / `field_fences` |
| harvest-conversion with VP | `beer_keg`, `furniture_carpenter` |
| animal at a market | `cowherd` |
| occupancy override | `sleeping_corner`, `forest_school` |

**Integration checklist** (per batch): run the new card tests, wire `__init__.py`, archive any
deferred card's files to `archive/deferred_cards/` (archive, never delete), full suite
(`~/miniconda3/bin/python -m pytest tests/ -n 4 --dist worksteal`) with the C++ gates green
untouched, **update §1 Status below**, commit.

**The maintenance contract: a batch is not integrated until §1 is updated** — counts, deck
progress, and the stamp. This mirrors the `nn_models/REGISTRY.md` convention: "the run isn't
complete until the registry knows about it."

---

## 8. Boundaries — what deliberately does not exist

Each entry is a *decision with a reason*, not an oversight. A card blocked by one of these is a
defer (§7); building the missing piece is a design conversation with the user first
(`CARD_DEFERRED_PLANS.md` holds the concrete proposals).

- **No end-of-turn event.** One was added (Unit 4 of the space-host refactor) and then
  deliberately **removed** with Firewood Collector's re-deferral: the space-host pop coincides
  with turn end only because nothing player-controllable currently sits between an action's
  resolution and the turn ending. Once "at any time" effects exist, an end-of-turn hook fired at
  the pop lands one window too early (goods would still be spendable within the turn). End-of-
  turn timing and at-any-time modeling are co-dependent — design them together
  (`_apply_stop`'s comment; CARD_IMPLEMENTATION_PLAN.md's Firewood note).
- **No at-any-time standalone conversions.** The Foundations "preserving optionality" principle
  bundles conversions into the decision points that need their proceeds; food liquidation (§5.3)
  is that principle applied to food costs. A card whose conversion proceeds are a non-food good
  ("buy wood for food at any time") has no bundling point yet — defer.
- **No `PendingBeforeScoring`** (CARD_SYSTEM_DESIGN.md §7): end-game conversions whose proceeds
  are points (Sheep Walker) need a decision window between round 14 and scoring, coupled to
  arrangement-scoring questions (Organic Farmer). Flagged, unbuilt.
- **Events carry no payload.** `after_play_minor` etc. name an event, not the card played — so a
  card cannot distinguish *its own* play from a later one (Seed Almanac's deferral), and there is
  no newborns-gained event (Dung Collector). Adding payloads is a firing-API change; defer until
  a cluster justifies it.
- **No harvest feed/breed trigger events.** `PendingHarvestFeed`/`Breed` still carry no
  `triggers_resolved` (the Phase-1 deferral stands); harvest cards ride the auto-only
  `harvest_field` hook or the harvest-conversion registry. An optional feed/breed-window card is
  a defer.
- **No round-end / after-feeding / before-round-start hooks.** Designed in sketch, gated on the
  user (`CARD_DEFERRED_PLANS.md`); `resource_analyzer` (deck E) is deferred on exactly
  "before the start of each round".
- **Cost-model gaps** (each flagged so the model isn't mistaken for complete): a
  payment-*source* restriction (Carpenter's Bench "use only the taken wood") — `effective_
  payments` has no concept of where goods came from; a *minimum-spend* filter (Stone Company);
  a per-game Nth-fence ordinal (Carpenter's Apprentice — needs a cumulative cross-action
  segment counter); raze-and-rebuild (Overhaul — a new primitive). And a scope caveat: the
  conversion-chaining claims (§5.1 step 2) were verified against decks A–E only; the §4.7
  closure-equality guard is the backstop as new conversion cards land — promote it to the full
  multi-card form then.
- **Grocer / conversion-reachability legality** (CARD_SYSTEM_DESIGN.md §15 — the full analysis,
  with a verified 7-step worked fixture and seven candidate approaches; read it before touching
  this). The unique problem: Grocer's goods-on-the-card make *affordability* a reachability
  question over interleaved buys and spends, where componentwise Pareto dominance is unsound
  under fungibility. The *storage* half now exists (`interim_storage` holds goods on a card in
  CardStore); the **legality half — card-held goods participating in affordability — is the open
  part**, and it will shape how all buy-conversion cards land.
- **Capacity negation.** `Milking Place` (D012) — "you can no longer hold animals in your house,
  not even via another card" — must force the house fold to 0, which the max-fold cannot
  express; it explicitly negates Animal Tamer, so wire the negation as a separate check when it
  lands (capacity_mods' docstring flags this).
- **No speculative placement-time legality** (COST_MODIFIER_DESIGN.md A7). A grant that fires
  *after placing* is handled at the build; *deciding to place* based on a not-yet-fired grant's
  proceeds is the deferred gap (the Pan-Baker-enables-Potter compound case in
  ENGINE_IMPLEMENTATION.md §6 is the same shape). `_payable_occupation`'s single-source
  simulation and the fence-budget anticipation are the two narrow, load-bearing exceptions
  built so far.
- **C++ has no card content.** The C++ engine is Family-only — `FireTrigger` throws, no
  registries, no card frames. Every *Family-shape* card refactor **is** ported and
  differential-gated (§0); there are **no card-mode differential gates yet** — porting the card
  game to C++ is a future project the harness makes safe.
- **The typing unions are documentation, not dispatch.** `pending.PendingDecision` and
  `actions.Action` are typing-only aliases with no runtime role — dispatch is by
  isinstance/table. Keep them in sync when adding a frame/action (they have lagged before), but
  the authoritative census is `PENDING_ENUMERATORS` / `COMMIT_SUBACTION_HANDLERS`.

---

## 9. Doc map

Every card-system document, its role, and when to read it. **This file is the
reference-of-record for the as-built machinery**; the design records keep rationale. The live
docs sit at the repo root; the design + batch records live under `design_docs/cards/`.

| Doc | Role | Read when |
|---|---|---|
| `CARD_AUTHORING_GUIDE.md` | **LIVE how-to** — reading a card, pitfalls, worked example, discipline checklist | before implementing any card |
| `CARD_IMPLEMENTATION_PROGRESS.md` | **LIVE per-card ledger** — two-pass mechanics classification, adjudicated | looking up a specific card's status/tags |
| `CARD_DEFERRED_PLANS.md` | **LIVE decision surface** — defer clusters, infra proposals, open user questions | deferring a card; planning infra |
| `CARD_SYSTEM_DESIGN.md` | design record — terminology (§0), firing architecture rationale, open questions (§13), **Grocer (§15)** | rationale questions; anything touching buy-conversions. Its §2 Environment/observe sketches are superseded by hands-on-`PlayerState` |
| `CARD_IMPLEMENTATION_PLAN.md` | **FROZEN** plan + ledger — the original build plan, per-category canonical code, decisions log | provenance; the Firewood/end-of-turn note. Its §II sketches are partly superseded by as-built deviations; "Acorns Basket deferred" is stale (implemented) |
| `COST_MODIFIER_DESIGN.md` | design + red-team record for §5.1/5.2 — worked frontier traces (§4), attacks A1–A7, the fence slice (§9) | changing the cost pipeline; any new cost card shape |
| `FOOD_PAYMENT_DESIGN.md` | design record for §5.3 — the raise-only decision, banking arithmetic, red-team | changing food payment; Ox-Goad-shaped cards |
| `SPACE_HOST_REFACTOR.md` / `SUBACTION_HOOK_REFACTOR.md` | **frozen refactor records (LANDED)** — the host lifecycle's design + staging | archaeology of §2's mechanisms |
| `POST_COMPACTION_DETOUR.md`, `CARD_BATCH_AB_SUMMARY.md`, `CARD_BATCH_TRIAGE.md`, `CARD_TRIAGE_CDE.md`, `PAY_FOOD_PLOW_CARDS.md` | historical batch records | provenance of a specific batch/fix (enforce-first: POST_COMPACTION_DETOUR §2) |
| `ROOM_CARDS.md` / `STABLE_CARDS.md` | catalog analyses (cards touching rooms/stables) | planning those clusters |
| `scripts/card_batch/README.md` | the batch workflow tooling | running a triage/implement batch |
| `CARD_BATCH_HANDOFF.md` (gitignored) | session-local working notes | resuming a batch session |
