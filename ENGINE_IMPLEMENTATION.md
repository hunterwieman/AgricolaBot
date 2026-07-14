# ENGINE_IMPLEMENTATION.md

Deep-mechanics companion to **CLAUDE.md → Phase 1 (The Game Engine)**. Phase 1 is the
orientation layer — the two-function API, the state model, the pending stack at a conceptual
level, the decider rule. This document is the reference layer: dispatch tables, the full
provenance scheme, the complete pending invariants, sub-action cost handling, the Fencing /
animal-accommodation / Harvest subsystems, and the coding conventions. The **card system**
built on top of this engine has its own reference companion, **`CARD_ENGINE_IMPLEMENTATION.md`**
(read it after this one when doing card work); §6 below keeps the seam summary and the
nature-policy layer.

It **assumes you have read Phase 1**, and it does not repeat the Foundational principles
(frozen dataclasses, functional core, determinism, derived-not-cached, action-space shaping) —
those live in CLAUDE.md → Foundations and are referenced here, not restated. Some overlap with
Phase 1 is intentional: each section below is written to be internally coherent, so a reader
landing here while doing surgery on one subsystem gets the whole picture without flipping back.

Contents:
1. Engine structure & dispatch
2. The pending-decision stack (full)
3. Sub-action mechanics
4. Subsystems — Fencing, Animal accommodation, Harvest
5. Coding conventions (appendix)
6. Card machinery (pointer) & the nature-policy seam

---

## 1. Engine structure & dispatch

This section is the control-flow spine: how `step` drives one action through the engine, in the
order a turn actually unfolds — placement, sub-action choice, commit, triggers/stop — followed by
the phase walk and the legality entry point. The components it touches (`Pending*` frames,
`Commit*` types, the per-pending enumerators) are detailed in §2–§4; here they appear in the flow
that ties them together.

### `step` — the only transition

`step(state, action) -> GameState` (`engine.py`) is the sole transition function and does four
things in order:

1. **Apply the action** via `_apply_action`.
2. **Alternate the active player** — but only when `state.phase == Phase.WORK and not
   state.pending_stack`, which indicates that a player has finished their turn in the work
   phase. This is *the* alternation point; player rotation happens nowhere else. The
   `phase == WORK` guard matters once cards introduce mid-RETURN_HOME / mid-HARVEST agent
   decisions: resolving such a decision must not rotate workers (none are being placed then).
3. **`_advance_until_decision`** — walk system transitions until the next agent decision or
   game-over.
4. **Non-negativity check** (`_assert_nonnegative_state`), gated on `__debug__` so `python -O`
   strips it for training/self-play. `Resources.__sub__` / `__add__` permit negative components
   (no clamping), and `Animals` counts can go negative via direct construction in effect code, so
   the invariant is checked at this transition boundary; the assertion names the action and
   player for tight bug-localization. (PROFILING.md R2.)

`step` does not validate legality (`action in legal_actions(state)` is the caller's
responsibility), does not auto-resolve singleton decisions, and raises `RuntimeError` if called
at `Phase.BEFORE_SCORING`.

### `_apply_action` — dispatch on action type

Which action type is expected is fully determined by the stack. An **empty stack** means the
start of a worker placement in the WORK phase, so the only legal action is `PlaceWorker`. A
**non-empty stack** means a player is mid-turn: the top frame encodes how far the turn has
progressed and which action type it expects next (`ChooseSubAction`, a `Commit*`, `FireTrigger`,
or `Stop`). `_apply_action` dispatches on the action's type:

```
PlaceWorker      -> _apply_place_worker
ChooseSubAction  -> _apply_choose_sub_action
CommitCardChoice -> _apply_commit_card_choice    (card game — checked before the marker base)
CommitSubAction  -> _apply_commit_subaction      (all other Commit* subclasses)
FireTrigger      -> _apply_fire_trigger
Stop             -> _apply_stop
Proceed          -> _apply_proceed               (host work-complete flip — CARD_ENGINE_IMPLEMENTATION.md §2)
CommitDraftPick  -> _apply_draft_pick            (card game, Phase.DRAFT — a top-level action like RevealCard)
RevealCard       -> _apply_reveal_card
```

`CommitSubAction` is a marker base; every concrete `Commit*` routes through the one generic
commit handler, so adding a commit type never touches `_apply_action`.

`RevealCard` is a top-level transition (like `PlaceWorker`, not a `CommitSubAction`) — nature's
action turning up the round's stage card. It is dispatched directly in `_apply_action` to
`_apply_reveal_card`, which does exactly one thing: set the named card's `revealed=True` and pop
the `PendingReveal` frame. It leaves `phase = PREPARATION` untouched (the round increment and
accumulation refill happen later, in the phase walk — see below), so the `step` alternation guard
(WORK-only) never sees a reveal step.

Those handlers map onto four dispatch tables, one per turn stage:

| Table (module) | Triggered by | Keyed on | Handler |
|---|---|---|---|
| `ATOMIC_HANDLERS` (`resolution.py`) | `PlaceWorker` | `space_id: str` | `_resolve_<space>(state)` |
| `NONATOMIC_HANDLERS` (`resolution.py`) | `PlaceWorker` | `space_id: str` | `_initiate_<space>(state)` |
| `CHOOSE_SUBACTION_HANDLERS` (`resolution.py`) | `ChooseSubAction` | top pending **type** | `_choose_subaction_<x>(state, action)` |
| `COMMIT_SUBACTION_HANDLERS` (`engine.py`) | `Commit*` | `Commit*` **type** | `(expected_pending, effect_fn, auto_pop)` |

The rest of this section walks those tables in turn order.

### Worker placement (`PlaceWorker`)

`_apply_place_worker` first does cross-cutting bookkeeping (`_apply_worker_placement` — workers,
`people_home`), then dispatches by space id to `ATOMIC_HANDLERS` (apply the effect and return) or
`NONATOMIC_HANDLERS` (push the space's parent pending and return). Every space in `SPACE_IDS` now
has a handler in both game modes (`lessons` included — its card-game handler `_initiate_lessons`
is registered; the Family game simply never surfaces it, via `legal_placements`' mode table), so
the `NotImplementedError` branch is a defensive guard for a future space added without a handler.
Two card-mode detours run before the table dispatch: card-mode Meeting Place routes directly to
its self-hosting handler, and an atomic space a played card hooks is wrapped in a host frame
instead of resolving immediately (`should_host_space` — both in CARD_ENGINE_IMPLEMENTATION.md §2;
in the Family game neither branch can fire).

Every placement action is `PlaceWorker(space=<space_id>)` — the bare id. (The prefixed
`"space:<id>"` form is the pushed pending's `initiated_by_id`, not the action's `space` field;
see §2.)

25 spaces live in `SPACE_IDS` (11 permanent + 14 stage cards, canonical fixed order). Each
`ActionSpaceState` carries a `revealed: bool` — permanents are `revealed=True` from setup, stage
cards start `revealed=False` and flip to `True` when their `RevealCard` fires. The hidden per-game
reveal order does **not** live in `GameState` at all (it sits in the `Environment` — §6), so
`GameState` holds only common knowledge and two info-equivalent states hash equal. In the
**Family game** 12 spaces are atomic, 12 are non-atomic, and `lessons` is never legal. The
**card game** reshapes the board (CARD_ENGINE_IMPLEMENTATION.md §0/§4): Side Job is gone,
`lessons` becomes a non-atomic space (play an occupation), Meeting Place becomes a self-hosting
non-atomic space (become SP + optional minor, no food), and `legal_placements` dispatches on
`state.mode` between the two legality tables.

**Atomic** (`ATOMIC_HANDLERS` → `_resolve_<space>`; apply effect, done — effects are in RULES.md):

```
day_laborer  fishing  forest  clay_pit  reed_bank  grain_seeds
meeting_place  western_quarry  vegetable_seeds  eastern_quarry
basic_wish_for_children  urgent_wish_for_children
```

(In the Family game, family growth — `basic_/urgent_wish_for_children` — is atomic; the optional
minor-improvement path is unimplemented.)

**Non-atomic** (`NONATOMIC_HANDLERS` → `_initiate_<space>`; push the parent pending). The
"initiates" column is the primitive composition, not the game effect:

| Space | Parent pending | Initiates |
|---|---|---|
| `grain_utilization` | `PendingGrainUtilization` | Sow + Bake Bread |
| `farmland` | `PendingSubActionSpace` | Plow |
| `cultivation` | `PendingCultivation` | Plow + Sow |
| `side_job` | `PendingSideJob` | Build Stable + Bake Bread |
| `sheep_market` | `PendingSheepMarket` | take sheep → accommodate |
| `pig_market` | `PendingPigMarket` | take boar → accommodate |
| `cattle_market` | `PendingCattleMarket` | take cattle → accommodate |
| `major_improvement` | `PendingSubActionSpace` | buy major (→ free Bake for Clay/Stone Oven); in cards, also play a minor |
| `house_redevelopment` | `PendingHouseRedevelopment` | Renovate |
| `farm_expansion` | `PendingFarmExpansion` | Build Rooms + Build Stables |
| `fencing` | `PendingSubActionSpace` | Build Fences |
| `farm_redevelopment` | `PendingFarmRedevelopment` | Renovate + Build Fences |

`PendingSubActionSpace` is the generic **Delegating** host for a space with exactly one mandatory
sub-action — it replaced the old per-space `PendingFarmland` / `PendingFencing` classes, and also
serves `major_improvement` (its choose pushes the composite `PendingMajorMinorImprovement`) and
the card game's `lessons`. Host-lifecycle mechanics: CARD_ENGINE_IMPLEMENTATION.md §2.

### Sub-action choice (`ChooseSubAction`)

`_apply_choose_sub_action` dispatches on the **type** of the top frame via
`CHOOSE_SUBACTION_HANDLERS` (13 entries: the space parents that branch into categories — incl.
the generic `PendingSubActionSpace` and the card-only Basic Wish / Meeting Place / granted-fences
parents — plus the Clay/Stone Oven sub-pendings; the three animal markets are absent, since they
commit accommodation directly with no `ChooseSubAction` step).
The handler sets the parent's `<cat>_chosen` flag **and** pushes the category's pending — both in
the one handler. (Why choose-time, not commit-time: §2, invariant 7.)

### Sub-action commit (`Commit*`)

`_apply_commit_subaction` is the generic commit dispatcher: look up
`(expected_pending_type, effect_fn)`, assert the expected pending is on top, run
`effect_fn(state, top.player_idx, action)`. The dispatcher **never pops** — the effect function
owns all stack manipulation (flip to the after-phase, multi-shot `replace_top`, oven-pending
pushes, etc.; the old per-row `auto_pop` flag was removed once every sub-action became a uniform
before/after host — see §3).
It does **not** touch parent `*_chosen` flags. `effect_fn` takes `player_idx` explicitly (the
active player may differ from the commit's owner under out-of-turn trigger frames) and may read
`state.pending_stack[-1]` for its own frame. The full `Commit* → pending` table is in §3.

### Triggers and Stop (`FireTrigger`, `Stop`)

`_apply_fire_trigger` looks up the card in the `CARDS` registry, runs its `apply_fn`, and records
the fire by `replace_top`-ing `triggers_resolved | {card_id}`. `_apply_stop` pops the top frame
only (no assertion that the stack empties — future cards may Stop at non-bottom frames).

### `_advance_until_decision` — the phase walk

Called at the end of every `step` (stage 3). A `while True` loop that returns as soon as a real
decision is pending, otherwise drives system transitions. **State-driven and idempotent** —
re-running it on a returned state is a no-op. The cases, in order:

1. **Pending stack non-empty** → return (agent decision awaiting) — after the accommodation
   barrier reconciles, and UNLESS the top host's work just completed, in which case it is first
   auto-flipped to its after-phase (`_enter_after_phase`) — the engine, not a player decision,
   is the work-complete signal. Two signals share the one flip rule: a **Delegating** space
   host's `subaction_complete`, and a **commit-terminated** host's `effect_initiated` (the
   deferred after-flip, ruling 60 — set by the commit executor, so the flip waits for anything
   the effect pushed; the oven free-bake is the Family-reachable case)
   (CARD_ENGINE_IMPLEMENTATION.md §2).
1.5. **DRAFT with empty stack** (card game, `draft=True` setups only) → push the next
   `PendingDraftPick`, or transition to PREPARATION once all four pools are empty
   (CARD_ENGINE_IMPLEMENTATION.md §4).
2. **PREPARATION** → the preparation ladder (ruling 54, 2026-07-14 as revised):
   `_advance_preparation` walks `agricola/cards/preparation.py`'s step table — the
   `before_round` card window ("before the start of each round") → `__reveal__` (push a
   `PendingReveal()` with `player_idx=None` if the round card is face-down — case 1 then
   returns on the non-empty stack, pausing at the nature decision) → `__round_setup__`
   (`round_number += 1`) → the `reveal` card window → `__collect__` (newborns become adults,
   used-sets clear, round-space `future_resources` + scheduled `future_rewards` animals
   collected; the animals reconcile through the accommodation barrier) → the
   `round_space_collection` and `start_of_round` card windows → `__replenish__` (refill every
   accumulation space where `sp.revealed`, the just-revealed card included) → the
   `replenishment` / `before_work` / `start_of_work` card windows → flip to WORK with
   `current_player = starting_player`. At `before_round` and the reveal, `round_number` still
   names the round just *completed* (the increment is post-reveal), preserving the
   `count == round_number` public-state discriminator; a resume with
   `count == round_number + 1` re-enters at `__round_setup__`, and a card window's pause is
   carried by `GameState.prep_cursor` (card-only, Family-constant None; never set across the
   reveal). In Family every window is empty, so the walk is the mechanical steps plus the
   reveal pause, in the pre-ladder order — byte-identical, no C++ change; hosting is
   eligibility-driven per window (CARD_ENGINE_IMPLEMENTATION.md §5d). `_complete_preparation`
   survives as the legacy test/compat shape (the whole ladder, reveal step assumed done).

   Continue.
3. **WORK** → if all players have `people_home == 0`, set phase `RETURN_HOME` and continue;
   else return (a placement decision is awaiting).
4. **RETURN_HOME** → `_resolve_return_home` (end-of-round bookkeeping; routes to HARVEST_FIELD
   on harvest rounds, else PREPARATION); continue.
5. **HARVEST_FIELD** → `_resolve_harvest_field` (mechanical FIELD work, resets
   `harvest_conversions_used`, pushes FEED pendings, transitions to HARVEST_FEED); continue.
   *Card mode:* when a player owns a harvest-field card, a transient `PendingHarvestField` host
   fires the `harvest_field` automatic effects *before* the crop take
   (CARD_ENGINE_IMPLEMENTATION.md §2) — skipped entirely in Family.
6. **HARVEST_FEED with empty stack** = exit signal (all FEED frames Stop'd) → push BREED
   pendings, transition to HARVEST_BREED; continue.
7. **HARVEST_BREED with empty stack** = exit signal → BEFORE_SCORING if
   `round_number >= NUM_ROUNDS` (14), else PREPARATION; continue.
8. **BEFORE_SCORING** → terminal; no more steps.

The dual-meaning of HARVEST_FEED / HARVEST_BREED (stack non-empty = a player is deciding; stack
empty = phase-exit signal) is what makes cases 6–7 work: the only way to reach those phases
with an empty stack is for the entry resolver to have pushed per-player frames that have since
been drained by Stop.

### `legal_actions` — the only legality entry point

`legal_actions(state)` (`legality.py`) generates the *next* decision after
`_advance_until_decision` lands on it. It dispatches on stack + phase:

```
pending_stack non-empty  -> _enumerate_pending(state, pending_stack[-1])
phase == BEFORE_SCORING  -> []
phase == WORK            -> legal_placements(state)
(otherwise)              -> AssertionError
```

`_enumerate_pending` dispatches on the **type** of the top frame via the `PENDING_ENUMERATORS`
table (36 entries at last count — the Family frames plus the card-only ones; the three animal
markets share `_enumerate_pending_animal_market`). A
`PendingReveal` on top routes to `_enumerate_pending_reveal`, which returns one `RevealCard` per
still-unrevealed card of `stage_of_round(round_number + 1)` (the candidate set derived purely from
public state — a single trivial outcome on k=1 rounds). Each
enumerator follows the signature convention `(state, pending: PendingX) -> list[Action]` — the
dispatcher passes `pending` explicitly, so enumerators read `pending.X` directly and are
testable without building a stack. Per-enumerator legality/ordering is documented at each
function, and the interesting ones are covered in §4 next to their subsystems.

`legal_placements(state)` returns `[]` if the active player has no workers, else
`[PlaceWorker(space=s) for s, predicate in table.items() if predicate(state)]`, where `table`
is picked by `state.mode` — `FAMILY_GAME_LEGALITY` (the pre-card board) or `CARD_GAME_LEGALITY`
(no Side Job; `lessons` + the major-or-minor predicate) — one per-space placement predicate,
evaluated for the active player.

**Memoization.** `legal_actions` is uncached by default. Inside a `with legal_actions_cache():`
block it memoizes on `id(state)` (identity, not content hash — `hash(GameState)` is ~26 µs and
recursively hashes the whole state; identity lookup is ~70 ns). The cache stores
`(state, result)` so the object can't be GC'd and its id recycled. Intended for MCTS, where a
node holds a reference to its state and queries the same object repeatedly. Content-keyed
transposition tables are a separate, future layer. The returned list is shared by reference —
**callers must not mutate `legal_actions` output.** (PROFILING.md R1.)

---

## 2. The pending-decision stack (full)

`GameState.pending_stack: tuple[PendingDecision, ...]`, bottom-to-top, top is `[-1]`. Each
frame is a frozen, type-tagged dataclass; `PendingDecision` is the union. Phase 1 covers the
structure and the decider rule; this section is the complete reference.

### Provenance metadata

Every pending class carries two identities:

- `initiated_by_id: str` — mandatory instance field. Identifies the entity/event that pushed
  this frame.
- `PENDING_ID: ClassVar[str]` — class attribute. Identifies the *kind* of pending.

Three class shapes and their `PENDING_ID` style:

| Pending class | `PENDING_ID` |
|---|---|
| Space parent (`PendingGrainUtilization`) | `"grain_utilization"` |
| Generic sub-action (`PendingBakeBread`) | `"bake_bread"` |
| Card-specific template (`Pending<CardName>`) | the card's id in snake_case |

Four `initiated_by_id` value categories, using a namespaced prefix scheme so the two
cross-cutting namespaces (spaces, cards) cannot collide:

| Pushed by | `initiated_by_id` | Example |
|---|---|---|
| `PlaceWorker` (top-level) | `"space:<id>"` | `"space:grain_utilization"` |
| `ChooseSubAction` at a parent | parent's `PENDING_ID` (no prefix) | `PendingSow.initiated_by_id = "grain_utilization"` |
| A phase resolver (harvest, reveal) | `"phase:<id>"` | `"phase:harvest_feed"`, `"phase:reveal"` |
| A card trigger's effect | `"card:<id>"` | `"card:swing_plow"` |

The `space:` / `phase:` / `card:` prefixes make the namespaces disjoint by construction.

### The 10 stack invariants

1. **One pending per sub-action category.** No separate "intent" and "execution" frames; the
   frame's presence *is* the record of intent.
2. **Simple triggers don't push their own pending.** Parameter-free trigger fires are actions
   at the parent's level (e.g. `FireTrigger(card_id="potter_ceramics")` at `PendingBakeBread`).
   A trigger gets its own frame only if it needs parameterized sub-decisions.
3. **There is no `SkipTrigger`.** Declining is implicit — picking a commit (or another trigger)
   skips. Removing it eliminates a thorny one-ply-lookahead helper and adds no expressive power.
4. **Every pending carries `player_idx`.** Always set, never derived — enables out-of-turn
   trigger frames without retrofitting. The one frame with no owning player is `PendingReveal`,
   whose `player_idx` is `None` — the nature sentinel (see the decider rule below and §6).
5. **Non-atomic spaces push a parent pending**, even single-sub-action ones. The parent (a)
   tracks `*_chosen` flags (used by Stop-legality) and (b) hosts the space's trigger events.
6. **`PlaceWorker` and each `ChooseSubAction` push exactly one frame** — so triggers fire
   between well-defined stack states, not "somewhere mid-push."
7. **Parent `*_chosen` flags are set at choose-time, not commit-time.** The
   `_choose_subaction_*` handler does `replace_top(state, fast_replace(parent, <cat>_chosen=True))`
   before pushing; the commit dispatcher only asserts/effects/pops.
8. **Commit sub-actions inherit from `CommitSubAction`** and dispatch uniformly through
   `COMMIT_SUBACTION_HANDLERS`.
9. **`TRIGGER_EVENT` is a `ClassVar`** on pending types that fire triggers — read by
   enumerators to filter the trigger registry. Type-derived identity, no field bloat. Event
   names follow `"before_<PENDING_ID>"` / `"after_<PENDING_ID>"`. *(The card system revises this —
   see `CARD_IMPLEMENTATION_PLAN.md` §II.2: the event is **derived** rather than stored as a
   per-frame ClassVar, by routing `PENDING_ID` through a bucket. All **space-host** frames — the
   generic `PendingActionSpace` plus the per-space non-atomic frames — share the `action_space` base
   and fire a coarse `before_/after_action_space`; **sub-action** frames keep `<PENDING_ID>`. A
   `phase` field selects before/after. Routing on `PENDING_ID`, not `initiated_by_id`, is load-bearing:
   a sub-action frame's `initiated_by_id` is its parent's id, so it would mis-route.)*
10. **`triggers_resolved` is scoped to a frame's lifetime** — once-per-event-instance; a fresh
    frame starts with an empty set. **Never put `triggers_resolved`-like state on
    `PlayerState`** (that would make a trigger fire once per game, not once per event).

### Lifecycle of a non-atomic turn

- `PlaceWorker(space=…)` pushes the space's parent frame.
- `ChooseSubAction(name=…)` sets the parent's `<cat>_chosen` flag **and** pushes the category
  frame (one handler, both effects).
- `CommitX(…)` marks its single-commit sub-action host's work applied (`effect_initiated`);
  `_advance_until_decision` flips it to `phase="after"` (via `_enter_after_phase`) once the
  host is back on top — the **deferred after-flip** (ruling 60, 2026-07-14): anything the
  effect pushed resolves before the after-autos fire. For the usual push-nothing effect the
  flip lands within the same `step`. The trailing `Stop` pops. **Multi-shot hosts:** for
  `PendingBuildStables` / `PendingBuildRooms` / `PendingBuildFences`, the commit increments a
  counter and `replace_top`s, leaving the frame in its before-phase; **`Proceed`** (legal once the
  counter `>= 1`) flips it to after, and the trailing `Stop` pops. (The old per-commit
  `auto_pop=True` was removed when every sub-action became a uniform before/after host —
  SUBACTION_HOOK_REFACTOR.md.)
- `CommitBuildMajor` is the one commit that can *push* instead of pop: a plain major pops
  `PendingBuildMajor`, but a Clay/Stone Oven purchase pushes that oven's pending (which hosts a
  free Bake) on top, extending the chain — the build-major host stays in its before-phase
  (with `effect_initiated` set) until the wrapper resolves, then flips.
- `FireTrigger(card_id=…)` records the fire on the top frame; no push/pop.
- `Stop` pops the top frame.

Card-triggered sub-decisions push **on top of** the frame whose event they fire from — never
between existing frames. This guarantees that when a commit pops, the new top is always the
parent, with no stack-walking.

### The decider rule (restated)

Empty stack → `state.current_player`. Non-empty stack → `pending_stack[-1].player_idx`
(`decider_of`, `agents/base.py`, returns `int | None`). `current_player` = "whose worker
placement is being resolved"; `player_idx` = "whose decision this frame is for." They diverge
today during the harvest (one FEED and one BREED frame per player) and will diverge for future
out-of-turn card triggers.

A `PendingReveal` on top makes `player_idx` — and thus `decider_of` — `None`: **nature** decides,
not a strategic agent. The driver routes such a decision to the dealer (the `Environment` — §6),
never to `agents[...]`; `None` is not a valid list index, so a forgotten guard fails loudly rather
than silently routing to player 1. The `PendingReveal` frame itself is a nature/phase frame:
`PENDING_ID = "reveal"`, `initiated_by_id = "phase:reveal"`, `player_idx = None`. It is pushed by
the PREPARATION phase walk (§1, case 2), hosts exactly one `RevealCard`, and pops.

### Built with cards in mind

Several pieces were designed for card patterns ahead of need — all of them are now **live**,
exercised by the ~270 implemented cards:

- Out-of-turn triggers via per-frame `player_idx`.
- Triggers with sub-decisions via arbitrary stack depth.
- Card-aware legality via `*_EXTENSIONS` registries on `_can_*` predicates (e.g.
  `BAKE_BREAD_ELIGIBILITY_EXTENSIONS`; the full extension catalog is
  CARD_ENGINE_IMPLEMENTATION.md §3).
- Once-per-action trigger budgets via `triggers_resolved`.
- Provenance via `initiated_by_id` + `PENDING_ID` — now load-bearing for grant scoping (which
  card's discounts apply to a pushed frame) as well as debugging.
- Atomic spaces adopt the "push a parent pending" pattern when a played card hooks them — a
  *conditional* push (via `should_host_space`) of the generic `PendingActionSpace`.
  `ATOMIC_HANDLERS` still runs the primary effect (on `Proceed`), so the handler split
  **persists** rather than collapsing.
- A coarse `before_/after_action_space` event shared by **all** action spaces (atomic +
  non-atomic), with cards filtering by `space_id`. *(This superseded an earlier per-space
  `before_<space>` plan — the `PENDING_ID`-bucket routing, invariant 9.)*

The card system built on these seams is documented in **`CARD_ENGINE_IMPLEMENTATION.md`** —
hosts & firing (§2), the registries (§3), card state (§4), and the cost/food/capacity layers
(§5).

**Per-card budgets that span events** (once-per-round / -game / -harvest) live on `PlayerState`
or `BoardState`, not on frames. The stack holds *active* decisions, not a per-game scoreboard.

---

## 3. Sub-action mechanics

### The commit dispatch table

Every `Commit*` action maps to an `(expected_pending, effect_fn)` row in
`COMMIT_SUBACTION_HANDLERS` (`engine.py`), dispatched generically by `_apply_commit_subaction`
(§1). The dispatcher never pops — the effect function owns all stack manipulation. Once every
sub-action became a uniform before/after host (SUBACTION_HOOK_REFACTOR.md) the old per-row
`auto_pop` flag was uniformly `False`, so it was removed; the effect always either flips its host
to `phase="after"` (so the trailing `Stop` pops) or `replace_top`s for a multi-shot. The
"behavior" column below is what each effect does after applying its effect:

| Commit | Pending | Behavior |
|---|---|---|
| `CommitSow` | `PendingSow` | flip to after (`Stop` pops) |
| `CommitBake` | `PendingBakeBread` | flip to after (`Stop` pops) |
| `CommitPlow` | `PendingPlow` | flip to after (`Stop` pops) |
| `CommitBuildStable` | `PendingBuildStables` | multi-shot: `replace_top`; `Proceed` flips, `Stop` pops |
| `CommitBuildRoom` | `PendingBuildRooms` | multi-shot: `replace_top`; `Proceed` flips, `Stop` pops |
| `CommitRenovate` | `PendingRenovate` | flip to after (`Stop` pops) |
| `CommitAccommodate` | `(PendingSheepMarket, PendingPigMarket, PendingCattleMarket)` | pivots the market host to its after-phase, then `Stop` pops (CARD_IMPLEMENTATION_PLAN.md 4b) |
| `CommitBuildMajor` | `PendingBuildMajor` | flip to after, then pop (plain major) or push an oven pending |
| `CommitBuildPasture` | `PendingBuildFences` | multi-shot: `replace_top`; `Proceed` flips, `Stop` pops |
| `CommitHarvestConversion` | `PendingHarvestFeed` | False |
| `CommitConvert` | `PendingHarvestFeed` | False |
| `CommitBreed` | `PendingHarvestBreed` | False |

### Reusable sub-action pendings

Each primitive (plow, sow, bake, renovate, build stable/room/fence) is implemented **once** as a
reusable pending that any caller pushes, supplying its own per-call state. This is what lets a
wide range of spaces — and, later, cards — be expressed as compositions of primitives rather
than bespoke per-caller code.

**Directive, for the card phase** (tiered — reach for the lowest tier that works):

1. **Compose existing primitives.** A card effect that plows, sows, bakes, etc. pushes the
   existing primitive pending(s). No new code beyond the push.
2. **Add a new common primitive** if the effect generalizes across callers — a reusable pending,
   not a card-specific one.
3. **Mint a card-unique pending** (`Pending<CardName>` template, `PENDING_ID` = card id) only
   when the effect genuinely doesn't generalize. This is a sanctioned fallback, but the option
   of last resort — most card effects should land in tier 1 or 2.

**Caller-supplied state** is what makes one shared pending serve different callers. Set at push
time:

- `cost: Resources` — Side Job pushes `PendingBuildStables` with `cost=Resources(wood=1)`; Farm
  Expansion with `cost=Resources(wood=2)`.
- `max_builds: int | None` — Side Job pushes `max_builds=1`; Farm Expansion `max_builds=None`.
- `initiated_by_id: str` — provenance lets future code gate on entry point ("fires only when Bake
  Bread is reached via Grain Utilization").

The reusable pending stays generic; entry-point semantics live in the caller's pushed metadata.

| Pending | Distinguishing fields | Callers |
|---|---|---|
| `PendingPlow` | — | Farmland, Cultivation, card grants |
| `PendingSow` | — | Grain Utilization, Cultivation, card grants |
| `PendingBakeBread` | — | Grain Utilization, Side Job, Clay Oven, Stone Oven, card grants |
| `PendingRenovate` | — | House Redev, Farm Redev, card grants |
| `PendingBuildStables` | `cost`, `max_builds`, `num_built` | Side Job (cap 1), Farm Expansion (uncapped), card grants |
| `PendingBuildRooms` | `max_builds`, `num_built` | Farm Expansion, card grants |
| `PendingBuildFences` | `pastures_built`, `fences_built`, `subdivision_started` | Fencing, Farm Redev, card grants |

(`PendingRenovate` and `PendingBuildRooms` no longer store a `cost` — it is derived per commit
through the cost-modifier chokepoint; see the buckets below. The card game adds default-skipped
fields to `PendingPlow` / `PendingBuildFences` — multi-shot grants, the deferred fence tally,
restrictions — inert in Family: CARD_ENGINE_IMPLEMENTATION.md §4.)

**Exceptions:** if a future sub-action genuinely doesn't generalize across callers, document the
reasoning when the specialization is introduced — but default to reusable until proven otherwise.

### Sub-action cost handling — where the BASE cost comes from

The buckets below classify where an action's **base (printed) cost** originates. What happens to
that base is now uniform: every cost-modifiable action resolves it through the cost-modifier
chokepoint `effective_payments` / `can_pay` (CARD_ENGINE_IMPLEMENTATION.md §5), which in the
Family game — no cost cards owned — degenerates to exactly the base cost, byte-identically.

1. **No cost.** The sub-action doesn't debit (e.g. `PendingPlow`). No `cost` field.
2. **Caller-supplied — field on the pending.** The push site's *intent* determines the base and
   is not derivable from state: `PendingBuildStables.cost` (Side Job 1 wood, Farm Expansion
   2 wood, card grants 0) — the **one** cost still stored on a frame.
3. **Derived from player/commit state at resolve time.** The base is recomputed per commit by
   the action's `CostCtx` adapter: rooms (`ROOM_COSTS[house_material]`), renovate (per-room
   next-material + reed, priced per `CommitRenovate.to_material` target), majors
   (`MAJOR_IMPROVEMENT_COSTS[commit.major_idx]`), minors (the `MinorSpec` cost or its
   "/"-alternatives). The old stored `PendingRenovate.cost` / `PendingBuildRooms.cost` were
   removed — a stored cost is a cache that goes stale once cost cards make it depend on owned
   cards. The chosen payment rides explicitly on the *wide* commits
   (`CommitRenovate.payment`, `CommitBuildMajor.payment`, `CommitPlayMinor.payment`).
4. **Pure function of (state, commit) — geometry-derived.** `PendingBuildFences` /
   `CommitBuildPasture`: base = 1 wood × popcount(new boundary edges), computed by
   `compute_new_fence_edges(farmyard, cells)` in `fences.py` — each commit's cost depends on the
   farm state left by prior commits. The commit stays the minimal source of truth for action
   *identity*; the helper is the single source of truth for the base *formula*. (Fence payment
   is additionally **mode-branched** — Family debits per commit, Cards accrues and settles at
   `Proceed` — the one non-uniform cost path: CARD_ENGINE_IMPLEMENTATION.md §5.2.)

### Multi-shot sub-action pendings

Some categories allow multiple commits within one invocation: Farm Expansion's rooms/stables
(Side Job's stable is a degenerate cap-1 case) and Fencing's pastures. All three are **uniform
before/after hosts** (SUBACTION_HOOK_REFACTOR.md): they carry a `phase` ("before"/"after") and a
`triggers_resolved` set, exactly like the single-commit sub-actions, but because a multi-shot
frame has **no single commit to flip on**, the work-complete flip is an explicit **`Proceed`**
(the same signal the and/or space hosts use). The pattern:

- A counter (`num_built` for rooms/stables, `pastures_built` for fences; increments per commit)
  and, for rooms/stables, `max_builds: int | None` (caller cap, push time; `None` = uncapped).
  `max_builds` encodes only **caller intent** — affordability, supply, and placement availability
  are checked separately in the per-pending enumerator. Side Job pushes `max_builds=1`; Farm
  Expansion pushes `None`. `PendingBuildFences` has **no `max_builds`** (uncapped — the
  enumerator's dynamic constraints do all the bounding) and carries the builds-before-subdivisions
  flag `subdivision_started`.
- Each commit applies its effect, increments the counter, and `replace_top`s, leaving the frame in
  its **before-phase** — it does **not** pop and does **not** flip. (`COMMIT_SUBACTION_HANDLERS`
  no longer carries the old `auto_pop` flag; it was uniformly `False` once every sub-action became
  a before/after host, so it was removed — §1.)
- **`Proceed`** is the before-phase exit, legal once the counter `>= 1` ("must do at least one when
  entering a category"); not legal at `0`. It flips the frame to `phase="after"` via
  `_enter_after_phase` (firing the `after_<id>` automatic effects), where the enumerator offers
  `after_<id>` triggers + `Stop`, and **`Stop` pops** (a pure pop).
- The before-phase enumerator offers `Commit*` only while `(max_builds is None or num_built <
  max_builds)` AND affordability/placement/supply permit, plus `before_<id>` triggers, plus
  `Proceed` once the counter `>= 1`. When no commit is legal but the counter `>= 1`, `Proceed` is
  the only legal action — a singleton that arises uniformly whether the cap, supply, affordability,
  or cell-availability is the binding constraint, and which the agents auto-skip (the after-phase
  `Stop` is likewise a singleton). This matches the engine's "no auto-resolved singleton decisions"
  principle — uniformity over optimization.

The events these hosts fire are **derived** (`before_/after_<PENDING_ID>` — e.g.
`before_build_fences`, `after_build_rooms`) via `legality.trigger_event` from the `phase` field, not
stored as a per-frame `TRIGGER_EVENT` ClassVar (that ClassVar was dropped — invariant 9). All three
ids are in `SUBACTION_PENDING_IDS`, so a freshly-pushed frame fires its `before_<id>` autos at the
push (`_fire_subaction_before_auto`). `triggers_resolved` is scoped to the frame's lifetime
(invariant 10), so it persists across the multi-shot's commits within one invocation. The lone
remaining Stop-terminated (no-`phase`) sub-action frame is `PendingSideJob` (Family-only, never
card-hooked).

---

## 4. Subsystems

> **Performance note.** The three hardest helpers in this section — the fence-universe scan
> (§4.1), the Pareto/accommodation frontier (§4.2), and the harvest frontiers (§4.3) — each have a
> **default-on** projection-keyed cache and/or algorithmic fast path used to speed up MCTS,
> toggled via `agricola/opt_config.py` (`PARETO_OPT_LEVEL`, `FENCE_SCAN_CACHE`). This section is the
> *semantics* (what they compute, baseline path = level 0, untouched); the *optimization* — the
> projection keys, the proofs, the toggle, and the cross-level equivalence tests — lives in
> **`FRONTIER_OPT_DESIGN.md`**. If you change **what one of these helpers reads** (e.g. a card makes
> `pareto_frontier` depend on a new field), update its cache projection key there or the memo goes
> stale — see §5 ("Coding conventions") and the projection table in `FRONTIER_OPT_DESIGN.md` §2.1.

### 4.1 Fencing & Build Fences

Fencing is the most complex action in Agricola. The farmyard has 38 fence-edge primitives
(4×5 horizontal + 3×6 vertical); the legal subset of final configurations runs to the hundreds
or low thousands per state. Spatial outcomes interact with future room/field/stable placement,
so single-axis Pareto pruning is unsafe, and the action representation must be stable (changing
it later invalidates trained models).

**Build one pasture at a time.** Rather than choosing one final configuration from the enormous
space, the player makes a sequence of `CommitBuildPasture` commits — each names one pasture
cell-set; the engine applies the implied new fences and debits the cost (bucket 4); the player
commits another or `Stop`s. Building *pastures* not *fences* shrinks the space further: a 1×1 at
`(0,3)` might need 4 new edges or 3 depending on what already exists, and all those collapse to
the one cell-set `{(0,3)}`. The agent commits semantic intent (which cells); the engine derives
the fence delta.

**Builds-before-subdivisions.** Once any subdivision commit lands (`subdivision_started=True` on
`PendingBuildFences`), new-pasture commits drop out of `legal_actions` for the rest of the
action. This keeps the search tree from inflating across commit-order permutations.
(task_files/TASK_6.md Part 2.3 has the reachability argument.)

**Enumeration.** Per call, `_enumerate_pending_build_fences` converts the farmyard into a bundle
of bitmaps (current H/V fences, enclosable cells, existing-pasture cells, wood + supply scalars)
and iterates the universe of candidate pastures, checking each with cheap bitwise ops against
precomputed boundary/adjacency bitmaps: legal iff the candidate is unenclosed and a legal
addition, OR enclosed within an existing pasture and a legal subdivision.

**Universes.** The candidate set is a fixed list constructed once at `fences.py` import, so the
eventual policy-head output dimension is stable (one slot per pasture) and per-call legality is a
filter, not an enumerate-from-scratch. Four layered universes —
`FULL (1518) ⊇ FAMILY (762) ⊇ EXTENDED (193) ⊇ RESTRICTED (109)`. The runtime default is
**`UNIVERSE_RESTRICTED`**, a strategist-curated subset omitting never-optimal pastures (tiny,
pathological, wasteful), ~14× smaller than FULL for faster learning and smaller branching.
`fence_universe.py` provides swapping tools: `active_universe(spec)` context manager,
`restrict_to(predicate, base=…)` builder, `NAMED_UNIVERSES`, `current_universe()`. Edge metadata
lives on `PastureCandidate` entries; pack/apply helpers and `compute_new_fence_edges` are in
`fences.py`.

Implementation: `fences.py` (universes, edge metadata, cost helper); `legality.py`
(`_legal_fencing`, the build-fences enumerators, `_any_legal_pasture_commit`); `resolution.py`
(`_initiate_fencing`, `_choose_subaction_fencing`, `_execute_build_pasture`). Farm Redevelopment
reaches Build Fences via `ChooseSubAction("build_fences")` at `PendingFarmRedevelopment` (after
an optional Renovate).

**The `Farmyard.pastures` caching exception.** This is the first of **two** accepted on-object
deviations from "derived data, not cached data" — the second is `PlayerState.fences_in_supply`
(commit 77fe629): the fence-piece supply pile is *stored*, because a card (Ash Trees) moves
pieces onto a card independently of building, so `15 − fences_built` stops being the supply the
moment a card holds pieces. It equals `15 − fences_built` throughout any Family game, but its
value varies, so it is serialized and mirrored in the C++ `PlayerState`
(CARD_ENGINE_IMPLEMENTATION.md §5.2). Two further Cards-only notes on this subsystem: fence
*payment* is mode-branched (Family per-commit debit; Cards accrue-then-settle at `Proceed`), and
the fence-scan cache below serves **only** Family mode (its projection key can't see free-fence
budgets/restrictions) — both in CARD_ENGINE_IMPLEMENTATION.md §5.2.

`Farmyard.pastures` (the pasture decomposition) is cached on
`Farmyard`; all higher-level pasture-derived quantities (`enclosed_cells`, capacities, pasture
count, fenced-stable count) remain on-demand derivations from this one cached value. The cache
is maintained by **caller discipline**, not structural enforcement: the two pasture-changing
effect functions — `_execute_build_stable` (Side Job / Farm Expansion via `CommitBuildStable`)
and `_execute_build_pasture` (Fencing / Farm Redev via `CommitBuildPasture`) — pass
`pastures=compute_pastures_from_arrays(...)` explicitly when constructing the new `Farmyard`;
all other `Farmyard` mutations leave `pastures` alone and it rides along via `fast_replace`.
This deliberately weakens the "enforce structurally" factor — `__post_init__` auto-fill was the
original mechanism but is not used today (CHANGES.md Changes 2 & 3 have the rationale).

### 4.2 Animal accommodation & the Pareto frontier

The animal markets (`sheep_market` / `pig_market` / `cattle_market`) are accumulation spaces.
`_initiate_<x>_market` takes **all** accumulated animals onto the pending (the `gained` field —
staged, not yet on the player), zeros the space, and pushes the market parent. The player then
commits a final `CommitAccommodate(sheep, boar, cattle)` (post-event counts) that lands directly
on the market parent (no separate sub-action pending; the dispatcher's expected-type entry is the
tuple of all three market types).

**The Pareto frontier as the legal action set.** When the taken animals exceed what the farm can
hold, the player must release or convert the overflow. Rather than enumerate every
(keep, release, convert) configuration, `legal_actions` returns only the **Pareto-optimal
frontier over the upstream goods** (animals kept), computed by `pareto_frontier`. Helpers in
`helpers.py`: `extract_slots` (the farm's animal-holding capacity decomposition),
`can_accommodate` (does a configuration fit?), `pareto_frontier` (the frontier itself).
Card capacity modifiers plug into `extract_slots` via two folds — the house's flexible-slot
count (Family default 1, the pet) and a flat per-pasture bonus (default 0) — so every frontier
consumer inherits them; CARD_ENGINE_IMPLEMENTATION.md §5.4.

**Accommodation model.** Animals are **not** tracked per-pasture — only aggregate counts per
species are stored, and capacity is a *derived* quantity (sum of pasture/stable/house
allowances). This is an implementation choice (IMPLEMENTATION_CHOICES.md) that holds because the
Family game never needs to know *which* pasture an animal sits in.

**Preserving-optionality bundling (realized here first).** Release-or-convert is **not** a
standalone action — it is bundled into choosing the accommodation configuration. This is the
simplest realization of the Foundations "preserving optionality" principle, and the place its key
implementation rule is established: **Pareto dominance is computed over the upstream goods
(animals) only, never over the downstream conversion proceeds (food).** If configuration B
dominates A on animals, B preserved the same-or-more animals; choosing A would mean having
converted an animal beyond what the configuration required — exactly the
irreversible-conversion-without-need the principle prohibits. A naïve "Pareto over (animals,
food)" filter falsely retains those dominated options. Food is still computed and returned
alongside each frontier point as the deterministic consequence. The Harvest's `breeding_frontier`
and `harvest_feed_frontier` (next) are variations on this same idea.

### 4.3 Harvest sub-phases

The harvest fires at the end of rounds 4, 7, 9, 11, 13, 14 (`HARVEST_ROUNDS`). It is the only
multi-phase span outside WORK where players make strategic decisions. `_resolve_return_home`
routes to `HARVEST_FIELD` instead of `PREPARATION` on harvest rounds. Progression: **FIELD →
FEED → BREED.**

**`HARVEST_FIELD`** (mechanical, no decisions). `_resolve_harvest_field` takes 1 crop from each
planted field, resets `harvest_conversions_used` on both players (the once-per-harvest budget),
pushes one `PendingHarvestFeed` per player, transitions to `HARVEST_FEED`. In card mode, when a
player owns a harvest-field card, the `harvest_field` automatic effects fire first — *before*
the crop take (Scythe Worker reads unharvested fields) — via a transient host frame; skipped
entirely in Family (CARD_ENGINE_IMPLEMENTATION.md §2).

**`HARVEST_FEED`** (the strategic core). Each adult needs 2 food, each just-born newborn 1.
**Food payment is deferred to the final `CommitConvert`** — the feed-start does not touch
`p.resources.food`. The player opts into any subset of owned once-per-harvest craft conversions
(`CommitHarvestConversion` for joinery 1 wood→2 food / pottery 1 clay→2 food / basketmaker
1 reed→3 food, plus future card entries; firing pays the input and adds `food_out` to supply —
declining a craft is implicit, just commit without firing it), then commits one final
`CommitConvert(grain, veg, sheep, boar, cattle)` (consumed
amounts) chosen from the Pareto frontier returned by `harvest_feed_frontier`.

`_execute_convert` is the **sole payment site**: it adds `food_produced` to supply, pays
`min(need, supply + food_produced)` to feeding (the "cannot withhold food tokens" rule is
structural — the player has no knob to keep food while begging), leaves surplus in supply, and
assigns the shortfall as begging markers (assigned here, not by `Stop`, preserving the
Stop-only-pops convention). `food_owed` is **derived** (`max(0, need − food)`), recomputed each
`legal_actions` call, not stored on the pending. Why deferred: pre-debiting would block a future
card chain that *ends* in more food (e.g. food→clay→Pottery→food); in the Family game both models
are identical, so deferral preserves the option without retrofitting.

`harvest_feed_frontier`'s Pareto dimensions are the upstream goods **and begging markers** (fewer
is better) — begging is included because it's a strategic cost the player genuinely chooses to
incur (pay food and avoid the −3, or preserve goods and take the marker); excluding it would let
any full-feed config dominate any partial-feed config on a phantom "food-paid" axis. Food surplus
is still excluded, per the principle.

**`HARVEST_BREED`.** `_initiate_harvest_breed` pushes one `PendingHarvestBreed` per player; the
agent commits one `CommitBreed(sheep, boar, cattle)` (post-breed counts) chosen from
`breeding_frontier`, which already encodes pre-breed eating + per-type breed rules.
`_execute_breed` applies the chosen point's food via `breeding_food_gained(pre, post, rates)` — the
shared formula helper that `breeding_frontier` also calls to tabulate each point — rather than
re-enumerating the frontier to look the value up. The helper is the single source of truth for the
breeding food formula.

**Dual-meaning phases & gratuitous Stop.** Both HARVEST_FEED and HARVEST_BREED carry two meanings
by stack state (non-empty = a player is deciding; empty = phase-exit signal — see §1, cases 6–7).
Every player gets a frame in each sub-phase even with no decision to make (no convertibles, no
breeding animals): it matches "no auto-resolved singleton decisions," provides stable trigger-host
frames for future cards, and is symmetric with the parent-pending pattern atomic spaces will adopt.

**The round-card reveal sits near the start of each round.** After HARVEST_BREED drains (round < 14),
the walk transitions to PREPARATION — the preparation ladder (§1, case 2; ruling 54, 2026-07-14 as
revised): the `before_round` window fires, then the reveal nature step runs (a `PendingReveal` is
pushed, the dealer / chance node turns up the next round's stage card), then the post-reveal
segment increments the round, collects round-space goods, clears newborns, and refills
accumulation. So on harvest
rounds the full span is RETURN_HOME → HARVEST_FIELD → FEED → BREED → PREPARATION (reveal) → WORK;
on non-harvest rounds it is RETURN_HOME → PREPARATION (reveal) → WORK. A reveal happens entering
**every** round 1–14 — round 1's is dealt inside `setup_env` (the round-1 nature node is resolved
at game construction, so it never reaches search; §6), rounds 2–14's by the game driver. After
round 14's harvest, case 7 goes straight to BEFORE_SCORING — there is no round-15 reveal.

Implementation: `engine.py` (`_resolve_harvest_field`, `_initiate_harvest_feed`,
`_initiate_harvest_breed`, the three branches in `_advance_until_decision`); `resolution.py`
(`_execute_harvest_conversion`, `_execute_convert`, `_execute_breed`); `legality.py`
(`_enumerate_pending_harvest_feed/breed`); `helpers.py` (4-tuple `cooking_rates`,
`food_payment_frontier`, `harvest_feed_frontier`, `breeding_frontier`);
`cards/harvest_conversions.py` (the `HARVEST_CONVERSIONS` registry).

---

## 5. Coding conventions (appendix)

> Deferred decision ("punt to the end"): where the truly-universal conventions live — e.g.
> `fast_replace` and keyword action constructors could be hoisted to CLAUDE.md → Foundations
> rather than living here. Resolve once the rest of the rewrite settles.

### Player parameter convention (two-step rule)

**Step 1 — decide whether to take `p: PlayerState`.** Take it when the function could plausibly be
called for any player, not only the active one (per-player legality helpers — MCTS rollouts,
opponent-affecting triggers, and tests may query a non-active player). Do **not** take it when the
function is intrinsically about whoever is acting (resolution handlers, per-space placement
predicates) — derive `ap = state.current_player; p = state.players[ap]` locally. When the function
is about a known specific player but `current_player` isn't the right identifier, prefer an
explicit `player_idx: int` (`score(state, player_idx)`, `cooking_rates(state, player_idx)`).

**Step 2 — if you took `p`, never reference `state.current_player` for player-keyed lookups.**
Derive the index from `p` itself: `player_idx = 0 if p is state.players[0] else 1`. Identity
(`is`) requires callers to pass the canonical reference (`state.players[idx]`).

| Function | Shape | Why |
|---|---|---|
| `_can_bake_bread(state, p)` | `(state, p)` | A future opponent-affecting card may ask about the opponent |
| `_can_sow(p)` | `(p,)` | Reads only the player's farmyard/resources |
| `_resolve_day_laborer(state)` | `(state,)` | Applies the active player's placement by definition |
| `score(state, player_idx)` | `(state, player_idx)` | Runs at game end; neither player is "active" |
| `legal_placements(state)` | `(state,)` | Derives `ap` once internally |

### Function-name prefix taxonomy

| Prefix | Meaning |
|---|---|
| `_resolve_<atomic_space>` | atomic placement — fully applies effect |
| `_initiate_<nonatomic_space>` | non-atomic placement — pushes pending |
| `_choose_subaction_<space>` | handles `ChooseSubAction` at that space's pending |
| `_execute_<sub_action>` | applies a committed sub-action's effect |
| `_resolve_<phase>` | phase bookkeeping (in `engine.py`) |

### Signatures

- **Enumerators:** `(state, pending: PendingX) -> list[Action]`. The dispatcher passes `pending`;
  use `pending.X` directly. Type the list (`actions: list[Action] = []`).
- **Effect functions:** `(state, player_idx, commit: CommitX) -> GameState`. `player_idx` is
  explicit — don't derive from `current_player` (out-of-turn frames). May read
  `state.pending_stack[-1]` for its own frame.

### Smaller patterns

- **Dataclass field ordering:** `ClassVar` declarations first, instance fields after.
- **Action constructors:** keyword form always — `PlaceWorker(space="forest")`,
  `CommitSow(grain=1, veg=0)`.
- **Resource arithmetic:** `__sub__` for pure subtraction (`p.resources - cost`); a single
  `Resources` literal with negative components for mixed add/subtract
  (`p.resources + Resources(grain=-g, food=rate*g)`).
- **`fast_replace`, not `dataclasses.replace`**, at every production mutation site (~20% faster;
  `agricola/replace.py`). Test code keeps stdlib `replace` as the reference. (CHANGES.md Change 9.)
- **`replace_top`:** one-line form when the inner `fast_replace` fits; named `new_top` otherwise.
- **Replaced `PlayerState`:** name it `new_player`, flowing into `_update_player(state, ap,
  new_player)`.
- **Choose-time flag-setting:** every `_choose_subaction_*` sets the parent `<cat>_chosen=True`
  before pushing; the commit dispatcher never sets flags.
- **Handler-top binding:** bind `ap`/`p` once at the top; read from them, not from
  `state.current_player`/`state.players[X]` repeatedly. For effect functions, `p =
  state.players[player_idx]`.
- **Prefer `_update_player` / `_update_space`** over manual full-state replacement. Card modules
  construct the players tuple themselves (they can't import the helpers from `resolution.py` due
  to module ordering) — the accepted exception.
- **Cached-helper projection keys are a correctness contract.** Several helpers
  (`pareto_frontier`, `breeding_frontier`, `food_payment_frontier`, `harvest_feed_frontier`, the
  fence-universe scan) have opt-in `lru_cache`s keyed on a *projection* — the small slice of state
  they actually read (see `FRONTIER_OPT_DESIGN.md` §2.1). The memo is correct only while that
  projection is the complete set of inputs. If you broaden what a helper reads — most likely when
  implementing a card that makes it depend on a new field — **you must add that field to the cache
  key**, or the cache silently returns stale results. The cross-level equivalence
  test (`tests/test_frontier_opt.py`) is the guard: extend its state corpus to cover the new
  dependency. The optimizations are **on by default** now, so this risk is live; level 0
  (`PARETO_OPT_LEVEL=0`, no longer the default) is the live-recompute fallback.

---

## 6. Card machinery (pointer) & the nature-policy seam

**The card system is built.** The trigger machinery this section originally introduced grew into
the full card engine — hosts & firing, three firing kinds, ~30 registries, card-only state and
frames, the cost-modifier / food-payment / capacity layers — implemented and exercised by ~270
cards. **The reference for all of it is `CARD_ENGINE_IMPLEMENTATION.md`**; this document remains
the reference for everything the Family game exercises (including the host/Proceed lifecycle,
which runs in Family and is C++-ported). **Potter Ceramics** — the single card originally built
to validate the trigger machinery end-to-end — is now just an ordinary dealable minor among the
rest.

Status of the design questions this section used to defer:

- **Atomic-space trigger hosting** — **done** as designed: the conditional `PendingActionSpace`
  host with `phase` + `Proceed` (§2 above; CARD_ENGINE_IMPLEMENTATION.md §2).
- **Trigger events on harvest pendings** — **partial**: a `harvest_field` hook exists (auto-only,
  fired before the crop take); `PendingHarvestFeed`/`Breed` still carry no trigger events — a
  live boundary (CARD_ENGINE_IMPLEMENTATION.md §8).
- **Compound interactions / speculative legality** — **partial**: liquidation-aware affordability
  gates, the occupation-food-source simulation, and the fence-budget anticipation cover the
  load-bearing cases; placement-time speculation on unfired grants and the Grocer
  conversion-reachability problem remain open (CARD_ENGINE_IMPLEMENTATION.md §8).

### The `Environment` and the nature-policy seam

The hidden per-game ground truth lives outside `GameState`, in a frozen `Environment`
(`agricola/environment.py`). Today it holds exactly the round-card reveal order
(`round_card_order`, length 14, `order[i]` is round `i+1`'s card), built once at `setup` (so
"all randomness resolved in setup" still holds — the order is just carried in the env rather than
baked into the public state). `setup_env(seed) -> (GameState, Environment)` is the full
constructor; `setup(seed)` is `setup_env(seed)[0]` and returns a round-1 WORK state (the round-1
reveal is pre-resolved inside `setup_env`). `GameState` itself carries only **common knowledge**.

The driver-facing seam is **`env.resolve(state) -> Action`**: the **nature policy**. Whenever
`decider_of(state) is None` (a `PendingReveal` is on top — nature decides), the game driver calls
`env.resolve(state)` to obtain the true action instead of consulting an agent. Today `resolve`
delegates to `reveal_action`, which returns `RevealCard(order[round_number])` (the next round's
card). New nature events (a card draft, a deck draw) will add branches to `resolve` and their own
`Pending*` frames; nothing structural in the engine changes — the seam is already the single point
where nature's choices enter.

This is the symmetric special case of a general world-state / information-state split. How the
forward-compat sketch actually resolved when the card game landed:

- **The Environment still holds exactly the reveal order.** The original sketch put future
  private hands and the draw deck here too; the card game **superseded that**: hands live
  concretely on `PlayerState.hand_occupations` / `hand_minors` (CARD_IMPLEMENTATION_PLAN.md I.5;
  CARD_ENGINE_IMPLEMENTATION.md §4). `legal_actions` / `step` only ever read the *decider's own*
  hand, and hiding the opponent's hand from a search agent is handled **above the engine**
  (ISMCTS determinization — dealing plausible replacement hands at the search layer). So
  "GameState holds only common knowledge" survives in a weakened, per-decision form: the state
  carries both hands, but no decision ever consults the non-decider's.
- **`observe(state, env, i)` was never built.** The HIDDEN_INFO_DESIGN.md sketch proposed it as
  the projection every consumer would be written against; in practice no code needed it (the
  Family game's hidden info is symmetric, and the card game chose determinization above the
  engine). It remains unimplemented design intent — do not look for it in the code.

The **pre-round-1 card draft** did arrive, but as an ordinary decision phase rather than a
nature step: `setup_env(seed, card_pool=..., draft=True)` returns a `Phase.DRAFT` state and the
players themselves pick (`PendingDraftPick` / `CommitDraftPick` —
CARD_ENGINE_IMPLEMENTATION.md §4); the randomness is only in the seeded pool deal. (Original
design and the asymmetric-info / determinization direction: `HIDDEN_INFO_DESIGN.md` §3.4, §3.6,
§4.)
