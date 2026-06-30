# Card Authoring Guide

A practical, opinionated guide for a future coding session implementing **more Agricola
cards** (occupations and minor improvements). It tells you how to *read* a card, how to
*classify* it against the machinery already built, how to *fit it in*, and — most
importantly — **which cards to defer and ask the user about rather than guess.**

This guide assumes the engine and card infrastructure described in
`CARD_SYSTEM_DESIGN.md` (the design), `CARD_IMPLEMENTATION_PLAN.md` (the build plan +
current status), `SUBACTION_HOOK_REFACTOR.md` and `SPACE_HOST_REFACTOR.md` (the host
lifecycle), and `ENGINE_IMPLEMENTATION.md` §2/§6 (the pending stack + card-trigger
machinery). Read this first; reach for those for depth.

---

## 0. The cardinal rule: when in doubt, DEFER and ASK

**The single most important instruction in this document.** If you cannot confidently map
a card onto the existing machinery — its timing is ambiguous, it needs a mechanism that
does not exist yet, it interacts with another card in a way you are unsure about, or you
find yourself inventing new infrastructure to make it fit — **do not guess. Defer the
card and ask the user.**

The user understands Agricola's rules, rulings, and card interactions far better than a
coding agent does (they play at a world-class level). A card implemented on a plausible-
but-wrong reading is *worse* than an unimplemented card: it passes its tests, looks
finished, and is silently wrong in ways that only surface in real play. Several cards in
this project were deliberately deferred for exactly this reason (see §9).

Concretely:
- **Prefer deferring to guessing.** A deferred card costs nothing; a subtly-wrong card
  costs trust and is hard to find later.
- **Ask the user about timing, optionality, and interactions you are unsure of** — these
  are precisely the things a coding agent gets wrong and an expert gets right.
- **Ask before inventing new engine machinery for one card.** New infrastructure is a
  design decision, not a coding task; surface it.
- When you defer, record *why* (which mechanism is missing, or which ruling is unclear)
  in `CARD_IMPLEMENTATION_PLAN.md`, so the next session and the user can pick it up.

Everything below helps you decide *whether* a card fits — and if it clearly does, *how*.
If it does not clearly fit: §0.

---

## 1. How to read a card (the framework)

Work through these steps for every card, in order. Do **not** skip step 1.

### Step 1 — Read the EXACT card text from the data files

Never reason from memory or from a paraphrase — **every time a card is named (by you or the
user), look up its exact text before reasoning about or implementing it.** This is a hard
rule: a paraphrase has burned us (e.g. "Side Job stable" / Feed Fence misreads). The
authoritative text lives in:

- `agricola/cards/data/revised_occupations.json`
- `agricola/cards/data/revised_minor_improvements.json`

**Use the lookup tool** rather than grepping the JSON by hand:

```
python scripts/card_text.py "feed fence" millwright "carpenter's parlor"
```

It searches both files by name **or** slug, prints the verbatim `text` plus
`cost`/`prerequisites`/`vps`/`passing_left` and deck/number/category, and marks whether each
card is already **IMPLEMENTED** (its slug is registered). `--exact` matches the full name.

Each entry has `deck`, `number`, `name`, `card_category`, `text`, and (for minors) `cost`,
`prerequisites`, `passing_left`, `vps`. The card id used throughout the code is the
slugified name (e.g. `"clay_hut_builder"`). Quote the exact text in the module docstring.

The full card set spans decks **A–E** — deck E is the Ephipparius expansion (the 5th
mini-expansion). Entries may also carry two fields sourced from the Unofficial Compendium:
`errata` and `clarifications` (the lookup tool prints both). **Always read these before
implementing a card** — `errata` is an *official correction that can change how the card
works* (e.g. "the jump may only be done once per turn", "remove the 'If you do' clause"), so
it overrides the printed `text`; `clarifications` resolve exactly the obscure timing/scope
rulings this guide is about (§2). A card with errata is a strong signal to slow down and, if
the corrected behaviour doesn't map cleanly onto the machinery, **defer and ask (§0)**.

### Step 2 — Classify the static facts

- **Occupation or minor?** Occupations register via `register_occupation`; minors via
  `register_minor` (which also carries cost / prerequisite / VPs / passing).
- **Cost** (minors): the spendable `Cost` (Resources + Animals) paid at play.
  - **Pitfall — "X in your supply" is a PREREQUISITE, not a cost.** Wording like *"5 Clay
    in your supply"* means *hold* ≥5 clay (a have-check), **not** spend it. Model it with
    a `prereq=` predicate and an empty `cost=Cost()`. (See `thick_forest.py`.)
- **Prerequisite**: "N occupations" → `min_occupations` / `max_occupations` bounds.
  Anything else (farm geometry, house material, goods held) → a custom `prereq` predicate.
- **Victory points**: a fixed printed VP → `vps=`. A *variable* VP (depends on end-state)
  → a scoring term via `register_scoring` (§4, "Scoring terms").
- **Passing** (traveling minors): `passing_left=True` — the card moves to the opponent
  after its on-play effect instead of staying in your tableau.

### Step 3 — Identify the effect's TIMING

This is where cards are won or lost. Ask: *when does the effect happen?*

- **On play** — a one-time effect when the card enters your tableau (gain goods, push a
  primitive). → `on_play`.
- **Triggered by an action / event** — "each time you use [space]", "each time you build a
  room", "when you renovate", etc. → a trigger or automatic effect on the relevant
  before/after event (§3).
- **At a phase boundary** — "at the start of each round", during the harvest field phase.
  → `start_of_round` / `harvest_field` hooks (§3).
- **A standing condition becomes true once** — "once you live in a stone house, …". →
  a one-shot conditional latch (§4).
- **Deferred to a future round** — "place goods on the next N round spaces". →
  `future_resources` / `future_rewards` (§4).
- **At end of game** — a scoring term (§4).
- **"At the end of that turn"** — ⚠️ **a distinct, currently-DEFERRED timing.** See the
  pitfalls in §2; do not implement these at the action-space pop.

### Step 4 — Identify the FIRING KIND

Three kinds (§3):

1. **Automatic effect** — mandatory and parameter-free ("you get 1 wood"). Applied
   directly at the hook, never offered as a choice. → `register_auto`.
2. **Optional trigger** — a "you may" / a granted sub-action. Surfaced as a `FireTrigger`
   the player can take or decline. → `register`.
3. **Mandatory-with-choice** — must happen, but the player picks how ("you must take 1
   grain or 1 vegetable"). → `register(..., mandatory=True)` + a `PendingCardChoice`.

> **Pitfall — a granted SUB-ACTION is optional even when worded as a command.** "Build a
> room", "plow a field" read like imperatives, but a card that *grants a sub-action* gives
> the player the *option* to take it; only an explicit **"you must"** is mandatory. Model
> grants as optional triggers (kind 2) with a decline path. A pure-goods grant with no
> downside ("you get 3 food") can be an automatic effect (kind 1). When unsure: §0.

### Step 5 — Identify the PRIMITIVE(s) it composes

Card effects should *compose* the engine's existing primitives, never re-implement them:
plow, sow, bake bread, build room, build stable, renovate, build fence, family growth,
gain goods, gain animals, play a card. Each is a reusable pending you `push`
(`PendingPlow`, `PendingBakeBread`, `PendingBuildRooms`, `PendingRenovate`, …) or a direct
state edit (gain goods). If a card seems to need a *new* primitive, that is a §0 moment.

### Step 6 — Map to a template and implement

Find the existing card with the same shape (§7 has the catalog), copy its structure, and
adapt. If no template matches, you are probably in §0 territory.

---

## 2. Obscure rules, rulings, and pitfalls (read this twice)

These are the things a coding agent reliably gets wrong. Most are settled rulings; when a
new one comes up that *isn't* settled here, that's a §0 (ask the user).

### "Each time you use [action space]" fires BEFORE the space's effect

The official Trigger-Timing ruling: a bare *"each time you use [X]"* triggers in the
**before** phase, before the space's own effect resolves — **not** after. This is the same
ruling that puts Milk Jug, Wood Cutter, Corn Scoop, Herring Pot, and Cottager on
`before_action_space`. A card fires in the **after** phase only when its text says so
explicitly ("immediately after…"). The phase is a **correctness** decision fixed by the
card text and the ruling — *never* chosen by convenience, and never "before/after doesn't
matter here, I'll pick one" (a real bug was caught from exactly that reasoning). When the
observable outcome would coincide either way, still classify by the ruling.

### "End of turn" is NOT "after the action's effects and triggers"

A worker-placement turn does not end when the action space's effect and all its
before/after triggers finish. The engine *currently* makes the action-space host pop
coincide with the turn end **only because nothing player-controllable sits between an
action's resolution and the turn ending today.** Once "at any time" effects exist (see
below), a player can act in that gap, and "end of turn" becomes a strictly later moment.

**Consequence:** cards that read **"at the end of that turn"** (e.g. Firewood Collector)
are **DEFERRED** — there is no correct anchor for end-of-turn until the at-any-time window
is defined. Do **not** implement them by firing at the action-space pop; that lands the
effect one window too early and is silently wrong. End-of-turn and at-any-time timings are
co-dependent and must be designed together (with the user — §0).

### A granted sub-action is optional (repeated because it's missed often)

See §1 step 4. "You can also build a room or renovate" (Cottager) is optional and a
*choice*; "you may plow" (Assistant Tiller, Plow Driver) is optional; only "you must" is
mandatory. Optional grants surface as `FireTrigger`s with a decline path (the host's
Proceed/Stop). Never force a granted sub-action.

### Optionality lives at the PARENT host, never as a per-frame "skip"

There is **no `SkipTrigger` action and no per-frame skip flag.** A player declines an
optional trigger by choosing something else at the host (a different commit, or the host's
Proceed/Stop). When you add a frame, mirror this: the *parent* host hosts the choice; the
pushed primitive, once entered, runs to completion. (See `ENGINE_IMPLEMENTATION.md` §2.)

### Always gate a grant on whether it's actually doable

Never offer a dead-end. A trigger's eligibility must check that the granted action is
*legal and affordable right now* — a plow grant requires a plowable cell, a build-room
grant requires affording the cost *and* a legal placement cell, a renovate grant requires
a non-stone house and the materials. Use the engine's own predicates (`_can_plow`,
`_can_build_room`, `_can_renovate`, `_can_bake_bread`, …) so the card matches native
legality. (Cottager's `_legal_variants` is the model.)

### before/after the host: what fires when

The uniform host lifecycle (every action space and sub-action; §3): **before-automatic
effects fire when the host is pushed → before-triggers are surfaced alongside the work →
the work happens → after-automatic effects fire at the work-complete boundary (the commit
flip / Proceed / auto-advance) → after-triggers are surfaced → Stop pops.** After-autos
fire at the *flip*, **not** at the trailing Stop (Stop is a pure pop). Getting this order
wrong (firing after-autos at Stop) was a real regression.

### Build Rooms / Build Stables / Build Fences is ONE action, not a sequence

**The rule.** Each of *Build Rooms*, *Build Stables*, and *Build Fences* is a **single,
instantaneous action that builds everything you pay for at once.** Building three rooms is
*one* action that produces three rooms simultaneously — there is no game-time moment, no
"step," and no recognized timing/event/trigger opportunity *between* the individual rooms.
The action has exactly two timing boundaries the rules recognize: just **before** it (its
cost/effects are about to happen) and just **after** it (everything it did is now done).

**The implementation.** For tractability — branching factor for MCTS / policy-head width
(the action-shaping Foundation: a layout is a *path* of small commits, not one choice over
all final layouts) — the engine resolves these actions as a **chain of one-piece commits**:
`CommitBuildRoom` / `CommitBuildStable` / `CommitBuildPasture`, each placing a single piece,
with the multi-shot host (`PendingBuildRooms` / `PendingBuildStables` / `PendingBuildFences`)
staying on top until `Proceed` ends the action. **This split is a search/representation
convenience, not a change to game semantics.** The chain must produce exactly the effects
the one-shot rule would.

**The invariant (load-bearing).** The chain's *internal* boundaries — the gaps between one
piece-commit and the next — are **not** a recognized time/event/trigger opportunity, so
**no card effect (trigger, automatic effect, reward, anything) may fire there.** Effects
fire only at the **action** boundaries: the host's before-phase (fired at push) and its
after-phase (fired at the `Proceed` work-complete flip). The before/after host model
enforces this — `before_/after_build_rooms` (etc.) fire at push/Proceed, never per piece —
so the way to *stay* correct is: **hook the action boundary, never a per-piece moment
(there is no such event to hook).**

**What this means when you author a card that interacts with one of these actions:**
- **Compute per-action effects over the WHOLE action, not per piece.** A budget, a count,
  a comparison, or a reward that the card text scopes to "when you build rooms/stables/
  fences" spans every piece of that one action.
  - *Millwright* ("replace up to 2 building resources … each time you build … rooms"): the
    2 is a per-**action** budget shared across every room/stable in the action — tracked in
    the card's `CardStore` (each piece-commit's debit reads the running count and caps,
    `record` adds what it used, the `after_build_*` auto resets it), **never** 2-per-piece.
  - *Shepherd's Crook* ("each time you fence a new pasture covering ≥4 spaces …"): snapshots
    the pasture decomposition in `before_build_fences` and computes the grant **once** in
    `after_build_fences` by diffing before-vs-after — **never** per `CommitBuildPasture`
    (that's also why a 6→4+2 split in one action grants only for the undivided 4).
  - *Feed Fence* ("for each new stable … for your last one, get 3 food"): the "last stable"
    is only knowable once the whole action is done → an after-phase computation, not per
    piece.
- **Do not invent a per-piece event or fire between commits.** If you find yourself wanting
  something to happen "after this one room but before the next," stop — that moment does not
  exist in the rules. It's either a before-action effect, an after-action effect, or a §0.

### Atomic spaces must be explicitly HOSTED to be hookable

A truly *atomic* action space (Forest, Day Laborer, Grain Seeds, Fishing, the accumulation
spaces) normally resolves in one step with **no host frame** — so there is nothing for a
before/after trigger to attach to. If your card hooks such a space, you must call
`register_action_space_hook(card_id, {space_id})` so the space gets a `PendingActionSpace`
host when your card is owned. **Non-atomic** spaces (Farm Expansion, Grain Utilization,
Cultivation, House Redevelopment, the animal markets, …) are always hosted, so they need
no hook registration — just register the trigger/auto on `before_/after_action_space` and
filter by `space_id` in the eligibility predicate.

### A pasture is not a `CellType` — empty fenced cells read as `EMPTY`

`CellType` has only `EMPTY / ROOM / FIELD / STABLE`; there is **no `PASTURE` value**.
Pastures are derived from the fence arrays, not stored on the cell — so a cell that is
fenced into a pasture but holds no stable keeps `cell_type == EMPTY`. Any card that reasons
about farmyard-space occupancy ("all spaces used," "an empty space," counting pastures, etc.)
must therefore **consult the fences, not just `cell_type`**: a cell is *used* when
`cell_type != EMPTY` **or** it is in `enclosed_cells(farmyard)` (from `agricola/helpers.py`,
which reads the cached `farmyard.pastures`). Checking `cell_type` alone silently undercounts
every empty pasture cell. This is exactly the bug that made **Big Country**'s "All Farmyard
Spaces Used" prerequisite reject a fully-fenced farm; `big_country.py`'s
`_all_farmyard_spaces_used` is the reference for the correct check. (Pasture *capacity* and
animal counts likewise come from `farmyard.pastures` / the accommodation helpers, never from
the grid.)

### Hidden information — do not leak hands

Each player's hand is private. The *engine* operates on full ground-truth `GameState`
(determinization for search is handled above the engine — it is not your concern when
writing a card effect). But never write a card whose *legal actions or visible effect*
depend on the opponent's hidden hand in a way that would reveal it. If a card seems to
require reading hidden information, that's a §0.

### Family byte-identity — card-only state must be invisible to the Family game

Any new field you add to `PlayerState`/`GameState` for cards **must default to a value the
Family game always holds**, and must be added to *both* the manual `PlayerState.__hash__`
(in `state.py`) and `canonical._DEFAULT_SKIP_FIELDS` (in `canonical.py`). This keeps the
Family game byte-identical and its C++ differential gates green (see §6). If you cannot
make the field default-skippable — i.e. the Family game can reach a non-default value —
then it is a **Family-reachable** change that must be ported to C++ too; that is a larger
undertaking and a §0.

### "At any time" conversions are NOT surfaced as standalone actions

The engine deliberately does not offer at-any-time grain/veg/animal→food conversions as
free-standing actions (a rational agent always defers them to the moment proceeds are
needed, so surfacing them only inflates the action set). They are bundled into the decision
points that need them (animal-overflow, capacity-blocked breeding, harvest feeding). Do
**not** add ad-hoc at-any-time conversions for a card's cost. Cards whose cost is payable
from convertible goods need the deferred at-any-time-cost machinery (§9) — that's a §0.

### Scoped "once per …" — pick the right scope

Several latches exist; choose deliberately:
- `triggers_resolved` (on a host frame) — "once per this host visit" (a trigger can't
  re-fire within one action). Handled automatically by the firing machinery.
- `used_this_round` — once per round (Plow Driver, Scholar).
- `used_this_turn` — once per turn.
- `fired_once` — once per game (conditional one-shots; never cleared).
- `CardStore` — arbitrary per-card persistent value (a counter, a snapshot).

---

## 3. The machinery — the firing model

### The host lifecycle (one paragraph)

Action spaces and sub-actions are **before/after hosts**. A host carries a `phase`
("before"→"after") and a `triggers_resolved` set. When pushed, its before-automatic
effects fire; its before-triggers are surfaced as `FireTrigger`s alongside the work
options. When the work completes (a single-commit sub-action *flips* on its commit; a
multi-shot builder — including `PendingBuildFences` — and an and/or space *flip* on an
explicit `Proceed`; a delegating space auto-advances), the host enters its after-phase,
firing after-automatic effects; its after-triggers are surfaced alongside `Stop`; `Stop`
pops. (Every sub-action host now carries a `phase`; the lone Stop-terminated holdout is
`PendingSideJob`, a Family-only space that is never card-hooked.)

### Event names

A card registers an effect against an **event string**:

- **Action spaces:** `before_action_space` / `after_action_space` (one coarse event for all
  spaces; filter by `space_id` in eligibility). The composite improvement host uses
  `before_major_minor_improvement` / `after_major_minor_improvement`.
- **Sub-actions:** `before_<id>` / `after_<id>` for `id` in `sow`, `bake_bread`, `plow`,
  `renovate`, `build_major`, `build_rooms`, `build_stables`, `build_fences`,
  `play_occupation`, `play_minor`, `family_growth`. (`build_fences` joined the uniform
  host model — it flips to its after-phase on `Proceed`, like the other multi-shot
  builders; Shepherd's Crook hooks `before_/after_build_fences`.)
- **Phase hooks:** `start_of_round`, `harvest_field`.
- (`end_of_turn` was removed with Firewood Collector — see §2 and §9.)

### The three firing kinds and how to register them

| Kind | Register with | Eligibility fn | Apply fn | Surfaced as |
|---|---|---|---|---|
| Automatic effect | `register_auto(event, card_id, eligible, apply, *, any_player=False)` | `(state, idx) -> bool` | `(state, idx) -> state` | nothing (applied at the hook) |
| Optional trigger | `register(event, card_id, eligible, apply)` | `(state, idx, triggers_resolved) -> bool` | `(state, idx) -> state` | a `FireTrigger` |
| Mandatory-with-choice | `register(event, card_id, eligible, apply, *, mandatory=True)` + `register_card_choice_resolver(card_id, resolver)` | `(state, idx, triggers_resolved) -> bool` | `(state, idx) -> state` (pushes `PendingCardChoice`) | a `FireTrigger` that gates the host's Proceed/Stop until fired |

Note the **eligibility-signature difference**: automatic effects take `(state, idx)`;
triggers take `(state, idx, triggers_resolved)`.

### Other registration helpers

- `register_action_space_hook(card_id, spaces, *, any_player=False)` — make an atomic space
  hosted when this card is owned (required for hooking atomic spaces; see §2).
  `any_player=True` hosts on *either* player's use (opponent hooks — Milk Jug).
- `register_start_of_round_hook(card_id)` — make this card's owner get a `PendingPreparation`
  host each round (so its `start_of_round` autos/triggers can fire). *Do not* use this for
  a one-time scheduled effect — gate hosting on the schedule instead (see Handplow, §7).
- `register_harvest_field_hook(card_id)` — fire during the harvest field phase.
- `register_conditional(card_id, condition_fn, apply_fn)` — a one-shot level-triggered
  effect (`condition_fn(state, idx) -> bool`; fires once, latched in `fired_once`).
- `register_play_variant_trigger(card_id, variants_fn)` — for a trigger that offers a
  *choice* between routes; `variants_fn(state, idx) -> list[str]` returns the legal routes,
  each surfaced as a distinct `FireTrigger(card_id, variant=…)`, and the apply fn becomes
  `(state, idx, variant) -> state` (Scholar, Cottager).
- `register_scoring(card_id, fn)` — an end-game scoring term; `fn(state, idx) -> int`.
- `register_occupation(card_id, on_play)` / `register_minor(card_id, *, cost, …, on_play)`
  — the static spec. `on_play(state, idx) -> state` (or `(state, idx, variant)` for a
  play-variant occupation — Roof Ballaster).

### Pushing a primitive from an apply fn

An apply fn may `push(state, PendingX(player_idx=idx, initiated_by_id="card:<id>", …))`.
The engine fires that primitive's before-autos at the push and resolves it before
returning to the host. Use `initiated_by_id="card:<card_id>"` as the provenance. For a
multi-shot grant capped at one (a single granted room/stable), push with `max_builds=1`.

---

## 4. The special mechanisms (when a card needs more than a hook)

- **Deferred goods (future round spaces)** — "place 1 food on each of the next 3 round
  spaces". Goods/food ride `PlayerState.future_resources` (a 14-slot `Resources` tuple);
  use the `schedule_resources` helper in `cards/schedules.py`. They're collected
  automatically at each round's start. (Pond Hut, Strawberry Patch, Sack Cart, Thick
  Forest, Large Greenhouse, Wall Builder.)
- **Deferred animals or a deferred EFFECT** — ride the card-only `future_rewards` tuple
  (animals are auto-accommodated at round start; an effect-card id surfaces an optional
  `start_of_round` trigger gated on the schedule). Handplow is the worked example of the
  deferred-optional-effect pattern; `schedule_effect` is the helper.
- **One-shot conditional latch** — "once you live in a stone house, …". `register_conditional`;
  fires the first moment the condition holds, swept after a renovate and after a card play,
  latched in `fired_once`. (Manservant, Clay Hut Builder.)
- **Per-card persistent state** — a counter or snapshot the card reads/writes over the
  game. Use the `CardStore` side-map (`PlayerState.card_state`, `get`/`set`). (Tutor's
  snapshot, Moldboard Plow's uses-left, Big Country's banked points.)
- **Scoring term** — a variable end-game VP. `register_scoring`. (Stable Architect, Manger,
  Wool Blankets, Big Country.)
- **Opponent-action hook** — fires on the *opponent's* use of a space. `any_player=True`.
  (Milk Jug.)
- **Play-variant choice** — a trigger offering two routes. `register_play_variant_trigger`.
  (Scholar, Cottager.)

---

## 5. The implementation recipe

1. **Read the card text** (§1 step 1) and write it verbatim into the module docstring.
2. **Classify** (§1 steps 2–5). If it doesn't clearly fit: **§0 — defer and ask.**
3. **Create `agricola/cards/<card_id>.py`**, copying the closest template (§7). The
   module's body is just the effect functions + the `register_*` calls at import.
4. **Register the import** in `agricola/cards/__init__.py` (this is what makes the card's
   `register_*` calls fire). Group it near similar cards with a one-line comment.
5. **Write tests** in `tests/test_cards_*.py` — at minimum: registration; the effect on the
   real engine flow that fires it (drive the actual placement/turn, don't poke frames where
   a real flow exists); eligibility boundaries (when it should and shouldn't be offered);
   optionality (it can be declined); and any "once per X" scoping. Mirror an existing card
   test file's idiom (`_own_occ`/`_own_minor` helpers, `run_actions`/`step` walks).
6. **Run the suite:** `~/miniconda3/bin/python -m pytest tests/ -n 4 --dist worksteal -q`.
   Card work is **card-only**, so it should be Family byte-identical and the C++ gates
   (`tests/test_cpp_*.py`) stay green untouched. If a C++ gate breaks, you made a
   Family-reachable change — stop and reconsider (§6).
7. **Update `CARD_IMPLEMENTATION_PLAN.md`** — mark the card done (or, if deferred, record
   *why*). This convention keeps the plan the source of truth for status.

---

## 6. The C++ engine and the differential gates

The C++ twin under `cpp/` is **Family-only** — it implements none of the card system
(`FireTrigger` literally throws there). The `tests/test_cpp_*.py` differential gates feed
it **Family** states only. Therefore:

- **Card-only work never touches C++ and the gates stay green without any C++ change.** This
  is by design and is why the gates passing after a card commit means "Family parity
  intact," *not* "the card logic was cross-validated." **Card logic is verified only by the
  Python test suite** — so write thorough Python tests.
- **A Family-reachable change is different.** If you change engine state/structure that the
  Family game can reach (a new `PlayerState` field the Family game populates, a change to a
  Family-reachable pending frame, legality, scoring, or the encoder), you **must** re-port
  it to C++ and keep the gates green — see the maintenance invariant in `CLAUDE.md`
  (Foundations) and `CPP_ENGINE_PLAN.md`. Most card work avoids this by keeping new state
  card-only and default-skipped (§2). If you can't, that's a §0.

---

## 7. Template catalog — which existing card to copy

Find the row that matches your card's shape and copy that module's structure.

| Card shape | Copy from |
|---|---|
| Cost modifier — reduction ("costs N less") | `bricklayer.py`, `lumber_mill.py`, `master_bricklayer.py` (state-dependent delta) |
| Cost modifier — whole-cost formula ("only costs X") | `carpenter.py`, `clay_plasterer.py` (conditional), `carpenters_parlor.py` |
| Cost modifier — conversion ("replace A with B") / per-action-budgeted sink | `frame_builder.py`, `millwright.py` (the per-action-budget + `record` pattern) |
| Cost modifier — renovate-target extension ("renovate wood→stone directly") | `conservator.py` (`register_renovate_target_extension`; cost follows the target) |
| On-play: gain goods | `consultant.py`, `clay_embankment.py` |
| On-play: push a primitive (plow/etc.) | `shifting_cultivation.py` |
| Passing (traveling) minor | `market_stall.py` |
| Variable end-game VP (scoring term) | `stable_architect.py`, `manger.py`, `wool_blankets.py` |
| Automatic income on space use (before/after) | `wood_cutter.py`, `corn_scoop.py` |
| Optional granted sub-action (trigger) | `assistant_tiller.py`, `threshing_board.py`, `oven_firing_boy.py` |
| Mandatory-with-choice | `seasonal_worker.py`, `childless.py` |
| Play-variant choice (two routes) | `scholar.py` (start-of-round), `cottager.py` (action-space) |
| Opponent-action hook (`any_player`) | `milk_jug.py` |
| Start-of-round effect | `plow_driver.py`, `small_scale_farmer.py`, `scullery.py`, `groom.py` |
| Harvest-field effect | `scythe_worker.py`, `loom.py`, `butter_churn.py`, `three_field_rotation.py` |
| One-shot conditional latch | `manservant.py`, `clay_hut_builder.py` |
| Deferred goods (future round spaces) | `pond_hut.py`, `strawberry_patch.py`, `sack_cart.py`, `thick_forest.py`, `large_greenhouse.py`, `wall_builder.py` |
| Deferred optional effect (future round) | `handplow.py` |
| Per-card persistent state (`CardStore`) | `tutor.py`, `moldboard_plow.py`, `big_country.py` |
| Play-variant occupation (pay-or-not on play) | `roof_ballaster.py` |

If nothing matches, you are likely in §0.

---

## 8. A worked example — Cottager (B87)

Card text: *"Each time you use the 'Day Laborer' action space, you can also either build
exactly 1 room or renovate your house. Either way, you have to pay the cost."*

Walking the framework:
1. **Text** read from `revised_occupations.json` (deck B, #87).
2. **Static:** an occupation; no printed VP.
3. **Timing:** triggered by *using* Day Laborer → "each time you use" → **before**
   `action_space` on `day_laborer` (the ruling — §2). Day Laborer yields only food, so
   before/after is observationally neutral, but the ruling fixes it to *before*.
4. **Firing kind:** "you can also **either … or …**" → optional, and a **choice** between
   two routes → a **play-variant trigger** (kind 2 + the variant mechanism).
5. **Primitives:** build 1 room (`PendingBuildRooms`, `max_builds=1`) or renovate
   (`PendingRenovate`), each at the normal cost.
6. **Map:** Day Laborer is *atomic*, so `register_action_space_hook` is needed to host it.
   The two routes need `register_play_variant_trigger` with `variants_fn` returning
   `["room", "renovate"]` filtered by affordability/legality (`_can_build_room`,
   `_can_renovate`) — never offer a dead-end. Firing pushes the chosen primitive; the
   host's `triggers_resolved` gives once-per-use; the host's Proceed is the decline.

This required a *small, general* engine addition (expanding variant triggers at the
action-space host, not just the start-of-round host) — which was discussed with the user
before landing. A one-card engine change is exactly the kind of thing to surface (§0),
even when it turns out to be the right call.

---

## 9. The hard set — cards to DEFER and ASK about

These are **not** buildable on today's machinery. Do not attempt them without the user;
they need design decisions, not just code.

- **Cost-modifier cards** (a card that makes a build/renovate/improvement cheaper, or lets
  you pay it differently) — **NOW SUPPORTED** for renovate / build-room / build-major /
  play-minor / build-stable via the cost-modifier chokepoint (`COST_MODIFIER_DESIGN.md`;
  registries in `agricola/cards/cost_mods.py`: `register_reduction` / `register_formula` /
  `register_conversion`). See the §7 template row. Still deferred: **build-FENCE** cost cards
  (plan in `COST_MODIFIER_DESIGN.md` §9, not yet wired) and the *exotic* shapes — per-segment
  "Nth fence/room" discounts, per-action *total*-reduction budgets (Hunting Trophy), and a
  card whose cost is payable from at-any-time-convertible goods (the conversion-closure set,
  below).
- **Cards whose cost is payable from convertible goods** — needs the at-any-time-cost
  machinery (surface the Pareto-frontier conversion at the moment the cost is charged).
- **At-any-time conversion / "conversion closure" cards** — see §2; these are deliberately
  not standalone today.
- **Legality-changing cards** (a card that makes a normally-illegal action legal, or
  removes/changes a space) — needs the `*_EXTENSIONS` machinery generalized.
- **Per-card goods-stack cards** (goods accumulating *on the card*) — needs per-card goods
  state beyond `CardStore`'s scalar map.
- **"At the end of that turn" cards** (e.g. Firewood Collector) — DEFERRED until a true
  post-at-any-time turn-end boundary exists; co-dependent with the at-any-time design
  (§2). Do not anchor them to the action-space pop.
- **Individually deferred base cards** with known blockers: **Organic Farmer** (scoring over
  aggregate animal counts + the end-game "remove animals to free capacity" play),
  **Acorns Basket** (deferred animals scheduling). Revisit each only when its blocker
  lands. (**Mini Pasture** and **Shepherd's Crook** were on this list but are now
  IMPLEMENTED — `mini_pasture.py` via the restricted free-fence grant, `shepherds_crook.py`
  via the before/after `build_fences` CardStore snapshot.)
- **Animal grants have NO general accommodation path.** Animals are only kept-or-overflowed
  through the accommodation machinery at four points: the animal-market action spaces and
  breeding (`pareto_frontier` / `breeding_frontier`), harvest feeding, and the deterministic
  round-start collection of *scheduled* animals (`engine._collect_future_rewards`, which
  auto-takes the best accommodatable `pareto_frontier` point). A card that grants animals
  **immediately** — `p.animals + Animals(...)` in an `on_play` or trigger — bypasses all of
  this and simply inflates the count past capacity (silently wrong). So an immediate animal
  grant is a **defer-and-ask** unless the grant is guaranteed to fit (e.g. 2 sheep onto a
  brand-new ≥4-cell pasture, Shepherd's Crook). A "place N animals on the next round spaces"
  schedule is the safe shape — it routes through `_collect_future_rewards`'s accommodation.

`CARD_SYSTEM_DESIGN.md` §8/§15 is the authoritative list of the hard set and the flagged
cards; `CARD_IMPLEMENTATION_PLAN.md` tracks current per-card status. When a deferred card's
blocker is built, re-read its text (§1) and re-classify before implementing.

---

## 10. Discipline checklist (every card)

- [ ] Read the **exact** card text from the data files (`python scripts/card_text.py "<name>"`);
      quoted in the docstring.
- [ ] Classified timing + firing kind + primitives; it clearly fits — **or** deferred and
      asked (§0).
- [ ] Module created + imported in `cards/__init__.py`.
- [ ] Tests cover registration, the real-flow effect, eligibility boundaries, optionality,
      and scoping.
- [ ] Full suite green, including the C++ differential gates (untouched for card-only work).
- [ ] New card-only state (if any) is default-skipped in `canonical.py` + added to
      `PlayerState.__hash__`.
- [ ] `CARD_IMPLEMENTATION_PLAN.md` status updated.

And above all: **if you are unsure, defer and ask the user.** It is the cheapest correct
move and the one most likely to be right.
