# AgricolaBot

A from-scratch Python implementation of the board game Agricola, with the long-term goal of
training a strong AI agent via MCTS and self-play reinforcement learning.

> **For new sessions:** this file is read automatically. It is organized as **Foundations**
> (cross-cutting principles) followed by the project's phases (engine → agent → cards), then a
> status-and-boundaries note, a documentation index, and an annotated directory tree. Deep engine
> mechanics live in
> **`ENGINE_IMPLEMENTATION.md`** (the reference companion to Phase 1). See also
> **`FILE_DESCRIPTIONS.md`** (per-file descriptions), **`TEST_DESCRIPTIONS.md`** (per-test
> coverage), **`task_files/ARCHITECTURE.md`** (original architecture spec, rules reference,
> dataclass definitions), and **`RULES.md`** (a comprehensive overview of the game's rules).

## Project Goal & Roadmap

Build a complete, deterministic game engine for the 2-player Family variant of Agricola, then
use it as the environment for training a strong self-play AI agent.

The project — and this document — is organized into three phases, preceded by a cross-cutting
**Foundations** section (ways of thinking about Agricola + the engineering invariants; read it
first):

- **Phase 1 — The Game Engine.** Fast, correct, fully playable. **Done.**
- **Phase 2 — Building an Agent.** A hand-built heuristic (2.1, *done* — it generates the
  self-play training data), MCTS (2.2, *first pass done; PUCT search machinery now landed*), and a
  value/policy neural network (2.3, *value slice is the strongest agent; policy head + PUCT
  integration now underway, self-play loop still ahead*).
- **Phase 3 — Cards (and maybe 4-player).** Implement the full card system, then repeat the
  Phase 2 agent process for the richer game. **Not started.**

The 2-player Family variant (no hand cards) is built first to validate the whole
engine → agent → NN pipeline before card complexity is added.

Strategic rationale for the phase order and the key algorithm choices (action-space structure,
animal accommodation, NN design) is in **`STRATEGY.md`**.

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
  order; **`observe(state, env, i)`** projects the partial state known to player `i` (the
  identity today, since the only hidden info is symmetric). Each round's stage card is turned up
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
  default-off toggles in `agricola/opt_config.py` (full design, correctness proofs, and the
  cross-level equivalence testing pattern in **`FRONTIER_OPT_DESIGN.md`**; the worked numbers in
  Phase 2.2 "Speeding up MCTS" and `PROFILING.md`). The one caveat for this form is a *hidden*
  global input not in the key (e.g. the active fence universe) — flush the cache when it changes,
  as `active_universe(...)` does. So the standing guidance is: for a hot **field of state**, weigh
  the three factors; for a hot **pure computation**, reach for projection-keyed memoization by
  default.

  The one current accepted exception *of the on-object kind* — `Farmyard.pastures` (the pasture
  decomposition) — and its caller-discipline maintenance contract are documented in
  `ENGINE_IMPLEMENTATION.md`.

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
and does not auto-resolve agent decisions. The **PREPARATION** phase hosts the round-card reveal
as a nature step: a two-state walk pushes a `PendingReveal` for the round being entered (the
nature decision pauses here), then on resume `_complete_preparation` increments `round_number`,
refills every `revealed` accumulation space, and returns to WORK. `RevealCard` is dispatched in
`_apply_action` (turning the named card's `revealed` to `True` and popping the frame) — a
top-level transition like `PlaceWorker`, not a `CommitSubAction`.

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
- **§6 — Card-trigger machinery.** The (currently minimal) card infrastructure and the open
  design questions for the full card system.

The trigger machinery is exercised end-to-end by exactly one card, **Potter Ceramics** — a
forward-compatibility test only, **not part of any game, and not used in play until the full
card suite is built** (see Phase 3).

---

## Phase 2 — Building an Agent

The agent is the project's central thrust, built in three stages that feed one another: a fast
hand-built **heuristic**, then **MCTS**, then a **neural network** with value and policy heads
trained by AlphaZero-style self-play (the end goal). The order is deliberate — the heuristic
exists mainly to *generate self-play game data* that bootstraps the NN, and MCTS is the search
half of the eventual self-play loop. Everything here consumes the engine's pure `step` /
`legal_actions` interface and nothing else; the agent code lives in `agricola/agents/`. The
agents also auto-skip singleton decisions — when only one action is legal they apply it without
consulting their evaluator (the engine still records the step, per its no-auto-resolve rule).

### Action-space restriction

Before any agent picks, the legal set is optionally narrowed by a wrapper over
`legal_actions(state)` — `restricted_legal_actions` (`agricola/agents/restricted.py`). It does
two things, both useful well beyond the heuristic:

1. **Shrinks the action space** — smaller branching for MCTS, a narrower policy head for the NN.
2. **Pushes the agent toward better choices** — it drops strategically dominated actions
   (plow-before-sow ordering, cell-priority lists, a min-begging filter, and similar priors).

It is an **agent-layer** tool, not part of the engine: `legal_actions` always enumerates every
mechanically-legal action, and the wrapper is opt-in. The priors live here rather than in the
engine because several of them look loss-less in the Family game but become lossy once cards are
added — keeping the engine an honest source of *all* legal actions preserves that. A
`_safe_narrow` guard enforces an always-≥1 invariant, so the wrapper never empties a non-empty
action set.

A stricter sibling, `strict_restricted_legal_actions`, layers additional MCTS-specific collapses
(Cultivation sow-max, hand-curated Fencing patterns, a harvest-feed cap). The heuristics and web
UI use the regular wrapper; tree search uses the strict one. Every interactive and training
context defaults its AI seats to a restricted wrapper, so the agent you play against in the
browser is the one being tuned. Details: CHANGES.md Change 11, MCTS_DESIGN.md §7.

### 2.1 — Heuristic agent

Kept short by design: this stage is largely settled and matters least for future decisions.

**Why.** A fast agent, good enough to generate self-play data of low-to-reasonable quality to
bootstrap NN training — not an end in itself.

**What was built (chronological).** V1 was a hand-built objective function (~50 coefficients)
that loosely scores a state by its expected endgame points, set from expert intuition — crude
but quick. Refinements (V2 and assorted tweaks) were tried in head-to-head matches; most didn't
beat V1. The architecture settled on **V3** (~250 coefficients, three combination styles). CMA-ES
then tuned the coefficients, evaluated against *multiple* baseline configs at once (not a single
opponent) so the result stays competitive against varied strategies rather than overfitting one.

**Where it stands.** Tuning produced an 8-config **data-generation ensemble**, deliberately
spread across the strength spectrum so self-play trajectories cover a diverse state distribution
rather than collapsing onto one playstyle. The current champion is **`alphas_gen_7`**
(= `tuned_configs/v3_best.json`). The roster (full descriptions in `DATA_GEN_ENSEMBLE.md`):

| Config | Round-robin | Note |
|---|---|---|
| `alphas_gen_7` | 86.4% | champion; `= v3_best.json` |
| `alphas_gen_1` | 81.1% | near-champion, slightly different style |
| `panel_wood_r1` | 61.1% | wood-tuned V3 |
| `panel_gen16` | 58.2% | former champion; reed-first opener |
| `panel_gen47_wood020` | 40.0% | adversarial wood-hoarder probe |
| `panel_gen_25` | 38.9% | alternate resources-tune style |
| `panel_gen47` | 30.4% | earlier champion |
| `t2` | ~5–15% vs V3 | V1 architecture — cross-style diversity |

Design and pipeline details live in the docs: V1 → `HUBRIS_V1_NOTES.md`; V3 → `V3_DESIGN.md`;
the tuning pipeline (CMA-ES, multi-baseline, regression detector, promotion gating) →
`V3_TRAINING_PIPELINE.md`; the ensemble → `tuned_configs/DATA_GEN_ENSEMBLE.md`.

### 2.2 — MCTS

Stronger play through search, and ultimately the search half of the AlphaZero-style loop. The
architecture decisions live here; the implementation is in **`MCTS_DESIGN.md`**.

**The design.** Vanilla **UCT** with a first-play-urgency (FPU) term for unvisited nodes; a
**DAG with a transposition table** keyed on `GameState`'s hash, so different action orders
reaching the same state share statistics; **leaf evaluation** via the V3 heuristic's margin
rather than random rollouts; and **macro-actions for Fencing** — a fence layout is a *path* of
pasture-commits, so a `MacroFencingAction` collapses the whole layout to one node and keeps the
tree from exploding in depth. MCTS consumes the strict-restriction wrapper; self-play and
head-to-head matches can share a tree or use separate ones.

**Chance nodes for hidden reveals.** Because the round-card order is hidden (Foundations —
"Determinism after setup"), a reveal state is an explicit **chance node**: search routes through
it via a deterministic round-robin over the ≤3 candidate `RevealCard`s (reconstructed from public
state — MCTS reads no `Environment`), never leaf-evaluates it, and takes the expectation over its
children rather than maxing. A chance node carries a P0 frame label (`decider = 0`) so the
backprop sign-flip and UCB reads stay unchanged; `is_chance` — not `decider` — flags the routing.
The search therefore no longer conditions on the hidden future across a round boundary.

**Where it stands (empirical).** At the current 200–500-simulation budgets, with vanilla UCT and
the *heuristic* as leaf evaluator, MCTS **loses ~3–5 points to the same heuristic used
standalone**. But that appears to be leaf-evaluator-specific: with the **value NN** as the leaf
evaluator, MCTS beats the NN's plain 1-turn lookahead head-to-head (early result) — preliminary
evidence that the loss was tied to the *weak heuristic leaf*, not to MCTS itself, and that MCTS
pays off once the evaluator is strong enough. That is exactly the long-term thesis. **PUCT is now
implemented (c0)** — a `policy_fn` prior injected into `MCTSSearch` (UCT remains the no-policy path),
forced-move step-through, and a `FenceMode` toggle; design + change plan in POLICY_PUCT_DESIGN.md. A
trained policy head and higher simulation counts are the active next steps.

**Speeding up MCTS (toggleable, default-off).** Legal-action enumeration has optional speedups
behind **`agricola/opt_config.py`** — flip these when MCTS runs feel slow:

- `PARETO_OPT_LEVEL` (int, 0–3, cumulative): algorithmic fast paths + projection-keyed caches for
  the Pareto/accommodation helpers (rate-descending `food_payment`, max-corner animal frontiers,
  exact/clipped caches, Φ farm-shape cache).
- `FENCE_SCAN_CACHE` (bool): caches the fence-universe legality scan.

Enable by setting the module globals before a run, e.g.
`from agricola import opt_config; opt_config.PARETO_OPT_LEVEL = 3; opt_config.FENCE_SCAN_CACHE = True`
(not yet wired to the MCTS CLI flags — set them in-process). They are **behavior-transparent**
(set-identical frontiers, cross-level-tested in `tests/test_frontier_opt.py`): toggling never
changes which actions are legal, only how fast they're enumerated, and the default (0 / off) is
byte-identical to the original engine. Measured **~9% MCTS wall-clock** at level 3 + fence cache
(150 sims, paired). Important caveat from the live profile: that win is **dominated by the fence
cache** — the Pareto/feeding helpers are fast per-call but rarely called in MCTS, so the remaining
ceiling is the **leaf evaluator (`evaluate_hubris_v3`, ~half of MCTS) and the pasture-decomposition
BFS**, not the frontier helpers. Full design + correctness proofs + benchmarks: **`FRONTIER_OPT_DESIGN.md`**;
the MCTS profile is in **`PROFILING.md`**; further candidates (incl. S9 pasture-BFS memoization) in
**`POSSIBLE_SPEEDUPS.md`**.

### 2.3 — Neural network

The end-goal agent: a network with a **value head and a policy head**, trained by AlphaZero-style
self-play.

**Where it stands.** The first slice is built and already paying off. A **supervised value
network** — trained on self-play data from the heuristic ensemble to predict the terminal score
margin — runs end-to-end: the data-generation pipeline, the ~170-feature encoder, the versioned
on-disk schema, the model and training loop, and the `NNAgent` that wraps the trained model.
**Early results make `NNAgent` the strongest agent to date** — apparently stronger than the
heuristic ensemble it learned from — and MCTS using this NN as its leaf evaluator beats
`NNAgent`'s plain 1-turn lookahead (see 2.2). The **policy head** (Phase c) is now partly built — a
factored multi-head policy (one `DecisionHead` per decision type) bootstrapped by behavioral cloning
of the existing `chosen_action` data, consumed by MCTS through the black-box `policy_fn`; the **PUCT
search machinery (c0) has landed** (POLICY_PUCT_DESIGN.md). **Three heads are now trained** —
`placement` (25-way), `choose_subaction` (8-way), and `commit_build_major` (14-way), with both
unweighted and AWR variants for the sub-action heads (see `POLICY_HEAD.md` + `nn_models/REGISTRY.md`).
Still ahead: the remaining heads (CommitSow, the cell heads, the pointer heads for the animal
frontiers), wiring the priors into PUCT, and the full AlphaZero-style self-play loop. The full
design — input encoding, supervision target, data pipeline, open questions — is in
**`FIRST_NN.md`**.

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

## Phase 3 — Cards (and maybe 4-player)

**Not yet started — the next major phase.** The full Agricola card system (the ~470 occupation
and minor-improvement cards) is the largest remaining piece of game content. The plan: 
implement the cards, possibly add the 4-player variant, then *repeat the agent-building process*
(Phase 2: heuristic → MCTS → NN) for the richer game.

**What exists today.** Exactly one card — **Potter Ceramics** (a minor improvement) — is
implemented, **solely to validate the trigger machinery end-to-end**. It is a
forward-compatibility test: **not part of any game, and not to be used in play until the full
card suite is built.** (Sessions have repeatedly misread this — the rule is firm.)

**The engine is already built for cards.** Much of the engine's apparent over-engineering is
deliberate forward-compatibility, so the card phase is additive rather than a rewrite: per-frame
`player_idx` for out-of-turn triggers, arbitrary stack depth for triggers with sub-decisions,
the `*_EXTENSIONS` registries for card-broadened legality, `triggers_resolved` budgets, the
`TRIGGERS` / `CARDS` registries, and the reusable sub-action primitives that card effects should
*compose* rather than re-implement. The mechanics and the known open design questions (compound
card interactions, atomic-space trigger hosting, harvest trigger events) live in
**`ENGINE_IMPLEMENTATION.md`** — §2 ("built with cards in mind") and §6 (card-trigger machinery).

**4-player** is a possible extension, but a real undertaking rather than a flag flip: the
player-alternation logic already uses modular arithmetic that generalizes to N players, but
`setup`, the action board, and the rest assume the 2-player Family variant.

---

*Future direction (speculative): card-level diagnostics / interpretability — e.g. surfacing
which cards and interactions a trained agent values, as an aid to expert analysis. Out of scope
until the card system exists.*

---

## Status & boundaries

Phase-level status is in the **Roadmap** at the top; the full pytest suite (`tests/`) passes. The
concrete boundary — what is *deliberately not* implemented — is:

- **Cards beyond Potter Ceramics.** As a consequence, `lessons` is permanently illegal in the
  Family game, and the optional minor / improvement paths at Basic Wish for Children, House
  Redevelopment, Major Improvement, and Farm Redevelopment are inert until card support lands.
  Every other space surfaced by `legal_placements` has a working path; the `NotImplementedError`
  branch in `_apply_place_worker` is a defensive guard for unknown space IDs (e.g. `lessons`).
- **The 4-player variant** (see Phase 3).

The full per-session build history — what was built each session, the design decisions made, and
the bugs caught and fixed — is in **`SESSION_HISTORY.md`**.

---

## Documentation Files

Top-level docs (live alongside CLAUDE.md and are kept current as the project evolves):

| File | Description |
|---|---|
| `RULES.md` | Complete rules reference for the 2-player Family game, including action space descriptions, major improvement effects, harvest rules, animal accommodation, and scoring tables. |
| `STRATEGY.md` | AI strategy and algorithm decisions: action space structure, MCTS approach, neural network design, and the rationale behind each project phase. |
| `ENGINE_IMPLEMENTATION.md` | Deep-mechanics reference companion to Phase 1 (the game engine): dispatch tables, the full pending-stack provenance scheme and invariants, sub-action cost handling, the Fencing / animal-accommodation / Harvest subsystems, the coding conventions, and the card-trigger machinery. Read alongside Phase 1 when doing engine surgery. |
| `CHANGES.md` | Significant cross-cutting refactors that touched many files at once (Resources extraction; two-track pasture cache model; dispatch refactor + pending provenance; harvest phases; `BoardState.action_spaces` canonical-tuple refactor; engine performance pass with `fast_replace` + `legal_actions_cache()`; HubrisHeuristicV3 architecture + iterative tuning pipeline). |
| `CLEANUP.md` | Three small targeted field-level fixes (house material location, field rename, field removal). |
| `SESSION_HISTORY.md` | Full record of what was built each session, including design decisions made and bugs caught. |
| `IMPLEMENTATION_CHOICES.md` | Fine-grained design decisions that worked well for the Family game but may need revisiting when cards are added. |
| `POSSIBLE_NEXT_STEPS.md` | Living planning doc — directions the project could take next, organized by scope and effort. Updated as the project progresses. |
| `POSSIBLE_SPEEDUPS.md` | Living catalog of performance optimizations — both ideas surfaced by profiling and not yet acted on, and forward-looking candidates. Sibling to POSSIBLE_NEXT_STEPS.md, scoped to performance specifically. |
| `FRONTIER_OPT_DESIGN.md` | Design + implementation record for the frontier/accommodation optimizations that speed up the Pareto/accommodation helpers in MCTS. Toggleable via `agricola/opt_config.py` (`PARETO_OPT_LEVEL` 0–3 + `FENCE_SCAN_CACHE`), default-off. Covers the algorithmic rewrites (rate-descending `food_payment`, max-corner), the projection-keyed caches (exact / Φ farm-shape / feeding clip), the correctness invariants + proofs (Appendix A), the cross-level equivalence testing strategy (§8.1) and benchmarking methodology (§8.2), and the landed-status/phasing. **Implemented** — see the Status note at the top. |
| `HEURISTIC_TUNING_PLAN.md` | V1-era plan for self-play tuning. Thread A (tuning harness) has been implemented and run; Threads B and C are partially superseded by V3. See `V3_TRAINING_PIPELINE.md` for the current pipeline. |
| `HUBRIS_V1_NOTES.md` | Design reference for HubrisHeuristic V1: per-term function/motivation/shape/magnitude for every component of `evaluate_hubris_v1`, the V1-vs-V2 finding with worked example, deferred alternatives (renovation bonus, newborn discount) with reasoning, known limitations and failure modes. Read before modifying V1; V3 has its own design doc. |
| `V3_DESIGN.md` | Comprehensive design reference for HubrisHeuristicV3: three combination styles (blend / additive / joint-alpha), per-category specs (fields/crops/pastures/animals/resources/food/joint-alpha), three-component resource pattern (wood/clay/reed/stone), V1 carry-overs and what V3 deletes, known limitations. Read before modifying V3. |
| `V3_TRAINING_PIPELINE.md` | Operational guide for the V3 tuning pipeline: CMA-ES basics, `scripts/tune_heuristic.py` semantics (CLI flags, multi-baseline + regression-detector tooling, save/resume, x0 fallback, `<arch>_best.json` auto-update), the `scripts/run_iterative_v3.py` orchestrator (block-coordinate descent), `v3_best.json` convention, current training state, next steps. |
| `MCTS_DESIGN.md` | Design spec for the MCTS phase (Phase 2.2). Architecture decisions (vanilla UCT + FPU + DAG-with-transpositions + leaf-evaluation + macro-enumeration for Fencing); data structures (MCTSNode / MCTSSearch / MCTSAgent); algorithm details (per-sim flow, UCB, sign-flip backprop, transposition table); strict-restrictions spec (new filters added to `agricola/agents/restricted.py`); implementation phases; open questions. Read before starting MCTS implementation. |
| `HIDDEN_INFO_DESIGN.md` | Design + implementation reference for the hidden-information refactor: the round-card reveal as an explicit nature/chance step, the public-state / Environment / observe split, the MCTS chance-node handling, the full file impact map, and the action plan. |
| `FIRST_NN.md` | Design spec for the first NN value function (Phase 2.3). Sections: goals/non-goals, strategic context, design principles (input-encoding philosophy, pre-compute selectively, mid-action encoding, terminal-margin target), input encoding (~170 features split across per-player ×2 / shared / mid-action / terminal-state handling), supervision target (terminal margin + terminal-state training pairs), data generation pipeline (fully specified: 8-config ensemble, bimodal per-agent T, snapshot semantics, file layout, resume protocol, validation), architecture (TBD), training (TBD), evaluation (TBD), open questions, implementation notes (file layout + schema versioning `DATA_VERSION` + `ENCODING_VERSION`), status. Read before working on the NN. |
| `POLICY_PUCT_DESIGN.md` | Design spec for the policy head + PUCT phase (Phase 2.3 (c)→(d)). The factored policy (fixed-width + mask heads for placement / sub-actions / Build Major; score-the-set heads for the fencing / animal-accommodation / harvest-feed / harvest-breed frontiers), the black-box `policy_fn(state, legal_actions) -> {action: prior}` interface MCTS consumes (untrained heads fall back to uniform), the AlphaZero PUCT formula + restated FPU + `leaf_value_scale`-calibrated `c_puct`, chance-node orthogonality, the regular-legality + soft-prune-via-prior rationale, the grounded decision-point taxonomy, the localized `mcts.py` change plan (UCT preserved as a control via `policy_fn=None`), the `fence_mode` enum (MACRO / FLATTEN / SEQUENCE_PRIOR) and the SEQUENCE_PRIOR `n(s,a,L)` per-step-target reconstruction, BC training from existing `chosen_action` data, the eval controls, shared-trunk + self-play forward-compat, and a pre-implementation-edits section. Read before implementing the policy head or PUCT. |
| `POLICY_HEAD.md` | Implementation + design record for the supervised behavioral-cloning **policy heads** (Phase 2.3 (c)). The factored `DecisionHead` spec (predicate + vocab + chosen→class + legal mask) and the `HEADS` registry; the three built heads (placement 25-way, choose_subaction 8-way, commit_build_major 14-way); the two loss variants (unweighted CE / AWR advantage-weighting with a value-net baseline, `w=clip(exp((R−V)/β),0,w_max)`); single-perspective encoding; warm-start trunk transplant; the `restricted.py` ordering-filter **forcing-fix** that surfaced plow/build_rooms as real choices; the `policy_prior` PUCT-consumer surface; the metrics (top-1/top-3 — agreement, not strength); and the deferred heads (CommitSow, the cell heads, the pointer heads for the animal frontiers). Read before adding a policy head. |
| `nn_models/REGISTRY.md` | Authoritative index of every trained NN checkpoint under `nn_models/`. Per-model row: id, `ENCODING_VERSION`, `DATA_VERSION`, training data source, architecture / regularization, train size, test MAE, current Status (active / superseded / incompatible). The checkpoint files themselves (`config.json`, `best.meta.json`, `test_metrics.json`) own the underlying numbers; this file is the catalog that ties them together and records which model is the current default. **Every training run must update this file** as part of its completion — see template at the bottom. |
| `PROFILING.md` | Findings from the item-C profiling pass: hot paths identified, workloads defined, and the R1-R6 recommendation list. The infrastructure (`scripts/profile_engine.py`, `scripts/profile_states.py`, `scripts/count_replaces.py`, `scripts/bench_replace.py`) is re-runnable; this doc captures the snapshot interpretation. |
| `FILE_DESCRIPTIONS.md` | Detailed per-file descriptions for every `agricola/*.py` and the test-infrastructure files (`tests/factories.py`, `tests/test_utils.py`). |
| `TEST_DESCRIPTIONS.md` | Per-file coverage descriptions for each `tests/test_*.py`. |
| `SESSION_INTRODUCTION.md` | Standard prompt to give a new coding agent at the start of a session. |
| `README.md` | Human-facing project README (the GitHub landing page): project summary, status overview, the playable-agent table, and future work. Overlaps this file's intro but targets a general reader rather than a coding session. |
| `WEB_UI_PLAN.md` | Living design doc for the browser-based UI (`play_web.py`): goal / non-goals, transport, file layout, action dispatch, MVP + stretch scope, and an always-current implementation-status ledger (§15). |
| `FRONTEND_FIXES.md` | Punch-list of web-UI *frontend* gaps (`static/app.js`, `static/style.css`, `templates/index.html`), ordered by certainty the fix is needed; each item states the problem, the backend data already exposed, and the specific frontend change. |

Historical task specs and design artifacts (in `task_files/`, frozen at the time of their task's landing):

| File | Description |
|---|---|
| `task_files/ARCHITECTURE.md` | Original full architecture spec, game rules reference, and original dataclass definitions. Field names may diverge from current code — inline annotations flag known discrepancies. |
| `task_files/FENCE_IDEAS.md` | Design conversation artifact from Task 6 — explores the broader Fencing action-space design alternatives. |
| `task_files/TASK_2.md` … `task_files/TASK_7.md` | Implementation task files, one per development task. Frozen at landing time; cross-referenced from `SESSION_HISTORY.md`. |

Archived (in `archive/`, fully superseded by current docs):

| File | Description |
|---|---|
| `archive/TESTS.md` | Pre-`TEST_DESCRIPTIONS.md` per-test reference. Superseded by `TEST_DESCRIPTIONS.md`. |

---

## Directory Structure

```
AgricolaBot/
    play.py                         # Top-level entry point — terminal-based human play UI. Wraps the engine in an interactive REPL with rendered farmyard / action-board / score-card output and action-selection prompts.

    play_web.py                     # Top-level entry point — browser-based human play UI. Serves a JSON game state over HTTP for a JavaScript frontend; shares formatting helpers with `play.py`. `--restricted` / `--no-restricted` (default ON) makes AI seats use `restricted_legal_actions` so the browser-UI agents behave the same way they do during training-pipeline fitness evaluation. `--v3-config <json>` loads a tuned V3 config (`best_config` field). The UI's Download-trace button writes the in-progress game's action log to `agricola-trace-seed<N>.json` — a list of action dicts with `round`, `phase`, `decider`, `type`, `params`, and `display` fields — usable for post-hoc debugging or replay.

    play_random_game.py             # Top-level entry point — random-vs-random driver. Plays one full game, prints the scoreboard with per-category breakdown and tiebreaker. `--trace` flag adds a per-round narrative (worker placements, sub-actions, harvest sub-phases).

    play_heuristic_game.py          # Top-level entry point — any-vs-any heuristic-agent driver. `--p0`/`--p1` pick from {random, simple, hubris, hubris_v1, hubris_v2}; `--temperature` for softmax sampling; `--lookahead` toggles the action/turn lookahead horizon. Same scoreboard output as `play_random_game.py`.

    templates/                      # Web UI assets served by `play_web.py` — the HTML shell.

        index.html                  # Single-page shell `play_web.py` serves; loads `static/app.js` + `static/style.css` and hosts the board DOM the JS populates from the JSON wire format. See WEB_UI_PLAN.md.

    static/                         # Web UI assets served by `play_web.py` — frontend JS + CSS.

        app.js                      # The browser frontend (~1.2k lines): fetches game state from `play_web.py`, renders the farmyard / action board / scoreboard, and dispatches the player's chosen action back to the backend. The target of FRONTEND_FIXES.md.

        style.css                   # Web UI styling: board layout, farmyard grid, action-space tiles, scoreboard.

    agricola/                       # Game engine package.

        __init__.py                 # Empty package marker.

        constants.py                # Named enums (Phase, HouseMaterial, CellType) plus lookup tables: action-space accumulation rates, MAJOR_IMPROVEMENT_COSTS, ROOM_COSTS, BAKING_IMPROVEMENT_SPECS, FIREPLACE/COOKING_HEARTH_INDICES, BAKING_IMPROVEMENTS. SPACE_IDS / SPACE_INDEX (canonical 25-entry ordering of all action spaces) index BoardState.action_spaces. stage_of_round(round) / STAGE_OF_ROUND map each round to its stage (used by the reveal enumerator to pick the candidate stage cards).

        resources.py                # Resources (wood/clay/reed/stone/food/grain/veg) and Animals (sheep/boar/cattle) frozen dataclasses with __add__/__sub__/__bool__ operators. Extracted from state.py to avoid circular imports with constants.py.

        pasture.py                  # Pasture dataclass (cells, num_stables, precomputed capacity) + compute_pastures_from_arrays BFS that flood-fills from outside the grid to find enclosed connected components. Independent of state.py via duck typing.

        replace.py                  # fast_replace(obj, **changes) — a drop-in faster equivalent of dataclasses.replace, ~20% faster per call (timeit-measured). Used at every state-mutation site in engine.py / resolution.py / pending.py / cards/. See CHANGES.md Change 9.

        opt_config.py               # Runtime toggles for the frontier/accommodation optimizations: PARETO_OPT_LEVEL (0–3, cumulative) and FENCE_SCAN_CACHE (bool). Both default to the no-op baseline so the default behavior is unchanged; helpers.py / legality.py read them to dispatch to optimized (caching / algorithmic) paths. See FRONTIER_OPT_DESIGN.md.

        environment.py              # The Environment frozen dataclass — the hidden ground truth + nature policy for one game. Holds the per-game stage-card reveal order (NOT in GameState); exposes resolve(state) (the driver-facing nature seam) and reveal_action(state) -> RevealCard. The dealer in real games; agents and MCTS never see it. Forward-compat home for future private hands / draw deck + the observe(state, env, i) projection (identity today). See HIDDEN_INFO_DESIGN.md §3.4 / §3.6.

        state.py                    # All frozen state dataclasses: Cell, Farmyard (with cached pastures), ActionSpaceState (with revealed: bool common-knowledge flag), PlayerState, BoardState, GameState — plus get_space / with_space free-function helpers for keyed access to BoardState.action_spaces (a canonical-ordered tuple). The hidden reveal order is NOT on BoardState — it lives in the Environment. The top-level GameState snapshot — every transition produces a new one via fast_replace — is fully hashable.

        setup.py                    # setup_env(seed) -> (GameState, Environment) — the full constructor for the initial 2-player Family game: builds the per-stage shuffled reveal order into the Environment, pre-deals round 1 (via env.reveal_action), and returns the round-1 WORK state. setup(seed) = setup_env(seed)[0] (drops the env). All randomness (starting player, per-stage card shuffle) is resolved here via a seeded NumPy RNG; the order is hidden in the Environment and the engine is fully deterministic afterward.

        helpers.py                  # Pure derived-quantity functions (fences_in_supply, stables_in_supply, cooking_rates 4-tuple, enclosed_cells) and the Pareto frontier helpers (extract_slots, can_accommodate, pareto_frontier, breeding_frontier, food_payment_frontier, harvest_feed_frontier).

        actions.py                  # All Action dataclasses (PlaceWorker, ChooseSubAction, the full Commit* family, FireTrigger, Stop, RevealCard) plus the CommitSubAction marker base used by the generic commit dispatcher. RevealCard (nature's round-card reveal) is a top-level transition, not a CommitSubAction.

        pending.py                  # All Pending* frozen dataclasses (sub-action + parent + wrapper variants, plus the PendingReveal nature/phase frame with player_idx=None), the PendingDecision union alias, and the three pure stack ops (push, pop, replace_top).

        legality.py                 # Top-level legal_actions (stack-state dispatch) + legal_placements + per-space placement predicates + shared helpers (_can_bake_bread, _can_build_stable, …) + per-pending sub-action enumerators (incl. _enumerate_pending_reveal, the ≤3 candidate RevealCards for the round being entered, derived purely from public state) + card extension registries.

        resolution.py               # Atomic _resolve_<space> handlers, non-atomic _initiate_<space> + _choose_subaction_<space> handlers, sub-action _execute_<sub_action> effect functions, and the function-pointer dispatch tables (ATOMIC_HANDLERS, NONATOMIC_HANDLERS, CHOOSE_SUBACTION_HANDLERS).

        scoring.py                  # score(state, player_idx) -> (total, ScoreBreakdown) and tiebreaker — end-game evaluation across all categories (fields, pastures, animals, rooms, people, majors, craft bonuses, begging penalties).

        engine.py                   # The transition engine: step + _apply_action dispatch (incl. the RevealCard branch) + _advance_until_decision + phase resolvers (_resolve_return_home, the two-state PREPARATION reveal walk — push PendingReveal then _complete_preparation — _resolve_harvest_field, _initiate_harvest_feed, _initiate_harvest_breed) + the COMMIT_SUBACTION_HANDLERS metadata table for generic commit dispatch.

        fences.py                   # Four layered pasture-shape universes (FULL=1518 / FAMILY=762 / EXTENDED=193 / RESTRICTED=109) with PastureCandidate edge-metadata entries, fence-array pack/apply helpers, and the compute_new_fence_edges cost helper. Standalone module, no engine dependencies.

        fence_universe.py           # Experimental tooling for swapping the active fence universe: the active_universe(spec) context manager (named universes or explicit triples), restrict_to(predicate, base=...) builder for derived universes, NAMED_UNIVERSES registry, and current_universe() accessor.

        cards/                      # Card framework + concrete card modules + harvest-conversion registry.

            __init__.py             # Imports each card module + harvest_conversions so their register() calls fire at load time, populating TRIGGERS / CARDS / HARVEST_CONVERSIONS and BAKE_BREAD_ELIGIBILITY_EXTENSIONS.

            triggers.py             # Two parallel registries — TRIGGERS (event-keyed list, used by enumerators) and CARDS (card-id-keyed direct lookup, used by _apply_fire_trigger) — plus the register() function called by card modules at import time.

            potter_ceramics.py      # The one card in scope: "exchange 1 clay for 1 grain before each Bake Bread action, at most once per action." Exercises the trigger machinery end-to-end.

            harvest_conversions.py  # HARVEST_CONVERSIONS registry + HarvestConversionSpec dataclass + register_harvest_conversion(). Three built-in entries: joinery (1 wood -> 2 food), pottery (1 clay -> 2 food), basketmaker (1 reed -> 3 food).

        agents/                     # Agent implementations: random + heuristics. Built atop the engine's pure `step` / `legal_actions` interface.

            __init__.py             # Re-exports Agent / HeuristicAgent / RandomAgent / SimpleHeuristic / HubrisHeuristic[V1,V2,V3] / HubrisHeuristicV1Differential / HubrisHeuristicV3Differential / HeuristicConfig / HeuristicConfigV3 / DEFAULT_CONFIG / DEFAULT_CONFIG_V3 / CONFIG_V1_T2 / evaluator functions (+ differential variants + `compose_evaluators`, `make_differential_evaluator`, `r1_force_forest_bonus`) / play_game / restricted_legal_actions / strict_restricted_legal_actions / make_strict_restricted_legal_actions / MCTSAgent / MCTSSearch / MCTSNode / MacroFencingAction + priority constants.

            base.py                 # `Agent` Protocol, decider_of helper (-> int | None; None = nature's round-card reveal, routed to the dealer), RandomAgent, generic HeuristicAgent (1-turn or 1-action lookahead, singleton-skip always on, softmax-with-temperature action selection; its `_eval` helper averages the evaluator over the ≤3 reveal outcomes at a nature node rather than evaluating the between-rounds state), play_game(initial, agents, dealer) game-driver (the dealer — typically env.resolve — resolves reveals; agents never see a nature node). Both agent classes accept a `legal_actions_fn` kwarg (default = unrestricted `legal_actions`) threaded through every legality consultation.

            heuristic.py            # All heuristic agent code. HeuristicConfig + evaluate_simple/evaluate_hubris_v1/_v2 + SimpleHeuristic / HubrisHeuristicV1 / V2 (V1-era). CONFIG_V1_T2 (round-2-tuned V1 constant). HeuristicConfigV3 + evaluate_hubris_v3 + HubrisHeuristicV3 (current main heuristic). Opt-in V3 config fields default 0: `wood_flat_bonus`, `temperature`, `r1_force_forest_bonus`. `compose_evaluators(*evaluators)` sums callables additively. Standalone `r1_force_forest_bonus(state, p, cfg)` helper available alongside the config field. Differential wrappers: `make_differential_evaluator(base)`, `evaluate_hubris_v3_differential`, `evaluate_hubris_v1_differential`, `HubrisHeuristicV3Differential`, `HubrisHeuristicV1Differential`. All V1 helpers (family-future, empty-room, location bonuses, SP, renovation, major-override, food/begging) are shared duck-typed across V1/V3 configs. Subclasses forward the `legal_actions_fn` kwarg to the base. See V3_DESIGN.md and HUBRIS_V1_NOTES.md.

            restricted.py           # Action-pruning wrappers over `legal_actions(state)`. Exports `restricted_legal_actions(state)` (regular: ordering / cell-priority / room-cap / first-pasture / min-begging / drop-`use=False`-craft), `strict_restricted_legal_actions(state)` (strict MCTS variant adding Cultivation sow-max, Grain-Util veggie auto-max, 9 fencing patterns, harvest-feed cap of top-5-V3 + 2 random), and `make_strict_restricted_legal_actions(*, config, rng)` factory for injected RNG/config. Priority constants (STABLE_PRIORITY, ROOM_PRIORITY, PLOW_PRIORITY, FIRST_PASTURE_REQUIRED_CELLS, MAX_TOTAL_ROOMS). Every filter routes through `_safe_narrow` so neither wrapper empties a non-empty input. See CHANGES.md Change 11 (regular wrapper) and MCTS_DESIGN.md §7 (strict additions).

            mcts.py                 # MCTS agent. `MCTSNode` (identity equality, lazy `_legal_actions` cache, `macro_sequences` on fencing-trigger parents, `is_chance` + `chance_counts` for round-card reveal nodes), `MCTSSearch` (transposition table + per-search RNG + cached HubrisHeuristicV3 for greedy macros), `MCTSAgent` (vanilla UCT with FPU, path-only backprop, softmax action selection at T=0.2). **Optional PUCT** (POLICY_PUCT_DESIGN.md): pass `policy_fn(state, legal_actions) -> {action: prior}` + `fence_mode=FenceMode.FLATTEN` to `MCTSSearch`, and `_select_via_puct` replaces UCB with AlphaZero `Q + c·P·√ΣN/(1+n)` over all legal actions (`policy_fn=None` selects UCT, PUCT otherwise); priors are computed lazily (`_ensure_priors`, split from `_compute_legal_actions`). Both modes **step through forced (singleton) moves** before evaluating the leaf (so V is queried at real decisions, not mid-action singletons; UCT is therefore no longer byte-identical to the pre-PUCT engine). `uniform_policy` is the c0 placeholder prior, `root_visit_distribution(root)` exposes the root π. `FenceMode`: MACRO (UCT macros) / FLATTEN (per-pasture commits, required for PUCT) / SEQUENCE_PRIOR (c3, not yet implemented). Hidden reveals are explicit chance nodes: `_chance_route` round-robins over the ≤3 candidate RevealCards (reconstructed from public state — no Environment), they are never leaf-evaluated, and carry a P0 frame label (decider=0) so backprop/UCB are unchanged. Macro-fencing for both trigger points (PlaceWorker("fencing") + ChooseSubAction("build_fences") at PendingFarmRedev), with explicit entry/exit phases handling the outer PendingFencing wrapper. Tree reuse via `re_root(new_root)` (prunes transpositions to live subtree). `MacroFencingAction` is the MCTS-internal action type; the engine never sees it. See MCTS_DESIGN.md §4-5.

            nn/                     # NN value-function infrastructure (subpackage). Schema, recording, and encoder are torch-free so data-generation scripts don't pay the import cost; dataset / model / training / agent import torch and must be imported explicitly (not re-exported from `__init__.py`). See FIRST_NN.md §11.1 for the file-by-file rationale.

                __init__.py         # Re-exports the torch-free public surface (`DATA_VERSION`, `ENCODING_VERSION`, `ENCODED_DIM`, `DecisionSnapshot`, `GameRecord`, `DataVersionMismatch`, `compute_winner`, `load_game_records`, `play_recording_game`, `encode_state`, `feature_names`) so external code can `from agricola.agents.nn import X` regardless of internal layout. Torch-using submodules (`dataset`, `model`, `training`, `agent`) require explicit imports.

                schema.py           # On-disk dataset schema. `DATA_VERSION` constant + hard-fail load check (`DataVersionMismatch`). Frozen dataclasses: `DecisionSnapshot` (state + chosen_action + decider_idx), `GameRecord` (game-level metadata + final scores + winner + terminal_state + decisions tuple). `load_game_records(path)` loader + `compute_winner(s0, s1, tb0, tb1)` helper.

                recording.py        # `play_recording_game(initial_state, p0_agent, p1_agent, *, metadata, legal_actions_fn=restricted_legal_actions)` — plays one full game, captures every non-singleton state as a `DecisionSnapshot` (state recorded BEFORE the agent call so the snapshot matches what the agent saw), then captures terminal state + final scores + tiebreakers + winner into a complete `GameRecord`. Deterministic given pre-seeded agents.

                encoder.py          # Input-vector encoder. `ENCODING_VERSION` + `ENCODED_DIM=170`. `encode_state(state, player_idx) -> np.ndarray` (float32) translates a `GameState` into the flat ~170-feature vector specified in FIRST_NN.md §4: own-player block (54) + opponent block (54) + shared/board (54) + mid-action singletons (8). Numpy-only — the training pipeline converts at the model boundary via `torch.from_numpy(arr)`. `feature_names()` returns the parallel string list for debugging / per-feature analysis.

                dataset.py          # PyTorch dataset builders. `build_datasets(run_dirs, ...)` / `build_datasets_from_games(games, ...)` load `GameRecord`s, split games by index into train/val/test, expand each game's non-singleton snapshots + terminal state into `_ExampleDescriptor`s (state-keyed, dual-perspective on the same key), encode in numpy, fit `NormStats` (per-feature input mean/std + scalar target-margin std) on the training split only, and return three `AgricolaValueDataset`s + the fit `NormStats`. Imports torch. Not re-exported from `__init__.py`.

                model.py            # PyTorch model + normalization wrapper. `ConfigurableMLP` (configurable input_dim / hidden_dims / activation / dropout / norm; composable as a sub-encoder via `output_dim`), `NormalizedValueModel(net, stats)` (wraps a net with fixed input/output normalization buffers; `forward` returns normalized output, `predict_margin` returns raw margin units), `NET_REGISTRY` (name → factory), `EncodingVersionMismatch`. `save(path)` / `load(path)` checkpoint helpers preserve the `NormStats` + the model state in one file. Imports torch.

                training.py         # Training-loop library. `train(run_dirs, out_dir, ...)` programmatic entry runs the full pipeline (load → split → fit norm → AdamW + early-stop on val MSE → checkpoint + curves + calibration plot + metadata JSON). Smaller helpers (`train_one_epoch`, `evaluate`, `setup_seeds`, `make_run_id`, `current_git_sha`, `print_header`, `print_epoch_line`, `save_curves_plot`, `save_calibration_plot`) factored out so future training experiments can compose differently. `l2sp` (L2-SP anchor `λ·‖θ−θ₀‖²` toward the `init_from` warm-start weights — a trust region; requires a warm-start) and `save_all_epochs` (write `epoch_NNN.pt` each epoch for gameplay-based checkpoint selection) added for the FIRST_NN C20 self-play fine-tunes. Library — the CLI wrapper lives at `scripts/nn/train_first.py`. Imports torch.

                agent.py            # `NNAgent(model, *, differential=True, ...)` — `HeuristicAgent` subclass using an NN-backed evaluator. Two evaluators: `nn_evaluator` (single forward pass), `nn_evaluator_differential` (batched 2-input forward; exactly antisymmetric `V_diff(s, 0) = -V_diff(s, 1)` by construction). `model.eval()` set at construction; queries run under `@torch.no_grad()`. Drop-in replacement for `HubrisHeuristicV3` in `play_game` / `play_match.py`. Imports torch.

                policy_heads.py     # `DecisionHead` spec + the `HEADS` registry (placement / choose_subaction / commit_build_major). Each head declares owns(state) (the pending-stack-top predicate), output vocab, target_index(action) (chosen→class), legal_mask(state). The factored policy: dataset/model/training/policy_prior are all head-driven, so adding a head is a new DecisionHead here, not new modules. Torch-free. See POLICY_HEAD.md.

                policy_dataset.py   # Policy-head dataset (behavioral cloning). `PolicyNormStats` (input-norm only), `AgricolaPolicyDataset`, `_decision_rows(games, head)` (head-driven single-perspective extraction), `build_policy_datasets[_from_games](..., head=...)`. Streams worker pickles (memory-bounded). For the `awr` loss variant, computes advantage weights `clip(exp((R−V_θ(s))/β), 0, w_max)` from a value-net baseline. Imports torch.

                policy_model.py     # `NormalizedPolicyModel` — input-normalized classifier (`head.num_classes` logits) with masked softmax (illegal classes → prob 0; all-illegal guard). Persistence mirrors `NormalizedValueModel` (meta sidecar carries `model_kind="policy"` + the `head` name; ENCODING_VERSION hard-checked). Imports torch.

                policy_training.py  # `train_policy(run_dirs, out_dir, *, head, loss_weight, value_ckpt, awr_clip, init_from, ...)` — weighted masked cross-entropy, top-1/top-3 (+winners-subset) metrics, early-stop on val CE. `--init-from` warm-starts the trunk from a value OR policy checkpoint (shape-tolerant transplant; head layer stays fresh). CLI: scripts/nn/train_policy.py. Imports torch.

                policy.py           # `policy_prior(state, model, *, head=None) -> {action: prob} | NO_PRIOR` — the PUCT consumer surface. Auto-dispatches via `model.head_name`; returns NO_PRIOR off the head's decision points (the fallback is PUCT's call). Imports torch.

    tests/                          # pytest test suite — per-file coverage descriptions in TEST_DESCRIPTIONS.md.

        __init__.py                 # Empty package marker.

        conftest.py                 # Shared pytest fixtures. Autouse `_reset_opt_config` snapshots/restores `agricola.opt_config` flags and clears the frontier/fence lru_caches between tests, so the cross-level tests that flip `PARETO_OPT_LEVEL` / `FENCE_SCAN_CACHE` never leak state.

        factories.py                # Prefabricated-state helpers (with_resources, with_animals, with_majors, with_grid, with_pending_stack, etc.) for composing test states — including states unreachable through gameplay. Project-wide convention for test setup.

        test_utils.py               # Test infrastructure (not a test file): run_actions for scripted multi-action walks, random_agent_play driver, and the IMPLEMENTED_NON_ATOMIC_SPACES / filter_implemented action filter (forward-compat as new action types land).

        test_state.py
        test_helpers.py
        test_scoring.py
        test_legality_atomic.py
        test_legality_non_atomic.py
        test_resolution_atomic.py
        test_engine.py
        test_reveal.py
        test_grain_utilization.py
        test_potter_ceramics.py
        test_bake_bread.py
        test_farmland.py
        test_cultivation.py
        test_side_job.py
        test_animal_markets.py
        test_major_improvement.py
        test_house_redevelopment.py
        test_farm_expansion.py
        test_fences.py
        test_fencing.py
        test_farm_redevelopment.py
        test_harvest_field.py
        test_harvest_feed.py
        test_harvest_breed.py
        test_harvest_integration.py
        test_replace.py
        test_agents_heuristic.py
        test_restricted_actions.py
        test_mcts.py
        test_frontier_opt.py
        test_nn_records.py
        test_nn_encoder.py
        test_nn_dataset.py
        test_nn_model.py
        test_train_first_nn.py
        test_nn_agent.py
        test_nn_policy.py
        test_generate_nn_training_data.py
        test_validate_nn_dataset.py

    scripts/                        # Out-of-tree utilities — profiling, benchmarking, tuning. Re-runnable; not imported by `agricola/` or `tests/`. Used to produce / update PROFILING.md and the tuned-config JSONs in `tuned_configs/`.

        profile_engine.py           # Three-workload runner (A: random from setup; B: random from wealthy prefab; C: micro-bench across 9 prefab states) with cProfile + wall-clock.

        profile_states.py           # 9 prefab `GameState` factories covering early/mid/late game; the round-14 state alone makes every non-`lessons` space legal (the coverage requirement for Workload C).

        count_replaces.py           # Monkey-patch counter for `dataclasses.replace` / `fast_replace` call shapes.

        bench_replace.py            # `timeit`-based microbenchmark comparing stdlib replace vs `fast_replace`.

        profile_frontier_helpers.py # Frontier/accommodation optimization profiler (FRONTIER_OPT_DESIGN.md §8.2). `--mode microbench` times each Pareto/feeding helper per-call over the 9 prefab states at a given `--level`; `--mode collision` wraps the helpers during one MCTS game and reports the projection-collision hit rate a perfect cache would achieve (the Phase-2/3 gate). Runnable independent of whether the optimizations are enabled.

        play_match.py               # Match-runner library + CLI. `play_match(p0_factory, p1_factory, seeds)` returns `MatchResult` (win/draw/loss counts, score sums, per-game records). Used by `tune_heuristic.py` and as a standalone head-to-head tool (CLI: `--p0 hubris_v3 --p1 hubris --n 100`). Per-seat `--p0-restricted` / `--p1-restricted` flags wrap each seat's agent in `restricted_legal_actions` independently.

        tune_heuristic.py           # CMA-ES tuner for one TUNABLE category at a time. Supports V1 and V3 configs via `--category` + `--arch`-derived dispatch. Save/resume via pickle (`.cma.pkl` per generation). x0 fallback prevents chain-forward regression. Auto-updates `tuned_configs/<arch>_best.json` when holdout improves (`--no-promote` disables; comparison metric is `holdout.regression.avg_margin` with min-n=30 + same-baseline gate). Parallel across `--jobs` cores; per-baseline diagnostic also parallelized. `--restricted` / `--no-restricted` (default ON), `--fitness {margin,sublinear,truncated,win_rate}` + `--fitness-k`, `--rotate-seeds` / `--rotate-start`, `--validation-pool` / `--validation-pool-start`, `--candidate-r1-force-forest` all recorded in the output JSON. `gen_best_x` persisted in history alongside `session_best_x`. See V3_TRAINING_PIPELINE.md.

        run_iterative_v3.py         # Orchestrator chaining V3 category tunings as block-coordinate descent. Per pass: fields_crops → food → resources → pastures_animals. On passes 2+, each category resumes its previous CMA-ES state. Supports `--start-step N` and `--initial-pickles "cat:path,..."` for resuming partial iterations. `--restricted` / `--no-restricted` (default ON) is forwarded to every tune_heuristic.py subprocess so candidate and baseline both consult `restricted_legal_actions`.

        play_mcts_match.py          # MCTS-vs-opponent match driver. `--opponent {hubris_v3, random, mcts}`, `--v3-config <json>` for the V3 evaluator's tuned config, per-MCTS knobs (`--sims`, `--c-uct`, `--n-random-fencing`, `--fpu-offset`, `--temperature`), `--mcts-as-p1` to swap seats. `--jobs N` (default `cpu_count()`) parallelizes via `multiprocessing.Pool`; workers construct agents in-process (avoids pickling `MCTSSearch` transposition tables — they hold node back-refs to the search). Streams per-game lines as games complete (running win tally + ETA, `flush=True`). Heuristic opponent uses the same strict-restricted legality as MCTS. For best throughput pick `--n` as a multiple of `--jobs` (a 10-seed run on 8 cores wastes 6 cores on the trailing batch of 2).

        nn/                         # NN-specific scripts (subdirectory to keep NN tooling separate from general utilities). All are re-runnable CLIs; the underlying libraries live in `agricola/agents/nn/`.

            generate_training_data.py # NN training-data batch generator. Plays many games between agents drawn from an approved-config ensemble (default: 8 configs from `tuned_configs/DATA_GEN_ENSEMBLE.md`); writes `GameRecord`s to per-worker pickle files under `data/nn_training/runs/<run_id>/games/`. Multiprocessing pool, deterministic plan computation from (n_games, base_seed, approved_configs), balanced contiguous worker slicing, atomic per-game pickle writes, resume-on-existing (loads existing pickle + skips completed game_idxs), bimodal per-agent T draws (95% uniform [0.3, 1.0] + 5% T=4 — independently per agent). Config dispatch: `"random"` / `"t2"` sentinels + JSON paths + `nn:<checkpoint>` for NN seats. Per-game errors caught, logged in metadata.json's `errored_games`, run continues. CLI `--n-games / --n-workers / --out-dir (resume if exists) / --base-seed / --approved-configs / --config-weights / --restricted`, plus `--p0-fixed-config` (pin seat 0 to one config; `--approved-configs`/`--config-weights` then sample P1 only — the asymmetric hard-mining scheme behind `e14_hardmix_1k`, FIRST_NN C21). See FIRST_NN.md §6.

            validate_dataset.py     # Post-generation invariant checker per FIRST_NN.md §6.6. Loads all (or `--sample-size N` random subset of) records from a run dir's worker pickles; runs invariants: `data_version` matches, `chosen_action ∈ legal_actions(state)`, non-singleton snapshots, `state.phase != BEFORE_SCORING`, non-empty `decisions`, `decider_idx == decider_of(state)`, `terminal_state.phase == BEFORE_SCORING`, stored-vs-recomputed final scores. Continues past individual failures to report all issues. Failure summary groups by check type + locates offending game_idx + snapshot. Exit codes 0/1/2 (pass / fail / invalid run dir).

            train_first.py          # Thin CLI wrapper over `agricola.agents.nn.training.train(...)` — argparse for hyperparameters (run-dir, hidden_dims, lr, batch_size, max_epochs, early-stop patience, `--init-from` warm-start, `--l2sp <λ>` L2-SP anchor, `--save-all-epochs`, …) and dispatches into the library. Output: best-model checkpoint + training-curve plot + calibration plot + metadata JSON in the configured out-dir.

            eval_vs_ensemble.py     # Parallel, single-seat evaluation of a trained NN checkpoint vs the 8-config data-gen ensemble. Subprocess-drives `scripts/nn/play_match.py` (multiprocessing `--jobs`) once per opponent, NN as P0, regular legality; prints a per-opponent win%/margin table + aggregate. Single-seat (P0/P1 symmetric, one seat averages SP), so aggregates are NOT comparable to older seat-swapped numbers. `--model <best.pt> --n 100 --jobs 8`. This fixed ensemble is the cleanest *uncontaminated* objective yardstick (see FIRST_NN C22): gate on it, not head-to-head-vs-parent.

            retention_eval.py       # Post-hoc retention sweep (FIRST_NN C20): encode a fixed held-out slice of a BROAD-distribution run dir once (`--probe-dir`/`--probe-games`), then compute raw-margin MAE for any list of checkpoints (`--sweep` globs, e.g. every epoch of a fine-tune) with a `--baseline` model as the reference line. `predict_margin` denormalizes per-model so MAE-in-points is comparable across checkpoints with different NormStats. The instrument that exposes self-play forgetting that a fine-tune's own val split cannot — though MAE≠strength, so it diagnoses, it doesn't gate.

            train_policy.py         # Thin CLI over `agricola.agents.nn.policy_training.train_policy` (`--head {placement,choose_subaction,commit_build_major}`, `--loss-weight {none,awr}`, `--value-ckpt`, `--awr-clip`, `--init-from`). Trains one policy head; writes best.{pt,meta.json} + config + policy_norm_stats + train_log + test_metrics + curves under the out-dir, mirroring train_first.py. See POLICY_HEAD.md.

    tuned_configs/                  # Persistent artifacts from tuning runs. Each completed run writes `<timestamp>.json` (best config, history, holdout), `<timestamp>.log` (human-readable progress mirror), and `<timestamp>.cma.pkl` (full CMA-ES state for resume). `v1_best.json` and `v3_best.json` are auto-maintained pointers to the strongest config per architecture. The 8-config data-gen ensemble (alphas_gen_1, alphas_gen_7, panel_gen16, panel_gen_25, panel_gen47, panel_gen47_wood020, panel_wood_r1 + t2) plus `panel_gen16_temp05.json` (panel-only diversity baseline) live here as named JSONs alongside the timestamped run outputs. `DATA_GEN_ENSEMBLE.md` describes the ensemble. See V3_TRAINING_PIPELINE.md.

    data/nn_training/runs/          # NN training-data datasets (gitignored — regenerable from the deterministic plan). Each generation invocation produces one run directory `<run_id>/` containing `games/worker_NN.pkl` (one per worker, holding `list[GameRecord]`) plus `metadata.json` (run-level metadata: code SHA, host, approved configs, T distribution, restricted flag, base_seed, planned/completed/errored game counts, data_version). See FIRST_NN.md §6.3.

    nn_models/                      # Trained NN checkpoints. Each completed `train_first.py` run produces one subdirectory (`<timestamp>-<suffix>/`) containing `best.pt` (state_dict + NormStats buffers), `best.meta.json` (architecture config + encoding_version), `config.json` (full run configuration for reproducibility), `norm_stats.json` (separate JSON copy of NormStats), `train_log.jsonl` (per-epoch metrics), `train_curves.png`, `calibration.png` (test-split predicted-vs-actual), and `test_metrics.json` (final test MSE/MAE). Top-level `REGISTRY.md` is the authoritative catalog of every checkpoint here — **must be updated as part of every training run** (see CLAUDE.md §2.3).

    task_files/                     # Historical task specs and design artifacts — frozen at the time their task landed; referenced from SESSION_HISTORY.md / CHANGES.md as the design-rationale anchors. Not auto-read; consult when a session-history entry points here.

        ARCHITECTURE.md             # Original full architecture spec + game rules reference + original dataclass definitions. Inline `> Note:` annotations flag known divergences from current code.

        FENCE_IDEAS.md              # Design conversation artifact from Task 6 — broader Fencing design-space alternatives considered before the bitmap-fixed-universe approach.

        TASK_2.md                   # Pastures, slots, accommodation, Pareto frontier.

        TASK_3.md                   # Cooking rates, modified pareto_frontier, breeding_frontier.

        TASK_4a_i.md                # State additions + atomic-space legality.

        TASK_4a_ii.md               # Atomic-space resolution.

        TASK_4a_iii.md              # Pasture cache scaffolding.

        TASK_4b_i.md                # Non-atomic legality (initial pass).

        TASK_5.md                   # The `step` function + pending stack + Grain Utilization + Potter Ceramics.

        TASK_5B_DISPATCH_CLEANUP.md # Dispatch refactor + pending provenance.

        TASK_5C.md                  # Eight non-atomic spaces + convention shifts.

        TASK_5D.md                  # Farm Expansion + multi-shot sub-action pendings.

        TASK_6_pre.md               # Fencing universe enumeration.

        TASK_6.md                   # Fencing + Build Fences + Farm Redevelopment.

        TASK_7.md                   # Harvest phases + rounds 5–14.

    archive/                        # Fully superseded docs kept for historical reference. Not load-bearing.

        TESTS.md                    # Pre-TEST_DESCRIPTIONS.md per-test reference (170-test snapshot). Superseded.
```

For deeper per-file details, see **`FILE_DESCRIPTIONS.md`** (every `agricola/*.py` + the test-infrastructure files). For test-file coverage, see **`TEST_DESCRIPTIONS.md`**.
