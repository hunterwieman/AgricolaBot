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
2. **The one document a card-implementation session reads first.** Machinery (§2–§5b), rulings and
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
5b. The harvest timing windows — the ladder, the take & its manifest, take-modifiers, skips
5c. The round-end timing ladder — the seven-step walk between the last placement and the round transition
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
  frame on an atomic space, host a harvest window, host round start), a hosting predicate
  (`should_host_space`, `should_host_preparation`, `owns_window_card`) consults a
  registration-time index of card ids and short-circuits on the empty set — the Family game
  never constructs the frame at all (§2, §3, §5b).
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

> **Last updated: 2026-07-13, HEAD `c4f813d`.** A card batch is not integrated until this
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

- **Implemented & registered: 348 cards — 105 occupations + 243 minors** (Heresy Teacher
  un-implemented 2026-07-13, ruling 53; the livestock-provider batch — Early Cattle,
  Pigswill, Automatic Water Trough, Bartering Hut — landed 2026-07-13, introducing
  `PendingAccommodate.min_keep`; the goods-provider batch — Vegetable Slicer, Canvas Sack,
  Beating Rod, Hauberg, Bee Statue, Water Gully, Muddy Waters — landed 2026-07-13, introducing
  two additive seams: the `upgrade_to_cooking_hearth` event and `MinorSpec.cost_labels`;
  the **deck-B/E scoring-and-timing batch** — Heirloom, Nave, Land Register, Misanthropy, Rod
  Collection, Upholstery, Herbal Garden, Beaver Colony, Hook Knife, Ox Skull, Cookery Lesson —
  landed 2026-07-13, introducing FOUR additive seams: `register_empty_pasture` (a pasture
  capacity REDUCTION folded into `extract_slots`), `register_boundary_one_shot` (the
  decision-boundary one-shot sweep), `register_before_scoring` (the minimal BEFORE_SCORING
  decision window, reusing `PendingCardChoice`), and `register_animal_cook_reaction` (the
  animal-cook seam at the two work-phase cook sites); Muck Rake deferred (scoring-time animal
  arrangement), Breed Registry postponed (game-long sheep provenance), Writing Chamber marked
  not-to-be-implemented), spanning decks A–E
  (deck = 168 cards interleaving Base-Revised + one expansion: A=Artifex, B=Bubulcus,
  C=Corbarius, D=Dulcinaria, E=Ephipparius; catalog 420 + 420 total). All firing machinery of
  §2–§5b is live and exercised; the full pytest suite and the C++ Family differential gates are
  green as of the last integrated batch.
- **The harvest timing-window system landed (the 2026-07-03 → 05 arc)**: the window ladder +
  virtual walk, the take-occasion manifest, the take-modifier fold-ins, harvest skips, and
  feeding income. **§5b is the machinery reference**; `design_docs/cards/HARVEST_WINDOWS_DESIGN.md`
  is the design of record (its §12 is the as-built code map), `HARVEST_HANDOFF.md` (repo root)
  preserves the session reasoning behind every ruling, and the 19 dated rulings live in
  `CARD_DEFERRED_PLANS.md`. The legacy `harvest_field` seam is deleted (§5b, last subsection).
- **The four follow-on seams landed (`ff874ba`)**, all Family-inert: BREED-frame triggers
  (ruling 20 — events `"breeding"` / `"breeding_outcome"`) + the breeding-outcome payload
  event, the per-occasion trigger host `PendingHarvestOccasion` (the loud guard is gone),
  replace-kind take-modifiers (`TakeFold` — Grain Thief's shape), and the
  `feeding_requirement` chokepoint + `PendingSow.max_fields`. All are in §5b/§3/§4.
- **The 2026-07-05 → 06 waves landed** (the seam-consumer cards, the after-harvest wave, the
  arrangement trio — Dolly's Mother / Mineral Feeder / Beer Stall; rulings 18–41 in
  `CARD_DEFERRED_PLANS.md`, reasoning in `HARVEST_HANDOFF.md` Part II).
- **The round-end ladder landed (2026-07-12; rulings 49–51, `3146fe6`)**: a second, smaller
  timing ladder (`agricola/cards/round_end.py`) between the work phase's last placement and
  the round transition, with six member cards — **§5c is the machinery reference**. Ruling 50
  also created the durable DEFERRED-FOR-AMBIGUITY category in `CARD_DEFERRED_PLANS.md`
  (holding Perennial Rye + Lumber Virtuoso).
- **The converter cluster landed (2026-07-12; rulings 34–39, `f084826`)**: the
  generalized in-harvest raise frame — `food_payment_frontier` takes span-converter
  subsets and ruling 39's post-breed cooking floors as memo-safe arguments (both applied
  OUTSIDE the cached core); `HarvestConversionSpec.frontier_fire` marks pure
  building-resource converters (the craft majors, Stone Carver, Paintbrush's food
  branch); `register_free_span_trigger` covers ruling 36's whole span in one call (the
  feed payment frame rides the card's own conversion entry — one shared
  once-per-harvest budget across every surface). Braid Maker E109 deferred (the
  play-minor major-build gap). Feeding itself stays UN-generalized (ruling 34) and
  Gypsy's Crock / Cooking Hearth Extension stay parked (rulings 35/42).
- **FEED/BREED banding landed (2026-07-12; ruling 40, `479135e`)**: the harvest walk's
  three phase segments each resolve whole-phase-per-player (the 26-position virtual walk;
  one payment/breeding frame per band pass, per-pass feeding income, the cursor carried
  while band frames are up — Family pauses at 14/17/20/23). The first Family-visible
  harvest-shape change; the C++ twin was re-ported in the same commit and all 139
  differential gates are green. The encoder's `has_fed` is band-aware (value-identical —
  no ENCODING_VERSION bump).
- **The card-fields system landed (2026-07-12; rulings 42–48)**: `agricola/cards/card_fields.py`
  is the machinery module — the spec registry, the CardStore per-stack (grain, veg, wood,
  stone) state, the ruling-45 count helpers, sow integration (`CommitSow.card_sows` +
  `PendingSow.crops_only`, both Family-default-skipped on the wire), the take's
  `source="card:<id>"` manifest entries, fold-key extension ("card", id, stack), and the
  NON-take-removal chokepoint (`remove_card_crop` / `register_card_crop_removal` — ruling 44;
  Craft Brewery × Crop Rotation Field is the proven consumer pair). All nine "this card is a
  field" cards are implemented; every implemented "field(s)"-reading card was swept to count
  card-fields (ruling 45), while "field tile" readers stay grid-only (ruling 32). Field
  Cultivator is automatic-take-the-maximum (ruling 41). Cooking Hearth Extension is deferred
  alongside Gypsy's Crock (ruling 42).
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
**`PendingChooseCost` / `PendingFoodPayment` / `PendingCardChoice` / `PendingDraftPick` /
`PendingAccommodate`** (closed
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
the coarse `after_build_improvement` ("any improvement built" — fired by
`_execute_play_minor` and the major-build path for cards like Junk Room), and the narrow
`upgrade_to_cooking_hearth` (fired only in the return-Fireplace branch of `_execute_build_major`
— building a Cooking Hearth by returning a Fireplace, which no post-build state can reconstruct;
Vegetable Slicer's seam). The harvest adds its
own event family: every simple harvest-window id is a literal event string (`start_of_harvest`,
`after_feeding`, `end_of_harvest`, …), plus the during-window `field_phase` and the
feeding-income `feeding` — §5b. (The old `harvest_field` event is deleted.)

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
| Harvest windows | the window-id autos + triggers | `engine._advance_harvest` — the virtual walk (§5b): per window, autos fire for both players SP-first, then a per-player `PendingHarvestWindow` choice host is pushed for each player with an eligible trigger (SP decides first) |
| Harvest field phase | `field_phase` autos + triggers; the take | `engine._field_phase_step` (§5b): autos, then `PendingFieldPhase` when the player has a during-window decision (an eligible trigger or a usable choice-bearing take-modifier), else the inline take — with a post-take re-check that hosts the frame when take income enabled a trigger |
| Harvest occasions | the per-occasion autos | `apply_harvest_occasion_autos`, wherever a `HarvestOccasion` is emitted — the walk's inline take, `_execute_field_take`, or a bare card-driven `field_take` (§5b) |
| Feeding income | `feeding` autos | `_initiate_harvest_feed_for(band_player)` — one player per FEED band pass (ruling 40), the autos firing before that player's payment frames are pushed (§5b) |
| Round-end windows | the six round-end window ids (autos + triggers) | `engine._advance_round_end` — the seven-step walk of §5c (window-major, no banding, harvest-skip guard OFF), reusing `_process_simple_window` + the `PendingHarvestWindow` choice host |
| Renovate / card play | the one-shot conditional sweep | `_fire_ready_one_shots` (§3), called after a renovate applies and after any card is played |
| Decision boundary | the boundary one-shot sweep | `engine._fire_boundary_one_shots` (§3), at both `_advance_until_decision` return points, after `_reconcile_accommodation` settles — resource/animal-count one-shots (Hook Knife) |
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
- **`register_minor(card_id, *, cost=Cost(), alt_costs=(), cost_labels=(), cost_fn=None,
  min_occupations=0, max_occupations=None, prereq=None, passing_left=False, vps=0,
  on_play=_noop)`** →
  `MINORS: dict[str, MinorSpec]`. The pieces:
  - `cost: Cost` — the spendable price (Resources + Animals), paid at play.
  - `alt_costs: tuple[Cost, ...]` — the printed **"/"-alternatives** (Chophouse "2 Wood / 2
    Clay"): the ways to pay are `(cost,) + alt_costs` and the player pays exactly one; each
    alternative is enumerated as its own `CommitPlayMinor` (§5). Not combinable with `cost_fn`.
  - `cost_labels: tuple[str, ...]` — optional per-alternative labels **parallel to**
    `(cost,) + alt_costs` (same length). When a card's REWARD is coupled to which alternative it
    paid (Canvas Sack "*paying grain/reed … get 1 vegetable/4 wood*"), the enumerator tags each
    alt-cost `CommitPlayMinor` with its label (carried on the commit's `variant`), and
    `_execute_play_minor` threads it into a 3-arg `on_play(state, idx, label)`. Crucially the cost
    is the real alternative — it still runs through `effective_payments`, so it stays
    cost-modifier-visible. This is the deliberate contrast with a play-variant *surcharge*
    (`register_play_minor_variant`), which is an effect price that bypasses cost modifiers; a
    genuine "/"-cost with a coupled reward must use `cost_labels`, never the surcharge. Default
    `()` → the reward doesn't depend on the alternative (ordinary `alt_costs` — Chophouse).
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
  the "paid option" principle (FOOD_PAYMENT_DESIGN.md §8).
- **`register_play_minor_variant(card_id, variants_fn)`** → `PLAY_MINOR_VARIANTS` — the minor
  analog (built 2026-07-06 for Facades Carving; user ruling: on-play optional choices surface
  WIDE). Same `variants_fn` signature; each variant's surcharge is folded into the commit's
  `payment` at enumeration (cost *modifiers* never see it — a discount reduces the card's cost,
  not the effect's price), and the variant threads to a 3-arg `on_play`. Consumers: Facades
  Carving, Plant Fertilizer, Petrified Wood (migrated from a deep on-play `PendingCardChoice`
  2026-07-13 — it predated the seam), and Automatic Water Trough (whose variants also carry a
  per-variant *eligibility* gate — the accommodation check — beside the surcharge). *(A stale
  note here previously said no minor equivalent exists; it misled the 2026-07-13 session.)*
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
- **`register_harvest_field_hook` is GONE** (2026-07-05, with the whole legacy `harvest_field`
  seam — `HARVEST_FIELD_CARDS`, `should_host_harvest_field`, `PendingHarvestField`). Harvest
  cards now register on the timing-window ladder: the printed instant's window id is the event
  (`register`/`register_auto` as usual) plus a `register_harvest_window_hook` index entry —
  see the `harvest_windows.py` block below and §5b.
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
  card is played**. A condition on *anything else* — a resource or animal count — is not
  reachable at those two seams; it belongs on the **decision-boundary** sweep below. Exemplar:
  `manservant`.
- **`register_boundary_one_shot(card_id, condition_fn, apply_fn)`** → `BOUNDARY_ONE_SHOTS`.
  The one-shot's *decision-boundary* sibling: `engine._fire_boundary_one_shots` runs it at
  **every agent-decision boundary** (both `_advance_until_decision` return points), rather than
  only the renovate/card-play seams — the home for a one-shot keyed to a **resource/animal count**
  that those two seams miss (Hook Knife's "when you have 8 sheep on your farm, get 2 points";
  sheep counts change at the market, at breeding, via cards). It runs **after
  `_reconcile_accommodation` settles**, so an animal-count condition sees the *housed* animals —
  the card's own condition still verifies accommodation (`accommodates`) so a transient
  over-capacity grant, at the boundary where its `PendingAccommodate` is still up, cannot fire it.
  Latches `fired_once` before applying (idempotent). Empty index → Family no-op / byte-identical.
  Exemplar: `hook_knife`.
- **`register_card_choice_resolver(card_id, resolver)`** → `CARD_CHOICE_RESOLVERS`.
  `resolver(state, player_idx, chosen_option) -> state` applies a `PendingCardChoice` pick and
  pops the frame itself. Pair with a `mandatory=True` trigger whose `apply_fn` pushes the frame.
- **`register_play_variant_trigger(card_id, variants_fn)`** → `PLAY_VARIANT_TRIGGERS`.
  `variants_fn(state, idx) -> list[str]` (empty = none legal now); expands the card's trigger
  into per-variant `FireTrigger`s (§2). Exemplars: `scholar`, `cottager`. **Both the atomic and
  the delegating space-host enumerators now expand these** (Cookery Lesson's cook-sheep/boar/cattle
  routes on the Lessons after-phase — the delegating expansion was added 2026-07-13, a no-op where
  no owned trigger is a variant trigger).
- **`register_before_scoring(card_id, options_fn)`** → `BEFORE_SCORING_CARDS`. The minimal
  before-scoring decision window: `engine._push_before_scoring_choice` runs at the BEFORE_SCORING
  boundary and, for each owning player (once — latched in `fired_once` at push) whose
  `options_fn(state, idx)` returns a non-empty option tuple, pushes a `PendingCardChoice`
  (`initiated_by_id="card:<id>"`) — reusing the existing choice frame + `register_card_choice_resolver`
  machinery. `step`'s terminal guard was relaxed to fire only on an EMPTY-stack BEFORE_SCORING, so a
  before-scoring frame is a valid step target. Offered only where a card makes an end-game
  animal-discard relevant (Ox Skull at exactly 1 cattle). Exemplar: `ox_skull`.
- **`register_animal_cook_reaction(card_id, react_fn)`** → `ANIMAL_COOK_REACTIONS`. A card reacting to
  an animal being COOKED (converted to food via a Fireplace/Cooking Hearth). `resolution.note_animal_cook`
  fires each owned card's `react_fn(state, owner_idx) -> state` at the two work-phase cook sites
  (`_execute_food_payment`, `_execute_accommodate`) right after the animal→food conversion — so "used a
  cooking improvement" is detected as the ACTUAL cook, never an animal-count change (an animal spent as
  a card cost / discarded / exchanged is not a cook). Cookery Lesson uses it to award its point for
  cooking on a Lessons turn, wherever the cook happens. Exemplar: `cookery_lesson`.

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
- **`register_stable_supply_removal(card_id, store_key)`** → `STABLE_SUPPLY_REMOVALS` — a card
  that removes stable pieces from its owner's supply *without building them* (Market Stall
  C54's play cost, "1 Stable from Your Supply"). The supply stays **derived**:
  `helpers.stables_in_supply(player)` = `4 − stables_built(farmyard) −
  stables_removed_from_supply(player)`, the removal count read from the card's own CardStore
  via `store_key`; `helpers.stables_built` is split out for built-count consumers (capacity,
  Tumbrel, the heuristic), since `4 − supply` would double-count removals as buildings. Chosen
  over a stored `PlayerState` field to keep the Family shape / canonical JSON / C++ untouched —
  the derived-not-stored default; the stored route stays available if reads get hot.

### `agricola/cards/capacity_mods.py` — animal capacity

Read by `helpers.extract_slots` (the accommodation decomposition every frontier consumes):

- **`register_house_capacity(card_id, capacity_fn)`** → `HOUSE_CAPACITY_MODS`. How many flexible
  (any-type, capacity-1) slots the *house* provides. Fold: **max over owned modifiers, starting
  from the default 1** (the house pet) — `house_pet_capacity`. Exemplar: `animal_tamer` (one per
  room).
- **`register_house_pet_negation(card_id)`** → `HOUSE_PET_NEGATIONS`. A card that *forbids*
  house animals outright: `house_pet_capacity` returns 0 for an owner, beating every raise —
  Milking Place's "you can no longer hold animals in your house, not even via another card"
  explicitly overrides Animal Tamer, which is why the negation is a separate check the max-fold
  is not asked to express. Playing a negation card also sets `animals_need_accommodation`, so a
  currently-housed animal is evicted through the standard keep-or-cook frame (§4's
  accommodation barrier).
- **`register_pasture_capacity(card_id, bonus_fn)`** → `PASTURE_CAPACITY_MODS`. A flat additive
  bonus applied to **every pasture's** final capacity (after the stable doubling — the card adds
  to the finished pasture, not inside the `2·cells·2^stables` formula). Fold: **sum over owned
  modifiers, default 0** — `pasture_capacity_bonus`. Exemplar: `drinking_trough` (+2).
- **`register_empty_pasture(card_id, qualifies_fn)`** → `EMPTY_PASTURE_CARDS`. The first capacity
  *reduction*: a card that forces one qualifying pasture to hold no animals ("at least one of your
  pastures must contain no animals" — Herbal Garden; "one of your pastures WITH stable cannot hold
  animals" — Beaver Colony). `qualifies_fn(pasture) -> bool` restricts which pastures can be the
  empty one (Herbal: any; Beaver: `num_stables >= 1`). `extract_slots` calls
  `reserved_empty_pasture_indices` and DROPS the smallest-capacity reserved pasture from the
  capacity list — dropping the smallest is optimal for max housing. Two rulings (2026-07-13): when
  both are owned, ONE empty pasture-with-stable satisfies both (the fold shares it); a member with
  no qualifying pasture imposes nothing. Owning one sets `animals_need_accommodation` on play
  (eviction, the Milking Place idiom). Exemplars: `herbal_garden`, `beaver_colony`.

The three folds are the first mechanism to make pasture capacities non-canonical (dependent on
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

Scope (re-drawn 2026-07-05 with the window system): the registry holds **only conversions the
card prints in the feeding phase**. Three cards that had been shoehorned into it despite other
printed timings — Cube Cutter, Winter Caretaker, Elephantgrass Plant — migrated to their printed
windows (`field_phase`, `end_of_harvest`, `after_harvest`; §5b). Furniture Carpenter is still
registered here pending its approved `end_of_harvest` anchor (the anytime-in-harvest converter
cluster, HARVEST_WINDOWS_DESIGN.md §10). Choice-free feeding-phase *income* is not a conversion
— it rides `register_auto("feeding", …)` (§5b).

### `agricola/cards/harvest_windows.py` — the harvest timing windows

The registration side of the window system; §5b has the mechanics and
`HARVEST_WINDOWS_DESIGN.md` the design of record:

- **`register_harvest_window_hook(card_id, window_id)`** → `HARVEST_WINDOW_CARDS` — the
  hosting index (the `should_host_space` pattern: empty → no frame ever built). Pairs with
  `register(<window_id>, …)` for an optional trigger or `register_auto(<window_id>, …)` for an
  automatic effect — the window id IS the event string. Registrable: every simple window, plus
  the sentinels `"field_phase"` (during-window triggers + pre-take flat autos) and `"feeding"`
  (**choice-free income autos only** — fired at the FEED entry, before the payment decision);
  `"breeding"` is not hook-registrable — there is no window frame to host at that sentinel;
  instead the breed frames host their own `"breeding"` / `"breeding_outcome"` triggers directly
  (§5b, ruling 20 — Stone Importer / Fodder Planter). A card may register in more than one
  window (Dentist).
- **`register_harvest_skip(card_id, skip_fn)`** → `HARVEST_SKIP_CARDS` — per-card window
  suppression predicates `(state, idx, window_id) -> bool` (§5b). Exemplars: `lunchtime_beer`,
  `layabout`.
- **`register_take_modifier(card_id, fold_fn, *, variants_fn=None, order=1,
  harvest_scoped=True)`** → `TAKE_MODIFIERS` — the field-phase take fold-ins (§5b): auto
  (`scythe_worker`) vs choice-bearing (`stable_manure`, `scythe`) vs replace-kind (a
  `TakeFold` with skipped cells — Grain Thief's shape). The list is kept sorted by `order`
  (replace < rigid < flexible), which fixes fold precedence — load-bearing for feasibility.
- **`register_harvest_occasion_auto(card_id, eligibility_fn, apply_fn)`** /
  **`register_harvest_occasion_trigger(..., *, variants_fn=None)`** → `HARVEST_OCCASION_AUTOS`
  / `_TRIGGERS` — the payload-bearing per-occasion registries, `(state, owner_idx, occasion)`
  signatures (§5b). Autos fire mechanically wherever an occasion is emitted
  (`apply_harvest_occasion_autos` returns `(state, fired_ids)`); triggers surface at the
  **`PendingHarvestOccasion`** host (§4), which `maybe_host_occasion_triggers` pushes
  right after the autos — registering a trigger also self-wires adapters into the generic
  trigger system, so the host's enumerator and `FireTrigger` dispatch serve it like any other
  trigger, reading the occasion off the frame. **A mandatory choice-free tier is an AUTO,
  never a forced offer** (ruling 21, 2026-07-05 — Potato Ridger's "with 4+ vegetables, you
  must do so" fires with no player input), and the host's `autos_fired` excludes a card whose
  automatic tier already reacted from also offering its optional tier on the same occasion.
- **`register_breeding_outcome_auto(card_id, eligibility_fn, apply_fn)`** →
  `BREEDING_OUTCOME_AUTOS` — `(state, owner_idx, outcome)` signatures over the
  `BreedingOutcome` payload (which newborns were actually PLACED); fired by `_execute_breed`
  with the breed frame still on top (§5b).
- **`register_feeding_requirement(card_id, fold_fn)`** → `FEEDING_REQUIREMENT_FOLDS` — folds
  `(state, owner_idx, need) -> need'` applied at the `helpers.feeding_requirement` chokepoint
  (Child's Toy's "your newborns require 2 food"; §5b).

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
  `future_rewards[slot].animals`; collected at round start by `engine._collect_future_rewards`,
  which grants them via **`helpers.grant_animals`** (add + flag). If they fit, nothing more
  happens; if they overflow the farm the **accommodation barrier** (below) surfaces a keep-which
  choice at the round's first worker placement — over-capacity round-start collection is the
  player's decision, not auto-trimmed. Exemplar: `acorns_basket`.

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

Exactly four card-new fields (plus the frames below riding the existing `pending_stack`):

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
- **`harvest_cursor: int | None = None`** — the harvest walk's resume index (§5b): set only
  while a frame pauses `engine._advance_harvest` mid-walk, `None` otherwise. It indexes the
  **virtual** ladder — the window ladder with the FIELD, FEED, and BREED bands each repeated
  once per player, starting player first (rulings 3 + 40) — decoded by
  `harvest_windows.walk_position(cursor, starting_player)`. Hash-included like every state
  field; skipped in `canonical.py` when `None`, but NOT Family-constant: a Family game carries
  it too while a payment/breeding frame is up (the banded walk — §5b), so mid-feed/mid-breed
  Family JSON emits it, mirrored by the C++ twin. Its sibling **`round_end_cursor: int | None = None`** is the same idea for
  the round-end ladder (§5c): the resume index into `round_end.ROUND_END_STEPS`, set only while
  a round-end window's choice frame is up, `None` the moment its segment completes — likewise
  hash-included, Family-constant `None`, default-skipped, no C++ change. The two cursors are
  distinct fields and coexist on harvest rounds (at different times — §5c).
  *(`harvest_cursor` replaced `field_triggers_offered`, the deleted two-stage-walk
  discriminator of the legacy `harvest_field` seam.)*

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
  - `harvest_conversions_used` (Phase-1) is the per-harvest scope, reset for both players at
    the harvest's fresh entry in `engine._advance_harvest` (moved 2026-07-05 from the field
    take — so a phase-skipping player still gets a fresh budget, and future
    anytime-in-harvest conversions start the harvest reset; §5b).
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
  **animals** (collected via `grant_animals` at round start, reconciled by the accommodation
  barrier below if they overflow — §3 schedules) and **effect-card ids** (round-start grant
  hooks). `FutureReward` is additive (`+` stacks animals and unions ids) and falsy when empty,
  which is what lets `_complete_preparation` skip the whole branch object-identically in Family.
- **`fences_in_supply: int = 15`** — stored, not derived; the one card field that is **not**
  default-skip (its value varies in Family too, where it equals `15 − fences_built`). See §5.
- **`animals_need_accommodation: bool = False`** — the accommodation barrier's flag. Set by
  `helpers.grant_animals` whenever a **decision-free** animal grant lands (round-start collection,
  an on-play gain), which adds the animals to `animals` *even past housing capacity* — a transient
  over-capacity state nothing asserts against, since only scoring reads the totals and the barrier
  always reconciles first. Default-skip (Family-constant False → byte-identical, no C++ change).

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
`initiated_by_id`). Pushed by Basic Wish (placement on the space) and — with
`place_on_space=False`, the card-granted form the user ruled occupies *no* action space — by
the harvest-window growth grants (Autumn Mother, Bed in the Grain Field; §5b). The room gate
(`people_total < 5` and `< rooms`) stays the caller's check, not the primitive's.

**Cost & food.** `PendingChooseCost` (the two-step payment menu for builds where geometry ⟂
payment, §5; a closed frame — frozen `payments` tuple + the underlying `action_kind`, no
phase/triggers/Stop) and `PendingFoodPayment` (the raise-only food-raising frame, §5; also
closed — `food_needed`, `resume_kind`, `reserved: Cost`, and the stored commit `action` for the
"rerun" continuation).

**Phase hosts.** `PendingPreparation` (start-of-round host, one per *owning* player,
non-starting player pushed first so the starting player decides first; `start_of_round` autos
fire at its push, triggers via its enumerator, `Proceed` pops — no after-phase), the two
harvest-window frames (§5b) — `PendingHarvestWindow` (the per-player simple-window choice
host: pushed only for a player with an eligible trigger on that window id, once-per-window via
`triggers_resolved`, `Proceed` declines and pops) and `PendingFieldPhase` (the FIELD
during-window host: free-order `field_phase` triggers around the mandatory `CommitFieldTake`,
which is the only path to `Proceed`; carries `take_fired` and the frame-scoped `occasions`
manifest) and `PendingHarvestOccasion` (the per-occasion reaction host: carries its
just-emitted `occasion` payload so the registered per-occasion triggers read exactly the event
they react to; `Proceed` declines and pops; pushed by `maybe_host_occasion_triggers` wherever
an occasion is emitted, stacking above whatever frame emitted it) — `PendingDraftPick`
(above), and
`PendingCardChoice` (the forced-pick frame of mandatory-with-choice, §2 — options only, no
decline; a single-option frame auto-resolves via singleton-skip). *(The legacy dual-use
`PendingHarvestField` is deleted — §5b.)* Beside the frames live the payload dataclasses they
log or hand to consumers: `HarvestOccasion` / `HarvestEntry` and `BreedingOutcome` (§5b).

**Grant wrappers.** `PendingGrantedBuildFences` — the choose-or-decline parent for an *optional*
granted Build Fences (Field Fences): offers `ChooseSubAction("build_fences")` or `Stop`
(declining), pushing the real multi-shot `PendingBuildFences` with the *card's* provenance so
its discounts scope correctly. This is the template for optional grants of a mandatory-shaped
primitive: the inner frame keeps its "must do ≥1" shape; **declining lives at the parent's
choose+Stop, never a per-frame flag** (ENGINE_IMPLEMENTATION.md §2 invariant 3's corollary).

**Reconciliation.** `PendingAccommodate` — a bare per-player frame (no before/after lifecycle)
hosting one `CommitAccommodate`: the player chooses which animals to KEEP (one option per
housable `pareto_frontier` config over their current animals) when a decision-free grant put
them over capacity; the excess is cooked to food. `CommitAccommodate` pops it (vs. the animal
markets' after-phase pivot — `_execute_accommodate` branches on the frame type). Pushed by the
**accommodation barrier** (below), not by any space or card handler.

### The accommodation barrier

A decision-free animal grant can hand a player more animals than their farm can house — Animal
Tamer fills the house, then an Acorns Basket boar arrives; Game Trade swaps 2 sheep for a
boar + cattle needing different homes. Scoring counts animal totals directly, so an unhoused pile
would over-count, and *which* animals to keep is a genuine strategic choice — not one the engine
may make silently. The barrier surfaces it:

- **Grant** — every decision-free grant routes through **`helpers.grant_animals`** (the single
  choke point): it adds the animals to `animals` (allowed over capacity) and sets
  `animals_need_accommodation`. The three animal markets and harvest breeding are NOT grants —
  they reconcile inline via their own frames/frontiers, so they don't use this path.
- **Reconcile** — **`engine._reconcile_accommodation`** runs at *every* agent-decision boundary in
  `_advance_until_decision` (Case 1 pending-frame return, Case 3 worker-placement return) — the
  single chokepoint every prompt flows through. Flag-gated: the no-grant common case is one bool
  test over both players; only a flagged player pays a `can_accommodate` scan. If a flagged
  player's animals don't fit, it pushes a `PendingAccommodate` (starting player on top, per the
  harvest push order); if they DO fit, it just clears the flag. The flag is cleared as each player
  is handled, so a committed accommodation (which lands on a housable config) is never re-pushed.
- **Batch** — because reconciliation is at the *next prompt*, several grants at the same game
  moment (all synchronous — e.g. two cards scheduling animals into the same round) land before any
  boundary, so the barrier sees the combined total and asks once. The per-card contract is simply
  "grant your animals in one synchronous shot" — never interleave a prompt between two same-moment
  grants (none do today).
- **Backstop** — `_advance_until_decision`'s BEFORE_SCORING return runs
  `_assert_animals_accommodated` under `__debug__`: no player may reach scoring over capacity. It
  never fires in correct code (every grant is reconciled before scoring); it localizes a missing
  `grant_animals` call or barrier if one is introduced. Stripped under `python -O`, like
  `_assert_nonnegative_state`.

This replaced an earlier bug where round-start collection auto-picked the "best" overflow config
by total kept — silently choosing `(1 sheep, 1 boar)` over `(2 sheep)` on a tie. There is no
"the engine does not force accommodation on a gain" rule; that was an incorrect convention on a
few on-play cards (Game Trade, Young Animal Market), now corrected to route through the barrier.

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
- **`PendingSow`**: `max_fields: int = 0` — a card-granted PARTIAL sow caps the commit at
  `grain + veg <= max_fields` ("for each newborn, sow crops in exactly 1 field"); `0` =
  uncapped, every Family sow and the full granted Sow action.
- **`PendingHarvestBreed`**: `triggers_resolved: frozenset` — the breed frame hosts card
  triggers in both of its stretches (§5b), but the frame itself is pushed in every Family
  harvest, so the field is skipped via a **qualified** canonical entry (below).
- The seven Proceed-host space parents (five Family + Basic Wish + Meeting Place) carry the
  derived `subaction_started` property (§2 — not a field, so nothing to skip).

### The canonical default-skip mechanism

`canonical._DEFAULT_SKIP_FIELDS` lists every card-only field name; the serializer omits a listed
field **when it equals its dataclass default**. A Family state never sets any of them, so its
JSON is byte-identical to the pre-card engine — which is what the C++ differential gates
consume. A Cards state that sets one simply emits it. Current set: `mode`, `hand_occupations`,
`hand_minors`, `used_this_turn`, `used_this_round`, `fired_once`, `card_state`,
`future_rewards`, `draft_pools`, `animals_need_accommodation`, the three `build_*_action`
flags, `accrued_cost`, `free_fence_budget`, `restrictions`, `must_preserve_base`, `max_plows`,
`num_plowed`, `max_fields`, `harvest_cursor`, and the qualified
`PendingHarvestBreed.triggers_resolved`. A **qualified entry** (`"<Type>.<field>"`) skips a
field on ONE dataclass only — for a field whose *name* is emitted on other, Family-live frames
(the sow/bake/plow frames keep emitting their `triggers_resolved`) but whose value is
Family-constant-default on this one.
**Adding a card-only field to a Family-reachable structure = default it to the Family-constant
value + add it here** (qualified if the name is shared) — that is the whole checklist for
staying byte-identical (plus the C++ port if the field can vary in Family, like
`fences_in_supply`).

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

## 5b. The harvest timing windows

Printed card text names many distinct instants around a harvest — "immediately before each
harvest", "at the start of the field phase", "after the feeding phase", "at the end of each
harvest". The engine's answer is an ordered **ladder of window ids** threaded through the
harvest's FIELD → FEED → BREED walk, where each simple window id doubles as a trigger/auto
event string and three entries are sentinels for the engine's own machinery. This section is
the machinery reference; **`design_docs/cards/HARVEST_WINDOWS_DESIGN.md` is the design of
record** (its §12 is the as-built code map) and **`HARVEST_HANDOFF.md`** preserves the
reasoning behind every ruling (the dated rulings themselves live in `CARD_DEFERRED_PLANS.md`).
The card machinery is Family-inert in the standard way — empty registries, no frames, the
card-only fields default-skipped in canonical JSON — but the walk's per-player banding (below)
is Family-visible: a Family game mid-feed or mid-breed carries `harvest_cursor` alongside one
player's payment/breeding frame, and the C++ twin mirrors the banded walk (differential gates
green).

### The ladder and the virtual walk

`harvest_windows.HARVEST_WINDOWS` — 15 ids in resolve order: `immediately_before_harvest`,
`start_of_harvest`, `before_field_phase`, `start_of_field_phase`, **`field_phase`**
(sentinel — the take), `end_of_field_phase`, `after_field_phase`, `start_of_feeding`,
**`feeding`** (sentinel — the payment frames), `after_feeding`, `start_of_breeding`,
**`breeding`** (sentinel — the breed frames), `after_breeding`, `end_of_harvest`,
`after_harvest`. The ordering is rules-derived (design doc §1). Two printed qualifiers name
instants the ladder already has: "immediately after each harvest" is `after_harvest`
(ruling 18) and "immediately after the feeding phase" is `after_feeding` (ruling 19) — in each
pair the "immediately" wording is the same instant, not a distinct earlier one. `end_of_harvest`
is the last chance for in-harvest conversions; `after_harvest` is outside the harvest. A card
registers on the instant its text names (§3's `harvest_windows.py` block has the registration
API); it never approximates a neighbor.

**The walk** is `engine._advance_harvest`, resuming at `GameState.harvest_cursor` (§4) — an
index into a **virtual** ladder in which each of the three phase segments is a per-player
**band** (`_BANDS` in `harvest_windows.py`): the FIELD band (`before_field_phase` …
`after_field_phase`, the take included), the FEED band (`start_of_feeding` … `after_feeding`,
the payment frame included) and the BREED band (`start_of_breeding` … `after_breeding`, the
breed frame included) each appear once **per player**, starting player first — a player
resolves their *entire* phase segment, its before/after windows included, before the other
player's band begins (rulings 3 and 40; ruling 3 is PROVISIONAL — it matches the official
implementation, but the user dislikes the later-player advantage and may revisit). At the FEED
and BREED sentinels the payment/breeding frames are pushed for **one player per band pass**,
via `_initiate_harvest_feed_for` / `_initiate_harvest_breed_for`. At 2 players the virtual
ladder is 26 positions; `walk_position(cursor, starting_player)` decodes an index into
(window, band player), and N players would repeat each band N times (the shape 4-player
needs). Only the four outer windows — `immediately_before_harvest`, `start_of_harvest`,
`end_of_harvest`, `after_harvest` — sit outside every band and resolve **window-major**: per
window, autos fire for both players SP-first, then a per-player **`PendingHarvestWindow`**
choice frame is pushed for each player with an eligible registered trigger (non-SP pushed
first, so the SP decides first); a banded window runs the same autos-then-frame step for its
one band player. Within one window **autos resolve before optional triggers** — the standing
ordering ruling 19 leans on: Social Benefits' "no food left" auto runs before Farm Store's
optional exchange, so a player ending feeding with exactly 1 food cannot spend it at Farm
Store and still collect the grant. At the harvest's fresh entry the walk also resets both
players' `harvest_conversions_used` (§4 — before the harvest's first conversion opportunity,
so it is skip- and anytime-conversion-proof).

`PendingHarvestWindow` is once-per-window via `triggers_resolved`; `Proceed` declines
whatever is unfired and pops. Growth grants prove the frames compose: **Autumn Mother**
(`immediately_before_harvest`; its 3-food cost rides `register_food_payment_resume`, §5.3)
and **Bed in the Grain Field** (`start_of_harvest`; a one-shot latched to its play round by
round arithmetic — declining consumes it) both push `PendingFamilyGrowth(place_on_space=
False)` mid-harvest, and the walk hosts the pushed primitive unchanged.

### The field phase: one event, the take, and the occasion manifest

**The one-event model (rulings 5 and 11 — the load-bearing insight).** The field-phase take
is ONE simultaneous event: 1 crop from every planted field at once — and ALL during-phase
extra harvesting **folds into it**. A full-catalog sweep found no sequential wording anywhere
(the evidence is in the ledger's ruling-11 entry); every "harvest 1 additional …" card is a
*modifier* of the singular event, never a second harvesting occasion.

**The take.** `resolution.field_take(state, idx, *, source="take", extra_takes=None)` is the
shared bare take: 1 crop per planted field (grain vs veg by what the field holds), plus the
`extra_takes` per-cell fold-in map; returns `(state, HarvestOccasion)`. Manifest entries
carry the **combined** base+fold-in amounts and **net** emptied flags — so every consumer
sees one event with everything in it — and assertions guarantee fold-ins never over-harvest.
It is deliberately bare (no budget reset, no autos, no frames — the callers own those). A
card that *plays* a field phase — Bumper Crop; ruling 4: "immediately carry out the field
phase" fires the EFFECT, not the phase and not a harvest — calls it bare with its own source
(`"card:bumper_crop"`; harvest-scoped modifiers don't apply to it, and an *unscoped* one is
surfaced as a `PendingCardChoice` — the take-modifier subsection) and then
`resolution.emit_harvest_occasion`, which appends the occasion to a live during-frame's
manifest if one is on top and fires the per-occasion autos.

**The manifest** (`pending.py`): `HarvestOccasion(source, entries)` with one
`HarvestEntry(source="cell:r,c", crop, amount, emptied)` per harvested FIELD; a real field
phase emits exactly ONE occasion (ruling 11). This is the payload the harvest-consequence
registries read — the deliberate exception to §8's "events carry no payload" boundary. Autos
(`register_harvest_occasion_auto`) fire wherever an occasion is emitted; optional per-occasion
TRIGGERS then surface at the **`PendingHarvestOccasion`** host, which
`maybe_host_occasion_triggers` pushes right after the autos iff the owner has an eligible
registered trigger — the frame carries the occasion, stacks above whatever emitted it (the
innermost, just-emitted event resolves first), and `Proceed` declines (§3, §4). A mandatory
choice-free tier never surfaces here — it is an occasion AUTO, fired with no player input
(ruling 21), and the frame's `autos_fired` keeps the same card's optional tier
from double-reacting to one occasion ("exactly 1 vegetable" — Potato Ridger harvesting into
4 veg auto-exchanges down to 3 without then being offered the at-3 exchange).

**The counting/scoping doctrine — a real bug shipped from getting this wrong.** What a
consequence card counts comes from its printed wording:

- "each grain FIELD you harvest" / "each harvested field TILE" / "take the last X from a
  field" → count **entries** (per field), IGNORE `amount`. Slurry Spreader was first written
  `2 × amount` per emptied grain entry — invisible while every amount was 1, wrong the moment
  a fold-in emptied a 2-grain field in one event (paid 4 on a text that pays per FIELD).
- "for each GRAIN / VEGETABLE you harvest" → count **units** (sum `amount`) — Crack Weeder,
  Potato Harvester.
- "if you harvest at least N X" → sum units once per occasion — Grain Sieve.

And the scope gate comes from the printed frame (ruling 12's harvest-verb lexicon):

- "…in the field phase OF A / EACH HARVEST" → phase-scoped: `state.phase ==
  Phase.HARVEST_FIELD` (Crack Weeder, Potato Harvester, Slurry Spreader). Includes fold-in
  extras (they are in the take), excludes a WORK-phase Bumper Crop.
- Ruled take-only cards (ruling 9: Grain Sieve, Barley Mill — "bonuses are based off the
  specifics of what happened in that action"; Lynchet's room-adjacent tile count) →
  `occasion.source == "take"`.
- UNSCOPED harvest-verb reactors fire on ANY verb-sense harvest, a played field phase
  included. The verb (ruling 12): crops moving to the player's supply via the field-phase
  effect *wherever it runs*, or a literal card "Harvest" wording. "Remove" is wider (any crop
  departure from a card-field); "obtain" wider still.

### Take-modifiers: the during-window and the claim-aware fold

Because the extras are part of the one event, a *choice-bearing* extra surfaces as **variants
of the take commit** — `CommitFieldTake(modifiers=((card_id, variant), …))` — never as a
separate trigger. `register_take_modifier(card_id, fold_fn, *, variants_fn=None, order=1,
harvest_scoped=True)`:

- **Auto fold-ins** (`variants_fn=None`; Scythe Worker's mandatory-max extra grain):
  choice-free, applied to every real-harvest take, hosted or inline.
- **Choice-bearing** (`variants_fn` given; Stable Manure's donor-count vectors, Scythe E73's
  harvest-one-field-fully): the enumerator offers one `CommitFieldTake` per modifier
  combination (bare `()` = decline all), and owning one with a currently-legal variant is
  itself a reason to host the during-frame.
- **Replace-kind** (Grain Thief's shape): a fold may return a rich
  **`TakeFold(extras, skipped, bonus)`** instead of a bare extras dict — a `skipped` cell is
  REPLACED out of the take entirely (the base 1 is not taken, the manifest gets **no entry**
  for it — the field was not harvested — and it is pre-claimed at full count so no later fold
  can touch it), and `bonus` is goods granted from the general supply (never in the manifest —
  not harvested). `field_take` gains `skip_cells`/`bonus` accordingly. A modifier printed
  without harvest scoping registers `harvest_scoped=False` and also applies to card-played
  takes — Bumper Crop surfaces the unscoped-modifier choice via a `PendingCardChoice`.

`engine._field_phase_step` runs one player's during-window: `field_phase` autos fire, then
**`PendingFieldPhase`** is hosted iff the player has a live decision there — an eligible
`field_phase` trigger OR a usable choice-bearing modifier; otherwise the take runs inline
(auto fold-ins + occasion autos). After an inline take the trigger check runs **once more**:
take income can enable a trigger mid-window (Crack Weeder's food affording Cube Cutter's
exchange — without the re-check that legal play would be silently denied), and the frame is
then hosted with `take_fired=True`. At the frame, triggers are free-order around the mandatory take,
`CommitFieldTake` is the only path to `Proceed`, and the frame's `occasions` tuple logs what
fired.

**Claim-aware allocation.** The fold signature is
`fold_fn(state, idx, variant, claimed) -> extras-per-cell | TakeFold | None`: chosen
modifiers allocate **in combo order = the `order`-sorted registry** — replace-kind
before rigid fixed-demand (Stable Manure) before flexible (Scythe), which is load-bearing for
feasibility — with the auto fold-ins last (they degrade gracefully: an emptied field simply
has no "additional" grain to give). The `claimed` pass-through is what makes the folds
compose — computed independently, they double-claimed the same field's spare crops and
over-harvested on an action the enumerator had offered as legal (Scythe Worker + Stable
Manure on a lone 2-grain field). A `None` fold marks the whole COMBINATION infeasible and
`fold_chosen_modifiers` returning `None` makes the enumerator drop it — **every offered
commit is executable**. The two extras members are printed "of each harvest", so their
fold-ins apply only to a real harvest's take (ruling 12; `harvest_scoped=True`). A replaced
field emits **no manifest entry** (ruling 22) — which is what keeps
Lynchet's per-tile count correct under a replacement.

### Skips, feeding income, and the FEED/BREED sentinels

**Harvest skips.** `register_harvest_skip(card_id, fn)` — per-card predicates
`(state, idx, window_id) -> bool` over ROUND-KEYED latches in the card's own CardStore
(harvest rounds are unique, so a stale latch from a past harvest is inert; nothing clears).
Consulted at every step of the walk — per window, window-major and banded alike, and by each
player's FEED/BREED band sentinel with the sentinel ids `"feeding"` / `"breeding"` — so a
skipping player gets no payment/breeding frame and no feeding income. Members: **Lunchtime
Beer** (ruling 1, definite: a skipped phase has no boundaries — every field-segment and
breeding-segment window is suppressed, take included;
feeding still happens; the +1 food and the latch ride its optional `start_of_harvest`
trigger) and **Layabout** (ruling 14, superseding the contested ruling 2: the cancellation is
TOTAL — every window on the ladder, feeding, and breeding, before/after boundaries included;
the user dislikes this reading but ruled to follow the official implementation; latched
automatically at play, targeting the next harvest round at-or-after the play round).

**Feeding income and the requirement chokepoint.** `register_auto("feeding", …)` fires in
`_initiate_harvest_feed_for` at each player's own FEED band pass, **before** that player's
payment frame is pushed — "in the feeding phase, you get X food" must be payable. Consumers:
Dentist (a two-window card — wood banked at its `start_of_harvest` trigger, per-wood food
paid out here), Town Hall,
Milking Place. Choice-free income only; in-feeding *conversions* stay on
`HARVEST_CONVERSIONS` (§3). Cards that change **what feeding costs** (Child's Toy's "your
newborns require 2 food") fold at the single computation chokepoint,
`helpers.feeding_requirement` (base `2·people_total − newborns`, owned
`register_feeding_requirement` folds applied in order, floored at 0). Cache safety: the
folded requirement flows into the memoized feed frontier as its `food_owed` **argument** —
part of the projection key — so a card-dependent requirement can never serve a stale frontier
(§5.4's contract, satisfied by construction).

**The BREED frame hosts triggers in both of its stretches** (ruling 20;
`breed_chosen` is the phase discriminator):

- **Before `CommitBreed` — event `"breeding"`**: in-breeding-phase effects that do not depend
  on the breeding outcome (Stone Importer's priced stone buy) are offered BEFORE the breed
  decision, never after. Firing one leaves the frame up.
- **After `CommitBreed`, before `Stop` — event `"breeding_outcome"`**: reactions to WHICH
  newborns were just placed. `_execute_breed` computes the **`BreedingOutcome`** payload
  (0/1 per type, from the engine's own kept-newborn indicator — an unaccommodated newborn is
  never placed, so "you must be able to accommodate each newborn to get it" is inherent) and
  fires the `register_breeding_outcome_auto` consumers with the frame still on top; an
  outcome-reactive *trigger* reads its own round-keyed CardStore latch written there (the
  frame carries no payload field). `Stop` declines whatever is unfired.

This is deliberately NOT an any-source newborns event — Dung Collector's "each time you get
2+ newborn animals" counts market gains too and stays out of scope (§8). The FEED frames, by
contrast, carry no trigger events (§8).

### The retired `harvest_field` seam

The legacy `harvest_field` seam no longer exists: every member card lives on the window /
occasion / take-modifier seams above, and `_resolve_harvest_field` survives only as a
test-compat alias (assert HARVEST_FIELD + `_advance_harvest` — many tests drive the walk by
that name). Any reference to a live "harvest-field hook" is stale; the deleted-name inventory
is in `HARVEST_WINDOWS_DESIGN.md`'s retirement record and `HARVEST_HANDOFF.md`. Lynchet's
migration is the cautionary exemplar: its old pre-take sown-adjacent snapshot was
extensionally equal to the manifest read in every then-reachable state yet breaks under Grain
Thief's replacement — extensional equality on today's states is not equivalence.

---

## 5c. The round-end timing ladder

Cards also fire in the seam **between the work phase's last placement and the round
transition** — "at the end of the round", "when you return home", "immediately before the
returning home phase". The engine's answer (rulings 49/50, 2026-07-12) is a second, smaller
timing ladder: the structural sibling of §5b's harvest ladder, sharing its window primitives
but with its own step table, driver, and cursor. It lives in **`agricola/cards/round_end.py`**;
the rulings' derivations are in `CARD_DEFERRED_PLANS.md` (rulings 49–51).

**The seven steps** (`round_end.ROUND_END_STEPS` — six window ids that double as trigger/auto
event strings, exactly like §5b's simple windows, plus one non-event sentinel):

| # | step | what it is |
|---|---|---|
| 0 | `end_of_work` | still *during* the work phase (ruling 49). Reserved — no live card yet |
| 1 | `after_work` | ruling 50's separate later rung ("immediately before the returning home phase"). Reserved |
| 2 | `start_of_returning_home` | before the phase proper. Reserved |
| 3 | `returning_home` | fires **PRE-reset**: the still-placed board is the event data — a member card reads live occupancy directly, no manifest (the generalized Swimming Class design). Members: Swimming Class (auto), Silage (trigger) |
| 4 | `__reset__` | **not an event** — the mechanical return-home bookkeeping (`_return_home_reset`: placements cleared, people home). Its position *is* the pre/post boundary |
| 5 | `after_returning_home` | post-reset, board cleared ("immediately after each returning home phase" merges here). Reserved |
| 6 | `end_of_round` | the round's last, distinct instant (ruling 49). Members: Credit (auto), Lifting Machine, Baking Course, Sculpture Course (triggers) |

**The walk.** `engine._advance_round_end(state) -> (state, paused)` drives it **window-major
with no banding** (unlike §5b's per-player phase bands — no round-end ordering ruling requires
banding). The ladder is split at the RETURN_HOME phase flip into two segments:
`_advance_until_decision`'s WORK case runs positions 0–1 once every worker is placed (before
flipping the phase), and its RETURN_HOME case runs positions 2–6, followed by
`_round_transition` (harvest routing / preparation). Each window resolves both players through
the **same primitives as §5b** — `_process_simple_window` fires the autos per player SP-first,
then pushes a per-player `PendingHarvestWindow` choice host (a round-end frame is simply a
`PendingHarvestWindow` whose `window_id` is a round-end id) for each player with an eligible
trigger, non-SP first so the SP decides first. A pushed frame pauses the walk:
**`GameState.round_end_cursor`** carries the resume index (card-only, hash-included,
Family-constant `None`, canonical default-skipped, no C++ change — §4), cleared when the
segment completes. `_resolve_return_home` survives only as a legacy compat shape
(`_round_transition ∘ _return_home_reset`) for tests that drive the transition by name.

**The harvest-skip guard is OFF on this ladder** (`_process_simple_window(...,
skip_guarded=False)`), deliberately: ruling 14's whole-harvest skip (Layabout) covers the
*harvest* ladder only — the returning-home phase is distinct from the harvest (ruling 49) —
and Layabout's skip predicate is round-latched and id-blind, so consulting it here would
wrongly swallow round-end windows on Layabout's latched round
(`tests/test_round_end_ladder.py` pins this).

**Sequencing on a harvest round:** the *entire* round-end ladder runs **before** the harvest —
WORK segment → phase flip → RETURN segment (through `end_of_round`) → `_round_transition`
routes to HARVEST_FIELD → §5b's `_advance_harvest`. The two cursors coexist on the state but
are live at different times.

**Member-card constraint:** a WORK-segment trigger must not grant a worker placement — the
"all workers placed" gate is that segment's resume guard, so placement-granting round-end
wordings are out of scope by design (defer).

---

## 6. Rulings & idioms

The rulings are *correctness decisions* — settled by the game's rules (the user is the
authority), never by implementation convenience. The idioms are recurring code patterns whose
naive alternative is a known bug. `CARD_AUTHORING_GUIDE.md` develops most of these with worked
examples; this is the reference list.

### Rulings

- **Rules fidelity is absolute — this ruling outranks every other.** A card is implemented
  exactly as printed or it is deferred; an implementing session has **no authority** to shift a
  timing, narrow a mechanism, or substitute a "behaviorally equivalent" reading — a neutrality
  argument is a reason to ask the user, never to proceed (the 2026-07-02 audit found a
  constructible problem behind every such "harmless" deviation). Docstrings may not
  self-ratify a deviation: any deviation must cite an explicit, dated user ruling, and an
  unattributed "accepted approximation" claim is a defer signal, not precedent. The rule
  propagates **verbatim into every subagent prompt** (CARD_AUTHORING_GUIDE.md §0.1 — subagents
  drift toward convenience; the verify stage checks text-vs-implementation fidelity first).
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
- **Every decision-free animal grant routes through `helpers.grant_animals`** — never a raw
  `p.animals + Animals(...)`. The grant may exceed capacity; the **accommodation barrier** (§4)
  reconciles at the next decision boundary, surfacing the keep-which choice and cooking the
  excess. At an animal *market*, still bump the pending's `gained` instead (the market's own
  frame accommodates inline — Cowherd); breeding and harvest feed likewise reconcile via their
  own frontiers. *(This supersedes the earlier ruling that an immediate un-accommodated grant
  is an automatic defer — that convention hid a real player choice, e.g. Animal Tamer + a
  scheduled boar arriving on a full house.)*
- **Card-granted family growth occupies no action space** (the user's ruling, now built):
  `PendingFamilyGrowth(place_on_space=False)` skips the space placement; the room gate
  (`people_total < 5` and `< rooms`) is the caller's check, not the primitive's. Live
  consumers: Autumn Mother, Bed in the Grain Field (§5b). A window-granted newborn is fed the
  standard 1 food (ruling 13).
- **"X in supply" is a prerequisite, not a cost** — a HAVE-check (`MinorSpec.prereq` /
  `min_occupations`), never debited.
- **"/" in a cost: now supported for minors; "/" in a *reward* is not.** A printed
  alternative cost (Chophouse "2 Wood / 2 Clay") is `MinorSpec.alt_costs`; a state-scaling cost
  is `cost_fn`; an occupation's pay-on-play choice is a play-variant (§3). *(This supersedes the
  earlier batch-era ruling that any "/" cost is an automatic defer — commit a8e1ee2.)* Still
  unsupported: a minor whose "/" is in the *effect* (Canvas Sack's choose-a-reward) — no
  `PLAY_MINOR_VARIANTS` registry exists; defer (§8).
- **A one-shot's sweep matches its condition's reachability.** A house-material condition
  ("once you live in a stone house") fires on the `register_conditional` sweep at the renovate /
  card-play seams (`_fire_ready_one_shots`). A **resource/animal-count** condition (Hook Knife's
  "8 sheep") those seams can't see fires on the `register_boundary_one_shot` sweep at every
  decision boundary (`_fire_boundary_one_shots`), after the accommodation barrier — with the
  card's own `accommodates` check so an un-trimmed over-capacity grant never fires it. Neither is
  a defer; pick the sweep whose timing the condition needs (§3), and never approximate with an
  action hook.
- **Harvest timing is the window ladder** — a harvest card registers on the window id its
  printed text names (§5b), never an approximated neighbor. The field phase is ONE
  simultaneous event (rulings 5/11): all during-phase extra harvesting folds into the take as
  a take-modifier, never a second occasion. *(Supersedes the `harvest_field` hook and its
  auto-only → autos+triggers evolution — that seam is deleted.)*
- **Every "immediately" in card text gets its own user ruling.** Rulings 18/19 merged the two
  after-harvest and after-feeding pairs ("immediately after X" = "after X" — the same
  instant), but the equivalence does **not** generalize: each future occurrence is a
  per-instance rules question, never a unilateral call (the standing instruction, also in
  CARD_AUTHORING_GUIDE.md §2).
- **An in-breeding-phase effect fires BEFORE the breed decision, never after** (ruling 20) —
  unless it reacts to the outcome itself, in which case it lives on the post-commit
  `"breeding_outcome"` event (§5b). The breed frame's `breed_chosen` flag is the phase
  discriminator.
- **Count what the text counts; scope by the printed frame.** "Each grain field" counts
  occasion ENTRIES (ignore amounts); "for each grain you harvest" counts UNITS (sum amounts);
  thresholds sum units once per occasion. "In the field phase of a/each harvest" → phase-gate;
  ruled take-only cards → `occasion.source == "take"`; unscoped harvest-verb wording fires on
  any verb-sense harvest. The doctrine + the Slurry Spreader bug that motivated it: §5b.
- **An on-play optional grant declines WIDE** (ruling 17 — Baker): "when you play this card,
  you can take a Bake Bread action" is offered as PLAY-VARIANTS
  (`register_play_occupation_variant`, the Roof Ballaster mechanism) — "play and bake" vs
  "play, decline the bake" are two `CommitPlayOccupation` variants. Never an after-play
  trigger: that would let the granted action interleave with other after-play triggers in
  player-chosen order, which "when you play this card" does not license. The pushed primitive
  is committed once the variant is chosen (the variant WAS the decline moment — no per-frame
  skip flag, per the standing optionality-at-the-parent invariant).
- **A card that REPLACES a convertible good it induced you to spend breaks the
  food-exclusion premise** (ruling 16 as amended — Shepherd's Whistle). The usual
  "food is never a frontier dimension" convention is a theorem whose premise is that
  conversion proceeds are obtainable later from unchanged holdings; a replacement card
  refunds the spent good, so its proceeds are non-deferrable and a cook-and-be-refunded
  option strictly beats declining. The built shape: the option frontier is over animals PLUS
  a received-vs-declined dimension (received dominates declined iff a sheep-conversion
  opportunity exists), food computed per option but never a dominance term; the "free
  unfenced stable" condition is capacity-theoretic, computed by handing the standard helpers
  a DOCTORED player with one standalone stable cell blanked. Among same-rate subset options,
  goods-only dominance stays exact (the food difference equals the deferred cook-value of the
  goods difference) — re-derive that identity before trusting any new frontier design. Full
  derivation with the counterexamples: HARVEST_HANDOFF.md §8.

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
to `CARD_DEFERRED_PLANS.md` (clustered by blocker, with a build proposal), not approximated —
and "it fits if I shift the timing slightly" **is** an approximation (§6's first ruling: rules
fidelity is absolute; convincing yourself the shift is harmless does not make it authorized). The
user understands the rules and interactions far better than a coding session; a deferred card
costs nothing, a plausible-but-wrong card costs trust. When work is delegated, this rule goes
into the subagent prompt verbatim. Defer indicators: ambiguous timing/optionality (genuinely
ambiguous *text* goes to the durable **ambiguity-defer category** in `CARD_DEFERRED_PLANS.md`
/ the PROGRESS ledger — ruling 50 — distinct from the power bans); needs new shared
infrastructure (§8's list); at-any-time effects; "/"-rewards; end-of-turn timing; geometry
beyond the fence universe; new shared action spaces; randomness inside `step`; temporary
workers; card-as-animal-holder. Formerly-deferred, now supported — don't re-defer these:
return-home / after-harvest timing (the §5c round-end ladder, §5b's `after_harvest` window),
immediate animal grants (`grant_animals`, §6), "/"-alternative *costs* (`MinorSpec.alt_costs`,
§3), and card-as-field (the `card_fields` machinery — §1's card-fields bullet).

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
| harvest-window trigger / auto | `haydryer`, `farm_store` / `social_benefits`, `home_brewer` |
| field-phase (during-window) trigger | `cube_cutter`, `beer_table` (end-of-field-phase) |
| take-modifier | `scythe_worker` (auto), `stable_manure`, `scythe` (choice-bearing) |
| occasion auto | `grain_sieve` (take-only), `crack_weeder` (phase-scoped), `lynchet` (per tile) |
| harvest skip | `lunchtime_beer` (phases), `layabout` (total) |
| feeding income | `town_hall`, `dentist` (two-window) |
| window growth grant | `autumn_mother`, `bed_in_the_grain_field` |
| conditional one-shot latch | `manservant` |
| deferred goods / effect | `pond_hut` / `handplow` |
| CardStore state | `big_country`, `tutor`, `shepherds_crook` |
| mandatory-with-choice | `childless`, `seasonal_worker` |
| play-variant occupation | `roof_ballaster` (surcharge), `baker` (wide-declined grant) |
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
- **The general firing system carries no event payload.** `after_play_minor` etc. name an
  event, not the card played — so a card cannot distinguish *its own* play from a later one
  (Seed Almanac's deferral), and there is no any-source newborns-gained event (Dung Collector —
  markets included, deliberately out of scope). Adding payloads to the general system is a
  firing-API change; defer until a cluster justifies it. **The two deliberate exceptions**,
  both harvest-scoped registries rather than general events: the harvest OCCASION registries
  (the `HarvestOccasion` manifest) and the breeding-outcome registry (the `BreedingOutcome`
  payload) — §5b.
- **No harvest FEED trigger events.** `PendingHarvestFeed` still carries no
  `triggers_resolved`; feeding-phase cards ride the feeding-income auto, the
  requirement folds, the harvest-conversion registry, or the
  `start_of_feeding`/`after_feeding` windows (§5b). *(The BREED half of the old deferral
  retired at `ff874ba`: the breed frame hosts `"breeding"` / `"breeding_outcome"` triggers —
  §5b.)*
- **No before-round-start hook.** `resource_analyzer` (deck E) is deferred on exactly
  "before the start of each round" — an instant after the round-end ladder but before round
  income, which no window covers yet. (Round-end and after-feeding are no longer in this
  list — the §5c ladder and §5b's `after_feeding` window exist now.)
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
| `HARVEST_WINDOWS_DESIGN.md` | design of record for §5b — ladder rationale, during-window classes, FEED/BREED, card-fields, anytime converters; **§12 = the as-built code map** | any harvest-window card or engine change |
| `HARVEST_HANDOFF.md` (repo root) | the 2026-07-03→05 session-reasoning record — every ruling's derivation, the bug stories, per-item cautions for the remaining work (§12 = the worklist) | resuming the harvest arc; before building any of its §12 items |
| `HARVEST_CARDS_REVIEW.md` | the 130-card verbatim census, grouped by window (2026-07-03 snapshot — impl markers dated) | triaging a harvest-timed card |
| `LEGALITY_HARD_CASES.md` (repo root) | **LIVE problem catalog (2026-07-09 arc)** — the 10 mechanisms (M1–M10) that break state-read placement legality, the good→gate matrix (M1b), food-as-universal-currency (M8b), worked multi-card interactions, confirmed live defects (§13), open rules questions (§14) | any card that could flip a resource-gated placement's legality; before building the reveal-order cluster |
| `PLACEMENT_REACHABILITY_DESIGN.md` (repo root) | **ON HOLD** — a solution sketch (reachability/closure-by-simulation oracle + phase ladder); NOT a plan of record, the user is designing the approach | revisiting the legality architecture |
| `CENSUS_AT_ANY_TIME.md` (repo root) | full-catalog sweep — the **31** "at any time" cards (a closed family, none implemented), difficulty core, Grocer collapse | at-any-time / anytime-conversion / Grocer-family work |
| `CENSUS_REACTIVE_TRIGGERS.md` (repo root) | full-catalog sweep — **153** cards firing on state-changes-however-caused (Potter's Yard family), by trigger class | reactive/however-caused trigger work; sizing the chain hazard |
| `CENSUS_COST_IMPOSITION.md` (repo root) | full-catalog sweep — the **8** cards that tax an otherwise-free action (Fishing Net, Dwelling Mound), none implemented | a card that imposes a cost on a free owner/opponent action |
| `SPACE_HOST_REFACTOR.md` / `SUBACTION_HOOK_REFACTOR.md` | **frozen refactor records (LANDED)** — the host lifecycle's design + staging | archaeology of §2's mechanisms |
| `POST_COMPACTION_DETOUR.md`, `CARD_BATCH_AB_SUMMARY.md`, `CARD_BATCH_TRIAGE.md`, `CARD_TRIAGE_CDE.md`, `PAY_FOOD_PLOW_CARDS.md` | historical batch records | provenance of a specific batch/fix (enforce-first: POST_COMPACTION_DETOUR §2) |
| `ROOM_CARDS.md` / `STABLE_CARDS.md` | catalog analyses (cards touching rooms/stables) | planning those clusters |
| `scripts/card_batch/README.md` | the batch workflow tooling | running a triage/implement batch |
| `CARD_BATCH_HANDOFF.md` (gitignored) | session-local working notes | resuming a batch session |
