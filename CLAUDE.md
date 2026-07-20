# AgricolaBot

A from-scratch Python implementation of the board game Agricola, with the long-term goal of
training a strong AI agent via MCTS and self-play reinforcement learning.

> **For new sessions:** this file is read automatically. It is organized as **Foundations**
> (cross-cutting principles), the project's phases (engine → agent → cards), two cross-cutting
> infrastructure sections (**the C++ twin engine**, **the web UI & deployment** — they serve
> multiple phases, so they live outside the phase ladder), then a status-and-boundaries note and
> a slim documentation index + directory map — **the full annotated versions of both live in
> `DIRECTORY.md`** (doc abstracts, per-file roles, script CLI flags; read on demand, not
> up-front). Deep engine mechanics live in
> **`ENGINE_IMPLEMENTATION.md`** (the reference companion to Phase 1). See also
> **`FILE_DESCRIPTIONS.md`** (per-file descriptions), **`TEST_DESCRIPTIONS.md`** (per-test
> coverage), **`design_docs/game_engine/ARCHITECTURE.md`** (original architecture spec, rules reference,
> dataclass definitions), and **`RULES.md`** (a comprehensive overview of the game's rules).

## Project Goal & Roadmap

Build a complete, deterministic Agricola engine and train a strong self-play AI agent on it —
first for the 2-player Family variant (done), now extending to the full card game.

The project — and this document — is organized into three phases, preceded by a cross-cutting
**Foundations** section (ways of thinking about Agricola + the engineering invariants; read it
first). This file carries orientation and a one-line status per phase; **dated, deep status
lives in each phase's reference doc** (that convention is what keeps this file from silently
going stale):

- **Phase 1 — The Game Engine.** Fast, correct, fully playable. **Done.**
  (Reference: `ENGINE_IMPLEMENTATION.md`.)
- **Phase 2 — Building an Agent** (Family game). Heuristic → MCTS → value/policy NN trained by
  self-play. **The AlphaZero-style loop is running; the joint shared-trunk champion has beaten
  world-class human players — including the project's author, a 2022 Agricola World Cup
  champion — and is believed stronger than any human at the 2-player Family game.** It plays as
  the web-UI bot. (Model lineage + current champion: `nn_models/REGISTRY.md`; design:
  `SHARED_TRUNK.md`.)
- **Phase 3 — Cards (and maybe 4-player).** Implement the full card system, then repeat the
  Phase 2 agent process for the richer game. **The card engine is built; ~528 of the 840-card
  catalog are implemented and playable in the web UI; no card-game agent exists yet.**
  (Reference + live status: `CARD_ENGINE_IMPLEMENTATION.md`.)

The 2-player Family variant (no hand cards) was built first to validate the whole
engine → agent → NN pipeline before card complexity was added.

---

## Foundations

These apply across every phase and should be internalized before working anywhere in the
codebase. They divide into *ways of thinking about Agricola* — which shape almost every
modeling decision — and *engineering invariants*, which the code's correctness depends on.

### Thinking about Agricola

**Turns decompose into primitive subactions.** Many worker placements are not atomic: a
placement initiates one or more *primitive subactions* — plow, sow, bake bread, build
fence, build room/stable, renovate. These primitives, not the action spaces, are the real
units by which a player changes the game state. Reason about the value of each primitive
separately (what is plowing worth? sowing? baking?) rather than treating an action space as
a monolith — a space is worth the sum of the primitives it unlocks. This is true now and
becomes central with cards, which recombine the same primitives into many new permutations.
The engine reflects this directly: each primitive is implemented once as a reusable building
block (see Phase 1 — "Reusable sub-action primitives").

**The legal action set is deliberately shaped.** What `legal_actions` hands the agent is not
a raw enumeration of everything mechanically possible — it is a deliberately narrowed set.
Branching factor (MCTS) and policy-head width (NN) are both downstream of how wide this set
is, so keeping it small *without discarding strategically meaningful options* is a recurring
concern. Three techniques recur:

- **Pareto frontiers.** When a decision has exponentially many configurations (which animals
  to keep on overflow, how much to breed, what goods to pay feeding with), we surface only
  the Pareto-optimal frontier over the *upstream goods*. Dominated configurations are never
  strategically correct, so pruning them is loss-less. (`pareto_frontier`,
  `breeding_frontier`, `harvest_feed_frontier`.)

- **Sequential decomposition.** Fencing, build-rooms, and build-stables are modeled as a
  *sequence* of small commits ("build one pasture," then optionally another) rather than one
  choice over all possible final layouts. A single-shot choice over every legal fence layout
  would be thousands of options; the sequential model keeps each step's branching tiny. This
  has a direct MCTS consequence: a fence layout becomes a *path* of commits, which is why
  `mcts.py` introduces macro-actions (`MacroFencingAction`) to keep the tree from exploding
  in depth.

- **Preserving optionality.** An irreversible "at any time" conversion (grain → food, say)
  can always be deferred to the exact moment its proceeds are needed; converting earlier only
  forfeits the chance to have spent those goods on something else. A rational agent therefore
  never converts early, so surfacing "convert now" as a standalone action only inflates the
  action set with choices it should never make. We never surface such conversions standalone
  — they are *bundled* into the decision points where the proceeds are actually needed
  (animal-acquisition overflow, capacity-blocked breeding, harvest feeding). One non-obvious
  consequence: when these decision points return a frontier, Pareto dominance is computed over
  the upstream goods only, never over the downstream proceeds (food) — including food would
  falsely retain the very options this principle prunes. (Full rule, the begging-marker
  refinement, and current applications: Phase 1 / `ENGINE_IMPLEMENTATION.md`.)

**Feeding is the worked example.** Feeding is the recurring pressure that organizes the whole
game: at each harvest (rounds 4, 7, 9, 11, 13, 14) every adult needs 2 food and every newborn
needs 1. It is where the ideas above meet — payment is *deferred* (preserving optionality: we
don't pre-debit food the player might route through a food-producing card chain) and the choice
of what to pay with is presented as a Pareto frontier over (goods converted, begging-markers),
with food surplus excluded. It is the single most subtle decision point in the engine and the
clearest illustration of why the action set is shaped as it is.

**The round-card reveal is nature's move.** Each round's stage card is turned up by a *chance
event* — nature's shuffle, not any player's choice — so the engine state carries only common
knowledge: the public `revealed` status of each card, never the hidden future order. A reveal is
modeled as an explicit nature step (Phase 1 — the reveal transition; Phase 2.2 — MCTS chance
nodes).

### Engineering invariants

The first three are near-absolute — they are load-bearing for MCTS and self-play, and
deviating from them would break the AI training pipeline. The fourth ("derived data, not
cached data") is a default with explicit guidance for when to deviate.

- **Immutable frozen dataclasses.** Every piece of game state is a `@dataclass(frozen=True)`.
  State is never modified in place; every transition produces a new state object via
  `fast_replace` (a faster drop-in for `dataclasses.replace`; see `ENGINE_IMPLEMENTATION.md` —
  Coding conventions). This makes tree search safe and cheap — MCTS branches share unchanged
  subtrees with no copying required.

- **Functional core.** Game logic lives in plain functions (`setup`, `legal_actions`,
  `resolve`, `score`). State objects have no methods that modify state.

- **Determinism after setup.** All randomness (starting player, the per-stage card shuffle) is
  resolved in `setup(seed)` using a seeded NumPy RNG. After `setup` returns, the engine is
  fully deterministic. The resulting reveal order is *hidden* — it does not live in `GameState`,
  which holds only common knowledge. Game state, hidden ground truth, and per-player observation
  are split across three layers: **`GameState`** carries common knowledge (the public `revealed`
  bool per card, public resources/farmyard); the **`Environment`** (`agricola/environment.py`,
  built at `setup`) holds the hidden ground truth + nature policy — today the round-card reveal
  order. (An `observe(state, env, i)` per-player projection was sketched as the third layer but
  **was never built** — the card game put private hands on `PlayerState` and handles hiding above
  the engine via determinization; see `CARD_ENGINE_IMPLEMENTATION.md` §4.) Each round's stage card is turned up
  by an explicit nature step — a `RevealCard` that consumes the next entry of the hidden order —
  driven by the `Environment` in real games and by chance nodes in MCTS. "All randomness resolved
  in `setup`" still holds; the order is simply carried in the `Environment` rather than baked into
  the public state. Because the seed also assigns the starting-player advantage — the only
  positional asymmetry in the game — P0 and P1 are otherwise symmetric labels: don't seat-swap
  in agent evaluation (one consistent-seat run over many seeds already averages the SP
  advantage) and don't read a per-seat W-D-L split as seat bias.

- **Derived data, not cached data (default).** Default to recomputing derived quantities
  (animal capacity, fences remaining, stables remaining, enclosed-cell membership, pasture
  count, etc.) on demand from ground-truth state rather than storing them separately. The
  reason: any cached value introduces a sync invariant — every code path that mutates the
  underlying state must also keep the cache consistent. In a frozen-dataclass codebase with
  millions of state objects flowing through MCTS, a single missed update creates
  silently-wrong states that are hard to debug. Recomputing is microseconds and trivially
  correct.

  **When to deviate.** This is a default, not a prohibition. Caching is sometimes the right
  call, and proposing one is welcome. Three factors make a cache safer to adopt; the more of
  them apply, the stronger the case:
  1. The derived value is genuinely expensive, or read often enough in hot paths (e.g. inside
     MCTS rollouts or legality enumeration) that the per-call cost is meaningful.
  2. The cache invariant can be enforced *structurally*, not by convention. The strongest form
     is auto-fill in `__post_init__` on a frozen dataclass: every constructor call (including
     `dataclasses.replace`) recomputes the cache, so there is no caller-discipline rule that
     can be forgotten.
  3. The cache lives on the same object that owns its inputs, so the only code paths that can
     produce a new cache value are the same ones that can produce a new input value.

  When caching, prefer the *most fundamental* form of the data and derive everything else from
  it. Don't cache multiple representations of the same underlying fact.

  **Note for future sessions.** If you find yourself instinctively rejecting a caching proposal
  because "the design doc says no," reread this principle: the doc describes a default and a
  set of analytical factors, not a hard rule. A well-reasoned caching proposal that addresses
  the three factors above can override this default.

  **Two kinds of caching — and the three factors above are about the riskier one.** Those
  factors govern caches *stored on a state object* (like `Farmyard.pastures`), where the
  sync-invariant footgun is real. A second technique sidesteps that footgun entirely:
  **projection-keyed memoization of a pure function** (`functools.lru_cache` on a helper, keyed
  on the small slice of state it actually reads). There is no sync invariant to maintain because
  the key *is* the inputs — a stale entry is impossible, since any change to the inputs yields a
  different key. This is the preferred form when the expensive thing is a *computation*
  (legality enumeration, a Pareto/accommodation frontier, the fence-universe scan) rather than a
  *field of a state object*, and it is exactly the form that makes "speed up MCTS" — factor 1 —
  a first-class reason to cache rather than a reluctant deviation. The first wave is **landed**:
  the frontier/accommodation helpers and the fence-universe scan are memoized this way behind
  toggles in `agricola/opt_config.py` (now **default-on**; full design, correctness proofs, and the
  cross-level equivalence testing pattern in **`FRONTIER_OPT_DESIGN.md`**; the worked numbers in
  Phase 2.2 "Speeding up MCTS" and `PROFILING.md`). The one caveat for this form is a *hidden*
  global input not in the key (e.g. the active fence universe) — flush the cache when it changes,
  as `active_universe(...)` does. So the standing guidance is: for a hot **field of state**, weigh
  the three factors; for a hot **pure computation**, reach for projection-keyed memoization by
  default.

  The two current accepted exceptions *of the on-object kind* — `Farmyard.pastures` (the pasture
  decomposition; caller-discipline maintenance contract in `ENGINE_IMPLEMENTATION.md`) and
  `PlayerState.fences_in_supply` (the fence-piece supply pile, stored because a card can hold
  pieces off-supply; `CARD_ENGINE_IMPLEMENTATION.md` §5.2) — are documented there.

- **The Python engine is the source of truth; keep the C++ differential gates green.** A native C++
  reimplementation of the self-play inner loop now exists (see "The C++ twin engine" /
  `CPP_ENGINE_PLAN.md`), validated
  against *this* Python engine by the `tests/test_cpp_*.py` differential harness (it is the oracle).
  **Any change to the Python engine — rules, legality, scoring, the encoder, or the state/action
  shape — must keep those gates green:** re-port the change into `cpp/` and re-run
  `~/miniconda3/bin/python -m pytest tests/test_cpp_*.py`. Otherwise the two engines silently
  diverge and the C++ self-play data becomes wrong. If you change the engine and don't update C++,
  say so explicitly and treat the C++ path as stale until re-synced. (The C++ engine is Family-only
  — cards must be ported there before C++ self-play is used for the card game; the harness makes
  that re-port safe.) This is the maintenance cost the differential harness exists to contain.

---

## Phase 1 — The Game Engine

*Orientation only. The deep mechanics — sub-action cost handling, the function-name taxonomy,
the fence universe, the harvest resolvers, the full pending-provenance scheme, and the
remaining stack invariants — live in `ENGINE_IMPLEMENTATION.md`.*

### The engine in one paragraph

The engine exposes exactly two functions. `legal_actions(state)` returns the actions legal
right now; `step(state, action)` applies one action and returns the next state. Both are pure
— no I/O, no agent queries, no game loop. The loop that drives a game
(`actions = legal_actions(state); a = pick(actions); state = step(state, a)`) lives in each
caller, not the engine. The rest of this section covers the state those two functions operate
on, then how they work.

### The state model

`GameState` is the top-level frozen snapshot. It is fully hashable, and every transition
produces a brand-new one via `fast_replace` — nothing is ever mutated in place (see
Foundations). Its fields:

- `players: tuple[PlayerState, PlayerState]` — the two players' full state.
- `board: BoardState` — the action spaces (a canonical-ordered tuple) and goods accumulated on
  them.
- `phase: Phase`, `round_number: int` — where in the game we are.
- `current_player: int` — whose worker placement is currently being resolved.
- `pending_stack: tuple[PendingDecision, ...]` — in-progress mid-turn decisions (next
  subsection).

A `PlayerState` carries that player's resources, animals, `Farmyard` (with its cached pasture
decomposition), house material and rooms, family members / workers, played cards
(`minor_improvements`, `occupations`), and per-game budgets such as `harvest_conversions_used`.
`BoardState` carries the action spaces and the goods sitting on accumulation spaces. Each
`ActionSpaceState` carries `revealed: bool` (common knowledge — `True` once the card has been
turned up; permanents are `True` from setup); the *hidden* reveal order is **not** on
`BoardState` — it lives in the `Environment` (Foundations — "Determinism after setup"). The
full constructor is `setup_env(seed) -> (GameState, Environment)`, which builds the order, deals
round 1, and returns the round-1 WORK state plus the env that deals rounds 2–14; `setup(seed)`
is the thin wrapper `setup_env(seed)[0]` for callers that only inspect or build on that state.

The first five fields describe the *game and player situation*. The sixth, `pending_stack`,
describes *turn execution* — the state the engine keeps while it pauses a non-atomic turn to
ask the agent a sub-question. It gets its own subsection because it is the one piece of
`GameState` that is non-obvious.

*(Field-by-field detail: `state.py` and `FILE_DESCRIPTIONS.md`.)*

### The pending-decision stack — structure

Many worker placements are non-atomic: a single placement initiates a chain of sub-decisions
before the turn ends (Foundations — subaction decomposition). The engine handles this by
pausing mid-action and resuming, driven entirely by agent choices. The `pending_stack` is
where the in-progress decisions live.

**Structure.** It is a `tuple[PendingDecision, ...]`, bottom-to-top; the top is
`pending_stack[-1]`. Each frame is a frozen, type-tagged dataclass — `PendingGrainUtilization`,
`PendingSow`, `PendingBakeBread`, `PendingFencing`, and so on — and `PendingDecision` is the
union over them. There is **one frame per sub-action category**: a frame's presence on the
stack *is* the record that its decision is in progress (no separate "intent" and "execution"
frames). Even a non-atomic space offering only one sub-action pushes a parent frame, because
the parent both tracks which sub-action categories have been chosen and hosts the trigger
events that cards will attach to that space. A few frames are *phase* frames rather than
sub-action frames — notably `PendingReveal`, the nature/phase frame for the round-card reveal
(`player_idx = None`).

**What a frame carries.** Every frame has a `player_idx` (whose decision this frame is for) and
provenance (`initiated_by_id` + a class-level `PENDING_ID`), plus its own sub-action fields.
Provenance is a debugging / card-gating breadcrumb; the full namespacing scheme is in the
engine doc.

**The decider rule** — the one genuinely non-obvious thing in the engine, and the thing
sessions get wrong:

> Whose decision is awaited *right now*?
> - **Empty stack** → `state.current_player` is the decider.
> - **Non-empty stack** → `pending_stack[-1].player_idx` is the decider.

So `decider_of(state)` returns `0`, `1`, or **`None`**. `None` is the nature case: a
`PendingReveal` (the round-card reveal) carries `player_idx = None`, so its decider is no player
— the driver routes it to the dealer (`env.resolve`), never to a strategic agent. (`None` is not
a valid list index, so a forgotten guard fails loudly rather than silently routing to player 1.)

`current_player` records "whose worker placement is being resolved"; a frame's `player_idx`
records "whose decision this frame is for." They are usually the same, and diverge when a
frame's decider isn't the active player. This is not hypothetical: the harvest pushes one
feeding frame and one breeding frame *per player*, so frames belonging to both players coexist
on the stack — that is the live, already-implemented case where `player_idx`, not
`current_player`, is the source of truth. (`PendingReveal`'s `player_idx = None` is the nature
case; future out-of-turn card triggers are another.)

How the stack *evolves* — push and pop — is part of the transition model below, since that is
driven by actions.

*(The remaining stack invariants — simple-trigger handling, `TRIGGER_EVENT` / `triggers_resolved`
scoping, the choose-time flag-setting convention, `CommitSubAction` dispatch — are in
`ENGINE_IMPLEMENTATION.md`; the card-trigger ones are also cross-referenced from Phase 3.)*

### Reusable sub-action primitives

The primitives from Foundations (plow, sow, bake bread, …) are each implemented **once**, as a
reusable pending that any caller can push — supplying its own provenance and, where relevant,
cost. This is what lets a wide range of action spaces and, later, cards be expressed as
compositions of the same primitives rather than bespoke per-space code.

| Pending | Callers |
|---|---|
| `PendingPlow` | Farmland, Cultivation |
| `PendingSow` | Grain Utilization, Cultivation |
| `PendingBakeBread` | Grain Utilization, Side Job, Clay Oven, Stone Oven |
| `PendingRenovate` | House Redevelopment, Farm Redevelopment |
| `PendingBuildStables` | Side Job, Farm Expansion |
| `PendingBuildFences` | Fencing, Farm Redevelopment |
| `PendingBuildRooms` | Farm Expansion |

The same primitive serves different callers through push-time parameters: Side Job pushes
`PendingBuildStables` with a 1-wood cost capped at one build, Farm Expansion pushes it with a
2-wood cost and no cap. How those parameters are carried — the cost-handling buckets, the
multi-shot counters — is in the engine doc.

Build Fences is the most complex — it is multi-shot (the player commits one pasture at a time)
and its cost is a function of the current farm state. The Foundations "sequential decomposition"
note covers *why*; the mechanics (cost buckets, multi-shot lifecycle, the fence universe) are in
the engine doc.

### The transition model — dynamics

**`step(state, action) -> GameState`** is the only transition. It is pure: takes a state and an
action, returns a new state; it does not loop, query an agent, or drive a game. Five
philosophies govern it:

- **`step` does not verify legality.** Callers must ensure `action in legal_actions(state)`
  (typically an `assert` in the agent loop). Single source of truth for legality.
- **`step` does not auto-resolve singleton decisions.** Even when `legal_actions` returns one
  action, that action is still an observed `step` boundary — the agent loop may skip the
  prompt, but the step is recorded. Trace consistency for MCTS, replay, debugging.
- **Player alternation lives in `step`**, not in `_advance_until_decision` — only `step` knows
  "an action was just applied."
- **The engine exports only `step` + `legal_actions`.** No `play_round` / `play_game` / MCTS
  driver — those are caller-dependent compositions.
- **`_advance_until_decision` is state-driven and idempotent.** Re-running it on a returned
  state is a no-op.

**`legal_actions(state) -> list[Action]`** is the only legality entry point. It dispatches on
the stack: empty stack → legal worker placements (`legal_placements`); non-empty stack → the
top frame's legal sub-actions (a per-pending enumerator).

**`_advance_until_decision(state)`**, called at the end of every `step`, walks *system*
transitions — phase changes (WORK → RETURN_HOME → PREPARATION → WORK), terminal detection —
until the state is at a real agent decision or game-over. It does not advance the current player
and does not auto-resolve agent decisions. The **PREPARATION** phase is a timing *ladder*
(`_advance_preparation` walking `agricola/cards/preparation.py`'s step table — ruling 54,
2026-07-14 as revised, the sibling of the harvest and round-end ladders): the `before_round`
card window fires, then the round-card reveal runs as a nature step (a `PendingReveal` for the
round being entered pauses the walk), then `round_number` increments, round-space goods are
collected and newborns become adults, the `start_of_round` card window fires, every `revealed`
accumulation space refills, and the `replenishment` / `before_work` / `start_of_work` card
windows fire before the phase flips to WORK. In the Family game every window is empty, so the
walk is the mechanical steps plus the reveal pause — byte-identical to the pre-ladder engine. `RevealCard` is dispatched in `_apply_action` (turning the named card's `revealed`
to `True` and popping the frame) — a top-level transition like `PlaceWorker`, not a
`CommitSubAction`.

**How the stack evolves.** Within a non-atomic turn:

- `PlaceWorker(space=…)` pushes the space's parent frame.
- `ChooseSubAction(name=…)` sets the parent's `<category>_chosen` flag **and** pushes the
  category's frame (both in one handler).
- `CommitX(…)` pops the category frame. *(Multi-shot pendings instead increment a counter and
  `replace_top`; `Stop` is the explicit exit that pops.)*
- `FireTrigger(card_id=…)` records the fire on the top frame; no push / pop.
- `Stop` pops the top frame.

`PlaceWorker` and each `ChooseSubAction` push **exactly one** frame, and card-triggered
sub-decisions push on top of the frame whose event they fire from — so when a commit pops, the
new top is always the parent, with no stack-walking.

**Worked example — Grain Utilization (sow one grain, then bake one bread):**

```
[]
  PlaceWorker(space="grain_utilization")        # empty stack → place a worker
[PendingGrainUtilization]
  ChooseSubAction(name="sow")                   # set sow_chosen, push PendingSow
[PendingGrainUtilization, PendingSow]
  CommitSow(grain=1, veg=0)                     # apply sow, pop
[PendingGrainUtilization]
  ChooseSubAction(name="bake_bread")            # set bake_chosen, push PendingBakeBread
[PendingGrainUtilization, PendingBakeBread]
  CommitBake(...)                               # apply bake, pop
[PendingGrainUtilization]
  Stop                                          # pop parent; turn ends
[]
```

#### Harvest (phase progression)

On rounds 4, 7, 9, 11, 13, and 14 the WORK → PREPARATION transition detours through a harvest:
FIELD → FEED → BREED. FIELD is mechanical; FEED and BREED each push one frame per player
(`PendingHarvestFeed` / `PendingHarvestBreed`) — the concrete case the decider rule exists for.
The mechanics (deferred food payment, the feed / breed frontiers) are in the engine doc.

### Going deeper

The deep mechanics live in **`ENGINE_IMPLEMENTATION.md`**, organized so you can jump to what you
need:

- **§1 — Engine structure & dispatch.** How `step` and `legal_actions` work inside: the dispatch
  tables, the phase walk, and the full list of action spaces.
- **§2 — The pending stack.** The complete reference: frame provenance, every stack invariant,
  and the non-atomic-turn lifecycle.
- **§3 — Sub-action mechanics.** How primitives are reused across callers, how their costs are
  handled, and the build-one-at-a-time (multi-shot) pattern.
- **§4 — Subsystems.** Deep dives on the three hardest areas: Fencing, animal accommodation, and
  the harvest.
- **§5 — Coding conventions.** The rules for writing engine code.
- **§6 — Card machinery (pointer) & the nature-policy seam.** A short summary of how the card
  system resolved this section's original deferred questions, plus the `Environment` layer; the
  card system itself is documented in **`CARD_ENGINE_IMPLEMENTATION.md`** (see Phase 3).

---

## Phase 2 — Building an Agent

The agent is the **AlphaZero-style self-play loop**: PUCT tree search (§2.2) driven by a joint
value+policy network (§2.3), in a generate → train → evaluate cycle (§2.4) whose generation runs
at native speed on the C++ twin engine and whose product is the web-UI bot (both are
cross-cutting top-level sections after Phase 3). Everything consumes
the engine's pure `step` / `legal_actions` interface and nothing else; the agent code lives in
`agricola/agents/`. Agents auto-skip singleton decisions — when only one action is legal they
apply it without consulting their evaluator (the engine still records the step, per its
no-auto-resolve rule).

### Action-space restriction

Before an agent picks, the legal set can be narrowed by a wrapper over `legal_actions(state)` —
`restricted_legal_actions` (`agricola/agents/restricted.py`): it shrinks branching and drops
strategically dominated actions (plow-before-sow ordering, cell-priority lists, a min-begging
filter). It is an **agent-layer** tool, not part of the engine — `legal_actions` always
enumerates every mechanically-legal action, because several of these priors look loss-less in
the Family game but become lossy once cards are added. A `_safe_narrow` guard ensures the
wrapper never empties a non-empty action set.

**The production search does not use it**: PUCT takes the full, unrestricted `legal_actions` and
lets the policy prior do all pruning. The regular wrapper survives on the web UI's AI seats
(`--restricted`) and in the recording pipeline; the stricter `strict_restricted_legal_actions`
was the pre-policy (UCT-era) prune and now serves only heuristic test paths. Details:
CHANGES.md Change 11, MCTS_IMPLEMENTATION.md §7.

### 2.1 — Heuristic agent (retired)

A hand-built, CMA-ES-tuned evaluation function (V1 ~50 coefficients → V3 ~250) whose only jobs
were to **bootstrap the first NN training data** (an 8-config ensemble spread across the
strength spectrum, for state-distribution diversity) and to baseline the first NN models. Both
jobs are done; **retired 2026-06-26** — never again an MCTS leaf, data generator, or eval
baseline (evaluation is NN-vs-NN head-to-head; the joint model beats the ensemble ~100%, so it
no longer discriminates). The code (`agricola/agents/heuristic.py`, `tuned_configs/`) stays in
place as the record of a completed phase. Full detail: `V3_DESIGN.md`, `V3_TRAINING_PIPELINE.md`,
`tuned_configs/DATA_GEN_ENSEMBLE.md`, `HUBRIS_V1_NOTES.md`.

### 2.2 — MCTS

The search half of the self-play loop. The comprehensive code reference for
`agricola/agents/mcts.py` is **`MCTS_IMPLEMENTATION.md`** — read that before touching the search.

**The production design is PUCT** (AlphaZero selection: `Q + c·P·√ΣN/(1+n)`): a `policy_fn`
prior from the joint network over the **full unrestricted** legal set (the prior is the sole
prune), the NN value as the leaf evaluator (no rollouts), a **DAG with a transposition table**
keyed on `GameState`'s hash (action orders reaching the same state share statistics),
forced-move step-through (the leaf value is queried at real decisions, not mid-action
singletons), and `FenceMode.FLATTEN` (per-pasture commits as ordinary nodes). `c_uct = 1.0` is
the unified default. Vanilla **UCT** (no prior, strict-restriction legality, macro-actions for
fencing) was the pre-policy mode and survives as a control path — MCTS_IMPLEMENTATION.md covers
it.

**Chance nodes for hidden reveals.** Because the round-card order is hidden (Foundations —
"Determinism after setup"), a reveal state is an explicit **chance node**: search routes through
it via a deterministic round-robin over the ≤3 candidate `RevealCard`s (reconstructed from public
state — MCTS reads no `Environment`), never leaf-evaluates it, and takes the expectation over its
children rather than maxing. The search therefore never conditions on the hidden future across a
round boundary.

**`prior_uniform_mix`** blends the PUCT prior with a uniform distribution
(`(1−w)·policy + w/k`) so zero-prior moves still get explored. A self-play A/B found `w = 0.05`
*not stronger* than pure policy, so the bot plays `w = 0` and the mix is used only to broaden
the web UI's analysis overlay (`w = 0.05`). C++-only; `MCTS_IMPLEMENTATION.md` §5.3.1.

**Performance.** The production per-move cost has been profiled and roughly halved; the catalog
is `SPEEDUPS.md`, the current profile `PROFILING.md`. Standing knobs: `agricola/opt_config.py`
(`PARETO_OPT_LEVEL` + `FENCE_SCAN_CACHE`, default ON, cross-level-tested — `FRONTIER_OPT_DESIGN.md`),
and the ops levers — run data-gen under `python -O` and with process parallelism (one game per
worker, `torch.set_num_threads(1)`).

### 2.3 — Neural network

**The agent's network is the `SharedTrunkModel`** — one trunk over the ~170-feature encoder
feeding a margin value head, an outcome value head (below), and nine policy heads (seven
fixed-vocab + two pointer heads that score variable-length Pareto frontiers), trained jointly on
PUCT self-play data with **soft-π** policy (cross-entropy against the visit distribution) +
margin-MSE value. MCTS consumes it through **`make_joint_fns`** — **one trunk forward per node**
(an embedding memo shares it between value and policy, so `mcts.py` is unchanged); the policy
covers every decision type over the full legal set, with tiny fallbacks (uniform /
cell-priority) where no head has signal. Full design + eval: **`SHARED_TRUNK.md`**.

The joint model superseded the original **separate-nets slice** — one supervised value net plus
nine independently-trained behavioral-cloning policy heads — which remains the fallback when a
single head is trained or probed in isolation (`FIRST_NN.md` + `POLICY_HEAD.md` are its design
records; one durable finding: the `fencing` head is spatially blind, the encoder has no per-cell
features).

**Strength vs humans.** The joint champion has beaten world-class human players at the 2-player
Family game — including the project's author, a 2022 Agricola World Cup champion — and is
believed stronger than any human at this variant.

**The current champion — `joint_a256_300k` (promoted 2026-06-25).** A `[256,256]→128` GELU
joint model retrained on the cleaner 300k-game self-play corpus generated by its predecessor —
*the corpus alone was the upgrade* (identical architecture, beats the prior champion 63.9%
head-to-head). One live decision is parked with the user: the wider **`B_wide` (512×512→256) is
stronger still** (58% at equal sims, 55–57% at equal wall-clock) but ~1.76× per forward — held
as a candidate, not promoted. Deployed: **value_scale 3.298, outcome_scale 0.549** (measured on
a common state set — value_scale is distribution-dependent), **mix leaf at α=0.9**. Full sweep +
eval: `SHARED_TRUNK.md` §2.2; rows in `nn_models/REGISTRY.md`.

**Champion lineage (compact — the full per-model records live in `nn_models/REGISTRY.md` +
`SHARED_TRUNK.md`).** `joint_taper128_thin` (117k corpus) → `joint_outcome_44k` (first
GCP-cloud-trained; introduced the *outcome* head below) → `joint_gelu_rand_240k` (240k corpus)
→ `joint_a256_300k` (current). Each beat its predecessor in C++ MCTS head-to-head; the two
durable experimental findings from the lineage are **GELU > leaky_relu** and **warm-start ≈
random-init** (a 2×2 experiment — the warm-start "edge" was training-seed noise).

**Two value heads, three leaf modes.** Beside the **margin** head (terminal score margin) sits
an **outcome** head (regresses `sign(margin)` — who wins, ignoring by how much), co-trained off
the same embedding at no extra forward cost. MCTS takes its leaf value in one of three modes —
**margin**, **outcome**, or the normalized **mix** `α·margin + (1−α)·outcome` — via
`set_leaf_mode` / `set_mix_alpha` (C++) and the matching script flags. A 10k-game mix-α
self-sweep found **margin-heavy is robust** (pure outcome worst, α≈0.9 best); **the deployed
bot plays the mix leaf at α=0.9**. Full detail: `SHARED_TRUNK.md` §10.

> **c_uct default is 1.0** (unified 2026-06-18 across scripts, the C++ binary, `MCTSAgent`, and the web-UI bot/analyze seats — was a 0.5/1.4 mix). Validated combined@1.0 ≈ combined@0.5. `value_scale` for fair head-to-head MCTS must be measured on a **common state set** (not the condition-biased training `target_std`) — see `SHARED_TRUNK.md` §9.1.

**Training-at-scale levers (from the 117k-corpus run — `SHARED_TRUNK.md` §4.1).** What makes a
100k+-game corpus tractable on the 8 GB M1: **per-game snapshot-thinning** (`--snapshot-keep` —
cuts rows + within-game autocorrelation), **int8 feature storage** (`--store-dtype int8`,
lossless — every feature is an integer), and **all CPU cores** for a single trainer (don't set
`OMP_NUM_THREADS=1`). That run also fixed two load-bearing warm-start bugs
(`target_std`/norm-buffer transplant; a `value_scale`-measurement `NameError`) that had
mis-calibrated every earlier warm-started joint model — the reason pre-2026-06-15 warm-start
comparisons are untrustworthy.

**`nn_models/best` resolves to the current joint champion** (`best.{pt,meta.json}` is a copy of
its checkpoint; `model_kind: "shared_trunk"`, not a separate-net value model). Consumers split
into two camps and stay working without per-call branching:
- **Value-only consumers** (the web UI `nn`/`mcts-leaf` seats; the `--value-ckpt` AWR baseline in
  `train_policy.py`) load through the **`model_kind`-aware `load_value_evaluator(stem)`**
  (`agricola/agents/nn/model.py`): `"value"` → `NormalizedValueModel.load`, `"shared_trunk"` →
  `SharedTrunkModel.load`. Both expose `predict_margin`/`value_scale`, so the joint value head is
  a drop-in 1-turn value leaf (its policy heads unused on this path).
- **MCTS-leaf consumers** (`play_mcts_match.py`, `generate_selfplay_data.py`,
  `bench_shared_tree.py`) detect the joint `best` and wire **value + policy off the one trunk**
  via `make_joint_fns`. (The separate-net/UCT-MACRO-era sweep scripts that couldn't take a fused
  policy are retired to `archive/scripts/` — see the archive note in `DIRECTORY.md`.)

`value_scale` lives in `best.meta.json` (meta-only) and is re-measured per promotion on a common
state set. The older separate-net champion `M_82k_warmM62k` remains the value-only fallback for
any consumer that wants a pure `NormalizedValueModel`.

> **Before refactoring the joint dataset builder (`shared_dataset.py`), read
> `SHARED_TRUNK.md` §3 — "the two memory lessons" — in full.** That builder's `build_shared_datasets`
> → `_finalize_payloads` is **memory-load-bearing on the 8 GB M1**: it streams chunk *paths* from disk
> (never loading a whole run dir) and assembles the value tensor **directly into its per-split arrays**
> (never a combined `value__X` that would double when mask-sliced). This is fragile in a specific,
> dangerous way: **the test suite does not exercise it** (the tests run on ~30 tiny games where memory
> is invisible), so a "tidy-up" back to load-all-then-`np.concatenate`-then-slice will pass green while
> silently reintroducing a ~10 GB OOM at 57k games — which is how the bug shipped originally. Keep the
> path-streaming + direct-to-split shape; §3 has the full rationale.

**Encoders are registry-dispatched.** A model declares its input encoder via an `encoder_tag`;
both Python (`EncoderSpec` / `ENCODERS` in `encoder.py`) and C++ (`encoder_for_tag`, read from
the exported manifest) dispatch through the registry — adding an encoder is one registry row +
one encode fn, no per-model branches. Trying a new encoder is cheap: `DecisionSnapshot` stores
the raw `GameState`, so it's a re-encode + retrain, never a data regen — and the C++ encoder is
ported eagerly so eval/self-play stay at C++ speed. A candidate 178-feature encoder
(`cand_feat178_v1`, begging stripped from the value target) exists but is **not promoted**;
status + details in `nn_models/REGISTRY.md`.

**Trained-model catalog: `nn_models/REGISTRY.md`.** The authoritative index of every checkpoint
on disk — `ENCODING_VERSION` it was trained against, training data source, hyperparameters,
test MAE, headline match results, and current Status (active / superseded / incompatible). The
checkpoint files themselves (`config.json`, `best.meta.json`, `test_metrics.json`) are the
source of truth for the numbers; the registry is the navigable index that ties them together
and records which model is the current default.

**Every NN training run must update `nn_models/REGISTRY.md`** as part of its completion — add a
new row to the summary table and a brief per-model details subsection (purpose, hyperparameter
delta from defaults, headline outcome, Status). If the new checkpoint supersedes an older one,
flip the older one's Status in the same edit. This convention keeps the registry accurate by
making "the run isn't complete until the registry knows about it" part of the workflow rather
than a separate hygiene task. Full template + bump policy at the bottom of `REGISTRY.md`.

---

### 2.4 — The self-play & training workflow

The pieces — Phase 1's engine, the MCTS (§2.2), the NN (§2.3), and the C++ twin engine (the
cross-cutting section after Phase 3) — compose into one loop: **generate
self-play games → train on them → evaluate → repeat**. This section is the orientation map for
*which script to reach for and why*; the per-flag detail lives in each script's `DIRECTORY.md` entry
and the linked design docs (`FIRST_NN.md`, `SHARED_TRUNK.md`, `CPP_ENGINE_PLAN.md`), which stay
authoritative — this is the narrative that ties them together.

#### Two MCTS-vs-MCTS modes — self-play vs evaluation

Both modes run MCTS against MCTS, but for opposite purposes, and the scripts split along that line:

- **Self-play *data generation* — one agent, both seats, shared tree.** The goal is a diverse stream
  of training trajectories, not a verdict, so a *single* agent (one NN leaf + one policy) drives both
  P0 and P1 off a shared search tree. This is what produces the `GameRecord`s training consumes
  (state + chosen action + visit distribution π + root value). Scripts:
  `scripts/nn/generate_selfplay_data.py` (Python) and its `~4×`-faster twin
  `scripts/nn/generate_selfplay_data_cpp.py` (C++ binary across a worker pool, replayed into the
  **identical** run-dir format). Per CLAUDE.md memory, the **C++ path is the default for any real
  generation run** — write the C++ port rather than wait hours on Python.

- **Evaluation *matches* — two (possibly different) agents, separate trees.** The goal is a verdict
  — is checkpoint A stronger than B? — so each seat gets its *own* agent and its *own* tree, with no
  shared statistics that would blur the comparison. Scripts: `scripts/play_mcts_match.py` (Python;
  a `--leaf-ckpt` pointing at a joint `SharedTrunkModel` auto-wires that seat via `make_joint_fns`,
  so it drives both separate-net and joint models) and `scripts/nn/run_cpp_match.py` (the C++
  two-net `selfplay --match --model-dir-p0 A --model-dir-p1 B`, the OOM-safe way to run an 800-sim
  match). Evaluation is checkpoint-vs-checkpoint; the old heuristic-ensemble yardstick
  (`eval_vs_ensemble.py`) is retired (§2.1).

The "port in different agents, or two of the same" flexibility is exactly this distinction: **same
agent both seats = self-play generation; different agents per seat = evaluation match.** The agent at
each seat is a `(value_fn, policy_fn)` pair behind the engine's black-box leaf/prior contracts, so
any evaluator drops in at either seat without touching `mcts.py` — that interchangeability is
what makes the same driver serve a head-to-head today and a card-game agent later.

**Defaults and why.** Production self-play uses the **joint shared-trunk model** as the agent —
one trunk supplying *both* the value leaf and the policy prior (`make_joint_fns`, §2.3).
**`nn_models/best` resolves to the current joint champion**, so `--leaf-ckpt nn_models/best`
(the default for the generation / match scripts) drives the joint agent directly; a different
checkpoint can be supplied explicitly via `--leaf-ckpt` (Python) or its exported manifest (C++).
Search runs PUCT with `FenceMode.FLATTEN` over the **full unrestricted** legal set (the policy
prior is the sole prune — §2.2), `c_uct = 1.0`, and a low played-move temperature so trajectories
stay near-greedy while π still records the search's exploration. Generation is
**chunked-streaming and resumable** (bounded
per-worker RAM, O(n) writes, skip-completed-game-idxs on restart) and runs **one game per worker
process** with `torch.set_num_threads(1)` — the throughput multipliers that matter on an 8-core
machine. The C++ generator's default **batch mode** loads the exported NN weights *once per worker*
(one process plays its whole slice) rather than once per game.

#### The training scripts

All are thin CLIs over libraries in `agricola/agents/nn/`; each writes a self-contained checkpoint
dir (`best.pt` + meta + config + metrics + curves) and **must update `nn_models/REGISTRY.md`** on
completion (§2.3). Which trainer to use:

- **`scripts/nn/train_shared.py`** — **the production trainer** (the joint shared-trunk model).
  Wraps `shared_training.train_shared`: interleaves per-head batches through the one trunk with
  **soft-π** policy CE + margin-MSE value, per-head gradient balancing, early-stop on **value**
  val-MSE.
- **`scripts/nn/train_first.py`** (a standalone value net) and **`train_policy.py` /
  `train_policy_pointer.py`** (one disjoint policy head at a time) — the separate-nets trainers,
  kept for probing a single head/net in isolation.

**Training defaults and why.** Per CLAUDE.md memory, NN training here is **step-bound, not
compute-bound** — the default `batch_size=256` wastes the machine — so use the `--fast-loader` with a
large batch (≈8192 for the value net, the joint trainer already defaults to 2048), and **re-tune +
validate the LR against the small-batch baseline** before trusting a big-batch model. Datasets are
built **streaming / per-pickle-chunked** to stay inside 8 GB (the encode peak is one pickle, not the
whole run). Training runs **single, quiet, no `caffeinate`** — macOS sleep and jetsam both kill long
runs on the 8 GB M1.

#### The end-to-end loop

Putting it together, one generation→training cycle is:

```
train (Python: train_shared / train_first+train_policy)
  → export weights (scripts/nn/export_weights.py → nn_models/cpp_export_<name>/)
  → ln -sfn <name> nn_models/cpp_export_best   # update the canonical pointer
  → generate self-play (generate_selfplay_data_cpp.py, C++, batch mode)
  → train on the new GameRecords
  → evaluate (run_cpp_match.py) → promote in REGISTRY.md → repeat
```

The export step exists because the C++ generator runs its own hand-rolled MLP inference (no
libtorch): `export_weights.py` writes the trained net to raw float32 blobs + a manifest the C++ side
loads (a `shared_trunk_v1` manifest for the joint model). Training always happens in Python; only
*generation* and *evaluation matches* cross into C++.

#### Running the loop on the cloud (GCP)

The same loop also runs **off the M1 on Google Cloud** for the compute-heavy steps — the path that
produced the 40k-game corpus behind `joint_outcome_44k` (§2.3). Because the C++ binary is torch-free
and builds ARM-native on a GCP T2A instance, generation, joint training (on a CPU box), evaluation,
and the α-sweep all ran in the cloud. The operator guide — project / budget / bucket setup, the
ARM build, launching each step, and the two non-obvious IAM gotchas (self-delete needs
`--scopes=cloud-platform` *and* the service account's `compute.instanceAdmin.v1` role; bucket writes
need `storage.objectAdmin`) — is **`CLOUD_RUNBOOK.md`**. The Spot-CPU quota was never granted, so runs
were capped at a 12-vCPU on-demand instance. (Bigger picture in CLAUDE.md memory `project_gcp_cloud_datagen`.)

---

## Phase 3 — Cards (and maybe 4-player)

**The card engine is built and the catalog is being implemented at scale.** The **card game**
(`GameMode.CARDS`; `setup_env(seed, card_pool=..., draft=...)`) is the full 2-player Agricola:
each player gets a private 7-occupation + 7-minor hand (dealt, or via a competitive draft), the
board reshapes (Side Job gone; Lessons usable; Meeting Place = become-SP + optional minor, no
food; the improvement spaces gain a play-minor branch), and played cards modify the game through
a general firing system — host frames with before/after windows on every action, optional
triggers / automatic effects / mandatory-with-choice, ~35 `register_*` seams (scoring, cost
modifiers, food payment, capacity, schedules, legality extensions), per-card state (`CardStore`),
and phase hooks (start-of-round, the harvest timing-window ladder). **~528 of the 840-card catalog** (Revised base
+ Artifex/Bubulcus/Corbarius/Dulcinaria/Ephipparius, decks A–E) are implemented, tested, and
dealt in the web UI's Cards mode.

**The one doc to read before card work is `CARD_ENGINE_IMPLEMENTATION.md`** — the as-built
machinery reference (hosts & firing, every registry, card state, the cost/food/capacity layers),
the rulings & idioms, the implementation process, the deliberate boundaries, and the **live
Status section** (updated per batch; per-card ledger in `CARD_IMPLEMENTATION_PROGRESS.md`).
`CARD_AUTHORING_GUIDE.md` is the practical how-to; `CARD_DEFERRED_PLANS.md` holds the deferred
clusters + open design decisions. The cardinal rule of card implementation: **a card that
doesn't clearly fit the machinery is deferred and brought to the user, never approximated** —
the user is the rules authority, a "harmless" timing/mechanism shift is still an approximation,
and the rule goes verbatim into every subagent prompt (CARD_AUTHORING_GUIDE.md §0.1).

**What remains in Phase 3:**
- **The rest of the catalog** — the remaining ~510 cards (many blocked on the deferred-cluster
  infrastructure decisions in `CARD_DEFERRED_PLANS.md`, which are user-gated).
- **The card-game agent** — repeat the Phase 2 process (MCTS → NN → self-play) for the richer
  game. Hidden hands are handled *above* the engine (ISMCTS determinization at the search
  layer); no card-game agent exists yet, so the web UI's Cards mode is human-vs-random or
  human-vs-human.
- **The C++ card port** — the C++ engine is Family-only today; porting the card game (guarded
  by new differential gates) is a prerequisite for card-game self-play at scale.

**4-player is an eventual goal** (user directive 2026-07-03), though a real undertaking rather
than a flag flip: the player-alternation logic already uses modular arithmetic that generalizes
to N players, but `setup`, the action board, and the rest assume 2 players. **Consequence for
card work NOW: give real weight to the [3+] and [4] cards.** They are not dealt in the 2-player
game, but they are *design inputs* — when designing shared machinery (hooks, events, registries,
timing windows), survey their shapes too and prefer designs that accommodate them. Do not
dismiss a card or a mechanism class as out-of-scope solely because its members are 3+/4+ —
sessions have repeatedly given them literally zero weight, and that habit builds machinery that
will need rework.

*Future direction (speculative): card-level diagnostics / interpretability — e.g. surfacing
which cards and interactions a trained agent values, as an aid to expert analysis. Waits on the
card-game agent.*

---

## The C++ twin engine

Cross-cutting infrastructure: built for Phase 2's self-play throughput, governed by Foundations'
lockstep invariant, and the future home of Phase 3's card port. Self-play data generation — the
throughput bottleneck for NN training (§2.3) — has a **second,
native implementation**: a faithful C++ reimplementation of the self-play *inner loop* — the engine
(`step` / `legal_actions` / scoring), MCTS (PUCT / FLATTEN / chance nodes), and NN inference
(hand-rolled MLPs, **no libtorch**) — that generates self-play games **~4× faster** than Python
single-thread and parallelizes per-core exactly as before. It lives entirely under `cpp/`; the
Python codebase is **untouched** and serves as the source-of-truth **oracle**.

**The two engines and how they stay in sync.** The C++ twin is validated against Python by a
**differential-test harness**: `tests/test_cpp_*.py` assert the C++ engine produces byte-identical
`legal_actions` / `step` / scoring, float-identical encodings, and ≤1e-4 NN value/policy outputs over
large random-state corpora (~118 gates). The shared contract is the canonical `GameState`↔JSON
serialization in `agricola/canonical.py`. Full design, the staged build, the JSON-hot-path profiling
story, and the benchmark are in **`CPP_ENGINE_PLAN.md`**.

> **Maintenance invariant (load-bearing) — see Foundations.** Python is the oracle; any change to the
> Python engine must keep the C++ differential gates green (`pytest tests/test_cpp_*.py`) or the two
> silently diverge. The full rule lives in **Foundations → Engineering invariants** ("the Python
> engine is the source of truth; keep the C++ differential gates green").

**Generating data with it.** `scripts/nn/generate_selfplay_data_cpp.py` mirrors
`generate_selfplay_data.py`'s CLI and produces the **identical** `GameRecord` run-dir format (so
training consumes it unchanged) — it generates via the C++ binary across a worker pool, then replays
the compact traces into `GameRecord`s (with π + root_value intact). Workflow: train in Python →
export weights (`scripts/nn/export_weights.py` → `nn_models/cpp_export_<name>/`) → generate
(`generate_selfplay_data_cpp.py`, default batch mode loads weights once per worker) → train on the
output. Build the binary per `cpp/README.md`.

**`cpp_export_best` — the canonical C++ export pointer.** `nn_models/cpp_export_best` is a symlink to
the C++ export dir of the current `nn_models/best` champion. When promoting a new champion: export it
(`export_weights.py`), then `ln -sfn <new_export_dir> nn_models/cpp_export_best`. The web UI's `mcts`
seat reads this symlink at startup and falls back to Python MCTS if it is absent.

**`selfplay --move` — single-move queries for the web UI.** `pick_move(state_json, model_dir, sims,
c_uct, temperature)` in `cpp/src/selfplay.cpp` (and the `--move` CLI mode in `cpp/apps/selfplay.cpp`)
reads a canonical `GameState` JSON from stdin, runs MCTS with the given NN + budget, and writes
`{"action": {type, params}, "root_value": float}` to stdout. `play_web.py` uses this via
`_CppMctsAgent` — a thin callable that shells out per AI turn — so the web UI `mcts` seat is backed
by the fast C++ binary (~4× Python) whenever the binary and `cpp_export_best` are present. Full
design: `CPP_ENGINE_PLAN.md`.

**Joint shared-trunk inference + a two-net match mode (Stage B; SHARED_TRUNK.md).** `NNInference` now
has a **mode toggle**: a `format: "shared_trunk_v1"` manifest (from `export_weights.py
--value-ckpt <joint-ckpt>`) loads the joint model — one trunk + standalone `embed_norm` + heads on the
embedding — with an internal `state_hash`-keyed **embedding cache** so it's one trunk forward per node
(the composite per-head path is untouched; `mcts.cpp` unchanged). Differential-validated ≤1e-4 vs the
Python `make_joint_fns`. A new **`selfplay --match --model-dir-p0 A --model-dir-p1 B`** mode
(`mcts_match_game`) plays one net vs another with separate trees + per-seat `value_scale`; driven in
parallel by `scripts/nn/run_cpp_match.py`. This is the path for fast, torch-free self-play generation
with the joint model.

**Outcome head + the three leaf modes in C++ (§2.3).** The joint manifest now also carries the
**outcome** head's weight blob + `outcome_scale` (written by `export_weights.py`), and the C++ search
exposes the three leaf-value modes off the one trunk forward — `set_leaf_mode` (margin / outcome / mix)
+ `set_mix_alpha`. The flags thread through every entry point: `selfplay --match / --move / --analyze`
and the `--sweep` self-sweep take `--leaf-mode` / `--mix-alpha`; `run_cpp_match.py` takes
`--leaf-mode-p0` / `--leaf-mode-p1`; and `run_cpp_sweep.py` gains a `--sweep-alpha` mode (each seat
draws an `α` per game, for the mix-α sweep). A permanent differential gate
(`test_cpp_outcome_matches_python`) validates the C++ outcome head ≤1e-4 vs Python.

---

## Web UI & online deployment

Cross-cutting product surface: it serves Phase 2 (the Family-mode bot) and Phase 3 (the Cards
mode) from one server. The browser game (`play_web.py` + `static/` + `templates/`) is playable **online** at
**https://agricolabot.fly.dev/**, deployed to **Fly.io** as a single always-on container. On entry (and on
every "New game") the player first picks the **game mode** via a landing overlay: **Family** (the cardless
2-player game) or **Cards (beta)**. The two modes share one server, registry, and wire format; a session
carries its mode and the choice never sticks across games.

In **Family** mode the game is human-vs-bot, and the bot is the joint-trunk champion (`joint_a256_300k`,
as of 2026-06-25; was `joint_gelu_rand_240k`) driven by **C++ MCTS PUCT** (the `selfplay --move` binary via
`_CppMctsAgent`, falling back to Python MCTS if the binary / `cpp_export_best` is absent), playing the
**mix leaf at α=0.9** (§2.3 — `play_web.py` sets `_CPP_LEAF_MODE="mix"` / `_CPP_MIX_ALPHA=0.9`, passed
through `selfplay --move`'s `--leaf-mode` / `--mix-alpha`).

In **Cards** mode the seats are **human-vs-random or human-vs-human** (no trained bot exists for the card
game yet, so MCTS/NN seats and the analysis overlay are disabled), and `setup_env(seed, card_pool=...)` is
called with a pool of **all implemented cards** (~528; live census via the `OCCUPATIONS`/`MINORS` registries) so each player is
dealt a random non-overlapping 7-occupation + 7-minor hand. The snapshot serializes each player's hand
under **hidden-information rules**: a hand is shown face-up only for a *human* seat, and among two human
seats (pass-and-play) only the **active player's** hand is revealed (the inactive seat sees a face-down
count) so handing the device over doesn't leak cards; a sole human (vs an AI) always sees their own hand.
The reveal rule lives in `state_to_json`'s `_reveal_hand`; card metadata (display name + effect text + the
structured minor cost) is built once at import into `_CARD_META` from `agricola/cards/data/*.json`, joined
to the implemented-card registries by slugified name. Card-play actions carry a `card` `ui_hint` and render
as named buttons.

Deploy walkthrough: **`DEPLOY.md`**; web-UI polish inbox: **`FRONTEND_FIXES.md`**.

**Server architecture.** A stdlib `ThreadingHTTPServer` (only non-stdlib dep is `numpy`). Every endpoint is
a single request/response that returns the full authoritative state — `{ok, …, "state":
session.snapshot()}`, where `snapshot()` (in `play_web.py`) is the server→client wire format: round/phase/
decider header fields, both players' resources/animals/farmyard/improvements (all display strings formatted
server-side), the action board, the pending-stack breadcrumb, and `legal_actions` (each carrying an
`index`, `display` string, `params`, and a `ui_hint`). The client renders strings only and serializes its
requests behind an `inputLocked` flag. **Multi-tenant**: a cookie-keyed `SessionRegistry` gives each browser
its own game; an `AGRICOLA_MAX_CONCURRENT_AI` semaphore (set to the vCPU count) caps concurrent MCTS
searches. State is **in memory** — a restart/redeploy drops in-progress games (by design; persistence would
need a datastore). `scripts/verify_web_sync.py` is the regression harness that HTTP-drives a server and
asserts rendered == authoritative across the move/undo/confirm/new-game flows.

**Action affordances (`ui_hint`).** `snapshot()` tags each legal action with a `ui_hint` (`_ui_hint_for` in
`play_web.py`) telling the frontend how to surface it; `static/app.js` dispatches its render on that tag:

| `ui_hint` | Action types | Frontend treatment |
|---|---|---|
| `space` | `PlaceWorker` | click the matching action-board card |
| `stop` | `Stop` | the turn-ending button |
| `button` | `ChooseSubAction`, `FireTrigger`, `CommitRenovate` | labeled button in the decision panel |
| `major` | `CommitBuildMajor` | click the major-improvement card (Cooking Hearth shows its return-fireplace variants) |
| `cell` | `CommitPlow`, `CommitBuildStable`, `CommitBuildRoom` | click a highlighted farmyard cell |
| `cell_set` | `CommitBuildPasture` | multi-select cells, confirm when the selection matches a legal pasture |
| `numeric` | `CommitSow`, `CommitBake`, `CommitAccommodate`, `CommitBreed`, `CommitConvert`, `CommitHarvestConversion` | button-list (Pareto frontiers are small) |
| `card` | `CommitPlayOccupation`, `CommitPlayMinor` | Cards mode only — a named-button group ("Play card") labeled by card name, highlighting the matching hand card |

**Per-game New-Game inputs** (prompted on "New game"): first the **game mode** (Family / Cards). In
**Family**: the **seed**, the **sims/move** budget (default 800), and the **opponent prior-mix** `w`
(default `0.0`; see §2.2 — broadens the bot's search, found not stronger so default off). In **Cards**: the
**seed** and the **opponent type** (random / human); the bot-only inputs are omitted.

**Toggles** (header): **Fast mode** (auto-submit singleton/forced actions and skip confirm on them);
**Confirm turns** (pause after each *non-forced* human turn to confirm/undo before the bot replies — undo
is only offered when this is on; harvest **feed** and **breed** are separate turns); **Show analysis** (a
read-only overlay of MCTS Q-value + visit count for each of the human's moves — async, never blocks the
move, cancelled when you move, uniform-prior-mixed at `w=0.05` for coverage). **Analysis is fully
decoupled from how the bot plays:** turning it on reveals a dedicated control row (below the header,
`#analysis-controls` in `index.html`) with four independently-tunable, localStorage-persisted knobs sent
per-request to `/api/analyze` (so they can change mid-game and re-run): the **Model** segmented control
(`margin` / `outcome` / `mix` — which value head the analysis leaf evaluates with, default `mix`), the
mix-blend **α** stepper (shown only for the mix leaf, step 0.05, default 0.9), the **Sims** budget (step
100, inherits the current game's sims on first open then sticky), and **c_uct** (step 0.2, default 1.0;
"higher = explore wider, lower = search deeper"). The overlay's Q is shown in the chosen leaf's natural
units: a **margin** leaf denormalizes the tree Q by the margin `value_scale` to points, an **outcome**
leaf denormalizes by `outcome_scale` to the `[−1, 1]` value, and a **mix** leaf emits the **raw,
un-denormalized** Q (no single scale for a blend) labeled `mix`. The C++ `analyze_position` derives the
reported `value_target` + scale from the **analysis leaf_mode** (not the model's primary training target),
and that descriptor is threaded `/api/analyze` → `app.js` so the badge labels itself correctly. The
action board lists spaces in **reveal order within each stage**, keeping the STAGE headers.

**Deploy.** `Dockerfile` compiles the C++ `selfplay` binary for Linux and copies the resolved
`cpp_export_best` champion into the image; `fly.toml` pins **one always-on machine**
(`min_machines_running=1`, `auto_stop_machines=false`) so the in-memory state survives between requests —
multi-machine + in-memory would desync. `.dockerignore` trims the build context (but re-includes
`tests/__init__.py` + `tests/test_utils.py`, which `agricola/agents/base.py` imports). Ship updates with
**`./deploy.sh`** — it resolves the `cpp_export_best` symlink (Docker `COPY` can't follow it) into the
concrete export dir and passes it to the `Dockerfile` as the `EXPORT_DIR` build-arg, then runs
`fly deploy`. **Promoting a new champion is therefore: re-point the symlink, then `./deploy.sh`** — no
Dockerfile edit.

---

## Status & boundaries

Phase-level status is in the **Roadmap** at the top (deep status: `nn_models/REGISTRY.md` for
models, `CARD_ENGINE_IMPLEMENTATION.md` §1 for cards); the full pytest suite (`tests/`) passes.
The concrete boundary — what is *deliberately not* implemented — is:

- **~510 of the 840 catalog cards** — unimplemented or deferred (clusters + build proposals in
  `CARD_DEFERRED_PLANS.md`; the deliberate machinery boundaries — end-of-turn, at-any-time
  conversions, Grocer-style reachability, event payloads — in `CARD_ENGINE_IMPLEMENTATION.md`
  §8). In the **Family** game `lessons` stays permanently illegal and the optional
  minor/improvement paths at Basic Wish / House Redevelopment / Major Improvement are inert —
  those are card-game features, live under `GameMode.CARDS`.
- **A card-game agent** — MCTS/NN seats and the analysis overlay are Family-only.
- **The C++ card port** — the C++ twin implements the Family game only.
- **The 4-player variant** (see Phase 3).

The full per-session build history — what was built each session, the design decisions made, and
the bugs caught and fixed — is in **`SESSION_HISTORY.md`**.

---
## Documentation index

One line per doc. **The paragraph-length abstracts live in `DIRECTORY.md`** (alongside the
annotated directory tree); each doc's own header banner carries its status. LIVE = updated as
the project moves; everything else is a frozen design/historical record.

**Rules & engine**
- `RULES.md` — complete game-rules reference (pure rules, no engine references).
- `ENGINE_IMPLEMENTATION.md` — Phase 1's deep-mechanics reference (dispatch, pending stack, subsystems, conventions).
- `FILE_DESCRIPTIONS.md` — deep per-file reference for `agricola/*.py` + test infrastructure.
- `TEST_DESCRIPTIONS.md` — per-test-file coverage.
- `DIRECTORY.md` — the full annotated repo map: doc abstracts + per-file tree entries (incl. script CLI flags).

**Cards (Phase 3)**
- `CARD_ENGINE_IMPLEMENTATION.md` — the card system's reference-of-record + LIVE status; the one doc card sessions read first. Its §9 maps every card doc.
- `CARD_AUTHORING_GUIDE.md` — LIVE how-to for implementing cards (pitfalls, templates, worked example).
- `CARD_IMPLEMENTATION_PROGRESS.md` — LIVE per-card ledger (adjudicated mechanics classification).
- `CARD_DEFERRED_PLANS.md` — LIVE defer clusters + infra proposals + open user questions (incl. the dated harvest-window rulings).
- `HARVEST_HANDOFF.md` — the harvest-window arc's session-reasoning record: every ruling's derivation, the bug stories, per-item cautions for the remaining work (§12).
- `design_docs/cards/`: `CARD_SYSTEM_DESIGN.md`, `CARD_IMPLEMENTATION_PLAN.md` (FROZEN), `COST_MODIFIER_DESIGN.md`, `FOOD_PAYMENT_DESIGN.md`, `HARVEST_WINDOWS_DESIGN.md` (the timing-window design of record; §12 = as-built map), the host-refactor records, batch/triage records — the card design records (rationale + red-teams; the as-built truth is CARD_ENGINE_IMPLEMENTATION.md).

**Agent (Phase 2)**
- `MCTS_IMPLEMENTATION.md` — the comprehensive search code reference (PUCT, UCT, chance nodes, fencing).
- `SHARED_TRUNK.md` — the joint value+policy model: design, training, C++ inference, evals (incl. the §3 dataset-builder memory lessons).
- `nn_models/REGISTRY.md` — LIVE checkpoint catalog; **every training run must update it**.
- `design_docs/`: `FIRST_NN.md`, `POLICY_HEAD.md`, `POLICY_PUCT_DESIGN.md`, `MCTS_DESIGN.md`, `HIDDEN_INFO_DESIGN.md` — agent design records.
- `design_docs/heuristic_models/`: `V3_DESIGN.md`, `V3_TRAINING_PIPELINE.md`, `HUBRIS_V1_NOTES.md`, `HEURISTIC_TUNING_PLAN.md` — the retired heuristic phase.

**Performance & infrastructure**
- `CPP_ENGINE_PLAN.md` — the C++ twin engine: design, staged build, differential harness, results.
- `SPEEDUPS.md` — the optimization catalog (implemented + candidates); `PROFILING.md` — current profiles + measurement caveats.
- `FRONTIER_OPT_DESIGN.md` — the frontier/fence caches (default-on): the live projection-key contract + cross-level test pattern.
- `NN_TRAINING_SPEEDUP.md` — training-speed diagnosis (landed parts; the untried MPS path).

**Deployment & ops**
- `DEPLOY.md` + `deploy.sh` — Fly.io web deploy (walkthrough + the one-command script).
- `CLOUD_RUNBOOK.md` — the GCP self-play/training loop runbook (incl. the IAM gotchas).
- `FRONTEND_FIXES.md` — web-UI frontend punch list.

**History & meta**
- `SESSION_HISTORY.md` — per-session build history; `CHANGES.md` — big cross-cutting refactors; `CLEANUP.md` — small field fixes.
- `IMPLEMENTATION_CHOICES.md` — Family-era decisions to revisit for cards; `POSSIBLE_NEXT_STEPS.md` — LIVE planning doc.
- `SESSION_INTRODUCTION.md` — standard new-session prompt; `README.md` — the public landing page.
- `design_docs/game_engine/` — frozen Phase-1 task specs (`ARCHITECTURE.md`, `TASK_2`–`TASK_7`, `FENCE_IDEAS.md`).
- `archive/` — fully superseded docs + retired scripts (not load-bearing).

---

## Directory structure

The bare map. **Per-file detail — roles, key functions, script CLI flags — lives in
`DIRECTORY.md`**; `FILE_DESCRIPTIONS.md` is the deep reference for `agricola/*.py`.

```
AgricolaBot/
    play_web.py                 # browser play server — Family (vs the bot) + Cards modes; the deployed app
    play.py                     # terminal human-play REPL
    play_random_game.py         # random-vs-random driver
    play_heuristic_game.py      # heuristic-vs-heuristic driver
    Dockerfile / fly.toml / deploy.sh / .dockerignore    # Fly.io deployment (DEPLOY.md)
    templates/ + static/        # web-UI shell (index.html) + frontend (app.js, style.css)
    agricola/                   # THE ENGINE PACKAGE
        constants.py            # enums (Phase, GameMode, ...) + lookup tables + the SPACE_IDS ordering
        resources.py            # Resources / Animals
        pasture.py              # Pasture + the flood-fill decomposition
        replace.py              # fast_replace (faster dataclasses.replace)
        opt_config.py           # frontier/fence cache toggles (default ON)
        environment.py          # hidden reveal order + nature policy (env.resolve)
        state.py                # all frozen state dataclasses; GameState
        canonical.py            # GameState<->JSON C++ contract + the card default-skip fields
        cost.py                 # PaymentOption / CostCtx / Pareto-min payment types
        setup.py                # setup_env(seed, card_pool=..., draft=...)
        helpers.py              # derived quantities + the Pareto frontier helpers
        actions.py              # all Action dataclasses
        pending.py              # all Pending* frames + stack ops + the event-routing buckets
        legality.py             # legal_actions + enumerators + the cost/food chokepoints + card extensions
        resolution.py           # space/sub-action resolvers + executors + _enter_after_phase
        scoring.py              # score() + the card scoring registries
        fences.py               # fence universes + edge math
        fence_universe.py       # universe-swapping tools
        engine.py               # step + dispatch + the phase walk + the card firing seams
        cards/                  # card framework (specs, triggers, cost_mods, capacity_mods, schedules, harvest_conversions, harvest_windows, round_end, preparation, display) + ~336 card modules
        agents/                 # base/play_game, random, heuristic (retired), the restricted wrappers, mcts.py (PUCT/UCT)
            nn/                 # the NN stack: schema/recording/encoder (torch-free) + datasets/models/training/policy + the joint shared-trunk model
    tests/                      # pytest suite; test_cpp_*.py = the C++ differential gates (coverage: TEST_DESCRIPTIONS.md)
    scripts/                    # profiling / benchmarking / tuning / match drivers + card_text.py, verify_web_sync.py, play_mcts_match.py
        nn/                     # the NN pipeline CLIs: generate_selfplay_data[_cpp].py, train_shared.py, export_weights.py, run_cpp_match.py, run_cpp_sweep.py, ...
        card_batch/             # the card triage/implement workflow generators
    tuned_configs/              # CMA-ES tuning artifacts + the retired data-gen ensemble configs
    data/nn_training/runs/      # self-play GameRecord datasets (gitignored)
    nn_models/                  # trained checkpoints + REGISTRY.md + the cpp_export_best symlink (C++ export)
    cpp/                        # the C++ twin engine (CPP_ENGINE_PLAN.md; build: cpp/README.md)
    design_docs/                # frozen design records (agent docs; cards/; game_engine/ task specs; heuristic_models/)
    archive/                    # superseded docs + retired scripts (not load-bearing)
```
