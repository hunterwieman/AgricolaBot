# AgricolaBot

A from-scratch Python implementation of the board game Agricola, with the long-term goal of
training a strong AI agent via MCTS and self-play reinforcement learning.

> **For new sessions:** this file is read automatically. It is organized as **Foundations**
> (cross-cutting principles) followed by the project's phases (engine → agent → cards), then a
> status-and-boundaries note, a documentation index, and an annotated directory tree. Deep engine
> mechanics live in
> **`ENGINE_IMPLEMENTATION.md`** (the reference companion to Phase 1). See also
> **`FILE_DESCRIPTIONS.md`** (per-file descriptions), **`TEST_DESCRIPTIONS.md`** (per-test
> coverage), **`design_docs/game_engine/ARCHITECTURE.md`** (original architecture spec, rules reference,
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
  toggles in `agricola/opt_config.py` (now **default-on**; full design, correctness proofs, and the
  cross-level equivalence testing pattern in **`FRONTIER_OPT_DESIGN.md`**; the worked numbers in
  Phase 2.2 "Speeding up MCTS" and `PROFILING.md`). The one caveat for this form is a *hidden*
  global input not in the key (e.g. the active fence universe) — flush the cache when it changes,
  as `active_universe(...)` does. So the standing guidance is: for a hot **field of state**, weigh
  the three factors; for a hot **pure computation**, reach for projection-keyed memoization by
  default.

  The one current accepted exception *of the on-object kind* — `Farmyard.pastures` (the pasture
  decomposition) — and its caller-discipline maintenance contract are documented in
  `ENGINE_IMPLEMENTATION.md`.

- **The Python engine is the source of truth; keep the C++ differential gates green.** A native C++
  reimplementation of the self-play inner loop now exists (§2.4 / `CPP_ENGINE_PLAN.md`), validated
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
(Cultivation sow-max, hand-curated Fencing patterns, a harvest-feed cap). Who uses which:

- **Heuristic agents now default to the *strict* wrapper** (`HeuristicAgent`'s class default; was
  the engine's unrestricted set). The heuristics are used for **evaluation** only now — no longer
  as MCTS leaves or for self-play data generation — so strict is the right default everywhere they
  run. Pass an explicit `legal_actions_fn` to override per-case. (`NNAgent` is not a `HeuristicAgent`,
  so it keeps the unrestricted default.)
- **MCTS tree search** is mode-aware (§2.2 / MCTS_IMPLEMENTATION.md §7): **UCT → strict**, **PUCT →
  full unrestricted** (the policy prior is the sole prune).
- **The web UI** still passes the *regular* wrapper to its AI seats via `--restricted` (an explicit
  override of the heuristic default), so browser play matches that flag.

Details: CHANGES.md Change 11, MCTS_DESIGN.md §7.

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
architecture decisions live here; the comprehensive code reference (UCT, PUCT, chance nodes,
fencing) is **`MCTS_IMPLEMENTATION.md`** — read that to understand `agricola/agents/mcts.py`.
(`MCTS_DESIGN.md` is the older design record, kept for rationale.)

**The design.** Vanilla **UCT** with a first-play-urgency (FPU) term for unvisited nodes; a
**DAG with a transposition table** keyed on `GameState`'s hash, so different action orders
reaching the same state share statistics; **leaf evaluation** via the V3 heuristic's margin
rather than random rollouts; and **macro-actions for Fencing** — a fence layout is a *path* of
pasture-commits, so a `MacroFencingAction` collapses the whole layout to one node and keeps the
tree from exploding in depth. Legality is **mode-aware**: UCT consumes the strict-restriction
wrapper (no prior to soft-prune), while PUCT takes the full, unrestricted `legal_actions` and lets
the policy prior do the pruning (MCTS_IMPLEMENTATION.md §7/§12). Self-play and head-to-head matches
can share a tree or use separate ones.

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

**Optional uniform-mix of the policy prior (`prior_uniform_mix`).** The PUCT prior can be blended with a
uniform distribution before selection — `prior'(s,a) = (1−w)·policy(s,a) + w·(1/k)` over the k legal
actions, `w ∈ [0,1]`, `w = 0` (pure policy) the default. The blend gives **every** legal action a non-zero
prior so PUCT will eventually explore moves the policy scored ≈0 — the fix for a sharply-peaked policy
dumping nearly all visits on the top 2–3 actions. It is implemented in the **C++ production search**
(`MCTSSearch::set_prior_uniform_mix` / `ensure_priors`), not in the Python `mcts.py` reference, and exposed
through the `selfplay` binary's `--prior-mix` / `--prior-mix-p0|-p1` flags. Two uses: the web UI's "Show
analysis" overlay mixes at `w = 0.05` for move-coverage, and the opponent bot can optionally mix (a per-game
New-Game input, default `0.0`). A 400-game self-play A/B (200 + 200 seat-flipped) found `w = 0.05` **not
stronger** than pure policy (≈46%), so it stays off for the bot by default and is used mainly to broaden
analysis coverage. Full detail: `MCTS_IMPLEMENTATION.md` §5.3.1.

**Speeding up MCTS.** The production data-generation workload — an NN value leaf + multi-head policy
PUCT — was profiled and optimized to a **~2× per-move speedup** (cached `GameState.__hash__`, an
optimized inference encoder, a device-query cache, plus a policy-head eval-mode *correctness* fix).
The full catalog is in **`SPEEDUPS.md`** (Part 1 *Implemented* / Part 2 *Potential* — including the
recommended next lever, NN-forward **leaf-batching**); the current production profile + measurement
caveats are in **`PROFILING.md`**; and `MCTS_IMPLEMENTATION.md` §14 maps each optimization onto the
search code. Two standing knobs worth knowing:

- **`agricola/opt_config.py`** — `PARETO_OPT_LEVEL` (0–3, cumulative) + `FENCE_SCAN_CACHE`, now
  **default ON** (level 3 + cache). Behavior-transparent and cross-level-tested
  (`tests/test_frontier_opt.py`): `FENCE_SCAN_CACHE` is result-identical; `PARETO_OPT_LEVEL ≥ 1` is
  set-identical but reorders the RNG realization (reproducible, just a different trajectory than level
  0). They speed legal-action enumeration; their ~9% win on the *old V3-leaf* workload was dominated by
  the fence cache (the Pareto/feeding helpers are cold in NN-leaf PUCT). Full design + proofs:
  **`FRONTIER_OPT_DESIGN.md`**.
- **Ops levers** (not code): run data-gen under **`python -O`** (drops the per-`step` assertion +
  `__debug__` work) and with **process parallelism** (one game per worker, `torch.set_num_threads(1)`)
  — the throughput multipliers, orthogonal to and compounding with the per-sim wins above.

### 2.3 — Neural network

The end-goal agent: a network with a **value head and a policy head**, trained by AlphaZero-style
self-play.

**Two trained model families exist.** They share the ~170-feature encoder and are interchangeable
at the MCTS leaf, but differ in how value and policy are packaged:

1. **Separate nets — a value net + nine disjoint policy heads.** The original slice: one supervised
   value network, plus nine independently-trained behavioral-cloning policy heads (seven fixed-vocab
   + two pointer), stitched into one `policy_fn` by the `make_policy_fn` combiner. This is the
   "Where it stands" paragraph below.
2. **The joint shared-trunk model (Stage B).** All ten outputs unified onto one shared trunk —
   trained jointly with soft-π policy + margin value, **the strongest agent to date**. This is the
   "Stage B" paragraph below.

The joint model is the current best and the basis for ongoing self-play; the separate nets are the
provenance it grew out of and remain the fallback when a single head is trained or probed in
isolation.

**Where it stands.** The first slice is built and already paying off. A **supervised value
network** — trained on self-play data from the heuristic ensemble to predict the terminal score
margin — runs end-to-end: the data-generation pipeline, the ~170-feature encoder, the versioned
on-disk schema, the model and training loop, and the `NNAgent` that wraps the trained model.
**Early results make `NNAgent` the strongest agent to date** — apparently stronger than the
heuristic ensemble it learned from — and MCTS using this NN as its leaf evaluator beats
`NNAgent`'s plain 1-turn lookahead (see 2.2). The **policy head** (Phase c) is now partly built — a
factored multi-head policy (one `DecisionHead` per decision type) bootstrapped by behavioral cloning
of the existing `chosen_action` data, consumed by MCTS through the black-box `policy_fn`; the **PUCT
search machinery (c0) has landed** (POLICY_PUCT_DESIGN.md). The policy now has **full decision-type
coverage** — nine trained heads (each `unweighted` + `awr`): seven fixed-vocab `DecisionHead`s (`placement`
25, `choose_subaction` 8, `commit_build_major` 14, `commit_sow` 104, `commit_bake` 6, `fencing` 110,
`build_stop` 2) and two `PointerHead`s (`animal_frontier`, `harvest_feed`) that score variable-length
Pareto frontiers (see `POLICY_HEAD.md` + `nn_models/REGISTRY.md`). The **`make_policy_fn` combiner**
assembles them into the full `policy_fn` MCTS consumes — it works over the full legal set and
dispatches per decision type (fixed head / pointer head / `build_stop` learned-P(stop) for multi-shot
rooms&stables / uniform-over-cell-priority for the no-signal spatial cells / uniform-over-full-legal),
so the prune lives entirely in the policy. `scripts/nn/build_combined_policy.py` ships the two
end-to-end functions (`build("unweighted")` / `build("awr")`). One known gap: the `fencing` head is
spatially blind (top-1 ~28%) because the encoder has no per-cell features. **Next:** PUCT
consumption/eval of the priors (the real test — accuracy ≠ strength). The full design is in
**`FIRST_NN.md`** and **`POLICY_HEAD.md`**.

**Stage B — the joint shared-trunk model (done; strongest agent to date).** The separate value net
and nine policy heads have been unified into one **`SharedTrunkModel`**: a single `170→256→256→128`
trunk feeding a value head + the 7 fixed + 2 pointer heads, trained jointly on the 41k PUCT self-play
data (the first **DATA_VERSION 3** training) with two upgrades — **soft-π** policy (cross-entropy
against the visit distribution, not one-hot behavioral cloning) and on-policy value. A value-capacity
sweep first settled the trunk size at **256×2** (extra width/depth didn't help — the count encoder is
the binding constraint — and *MAE was a backwards predictor of play strength*). The joint model
**beats the previous-best setup** (champion value + the 9 separate unweighted heads) at 800-sim PUCT:
Python (joint won) and a C++ replication of **99% (198-2, +12.95)**, with **value strength preserved**
(no negative transfer). MCTS consumes it through `make_joint_fns` — **one trunk forward per node** (an
embedding memo shares it between value and policy, so `mcts.py` is unchanged). The whole stack is also
ported to C++ (§2.4) for fast self-play generation. The joint family is now the **`nn_models/best`
pointer** — as of 2026-06-22 `best` is the joint `joint_outcome_44k` (see below), resolved
through a `model_kind`-aware loader. Full design + eval: **`SHARED_TRUNK.md`**.

**The current strongest model — `joint_outcome_44k` (44.6k self-play; the first GCP cloud-trained model; promoted 2026-06-22).** A joint shared-trunk model that **adds a second value head — an *outcome* head** (see "The outcome head + three leaf modes" below) — beside the existing margin value head. Trained warm-started from `exp_visit_combined` (L2-SP λ=1e-3, the recipe matched exactly: 256×256→128, dropout 0.2, lr 3e-4, bs 2048, value-weight 9, v2 encoder; best epoch 12) on **44,608 games** — 40k generated on GCP (1600-sim, seed 100100000; §2.5 cloud workflow) + a 4.6k local replayed set. The retrain **preserves value and policy strength** (the warm-start barely moves them) and **mainly adds the outcome head** (terminal sign-accuracy 0.69). Eval vs the prior champion `exp_visit_combined` is real-but-modest and **depth-dependent**: a 1000-game seat-balanced head-to-head (common-state `value_scale`) with the new model's *margin / outcome / mix* leaf gives 51.6 / 50.9 / 50.6% at 200 sims (a tie), 53.1 / 54.1 / 55.2% at 800, and 56.1 / 56.4 / **59.0**% at 1600 — the mix leaf wins most at depth. (A noisier 400-game run overstated this, so it was re-run at 1000 games with `value_scale` measured on a common state set — `SHARED_TRUNK.md` §9.1.) Full result: `SHARED_TRUNK.md` §10; row in `nn_models/REGISTRY.md`. The prior champion `exp_visit_combined` (40k diverse visit-selection self-play; was champion 2026-06-18→06-22; deployed value_scale 4.345) remains its named-dir fallback.

**The outcome head + three leaf modes.** The `SharedTrunkModel` now carries **two value heads off the same trunk embedding**: the original **margin** head (regresses the terminal score margin) and a new **outcome** head (an `E→1` linear layer regressing `sign(margin) ∈ {−1, 0, +1}` — who wins, ignoring by how much). The outcome head is co-trained inside the value-task batch off the *same* embedding, so it costs **no extra trunk forward**; L2-SP excludes the fresh head, and an old checkpoint without it still loads (backward-compatible). MCTS can then take its leaf value in one of **three modes**, all from that one trunk forward: **margin** (`margin / value_scale`), **outcome** (`outcome / outcome_scale`, already in `[−1, 1]`), or **mix** = `α·(margin/margin_scale) + (1−α)·(outcome/outcome_scale)` (normalize-then-average; `α=1` is pure margin, `α=0` pure outcome), with `α` tunable. A **mix-α self-sweep** (10k games, each seat's α ∼ U[0,1], kernel-regression analysis — `scripts/nn/analyze_alpha_sweep.py`) found the robust-best leaf is **margin-heavy (α≈0.9)**: pure outcome is the worst leaf and a 50/50 mix mediocre, and crucially this *flips* the vs-champion ranking above — so the mix/outcome edge in that head-to-head is partly champion-specific exploitation, while **margin is the robust leaf**. The **deployed bot therefore uses the mix leaf at α=0.9**. `train_shared.py --train-outcome` (default ON) trains the head; the C++ search exposes `set_leaf_mode` / `set_mix_alpha`; full detail in `SHARED_TRUNK.md` §10.

> **c_uct default is 1.0** (unified 2026-06-18 across scripts, the C++ binary, `MCTSAgent`, and the web-UI bot/analyze seats — was a 0.5/1.4 mix). Validated combined@1.0 ≈ combined@0.5. `value_scale` for fair head-to-head MCTS must be measured on a **common state set** (not the condition-biased training `target_std`) — see `SHARED_TRUNK.md` §9.1.

**`joint_taper128_thin` (117k snapshot-thinned; 2026-06-15) — the previous champion.** Scaling the
corpus to 117k games (the 57k + a fresh 60k self-play run generated *by* the 57k model) and retraining
the joint v2 model produced the strongest agent at the time. It **beats `joint_taper128_57k` 84-86% at
800-sim PUCT** AND **dominates the 8-config heuristic ensemble (~100%, ~2.4× their points)** — the first
joint model to clear the *objective* yardstick. The
levers that made 117k tractable on the 8 GB M1 (full 117k thrashed at ~1100 s/epoch): **per-game
snapshot-thinning** (`--snapshot-keep`, a per-run-dir keep-fraction — cuts rows + within-game
autocorrelation), **int8 feature storage** (`--store-dtype int8`, lossless: every feature is an integer),
and **all CPU cores** (don't set `OMP_NUM_THREADS=1` for a *single* trainer) → **~80 s/epoch**. This run
also fixed **two load-bearing warm-start bugs** (`target_std`/norm-buffer transplant + a `value_scale`-
measurement `NameError`) that had mis-calibrated every warm-started joint model, and surfaced that
**`value_scale` is distribution-dependent** (measure both seats on a common state set for fair matches).
Full detail in **`SHARED_TRUNK.md` §4.1** and `nn_models/REGISTRY.md`.

**`joint_taper128_thin_sp30k_lr3e4` is now `nn_models/best` (promoted 2026-06-15).** The `best.{pt,meta.json}` pair
is a copy of its checkpoint, so `best` resolves to a **joint `SharedTrunkModel`** (`model_kind:
"shared_trunk"`), not a separate-net value model. Consumers split into two camps and stay working
without per-call branching:
- **Value-only consumers** (the web UI `nn`/`mcts-leaf` seats; the `--value-ckpt` AWR baseline in
  `train_policy.py`) load through the new **`model_kind`-aware `load_value_evaluator(stem)`**
  (`agricola/agents/nn/model.py`): `"value"` → `NormalizedValueModel.load`, `"shared_trunk"` →
  `SharedTrunkModel.load`. Both expose `predict_margin`/`value_scale`, so the joint value head is a
  drop-in 1-turn value leaf (its policy heads unused on this path).
- **MCTS-leaf consumers** (`play_mcts_match.py`, `generate_selfplay_data.py`, `bench_shared_tree.py`)
  detect the joint `best` and wire **value + policy off the one trunk** via `make_joint_fns`. (The two
  UCT-MACRO-archetype search-sweep scripts that couldn't take a fused policy —
  `run_search_tournament.py` / `eval_search_vs_ensemble.py` — have been retired to `archive/scripts/`,
  along with the other separate-net/UCT-MACRO and V3-leaf instrumentation drivers; see the archive note
  in the directory tree.)
The promoted `best.meta.json` carries **`value_scale = 4.24`** (stored from the self-play distribution;
`value_scale` is meta-only). The older separate-net champion `M_82k_warmM62k` remains the value-only
fallback for any consumer that wants a pure `NormalizedValueModel`.

> **Before refactoring the joint dataset builder (`shared_dataset.py`), read
> `SHARED_TRUNK.md` §3 — "the two memory lessons" — in full.** That builder's `build_shared_datasets`
> → `_finalize_payloads` is **memory-load-bearing on the 8 GB M1**: it streams chunk *paths* from disk
> (never loading a whole run dir) and assembles the value tensor **directly into its per-split arrays**
> (never a combined `value__X` that would double when mask-sliced). This is fragile in a specific,
> dangerous way: **the test suite does not exercise it** (the tests run on ~30 tiny games where memory
> is invisible), so a "tidy-up" back to load-all-then-`np.concatenate`-then-slice will pass green while
> silently reintroducing a ~10 GB OOM at 57k games — which is how the bug shipped originally. Keep the
> path-streaming + direct-to-split shape; §3 has the full rationale.

**Encoder experiments — a forward-compatible encoder registry (mechanism landed; a candidate under
evaluation, NOT promoted).** A model now declares *which input encoder* it was trained with via an
`encoder_tag`, and both Python (`EncoderSpec` / `ENCODERS` in `encoder.py`) and C++ (`encoder_for_tag`
in `encoder.cpp`, read from the manifest's `encoder_tag`) **dispatch through a registry** — no
per-model branches; adding a future encoder is one registry row + one encode fn. The first use is a
**candidate 178-feature encoder** (`cand_feat178_v1`): per player it adds a begging-free running score,
turns-until-next-feeding, and can-renovate/can-grow capability bits, and it *removes* the begging count
— begging is a pure end-of-game penalty, so it's stripped from the value target and added back
deterministically at inference (`−3·(own−opp)`, margin-model only). The whole stack is encoder-aware:
`train_shared.py --encoder {v2,candidate}`, the joint dataset/model/policy thread the `EncoderSpec`,
and `export_weights.py` writes `encoder_tag` so C++ picks the right encoder; permanent C++ gates
(`test_cpp_joint_candidate_matches_python`) validate the candidate path ≤1e-4. The **cheap-iteration
recipe**: encoders re-encode the *same* raw self-play games (`DecisionSnapshot` stores the `GameState`,
not an encoding), so trying one is a re-encode + retrain, not a data regen — and the C++ encoder is
ported *eagerly* (it's incremental + differential-harness-safe) so eval/self-play run at C++ speed
rather than waiting hours on Python. The candidate beats `joint_taper128` at 800-sim PUCT (temp-0 63%,
temp-0.3 52%); promotion is held pending a 57k-game retrain. Catalog: `nn_models/REGISTRY.md`.

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

### 2.4 — The C++ self-play engine (performance)

Self-play data generation — the throughput bottleneck for NN training (2.3) — now has a **second,
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

### 2.5 — The self-play & training workflow

The pieces above (the engine, MCTS, the NN, the C++ twin) compose into one loop: **generate
self-play games → train on them → evaluate → repeat**. This section is the orientation map for
*which script to reach for and why*; the per-flag detail lives in each script's directory-tree entry
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
  match). `scripts/nn/eval_vs_ensemble.py` is the higher-level harness that drives a checkpoint
  against the fixed 8-config ensemble — the cleanest *uncontaminated* strength yardstick.

The "port in different agents, or two of the same" flexibility is exactly this distinction: **same
agent both seats = self-play generation; different agents per seat = evaluation match.** The agent at
each seat is a `(value_fn, policy_fn)` pair behind the engine's black-box leaf/prior contracts, so
any evaluator (heuristic V3, separate value net, joint trunk) drops in at either seat without
touching `mcts.py` — that interchangeability is what makes the same driver serve a head-to-head
today and a card-game agent later.

**Defaults and why.** Production self-play uses the **joint shared-trunk model** as the agent —
one trunk supplying *both* the value leaf and the policy prior (`make_joint_fns`, §2.3 Stage B). As of
2026-06-15 **`nn_models/best` itself resolves to the joint model** (`joint_taper128_thin`), loaded
through the `model_kind`-aware `load_value_evaluator` (value-only consumers) / `make_joint_fns`
(MCTS-leaf consumers) — so passing `--leaf-ckpt nn_models/best` (the default for the generation /
match scripts) now drives the joint value+policy agent directly. A different joint checkpoint can
still be supplied explicitly via `--leaf-ckpt <joint-ckpt>` (Python) or its exported manifest (C++).
The older *separate* value net (`M_82k_warmM62k`) + the nine-head combined behavioral-cloning policy
remain available as the value-only fallback for any consumer that wants a pure `NormalizedValueModel`.
Search runs PUCT with `FenceMode.FLATTEN` over the **full unrestricted** legal set (the policy prior
is the sole prune — §2.2), `c_uct = 1.0` (the unified default as of 2026-06-18; calibrated to the value head's common-state `value_scale`), and a low
played-move temperature so trajectories stay near-greedy while π still records the search's
exploration. Generation is **chunked-streaming and resumable** (bounded
per-worker RAM, O(n) writes, skip-completed-game-idxs on restart) and runs **one game per worker
process** with `torch.set_num_threads(1)` — the throughput multipliers that matter on an 8-core
machine. The C++ generator's default **batch mode** loads the exported NN weights *once per worker*
(one process plays its whole slice) rather than once per game.

#### The training scripts

All are thin CLIs over libraries in `agricola/agents/nn/`; each writes a self-contained checkpoint
dir (`best.pt` + meta + config + metrics + curves) and **must update `nn_models/REGISTRY.md`** on
completion (§2.3). Which trainer to use:

- **`scripts/nn/train_first.py`** — the **value net** (separate-net family). Wraps `training.train`:
  load → split → fit norm → AdamW + early-stop on val MSE → checkpoint. Supports warm-start
  (`--init-from`) and the L2-SP trust-region anchor for self-play fine-tunes.
- **`scripts/nn/train_policy.py` / `train_policy_pointer.py`** — one **disjoint policy head** at a
  time (the seven fixed heads / the two pointer heads), behavioral-cloned from `chosen_action` data
  with either the `unweighted` or advantage-weighted (`awr`) loss.
  `scripts/nn/build_combined_policy.py` then assembles the nine head checkpoints into the end-to-end
  `policy_fn`.
- **`scripts/nn/train_shared.py`** — the **joint shared-trunk model** (current best). Wraps
  `shared_training.train_shared`: interleaves per-head batches through the one trunk with **soft-π**
  policy CE + margin-MSE value, per-head gradient balancing, early-stop on **value** val-MSE.

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
  → evaluate (run_cpp_match.py / eval_vs_ensemble.py) → promote in REGISTRY.md → repeat
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

## 2.6 — Web UI & online deployment

The browser game (`play_web.py` + `static/` + `templates/`) is playable **online** at
**https://agricolabot.fly.dev/**, deployed to **Fly.io** as a single always-on container. Human-vs-bot
only; the bot is the joint-trunk model (`joint_outcome_44k`) driven by **C++ MCTS PUCT** (the `selfplay
--move` binary via `_CppMctsAgent`, falling back to Python MCTS if the binary / `cpp_export_best` is
absent), playing the **mix leaf at α=0.9** (§2.3 — `play_web.py` sets `_CPP_LEAF_MODE="mix"` /
`_CPP_MIX_ALPHA=0.9`, passed through `selfplay --move`'s `--leaf-mode` / `--mix-alpha`). Deploy
walkthrough: **`DEPLOY.md`**; web-UI polish inbox: **`FRONTEND_FIXES.md`**.

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

**Per-game New-Game inputs** (prompted on "New game"): the **seed**, the **sims/move** budget (default
800), and the **opponent prior-mix** `w` (default `0.0`; see §2.2 — broadens the bot's search, found not
stronger so default off).

**Toggles** (header): **Fast mode** (auto-submit singleton/forced actions and skip confirm on them);
**Confirm turns** (pause after each *non-forced* human turn to confirm/undo before the bot replies — undo
is only offered when this is on; harvest **feed** and **breed** are separate turns); **Show analysis** (a
read-only overlay of the bot's MCTS Q-value + visit count for each of the human's moves — async, never
blocks the move, cancelled when you move, uniform-prior-mixed at `w=0.05` for coverage; its **explore**
input is the analysis-only `c_uct`, default `1.0`). The overlay's Q is shown in the leaf's natural
units: for a **margin** leaf it denormalizes the tree Q by `value_scale` to points, for an **outcome**
leaf it labels the `[−1, 1]` value, and for a **MIX** leaf it emits the **raw, un-denormalized** Q
(there is no single scale for a blend) labeled `mix`. The leaf's `value_target` descriptor is threaded
end-to-end — model → training → export manifest → C++ `value_target()` → `/api/analyze` → `app.js` — so
the overlay labels itself correctly. The action board lists spaces in **reveal order within each
stage**, keeping the STAGE headers.

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

## Phase 3 — Cards (and maybe 4-player)

**Not yet started, but designed — the next major phase.** The full Agricola card system (the ~470 occupation
and minor-improvement cards) is the largest remaining piece of game content. The plan: 
implement the cards, possibly add the 4-player variant, then *repeat the agent-building process*
(Phase 2: heuristic → MCTS → NN) for the richer game.

**The design is scoped in `CARD_SYSTEM_DESIGN.md`** — target scope (Revised base + 5 named
expansions, 2-player, occupations + minors), the engine changes (`PendingPlayOccupation`/
`PendingPlayMinor`, the `PendingActionSpace` hook, the trigger/automatic-effect firing model, the
scoped used-set reset model), the card catalog under `agricola/cards/data/`, the per-group
implementation plan, and the open questions (asymmetric hidden info on the agent side; Grocer;
the deferred legality/affordability machinery). Read it before starting card work.

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
  Redevelopment, and Major Improvement are inert until card support lands. (Farm Redevelopment is
  *not* one of these — its optional second step is Build Fences, not an improvement, and it is
  fully implemented.) Every other space surfaced by `legal_placements` has a working path; the
  `NotImplementedError` branch in `_apply_place_worker` is a defensive guard for unknown space IDs
  (e.g. `lessons`).
- **The 4-player variant** (see Phase 3).

The full per-session build history — what was built each session, the design decisions made, and
the bugs caught and fixed — is in **`SESSION_HISTORY.md`**.

---

## Documentation Files

Top-level docs (live alongside CLAUDE.md and are kept current as the project evolves):

| File | Description |
|---|---|
| `RULES.md` | Complete rules reference for the 2-player Family game, including action space descriptions, major improvement effects, harvest rules, animal accommodation, and scoring tables. |
| `ENGINE_IMPLEMENTATION.md` | Deep-mechanics reference companion to Phase 1 (the game engine): dispatch tables, the full pending-stack provenance scheme and invariants, sub-action cost handling, the Fencing / animal-accommodation / Harvest subsystems, the coding conventions, and the card-trigger machinery. Read alongside Phase 1 when doing engine surgery. |
| `CARD_SYSTEM_DESIGN.md` | **The Phase 3 (Cards) design record** — living doc of the decisions for adding the full card system (Revised base + Artifex/Bubulcus/Corbarius/Dulcinaria/Consul Dirigens, 2-player, occupations + minors) plus the open questions. §0 terminology (hook vs trigger vs automatic effect); private hands of 7-each + configurable card pools; `PendingPlayOccupation`/`PendingPlayMinor`; the `PendingActionSpace` hook (before/after phases, `Proceed`, conditional push via the ownership index); the firing architecture (timing ruling, triggers vs automatic effects, Option-A event registration, opponent-action hooks); the scoped used-set reset model (`_enter_phase`/`_advance_current_player`); one-shot conditional latch + cumulative counters; deferred round-space goods, start-of-round phase, harvest-field hook; deferred legality/affordability machinery with the flagged-card list; the occupation + minor implementation groups; the one-engine/additive-hooks performance split; Python-first C++. Read before starting card work. |
| `CHANGES.md` | Significant cross-cutting refactors that touched many files at once (Resources extraction; two-track pasture cache model; dispatch refactor + pending provenance; harvest phases; `BoardState.action_spaces` canonical-tuple refactor; engine performance pass with `fast_replace` + `legal_actions_cache()`; HubrisHeuristicV3 architecture + iterative tuning pipeline). |
| `CLEANUP.md` | Three small targeted field-level fixes (house material location, field rename, field removal). |
| `SESSION_HISTORY.md` | Full record of what was built each session, including design decisions made and bugs caught. |
| `IMPLEMENTATION_CHOICES.md` | Fine-grained design decisions that worked well for the Family game but may need revisiting when cards are added. |
| `POSSIBLE_NEXT_STEPS.md` | Living planning doc — directions the project could take next, organized by scope and effort. Updated as the project progresses. |
| `SPEEDUPS.md` | Performance catalog in two parts: **Part 1 Implemented** (every optimization in the code, with what/why/where — `fast_replace`, cached `__hash__`, the `opt_config` frontier/fence caches, the NN inference encoder S10–S13, etc.) and **Part 2 Potential next steps** (sketched candidates + *measured no-gos* like jit.trace and the encoding-keyed cache). Stable `S1`–`Sn` identifiers; deep detail for the big ones lives in `FRONTIER_OPT_DESIGN.md` / `CHANGES.md`. (Renamed from `POSSIBLE_SPEEDUPS.md`.) Sibling to POSSIBLE_NEXT_STEPS.md, scoped to performance. |
| `CPP_ENGINE_PLAN.md` | Design + staged-build + results record for the **C++ self-play engine** (CLAUDE.md §2.4): a faithful native reimplementation of the self-play inner loop (engine + MCTS + hand-rolled NN inference) that runs ~4× faster than Python, validated against the Python oracle by the `tests/test_cpp_*.py` differential harness. Covers the architecture (traces, the canonical-JSON contract, the differential-testing methodology), the 7 stages with their equivalence gates (§8.1 status ledger), the JSON-hot-path profiling finding + the two optimization passes, the data-gen pipeline (`generate_selfplay_data_cpp.py`), and the maintenance invariant (Python is the oracle; keep the C++ gates green). All C++ lives under `cpp/`. |
| `INCREMENTAL_PASTURE_DESIGN.md` | Design sketch (NOT STARTED) for S9 option 2 — incrementally updating the cached `Farmyard.pastures` decomposition on fence/stable builds instead of re-running the full flood-fill BFS (`compute_pastures_from_arrays`), the #1 MCTS self-time function. Covers the new-pasture-vs-subdivision branch, the byte-identical-output constraint (the tuple feeds `Farmyard` hash/eq → the MCTS transposition table), the incidental-pocket / stable-repartition / combined-case concerns, and why it's gated on the S9 option-1 memoization landing first. A jumping-off point for a future session. |
| `FRONTIER_OPT_DESIGN.md` | Design + implementation record for the frontier/accommodation optimizations that speed up the Pareto/accommodation helpers in MCTS. Toggleable via `agricola/opt_config.py` (`PARETO_OPT_LEVEL` 0–3 + `FENCE_SCAN_CACHE`), now default-on. Covers the algorithmic rewrites (rate-descending `food_payment`, max-corner), the projection-keyed caches (exact / Φ farm-shape / feeding clip), the correctness invariants + proofs (Appendix A), the cross-level equivalence testing strategy (§8.1) and benchmarking methodology (§8.2), and the landed-status/phasing. **Implemented** — see the Status note at the top. |
| `HEURISTIC_TUNING_PLAN.md` | V1-era plan for self-play tuning. Thread A (tuning harness) has been implemented and run; Threads B and C are partially superseded by V3. See `V3_TRAINING_PIPELINE.md` for the current pipeline. |
| `HUBRIS_V1_NOTES.md` | Design reference for HubrisHeuristic V1: per-term function/motivation/shape/magnitude for every component of `evaluate_hubris_v1`, the V1-vs-V2 finding with worked example, deferred alternatives (renovation bonus, newborn discount) with reasoning, known limitations and failure modes. Read before modifying V1; V3 has its own design doc. |
| `V3_DESIGN.md` | Comprehensive design reference for HubrisHeuristicV3: three combination styles (blend / additive / joint-alpha), per-category specs (fields/crops/pastures/animals/resources/food/joint-alpha), three-component resource pattern (wood/clay/reed/stone), V1 carry-overs and what V3 deletes, known limitations. Read before modifying V3. |
| `V3_TRAINING_PIPELINE.md` | Operational guide for the V3 tuning pipeline: CMA-ES basics, `scripts/tune_heuristic.py` semantics (CLI flags, multi-baseline + regression-detector tooling, save/resume, x0 fallback, `<arch>_best.json` auto-update), the `scripts/run_iterative_v3.py` orchestrator (block-coordinate descent), `v3_best.json` convention, current training state, next steps. |
| `MCTS_IMPLEMENTATION.md` | **The** comprehensive, self-contained reference for the MCTS agent (`agricola/agents/mcts.py`) — read this to understand the search code. An algorithm overview (the four-phase loop, leaf-evaluation, the UCT-vs-PUCT subsection, the DAG/transposition table, sign-flipping, chance nodes, fencing), then the concrete implementation: `MCTSNode` / `MCTSSearch` / `MCTSAgent`, `_simulate` line-by-line + cost cheat-sheet, UCT (`_uct_select_child` / `_select_via_ucb` + FPU) and PUCT (`_puct_select_child` / `_select_via_puct` / `_ensure_priors`), `evaluate_leaf`, the strict/regular legality wrappers, the chance-node routing (`_chance_route` / `chance_counts`), a full Fencing section (`expand_macros` / the entry-body-exit macro generation / the agent's replay queue / `FenceMode`), the played move (`_select_action_with_temperature`), config reference, and an invariants / edge-cases / design-vs-code notes section. Treats the value evaluator and policy as black boxes (only their `(state, player, config) -> float` / `(state, legal) -> {action: prior}` contracts). |
| `MCTS_DESIGN.md` | **Historical design record** (superseded by `MCTS_IMPLEMENTATION.md` for understanding the code; kept for rationale/provenance). Design spec for the MCTS phase (Phase 2.2). Architecture decisions (vanilla UCT + FPU + DAG-with-transpositions + leaf-evaluation + macro-enumeration for Fencing); data structures (MCTSNode / MCTSSearch / MCTSAgent); algorithm details (per-sim flow, UCB, sign-flip backprop, transposition table); strict-restrictions spec (new filters added to `agricola/agents/restricted.py`); implementation phases; open questions. |
| `HIDDEN_INFO_DESIGN.md` | Design + implementation reference for the hidden-information refactor: the round-card reveal as an explicit nature/chance step, the public-state / Environment / observe split, the MCTS chance-node handling, the full file impact map, and the action plan. |
| `FIRST_NN.md` | Design spec for the first NN value function (Phase 2.3). Sections: goals/non-goals, strategic context, design principles (input-encoding philosophy, pre-compute selectively, mid-action encoding, terminal-margin target), input encoding (~170 features split across per-player ×2 / shared / mid-action / terminal-state handling), supervision target (terminal margin + terminal-state training pairs), data generation pipeline (fully specified: 8-config ensemble, bimodal per-agent T, snapshot semantics, file layout, resume protocol, validation), architecture (TBD), training (TBD), evaluation (TBD), open questions, implementation notes (file layout + schema versioning `DATA_VERSION` + `ENCODING_VERSION`), status. Read before working on the NN. |
| `POLICY_PUCT_DESIGN.md` | **Historical design record** (the PUCT search half is now implemented and documented in `MCTS_IMPLEMENTATION.md`; the policy half in `POLICY_HEAD.md`). Design spec for the policy head + PUCT phase (Phase 2.3 (c)→(d)). The factored policy (fixed-width + mask heads for placement / sub-actions / Build Major; score-the-set heads for the fencing / animal-accommodation / harvest-feed / harvest-breed frontiers), the black-box `policy_fn(state, legal_actions) -> {action: prior}` interface MCTS consumes (untrained heads fall back to uniform), the AlphaZero PUCT formula + restated FPU + `leaf_value_scale`-calibrated `c_puct`, chance-node orthogonality, the regular-legality + soft-prune-via-prior rationale, the grounded decision-point taxonomy, the localized `mcts.py` change plan (UCT preserved as a control via `policy_fn=None`), the `fence_mode` enum (MACRO / FLATTEN / SEQUENCE_PRIOR) and the SEQUENCE_PRIOR `n(s,a,L)` per-step-target reconstruction, BC training from existing `chosen_action` data, the eval controls, shared-trunk + self-play forward-compat, and a pre-implementation-edits section. Read before implementing the policy head or PUCT. |
| `POLICY_HEAD.md` | Implementation + design record for the supervised behavioral-cloning **policy heads** (Phase 2.3 (c)). §1–§10 are the original v1 placement-only spec (the factored `DecisionHead`: predicate + vocab + chosen→class + legal mask; `HEADS` registry; the two loss variants — unweighted CE / AWR `w=clip(exp((R−V)/β),0,w_max)`; single-perspective encoding; warm-start trunk transplant; the `restricted.py` ordering-filter **forcing-fix**; metrics = top-1/top-3 agreement, not strength). §11/§14 cover **the rest of the heads now built**: 7 fixed (placement/choose_subaction/commit_build_major/commit_sow/commit_bake/fencing/build_stop) + 2 pointer (animal_frontier/harvest_feed), the `make_policy_fn` combiner + the two end-to-end policy functions, and the spatially-blind-`fencing` finding. Read before adding a policy head. |
| `nn_models/REGISTRY.md` | Authoritative index of every trained NN checkpoint under `nn_models/`. Per-model row: id, `ENCODING_VERSION`, `DATA_VERSION`, training data source, architecture / regularization, train size, test MAE, current Status (active / superseded / incompatible). The checkpoint files themselves (`config.json`, `best.meta.json`, `test_metrics.json`) own the underlying numbers; this file is the catalog that ties them together and records which model is the current default. **Every training run must update this file** as part of its completion — see template at the bottom. |
| `SHARED_TRUNK.md` | Design + implementation + results record for the **joint shared-trunk value+policy model** (Phase 2.3, Stage B): one `170→256→256→128` trunk feeding a value head + 7 fixed + 2 pointer policy heads, trained jointly on the 41k self-play data with **soft-π** (cross-entropy against the visit distribution) policy + margin value. Covers `SharedTrunkModel` (`shared_model.py`), the one-pass cached `shared_dataset.py` (+ §3 **"the two memory lessons"** — the per-pickle-chunking *encode* peak AND the streamed-path / direct-to-split *finalize* peak that OOM'd at 57k; **load-bearing, untested, read before refactoring the builder**), the joint trainer (`shared_training.py`: per-head balance, value-MSE early-stop), the `make_joint_fns` inference adapter (`shared_policy.py`: **one trunk forward per node** via an embedding memo, so `mcts.py` is unchanged), the **C++ joint inference** (`shared_trunk_v1` manifest, mode toggle in `NNInference`, embedding cache, two-net `--match` mode), the value-capacity sweep that set the trunk size (256×2; MAE was a backwards predictor), and the eval (joint beats previous-best at 800-sim PUCT — C++ 99%). Read before touching the joint model. |
| `PROFILING.md` | Profiling findings. Foregrounds the **current production profile** — NN value-leaf + multi-head policy PUCT, i.e. where time goes in the code today (cost attribution, the ~2× session result, the diffuse-engine-remainder finding) — plus **measurement caveats** (laptop wall noise → min-of-N/pair-by-seed; cProfile over-attributes high-call tiny functions; the eval-mode requirement). Older random-play (Workloads A/B/C, R1–R6) and V3-leaf MCTS profiles are kept under **Archived profiles**. Re-run the current profile via `scripts/profile_mcts_nn.py`. |
| `NN_TRAINING_SPEEDUP.md` | Diagnosis + benchmark record for the NN value-training speedup. The *prescriptive* half (changes A batched-indexing + B large-batch `--fast-loader`) is **landed and validated** (see `REGISTRY.md`: bs=8192 fast-loader holds champion-recipe quality) — the code in `training.py` is now the source of truth, and the operational guidance lives in CLAUDE.md §2.5. Kept for its **unique content**: (1) §1–§2 the empirical *why* — training is overhead/optimizer-step-bound not compute-bound, with the per-step cost breakdown and the batch-size sweep (CPU flat past ~4096, MPS best at ~8192); (2) §4–§6 the **MPS (`--device mps`) path**, which was never implemented/validated — the only record of its recommended invocation, 8 GB-RAM/`--data-on-device` risks, non-determinism caveats, and nightly-PyTorch op-gap warnings, should the M1 GPU ever be tried. |
| `FILE_DESCRIPTIONS.md` | Detailed per-file descriptions for every `agricola/*.py` and the test-infrastructure files (`tests/factories.py`, `tests/test_utils.py`). |
| `TEST_DESCRIPTIONS.md` | Per-file coverage descriptions for each `tests/test_*.py`. |
| `SESSION_INTRODUCTION.md` | Standard prompt to give a new coding agent at the start of a session. |
| `README.md` | Human-facing project README (the GitHub landing page): project summary, status overview, the playable-agent table, and future work. Overlaps this file's intro but targets a general reader rather than a coding session. |
| `DEPLOY.md` | Beginner-friendly step-by-step guide to deploying the web UI online on **Fly.io** as a single always-on container (CLAUDE.md §2.6): install `flyctl`, create + deploy the app, logs, regions, rough cost, and the in-memory-game-state caveat (a redeploy drops in-progress games). The deploy artifacts it drives are `Dockerfile` / `.dockerignore` / `fly.toml` / `deploy.sh` at the repo root. |
| `deploy.sh` | One-command Fly.io deploy of the web UI with the *current* champion (CLAUDE.md §2.6): resolves the `nn_models/cpp_export_best` symlink (Docker `COPY` can't follow it) into the concrete export dir, passes it to the `Dockerfile` as the `EXPORT_DIR` build-arg, and runs `fly deploy` (extra args forwarded). Promoting a champion = re-point the symlink, then `./deploy.sh`. |
| `CLOUD_RUNBOOK.md` | Operator guide for running the self-play / training / eval loop **off the M1 on Google Cloud (GCP)** (CLAUDE.md §2.5): project / $50-budget / bucket (`gs://agricola-selfplay-…`) setup, the ARM-native C++ binary build on a T2A instance, launching generation / joint-training / evaluation / the α-sweep, durable upload + VM self-teardown, and the two IAM gotchas (self-delete needs `--scopes=cloud-platform` *and* the SA's `compute.instanceAdmin.v1` role; bucket writes need `storage.objectAdmin`). The path that produced the 40k corpus behind `joint_outcome_44k`. |
| `FRONTEND_FIXES.md` | Punch-list of web-UI *frontend* gaps (`static/app.js`, `static/style.css`, `templates/index.html`), ordered by certainty the fix is needed; each item states the problem, the backend data already exposed, and the specific frontend change. |

Historical task specs and design artifacts (in `design_docs/game_engine/`, frozen at the time of their task's landing):

| File | Description |
|---|---|
| `design_docs/game_engine/ARCHITECTURE.md` | Original full architecture spec, game rules reference, and original dataclass definitions. Field names may diverge from current code — inline annotations flag known discrepancies. |
| `design_docs/game_engine/FENCE_IDEAS.md` | Design conversation artifact from Task 6 — explores the broader Fencing action-space design alternatives. |
| `design_docs/game_engine/TASK_2.md` … `design_docs/game_engine/TASK_7.md` | Implementation task files, one per development task. Frozen at landing time; cross-referenced from `SESSION_HISTORY.md`. |

Archived (in `archive/`, fully superseded by current docs):

| File | Description |
|---|---|
| `archive/TESTS.md` | Pre-`TEST_DESCRIPTIONS.md` per-test reference. Superseded by `TEST_DESCRIPTIONS.md`. |

---

## Directory Structure

```
AgricolaBot/
    play.py                         # Top-level entry point — terminal-based human play UI. Wraps the engine in an interactive REPL with rendered farmyard / action-board / score-card output and action-selection prompts.

    play_web.py                     # Top-level entry point — browser-based human-vs-bot play UI (CLAUDE.md §2.6). Stdlib `ThreadingHTTPServer`; every endpoint is a single request/response returning the full authoritative state (`session.snapshot()`); shares formatting helpers with `play.py`. Multi-tenant: a cookie-keyed `SessionRegistry` gives each browser its own game, with an `AGRICOLA_MAX_CONCURRENT_AI` semaphore capping concurrent MCTS searches. The `mcts` seat delegates to the C++ `selfplay --move` binary (`_CppMctsAgent`) with the joint model when `cpp/build/selfplay` + `nn_models/cpp_export_best` are present, else falls back to Python MCTS; it plays the **mix leaf** (`_CPP_LEAF_MODE="mix"` / `_CPP_MIX_ALPHA=0.9`, passed through `selfplay --move`'s `--leaf-mode` / `--mix-alpha`; §2.3). Per-game New-Game inputs: seed, sims/move (default 800), opponent prior-mix (default 0). Toggles: Fast mode, Confirm turns (undo/confirm), Show analysis (`/api/analyze` → `selfplay --analyze` with `--leaf-mode`/`--mix-alpha`, prior-mix 0.05, async, cancel-on-move; the overlay denormalizes the tree Q by the leaf's `value_target` — margin points / outcome `[−1,1]` / raw `mix`). `--seats`, `--nn-model` (default `nn_models/best`), `--mcts-sims`, `--host`/`--port`/`--no-browser`. The Download-trace button writes the in-progress game's action log to `agricola-trace-seed<N>.json` for post-hoc debugging/replay.

    play_random_game.py             # Top-level entry point — random-vs-random driver. Plays one full game, prints the scoreboard with per-category breakdown and tiebreaker. `--trace` flag adds a per-round narrative (worker placements, sub-actions, harvest sub-phases).

    play_heuristic_game.py          # Top-level entry point — any-vs-any heuristic-agent driver. `--p0`/`--p1` pick from {random, simple, hubris, hubris_v1, hubris_v2}; `--temperature` for softmax sampling; `--lookahead` toggles the action/turn lookahead horizon. Same scoreboard output as `play_random_game.py`.

    Dockerfile                      # Web-UI deploy image (CLAUDE.md §2.6 / DEPLOY.md). Multi-stage: compiles the C++ `selfplay` binary for Linux, then a slim Python layer (stdlib server + numpy) that copies the resolved `cpp_export_best` champion into `nn_models/cpp_export_best/`. Serves `play_web.py` on port 8000.

    .dockerignore                   # Trims the Docker build context (skips tests/data/docs/cpp build artifacts) — but RE-INCLUDES `tests/__init__.py` + `tests/test_utils.py`, which `agricola/agents/base.py` imports at runtime.

    fly.toml                        # Fly.io app config (DEPLOY.md): single always-on machine (`min_machines_running=1`, `auto_stop_machines=false`) so the in-memory game state survives between requests; 2 shared vCPUs / 1 GB RAM; `AGRICOLA_MAX_CONCURRENT_AI=2`.

    DEPLOY.md                       # Beginner-friendly Fly.io deploy walkthrough for the web UI (install flyctl → create → deploy → logs → regions → cost). See CLAUDE.md §2.6.

    deploy.sh                       # One-command Fly.io deploy of the web UI with the current champion (CLAUDE.md §2.6): resolves the `nn_models/cpp_export_best` symlink into the concrete export dir and passes it to the Dockerfile as the `EXPORT_DIR` build-arg (Docker COPY can't follow the symlink), then runs `fly deploy` (extra args forwarded). Promote = re-point the symlink, then `./deploy.sh`.

    CLOUD_RUNBOOK.md                # Operator guide for running the self-play / training / eval loop off the M1 on GCP (CLAUDE.md §2.5): project / budget / bucket setup, the ARM-native C++ build on a T2A instance, launching each loop step, durable upload + VM self-teardown, and the IAM gotchas (self-delete needs `--scopes=cloud-platform` + `compute.instanceAdmin.v1`; bucket writes need `storage.objectAdmin`). Produced the 40k corpus behind `joint_outcome_44k`.

    templates/                      # Web UI assets served by `play_web.py` — the HTML shell.

        index.html                  # Single-page shell `play_web.py` serves; loads `static/app.js` + `static/style.css` and hosts the board DOM the JS populates from the JSON wire format. See CLAUDE.md §2.6.

    static/                         # Web UI assets served by `play_web.py` — frontend JS + CSS.

        app.js                      # The browser frontend (~1.2k lines): fetches game state from `play_web.py`, renders the farmyard / action board / scoreboard, and dispatches the player's chosen action back to the backend. The target of FRONTEND_FIXES.md.

        style.css                   # Web UI styling: board layout, farmyard grid, action-space tiles, scoreboard.

    agricola/                       # Game engine package.

        __init__.py                 # Empty package marker.

        constants.py                # Named enums (Phase, HouseMaterial, CellType) plus lookup tables: action-space accumulation rates, MAJOR_IMPROVEMENT_COSTS, ROOM_COSTS, BAKING_IMPROVEMENT_SPECS, FIREPLACE/COOKING_HEARTH_INDICES, BAKING_IMPROVEMENTS. SPACE_IDS / SPACE_INDEX (canonical 25-entry ordering of all action spaces) index BoardState.action_spaces. stage_of_round(round) / STAGE_OF_ROUND map each round to its stage (used by the reveal enumerator to pick the candidate stage cards).

        resources.py                # Resources (wood/clay/reed/stone/food/grain/veg) and Animals (sheep/boar/cattle) frozen dataclasses with __add__/__sub__/__bool__ operators. Extracted from state.py to avoid circular imports with constants.py.

        pasture.py                  # Pasture dataclass (cells, num_stables, precomputed capacity) + compute_pastures_from_arrays BFS that flood-fills from outside the grid to find enclosed connected components. Independent of state.py via duck typing.

        replace.py                  # fast_replace(obj, **changes) — a drop-in faster equivalent of dataclasses.replace, ~20% faster per call (timeit-measured). Used at every state-mutation site in engine.py / resolution.py / pending.py / cards/. See CHANGES.md Change 9.

        opt_config.py               # Runtime toggles for the frontier/accommodation optimizations: PARETO_OPT_LEVEL (0–3, cumulative) and FENCE_SCAN_CACHE (bool). Now default-ON (level 3 + cache); PARETO_OPT_LEVEL=0 + FENCE_SCAN_CACHE=False is the no-op baseline. helpers.py / legality.py read them to dispatch to optimized (caching / algorithmic) paths. See FRONTIER_OPT_DESIGN.md.

        environment.py              # The Environment frozen dataclass — the hidden ground truth + nature policy for one game. Holds the per-game stage-card reveal order (NOT in GameState); exposes resolve(state) (the driver-facing nature seam) and reveal_action(state) -> RevealCard. The dealer in real games; agents and MCTS never see it. Forward-compat home for future private hands / draw deck + the observe(state, env, i) projection (identity today). See HIDDEN_INFO_DESIGN.md §3.4 / §3.6.

        state.py                    # All frozen state dataclasses: Cell, Farmyard (with cached pastures), ActionSpaceState (with revealed: bool common-knowledge flag), PlayerState, BoardState, GameState — plus get_space / with_space free-function helpers for keyed access to BoardState.action_spaces (a canonical-ordered tuple). The hidden reveal order is NOT on BoardState — it lives in the Environment. The top-level GameState snapshot — every transition produces a new one via fast_replace — is fully hashable, and each hot state dataclass caches its `__hash__` (lazily, pickle-stripped) for the MCTS transposition table (SPEEDUPS.md S5).

        canonical.py                # Canonical, deterministic GameState↔JSON (`dumps`/`loads`) — the shared serialization CONTRACT the C++ engine must reproduce byte-for-byte (CLAUDE.md §2.4, CPP_ENGINE_PLAN.md §3.1). Tag-driven generic dataclass walker (drift-proof); test/interop scaffolding only, not on any production path. The Python engine is untouched.

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

            restricted.py           # Action-pruning wrappers over `legal_actions(state)`. Exports `restricted_legal_actions(state)` (regular: ordering / cell-priority / room-cap / first-pasture / min-begging), `strict_restricted_legal_actions(state)` (strict MCTS variant adding Cultivation sow-max, Grain-Util veggie auto-max, 9 fencing patterns, harvest-feed cap of top-5-V3 + 2 random), and `make_strict_restricted_legal_actions(*, config, rng)` factory for injected RNG/config. Priority constants (STABLE_PRIORITY, ROOM_PRIORITY, PLOW_PRIORITY, FIRST_PASTURE_REQUIRED_CELLS, MAX_TOTAL_ROOMS). Every filter routes through `_safe_narrow` so neither wrapper empties a non-empty input. See CHANGES.md Change 11 (regular wrapper) and MCTS_DESIGN.md §7 (strict additions).

            mcts.py                 # MCTS agent. `MCTSNode` (identity equality, lazy `_legal_actions` cache, `macro_sequences` on fencing-trigger parents, `is_chance` + `chance_counts` for round-card reveal nodes), `MCTSSearch` (transposition table + per-search RNG + cached HubrisHeuristicV3 for greedy macros), `MCTSAgent` (vanilla UCT with FPU, path-only backprop, softmax action selection at T=0.2). **Optional PUCT** (POLICY_PUCT_DESIGN.md): pass `policy_fn(state, legal_actions) -> {action: prior}` + `fence_mode=FenceMode.FLATTEN` to `MCTSSearch`, and `_select_via_puct` replaces UCB with AlphaZero `Q + c·P·√ΣN/(1+n)` over all legal actions (`policy_fn=None` selects UCT, PUCT otherwise); priors are computed lazily (`_ensure_priors`, split from `_compute_legal_actions`). Both modes **step through forced (singleton) moves** before evaluating the leaf (so V is queried at real decisions, not mid-action singletons; UCT is therefore no longer byte-identical to the pre-PUCT engine). `uniform_policy` is the c0 placeholder prior, `root_visit_distribution(root)` exposes the root π. `FenceMode`: MACRO (UCT macros) / FLATTEN (per-pasture commits, required for PUCT) / SEQUENCE_PRIOR (c3, not yet implemented). Hidden reveals are explicit chance nodes: `_chance_route` round-robins over the ≤3 candidate RevealCards (reconstructed from public state — no Environment), they are never leaf-evaluated, and carry a P0 frame label (decider=0) so backprop/UCB are unchanged. Macro-fencing for both trigger points (PlaceWorker("fencing") + ChooseSubAction("build_fences") at PendingFarmRedev), with explicit entry/exit phases handling the outer PendingFencing wrapper. Tree reuse via `re_root(new_root)` (prunes transpositions to live subtree). `MacroFencingAction` is the MCTS-internal action type; the engine never sees it. See MCTS_DESIGN.md §4-5.

            nn/                     # NN value-function infrastructure (subpackage). Schema, recording, and encoder are torch-free so data-generation scripts don't pay the import cost; dataset / model / training / agent import torch and must be imported explicitly (not re-exported from `__init__.py`). See FIRST_NN.md §11.1 for the file-by-file rationale.

                __init__.py         # Re-exports the torch-free public surface (`DATA_VERSION`, `ENCODING_VERSION`, `ENCODED_DIM`, `DecisionSnapshot`, `GameRecord`, `DataVersionMismatch`, `compute_winner`, `load_game_records`, `play_recording_game`, `encode_state`, `feature_names`) so external code can `from agricola.agents.nn import X` regardless of internal layout. Torch-using submodules (`dataset`, `model`, `training`, `agent`) require explicit imports.

                schema.py           # On-disk dataset schema. `DATA_VERSION` constant (currently **3**) + hard-fail load check (`DataVersionMismatch`). Frozen dataclasses: `DecisionSnapshot` (state + chosen_action + decider_idx, plus optional `visit_distribution` — the search's raw root visit counts π — and `root_value` — the P0-frame root value estimate; both default None and are populated ONLY by MCTS self-play recording, the v2→v3 bump), `GameRecord` (game-level metadata + final scores + winner + terminal_state + decisions tuple). `load_game_records(path)` loader + `compute_winner(s0, s1, tb0, tb1)` helper.

                recording.py        # `play_recording_game(initial_state, p0_agent, p1_agent, *, metadata, legal_actions_fn=restricted_legal_actions)` — plays one full game, captures every non-singleton state as a `DecisionSnapshot` (state recorded BEFORE the agent call so the snapshot matches what the agent saw), then captures terminal state + final scores + tiebreakers + winner into a complete `GameRecord`. Deterministic given pre-seeded agents.

                selfplay_recording.py # MCTS self-play recording driver (`DATA_VERSION` 3) — the self-play sibling of `recording.py`. `RootCapturingMCTSAgent` (an `MCTSAgent` subclass that stashes the searched root via `_select_action_with_temperature`, no edit to `mcts.py`) + `play_selfplay_recording_game(initial_state, agent, *, dealer, …)`: plays one SHARED-tree game (a single agent drives both seats), steps through forced (singleton) moves uninvoked, and records each non-singleton decision's state + chosen_action + root visit distribution π + P0-frame `root_value` into a v3 `GameRecord`. Torch-free at module level (the NN leaf rides in via the passed agent).

                trace_replay.py     # C++↔Python interop (CLAUDE.md §2.4): the game-trace serde + the replay adapter. `game_to_trace` (writer) / `replay_trace(trace) -> GameRecord` (reads a C++-emitted `agricola-cpp-trace-v1` trace, replays it through the engine, rebuilds a v3 `GameRecord` with π + root_value) / action↔`params` serde for all 17 action types (closes the web-UI `RevealCard.card` drop). Lets C++-generated self-play feed the unchanged training pipeline. See CPP_ENGINE_PLAN.md §2.

                encoder.py          # Input-vector encoder. `ENCODING_VERSION` + `ENCODED_DIM=170`. `encode_state(state, player_idx) -> np.ndarray` (float32) translates a `GameState` into the flat ~170-feature vector specified in FIRST_NN.md §4: own-player block (54) + opponent block (54) + shared/board (54) + mid-action singletons (8). Numpy-only — the training pipeline converts at the model boundary via `torch.from_numpy(arr)`. `feature_names()` returns the parallel string list for debugging / per-feature analysis. The MCTS-inference hot path goes through `encode_for_inference` (a swap-aware per-state memo) + `swap_perspective`, layered over an index-writer rewrite of `encode_state` (byte-identical to the original; the `(name,value)` `_assemble` is kept as the golden-test oracle + `feature_names` source). See SPEEDUPS.md S10–S13. ALSO hosts the **candidate encoder** (`encode_state_candidate`, 178 features, tag `cand_feat178_v1`: running-score + turns-to-feeding + renovate/grow bits, begging removed) + `begging_margin` + the **`EncoderSpec` registry** (`ENCODERS` / `ENCODER_V2` / `ENCODER_CANDIDATE`) — the forward-compatible encoder-by-tag dispatch the joint path threads (mirrored in C++ `encoder_for_tag`).

                dataset.py          # PyTorch dataset builders. `build_datasets(run_dirs, ...)` / `build_datasets_from_games(games, ...)` load `GameRecord`s, split games by index into train/val/test, expand each game's non-singleton snapshots + terminal state into `_ExampleDescriptor`s (state-keyed, dual-perspective on the same key), encode in numpy, fit `NormStats` (per-feature input mean/std + scalar target-margin std) on the training split only, and return three `AgricolaValueDataset`s + the fit `NormStats`. Imports torch. Not re-exported from `__init__.py`.

                model.py            # PyTorch model + normalization wrapper. `ConfigurableMLP` (configurable input_dim / hidden_dims / activation / dropout / norm; composable as a sub-encoder via `output_dim`), `NormalizedValueModel(net, stats)` (wraps a net with fixed input/output normalization buffers; `forward` returns normalized output, `predict_margin` returns raw margin units), `NET_REGISTRY` (name → factory), `EncodingVersionMismatch`. `save(path)` / `load(path)` checkpoint helpers preserve the `NormStats` + the model state in one file. `model_device(model)` caches the (constant CPU) inference device — the eager `next(model.parameters()).device` walked the module tree on every forward (SPEEDUPS.md S13). Imports torch.

                training.py         # Training-loop library. `train(run_dirs, out_dir, ...)` programmatic entry runs the full pipeline (load → split → fit norm → AdamW + early-stop on val MSE → checkpoint + curves + calibration plot + metadata JSON). Smaller helpers (`train_one_epoch`, `evaluate`, `setup_seeds`, `make_run_id`, `current_git_sha`, `print_header`, `print_epoch_line`, `save_curves_plot`, `save_calibration_plot`) factored out so future training experiments can compose differently. `l2sp` (L2-SP anchor `λ·‖θ−θ₀‖²` toward the `init_from` warm-start weights — a trust region; requires a warm-start) and `save_all_epochs` (write `epoch_NNN.pt` each epoch for gameplay-based checkpoint selection) added for the FIRST_NN C20 self-play fine-tunes. Library — the CLI wrapper lives at `scripts/nn/train_first.py`. Imports torch.

                agent.py            # `NNAgent(model, *, differential=True, ...)` — `HeuristicAgent` subclass using an NN-backed evaluator. Two evaluators: `nn_evaluator` (single forward pass), `nn_evaluator_differential` (batched 2-input forward; exactly antisymmetric `V_diff(s, 0) = -V_diff(s, 1)` by construction). `model.eval()` set at construction; queries run under `@torch.no_grad()`. Drop-in replacement for `HubrisHeuristicV3` in `play_game` / `play_match.py`. Imports torch.

                policy_heads.py     # `DecisionHead` spec + the `HEADS` registry — 7 fixed-vocab heads (placement / choose_subaction / commit_build_major / commit_sow / commit_bake / fencing / build_stop; owns/vocab/target_index/legal_mask). ALSO the `PointerHead` spec + `POINTER_HEADS` registry (`animal_frontier`, `harvest_feed`) for variable-cardinality Pareto frontiers — owns/candidate_dim/enumerate_candidates (re-derives the engine frontier with a small action-delta per candidate). `fencing` (110: 109 RESTRICTED shapes + Stop) is spatially blind; `build_stop` (2-way) learns P(stop) for multi-shot rooms/stables. The factored policy: dataset/model/training/prior are head-driven, so adding a head is a new spec here, not new modules. Torch-free. See POLICY_HEAD.md.

                policy_dataset.py   # Policy-head dataset (behavioral cloning). `PolicyNormStats` (input-norm only), `AgricolaPolicyDataset`, `_decision_rows(games, head)` (head-driven single-perspective extraction), `build_policy_datasets[_from_games](..., head=...)`. Streams worker pickles (memory-bounded). For the `awr` loss variant, computes advantage weights `clip(exp((R−V_θ(s))/β), 0, w_max)` from a value-net baseline. Imports torch.

                policy_model.py     # `NormalizedPolicyModel` — input-normalized classifier (`head.num_classes` logits) with masked softmax (illegal classes → prob 0; all-illegal guard). Persistence mirrors `NormalizedValueModel` (meta sidecar carries `model_kind="policy"` + the `head` name; ENCODING_VERSION hard-checked). Imports torch.

                policy_training.py  # `train_policy(run_dirs, out_dir, *, head, loss_weight, value_ckpt, awr_clip, init_from, ...)` — weighted masked cross-entropy, top-1/top-3 (+winners-subset) metrics, early-stop on val CE. `--init-from` warm-starts the trunk from a value OR policy checkpoint (shape-tolerant transplant; head layer stays fresh). CLI: scripts/nn/train_policy.py. Imports torch.

                policy_pointer_dataset.py # Pointer-head dataset (BC over ragged frontiers). `PointerNormStats` (norm over `[state ; cand]`), `AgricolaPointerDataset` (state stored once per snapshot, flat candidates sliced by offsets), `pointer_collate` (flatten a batch → state/cand/segment/chosen_flat/weight; no padding), `_pointer_rows`, `build_pointer_datasets[_from_games]`. Reuses `_seed_split` + `_compute_awr_weights`. Imports torch.

                policy_pointer_model.py # `NormalizedPointerModel` — per-candidate scorer over `[state ; cand]` rows (`score_flat` for the segment batch, `candidate_probs` for inference) + `segment_log_softmax` (per-segment normalize via scatter_reduce-amax + index_add_). Persists `model_kind="policy_pointer"` + candidate_dim. Imports torch.

                policy_pointer_training.py # `train_pointer(run_dirs, out_dir, *, head, loss_weight, value_ckpt, awr_clip, init_from, ...)` — weighted SEGMENT cross-entropy, within-frontier top-1/top-3 (+winners), early-stop on val CE. Mirrors train_policy artifacts (pointer_norm_stats.json). CLI: scripts/nn/train_policy_pointer.py. Imports torch.

                policy.py           # `policy_prior` (fixed heads) + `pointer_prior` (pointer heads) + `NO_PRIOR`, and `make_policy_fn(models)` / `load_policy_fn(checkpoints)` — the full `policy_fn(state, legal) -> {action: prior}` MCTS/PUCT consumes. Works over the FULL legal set, dispatching by decision type: fixed head / pointer head / `build_stop` (learned P(stop) + cell-priority build cell for multi-shot rooms&stables) / uniform over the cell-priority-filtered set (plow + first-build cells — no encoder signal) / uniform over full legal (the rest). The prune lives entirely in the policy. `make_policy_fn` puts the loaded heads in `eval()` mode — `load()` leaves them in TRAIN mode, which made PUCT priors nondeterministic (dropout active); see SPEEDUPS.md. Imports torch.

                shared_model.py     # `SharedTrunkModel` (Phase 2.3 Stage B, SHARED_TRUNK.md): the joint value+policy net — one `170 → trunk → E` trunk (+ embed_norm) feeding a **margin** value head, a co-trained **outcome** value head (`E→1`, regresses `sign(margin)`; §2.3), + 7 fixed + 2 pointer heads, all reusing `ConfigurableMLP`. Pointer heads score `[embedding ; candidate]` (trunk run once, candidate concatenated). The outcome head loads optionally (backward-compatible with pre-outcome checkpoints). Architecture-agnostic (every width a ctor arg); preserves `predict_margin`/`value_scale` (+ `predict_outcome`/`outcome_scale`); `config_dict()` + `NET_REGISTRY`. Imports torch.

                shared_dataset.py   # One-pass, **per-pickle-chunk-cached** joint dataset (`build_shared_datasets`): reads each run dir's pickles once → value rows (both perspectives + terminal, margin) + fixed-head rows (mask + soft-π) + pointer-head rows (candidates + soft-π), consistent split. Writes `shared_<encoder.tag>_chunks/` (encode peak = one pickle — the memory fix; the per-dir-accumulation version OOM'd). **Finalize is also memory-load-bearing**: `_finalize_payloads` streams chunk *paths* lazily from disk (never loads a whole run dir) and builds the value tensor **directly into its per-split arrays** (never a combined `value__X` — that doubled when mask-sliced and OOM'd at 57k); see SHARED_TRUNK.md §3 before refactoring. Takes an `encoder: EncoderSpec` (default v2; candidate re-encodes the same raw games to its own cache + begging-strips the value target). The per-pickle encode is **parallel** (`n_workers` → a `multiprocessing.Pool`, byte-identical to serial) and **truly resumable** (completeness = all chunks present under the matching roster, so a kill mid-encode just fills the gaps). Reuses the existing dataset classes. Imports torch.

                shared_training.py  # Joint trainer (`train_shared`; CLI scripts/nn/train_shared.py): interleaves per-task batches through the shared trunk — **soft-π** CE (fixed + segment for pointer) + margin MSE + (with `--train-outcome`, default ON) the **outcome** head's `sign(margin)` MSE co-trained in the value-task batch off the same embedding, **per-head gradient balancing** (equal-frequency sampling), `_CyclicTensor` fast-loader, early-stop on **value val-MSE** + `--save-all-epochs` (pick by play). Imports torch.

                shared_policy.py    # `make_joint_fns(model, *, leaf_mode, margin_scale, outcome_scale) -> (value_fn, policy_fn)` — the MCTS adapter for `SharedTrunkModel`. **One trunk forward per node**: margin, outcome, and policy all read off ONE memoized embedding (value sign-flipped to P0), so `mcts.py` is unchanged. `leaf_mode` ∈ margin / outcome / mix selects the value leaf (margin default; mix = the 50-50 normalized-Q average, §2.3 — the tunable-α blend lives in the C++ search). `policy_fn` mirrors `make_policy_fn`'s dispatch off the shared embedding; terminal short-circuit. Imports torch.

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
        test_cpp_canonical.py           # C++-port differential gates (CLAUDE.md §2.4 / CPP_ENGINE_PLAN.md):
        test_cpp_trace_replay.py        #   canonical serde, trace replay, state model + flood-fill,
        test_cpp_state.py               #   legality, step/scoring, encoder, NN value+policy, MCTS,
        test_cpp_legality.py            #   and the C++ self-play data-gen pipeline — each asserting
        test_cpp_step.py                #   the C++ engine matches the Python oracle. Skip if cpp/ unbuilt.
        test_cpp_binding.py
        test_cpp_nn.py                  #   (incl. `test_cpp_outcome_matches_python`: C++ outcome head ≤1e-4, §2.3)
        test_cpp_mcts.py
        test_cpp_selfplay.py
        test_cpp_selfplay_pipeline.py

    scripts/                        # Out-of-tree utilities — profiling, benchmarking, tuning. Re-runnable; not imported by `agricola/` or `tests/`. Used to produce / update PROFILING.md and the tuned-config JSONs in `tuned_configs/`.

        profile_engine.py           # Three-workload runner (A: random from setup; B: random from wealthy prefab; C: micro-bench across 9 prefab states) with cProfile + wall-clock.

        verify_web_sync.py          # Web-UI regression harness (CLAUDE.md §2.6). HTTP-drives a live `play_web.py` server and asserts the client-rendered state == the server's authoritative state across the move (farmland→plow), undo, confirm-turns, new-game, and opponent-mix flows. Prints "RESULT: ALL CHECKS PASSED". Guards the single-channel request/response invariant.

        profile_states.py           # 9 prefab `GameState` factories covering early/mid/late game; the round-14 state alone makes every non-`lessons` space legal (the coverage requirement for Workload C).

        count_replaces.py           # Monkey-patch counter for `dataclasses.replace` / `fast_replace` call shapes.

        bench_replace.py            # `timeit`-based microbenchmark comparing stdlib replace vs `fast_replace`.

        bench_shared_tree.py        # Benchmark: MCTS-vs-MCTS per-game wall time, shared tree (one `MCTSAgent`/`MCTSSearch` driving both seats — MCTS_IMPLEMENTATION.md §11.2 mode 2) vs separate trees (one per seat), at a fixed sim budget. Production NN-leaf PUCT config (value net + combined policy, FLATTEN, full legality); model + policy loaded and warmed up in the pool initializer (untimed) so only `play_game` is measured, `torch.set_num_threads(1)` per worker. Measured a ~1.4–1.6× shared-tree speedup at 500 sims (shared re-rooted nodes inherit the opponent's visits, so `cap_total_sims` runs fewer fresh sims).

        profile_frontier_helpers.py # Frontier/accommodation optimization profiler (FRONTIER_OPT_DESIGN.md §8.2). `--mode microbench` times each Pareto/feeding helper per-call over the 9 prefab states at a given `--level`; `--mode collision` wraps the helpers during one MCTS game and reports the projection-collision hit rate a perfect cache would achieve (the Phase-2/3 gate). Runnable independent of whether the optimizations are enabled.

        profile_mcts_nn.py          # THE production MCTS profiler — NN value leaf + 9-head combined policy PUCT (FLATTEN), the data-gen workload (every other profiler is V3-leaf). Direct cost attribution (wraps value/policy/encode/step/legality timers — no PUCT-vs-UCT confound), `--cprofile` function breakdown, `--wall-only --repeats N` for paired (e.g. git-stash) A/B, `--single-pass` vs differential leaf. Produces the PROFILING.md "Production MCTS-NN PUCT" numbers.

        bench_stop_is_legal.py      # Microbench + equivalence gate for the encoder's `stop_is_legal` guard (SPEEDUPS.md S10): captures the states encode is called on during a production PUCT run, times 3 ways to compute the bit (full legal_actions / empty-stack guard / direct predicate), and asserts they agree byte-for-byte.

        bench_encoding_collisions.py # Measures the encoding-collision rate (SPEEDUPS.md, the encoding-keyed-cache no-go): hooks the inference encoder during a PUCT game and reports distinct encodings vs distinct GameStates — the EXTRA forwards an encoding-keyed NN-output cache would save over a GameState-keyed one (~0.9%, hence no-go).

        proto_jit_trace.py          # PROTOTYPE measuring `jit.trace`+`freeze` on the NN forwards (SPEEDUPS.md, no-go): swaps each model's inner net for a traced+frozen graph, checks numerical exactness vs eager, and times eager-vs-traced end-to-end (interleaved min-of-N). Found ~6–10% — not worth the integration.

        play_match.py               # Match-runner library + CLI. `play_match(p0_factory, p1_factory, seeds)` returns `MatchResult` (win/draw/loss counts, score sums, per-game records). Used by `tune_heuristic.py` and as a standalone head-to-head tool (CLI: `--p0 hubris_v3 --p1 hubris --n 100`). Per-seat `--p0-restricted` / `--p1-restricted` flags wrap each seat's agent in `restricted_legal_actions` independently.

        tune_heuristic.py           # CMA-ES tuner for one TUNABLE category at a time. Supports V1 and V3 configs via `--category` + `--arch`-derived dispatch. Save/resume via pickle (`.cma.pkl` per generation). x0 fallback prevents chain-forward regression. Auto-updates `tuned_configs/<arch>_best.json` when holdout improves (`--no-promote` disables; comparison metric is `holdout.regression.avg_margin` with min-n=30 + same-baseline gate). Parallel across `--jobs` cores; per-baseline diagnostic also parallelized. `--restricted` / `--no-restricted` (default ON), `--fitness {margin,sublinear,truncated,win_rate}` + `--fitness-k`, `--rotate-seeds` / `--rotate-start`, `--validation-pool` / `--validation-pool-start`, `--candidate-r1-force-forest` all recorded in the output JSON. `gen_best_x` persisted in history alongside `session_best_x`. See V3_TRAINING_PIPELINE.md.

        run_iterative_v3.py         # Orchestrator chaining V3 category tunings as block-coordinate descent. Per pass: fields_crops → food → resources → pastures_animals. On passes 2+, each category resumes its previous CMA-ES state. Supports `--start-step N` and `--initial-pickles "cat:path,..."` for resuming partial iterations. `--restricted` / `--no-restricted` (default ON) is forwarded to every tune_heuristic.py subprocess so candidate and baseline both consult `restricted_legal_actions`.

        play_mcts_match.py          # MCTS-vs-opponent match driver. `--opponent {hubris_v3, random, mcts}`, `--v3-config <json>` for the V3 evaluator's tuned config, per-MCTS knobs (`--sims`, `--c-uct`, `--n-random-fencing`, `--fpu-offset`, `--temperature`), `--mcts-as-p1` to swap seats. `--jobs N` (default `cpu_count()`) parallelizes via `multiprocessing.Pool`; workers construct agents in-process (avoids pickling `MCTSSearch` transposition tables — they hold node back-refs to the search). Streams per-game lines as games complete (running win tally + ETA, `flush=True`). Heuristic opponent uses the same strict-restricted legality as MCTS. For best throughput pick `--n` as a multiple of `--jobs` (a 10-seed run on 8 cores wastes 6 cores on the trailing batch of 2). When a `--leaf-ckpt` / `--opp-leaf-ckpt` points at a **joint `SharedTrunkModel`**, that seat is built via `make_joint_fns` (value + policy off the one shared trunk, overriding `--policy`) — so this is the single Python match driver for both separate-net and joint models. (For the fast, torch-free C++ match use `scripts/nn/run_cpp_match.py`.)

        mcts_sweep.py               # MCTS hyperparameter-sweep driver (Python/torch path). Runs a series of match configs in sequence by shelling out to `play_mcts_match` — default sweeps `c_uct ∈ {0.7,1.0,1.4,2.0,2.8}` vs `hubris_v3` — writing a per-config `<label>_cuct_<v>.log` plus a `<label>_summary.json` and a final ranked table with 95% CI on each config's margin. Joint-model-ready by inheritance: a `--leaf-ckpt` pointing at a joint `SharedTrunkModel` is auto-wired by `play_mcts_match` via `make_joint_fns`. The torch-path counterpart to the C++ self-sweep `scripts/nn/run_cpp_sweep.py`; this one sweeps vs a fixed opponent, the C++ one self-plays a model against itself.

        nn/                         # NN-specific scripts (subdirectory to keep NN tooling separate from general utilities). All are re-runnable CLIs; the underlying libraries live in `agricola/agents/nn/`.

            generate_training_data.py # NN training-data batch generator. Plays many games between agents drawn from an approved-config ensemble (default: 8 configs from `tuned_configs/DATA_GEN_ENSEMBLE.md`); writes `GameRecord`s to per-worker pickle files under `data/nn_training/runs/<run_id>/games/`. Multiprocessing pool, deterministic plan computation from (n_games, base_seed, approved_configs), balanced contiguous worker slicing, atomic per-game pickle writes, resume-on-existing (loads existing pickle + skips completed game_idxs), bimodal per-agent T draws (95% uniform [0.3, 1.0] + 5% T=4 — independently per agent). Config dispatch: `"random"` / `"t2"` sentinels + JSON paths + `nn:<checkpoint>` for NN seats. Per-game errors caught, logged in metadata.json's `errored_games`, run continues. CLI `--n-games / --n-workers / --out-dir (resume if exists) / --base-seed / --approved-configs / --config-weights / --restricted`, plus `--p0-fixed-config` (pin seat 0 to one config; `--approved-configs`/`--config-weights` then sample P1 only — the asymmetric hard-mining scheme behind `e14_hardmix_1k`, FIRST_NN C21). See FIRST_NN.md §6.

            generate_selfplay_data.py # MCTS self-play training-data generator (`DATA_VERSION` 3) — the self-play sibling of `generate_training_data.py`. Plays N SHARED-tree MCTS-vs-MCTS games (NN value leaf `nn_models/best` + combined behavioral-cloning policy; PUCT / FLATTEN / full legality) via `play_selfplay_recording_game`, recording π + `root_value`. CHUNKED STREAMING writes (`worker_NN_cNNN.pkl` flushed every `--chunk-size` games then buffer dropped → bounded per-worker RAM + O(n) writes, vs the heuristic generator's O(n²) full-list rewrite); resumable (scans existing chunks for completed game_idxs); fresh tree per game (shared only between the two seats). Reuses `generate_training_data.py`'s `partition_plan` / `_write_pickle_atomic` / run-id scaffold + a live progress monitor with ETA. CLI: `--n-games / --out-dir (resume if exists) / --n-workers / --base-seed / --sims / --c-uct / --temperature / --chunk-size / --leaf-ckpt / --policy {unweighted,awr}`.

            generate_selfplay_data_cpp.py # C++ self-play data-gen driver (CLAUDE.md §2.4) — the C++-backed analog of `generate_selfplay_data.py`, producing the IDENTICAL `GameRecord` run-dir format so training consumes it unchanged. Runs the `cpp/build/selfplay --mcts` binary across a `multiprocessing` worker pool (default **batch** mode: one process per worker plays its whole slice via `--game-idxs`, loading NN weights once; `--per-game-process` is the one-process-per-game baseline), then `replay_trace`s each trace → `GameRecord` → chunked pickles. Reuses `generate_training_data.py`'s `partition_plan` / `_write_pickle_atomic` / run-id; resume + error-logging + overwrite-guard + `generation_mode` in metadata. ~4× faster than the Python generator. See CPP_ENGINE_PLAN.md.
            export_torchscript.py   # (Superseded by export_weights.py.) Exports the value net + 9 policy heads to TorchScript `.ts` for the original libtorch-based C++ inference. Kept for provenance; the C++ engine no longer uses libtorch.
            export_weights.py       # Exports the trained value net + 9 policy heads to raw float32 blobs + `weights_manifest.json` under `nn_models/cpp_export/`, consumed by the C++ hand-rolled MLP inference (CLAUDE.md §2.4). For a joint model also writes the **outcome** head blob + `outcome_scale` (§2.3) and the leaf's `value_target` descriptor. Run after training, before C++ data-gen. See CPP_ENGINE_PLAN.md §6 / "Optimization pass #2".

            validate_dataset.py     # Post-generation invariant checker per FIRST_NN.md §6.6. Loads all (or `--sample-size N` random subset of) records from a run dir's worker pickles; runs invariants: `data_version` matches, `chosen_action ∈ legal_actions(state)`, non-singleton snapshots, `state.phase != BEFORE_SCORING`, non-empty `decisions`, `decider_idx == decider_of(state)`, `terminal_state.phase == BEFORE_SCORING`, stored-vs-recomputed final scores. Continues past individual failures to report all issues. Failure summary groups by check type + locates offending game_idx + snapshot. Exit codes 0/1/2 (pass / fail / invalid run dir).

            train_first.py          # Thin CLI wrapper over `agricola.agents.nn.training.train(...)` — argparse for hyperparameters (run-dir, hidden_dims, lr, batch_size, max_epochs, early-stop patience, `--init-from` warm-start, `--l2sp <λ>` L2-SP anchor, `--save-all-epochs`, …) and dispatches into the library. Output: best-model checkpoint + training-curve plot + calibration plot + metadata JSON in the configured out-dir.

            eval_vs_ensemble.py     # Parallel, single-seat evaluation of a trained NN checkpoint vs the 8-config data-gen ensemble. Subprocess-drives `scripts/nn/play_match.py` (multiprocessing `--jobs`) once per opponent, NN as P0, regular legality; prints a per-opponent win%/margin table + aggregate. Single-seat (P0/P1 symmetric, one seat averages SP), so aggregates are NOT comparable to older seat-swapped numbers. `--model <best.pt> --n 100 --jobs 8`. This fixed ensemble is the cleanest *uncontaminated* objective yardstick (see FIRST_NN C22): gate on it, not head-to-head-vs-parent.

            retention_eval.py       # Post-hoc retention sweep (FIRST_NN C20): encode a fixed held-out slice of a BROAD-distribution run dir once (`--probe-dir`/`--probe-games`), then compute raw-margin MAE for any list of checkpoints (`--sweep` globs, e.g. every epoch of a fine-tune) with a `--baseline` model as the reference line. `predict_margin` denormalizes per-model so MAE-in-points is comparable across checkpoints with different NormStats. The instrument that exposes self-play forgetting that a fine-tune's own val split cannot — though MAE≠strength, so it diagnoses, it doesn't gate.

            train_policy.py         # Thin CLI over `agricola.agents.nn.policy_training.train_policy` (`--head` ∈ HEADS = {placement,choose_subaction,commit_build_major,commit_sow,commit_bake,fencing,build_stop}, `--loss-weight {unweighted,awr}`, `--value-ckpt`, `--awr-clip`, `--init-from`, `--legality {restricted,full}` — use `full` for fencing/build_stop). Trains one fixed head; writes best.{pt,meta.json} + config + policy_norm_stats + train_log + test_metrics + curves under the out-dir, mirroring train_first.py. See POLICY_HEAD.md.

            train_policy_pointer.py # Thin CLI over `agricola.agents.nn.policy_pointer_training.train_pointer` (`--head {animal_frontier,harvest_feed}`, `--loss-weight {unweighted,awr}`, `--value-ckpt`, `--awr-clip`, `--init-from`). Default `--run-dir` = the three hidden-info runs (a pointer head enumerates the full engine frontier, so it can train on all the hidden-info runs — not just hidden_info_v2_10k). See POLICY_HEAD.md.

            build_combined_policy.py # Assembles the two end-to-end policy functions MCTS/PUCT consumes: `build("unweighted")` / `build("awr")` (9 head checkpoints each, via `load_policy_fn`), with `UNWEIGHTED_SET`/`AWR_SET` manifests and a `__main__` that sanity-checks both load + produce priors. See POLICY_HEAD.md / nn_models/REGISTRY.md.

            train_shared.py         # Thin CLI over `agricola.agents.nn.shared_training.train_shared` — trains the joint shared-trunk value+policy model (Stage B, SHARED_TRUNK.md). Flags: `--trunk-hidden-dims`, `--embedding-dim`, per-head dims, `--batch-size` (default 2048), `--init-from` (warm trunk), `--hard-targets` (else soft-π), `--train-outcome` (default ON — co-train the outcome head, §2.3), `--no-fast-loader`, `--save-all-epochs`. Imports torch.


            run_cpp_match.py        # Parallel driver for the C++ two-net match: runs `cpp/build/selfplay --match --model-dir-p0 A --model-dir-p1 B` across a worker pool over a seed range. Workers stream per-game `GAME` lines back to the PARENT via a shared queue; the parent prints one clean running-tally stream to **stdout** (like `play_mcts_match.py`) — so a parallel run is one clean log. Per the logging convention, the launcher redirects to `eval_out/<label>.log`. Each model is encoder-self-describing (its manifest `encoder_tag` → the C++ registry picks v2 / candidate). `--leaf-mode-p0` / `--leaf-mode-p1` (+ `--mix-alpha`) pick each seat's value-leaf mode (margin / outcome / mix, §2.3). Memory-light (C++ hand-rolled inference, no torch) — the fast, OOM-safe way to run an 800-sim match. See SHARED_TRUNK.md / CPP_ENGINE_PLAN.md.

            run_cpp_sweep.py        # Parallel C++ self-sweep — one model vs itself, mapping how strength varies with `c_uct` and `sims` (and, with `--sweep-alpha`, the mix-leaf `α` — each seat draws its own per game, for the mix-α sweep). Each game EACH seat independently draws its swept params inside the binary from a per-game RNG (reproducible, reported back in each `GAME` line); a worker pool runs `cpp/build/selfplay` in batch `--game-idxs` mode (NN weights loaded once per process) and STREAMS each finished game to the parent via a shared queue, growing an `--out-csv` incrementally. Mirrors `run_cpp_match.py`'s live-queue shape; memory-light (no torch). The C++ hyperparameter-sweep counterpart to the Python `scripts/mcts_sweep.py` (which sweeps vs a fixed opponent); encoder-self-describing via the model manifest, so joint-model-ready. See CPP_ENGINE_PLAN.md.

            analyze_alpha_sweep.py  # Kernel-regression analysis of a mix-α self-sweep (§2.3). Reads one or more `run_cpp_sweep.py --sweep-alpha` CSVs (cols incl. `alpha0,alpha1,winner`), pools BOTH seats into `(α, result∈{1,0.5,0})` points, and fits a Gaussian Nadaraya-Watson kernel regression of win-prob on α — the curve whose peak is the best fixed α (found ≈0.9, margin-heavy). `--series "label=csv" …`, `--out-png`.

            replay_traces.py        # Replay a run dir's existing C++ self-play traces (`<run-dir>/traces/trace_<i>.json`) into `GameRecord` chunks under `games/` — the REPLAY half of `generate_selfplay_data_cpp.py` only, generating nothing and overwriting no traces. For salvaging a gen run interrupted after traces were written but before replay. Resumable (skips game_idxs already in `games/`), writes the `worker_*.pkl` format training consumes.

    tuned_configs/                  # Persistent artifacts from tuning runs. Each completed run writes `<timestamp>.json` (best config, history, holdout), `<timestamp>.log` (human-readable progress mirror), and `<timestamp>.cma.pkl` (full CMA-ES state for resume). `v1_best.json` and `v3_best.json` are auto-maintained pointers to the strongest config per architecture. The 8-config data-gen ensemble (alphas_gen_1, alphas_gen_7, panel_gen16, panel_gen_25, panel_gen47, panel_gen47_wood020, panel_wood_r1 + t2) plus `panel_gen16_temp05.json` (panel-only diversity baseline) live here as named JSONs alongside the timestamped run outputs. `DATA_GEN_ENSEMBLE.md` describes the ensemble. See V3_TRAINING_PIPELINE.md.

    data/nn_training/runs/          # NN training-data datasets (gitignored — regenerable from the deterministic plan). Each generation invocation produces one run directory `<run_id>/` containing `games/worker_NN.pkl` (one per worker, holding `list[GameRecord]`) plus `metadata.json` (run-level metadata: code SHA, host, approved configs, T distribution, restricted flag, base_seed, planned/completed/errored game counts, data_version). See FIRST_NN.md §6.3.

    nn_models/                      # Trained NN checkpoints. Each completed `train_first.py` run produces one subdirectory (`<timestamp>-<suffix>/`) containing `best.pt` (state_dict + NormStats buffers), `best.meta.json` (architecture config + encoding_version), `config.json` (full run configuration for reproducibility), `norm_stats.json` (separate JSON copy of NormStats), `train_log.jsonl` (per-epoch metrics), `train_curves.png`, `calibration.png` (test-split predicted-vs-actual), and `test_metrics.json` (final test MSE/MAE). Top-level `REGISTRY.md` is the authoritative catalog of every checkpoint here — **must be updated as part of every training run** (see CLAUDE.md §2.3). `cpp_export/` (gitignored) holds the raw float32 weight blobs + `weights_manifest.json` exported by `scripts/nn/export_weights.py` for the C++ engine's hand-rolled inference.

    cpp/                            # The C++ self-play engine (CLAUDE.md §2.4) — a faithful native reimplementation of the self-play inner loop (engine + MCTS + hand-rolled NN inference), ~4× faster than Python single-thread, validated against the Python oracle by the `tests/test_cpp_*.py` differential harness. Builds via CMake (`cpp/README.md`) into a pybind module (`agricola_cpp`, the differential-test surface) + a standalone `selfplay` binary (production data-gen). **No libtorch dependency.** The per-file layout, the staged build, and the §8.1 status ledger are in `CPP_ENGINE_PLAN.md` §9.1 (not duplicated here). `cpp/build/` is gitignored; `cpp/third_party/` vendors `nlohmann/json`.

    design_docs/                    # Design + training docs grouped here to keep the top level tidy. The agent (Phase 2.2/2.3) design records live at the top of this folder; the heuristic-agent (Phase 2.1) design + tuning docs live under heuristic_models/; the original engine (Phase 1) task specs live under game_engine/.

        heuristic_models/           # Heuristic-agent (Phase 2.1) design + tuning docs.

            HUBRIS_V1_NOTES.md      # Design reference for HubrisHeuristic V1: per-term function/motivation/shape/magnitude for every component of `evaluate_hubris_v1`, the V1-vs-V2 finding with worked example, deferred alternatives (renovation bonus, newborn discount), known limitations and failure modes. Read before modifying V1.

            HEURISTIC_TUNING_PLAN.md # V1-era plan for self-play tuning. Thread A (tuning harness) implemented and run; Threads B/C partially superseded by V3. See V3_TRAINING_PIPELINE.md for the current pipeline.

            V3_DESIGN.md            # Comprehensive design reference for HubrisHeuristicV3 — three combination styles, per-category specs, the three-component resource pattern, V1 carry-overs. Read before modifying V3.

            V3_TRAINING_PIPELINE.md # Operational guide for the V3 tuning pipeline: CMA-ES basics, `scripts/tune_heuristic.py` semantics, the `scripts/run_iterative_v3.py` orchestrator (block-coordinate descent), `v3_best.json` convention, current training state.

        MCTS_DESIGN.md              # Historical design record for the MCTS phase (Phase 2.2), superseded by `MCTS_IMPLEMENTATION.md` for understanding the code; kept for rationale/provenance.

        HIDDEN_INFO_DESIGN.md       # Design + implementation reference for the hidden-information refactor: the round-card reveal as a nature/chance step, the public-state / Environment / observe split, the MCTS chance-node handling.

        FIRST_NN.md                 # Design spec for the first NN value function (Phase 2.3): goals, design principles, input encoding (~170 features), supervision target, the fully-specified data-generation pipeline, schema versioning. Read before working on the NN.

        POLICY_PUCT_DESIGN.md       # Historical design record for the policy head + PUCT phase (the search half now implemented and documented in `MCTS_IMPLEMENTATION.md`, the policy half in `POLICY_HEAD.md`).

        POLICY_HEAD.md              # Implementation + design record for the supervised behavioral-cloning policy heads (Phase 2.3 (c)): the factored `DecisionHead`, the `HEADS` registry, the two loss variants, the pointer heads, the `make_policy_fn` combiner. Read before adding a policy head.

        game_engine/                # Original engine (Phase 1) task specs and design artifacts — frozen at the time their task landed; referenced from SESSION_HISTORY.md / CHANGES.md as the design-rationale anchors. Not auto-read; consult when a session-history entry points here.

            ARCHITECTURE.md         # Original full architecture spec + game rules reference + original dataclass definitions. Inline `> Note:` annotations flag known divergences from current code.

            FENCE_IDEAS.md          # Design conversation artifact from Task 6 — broader Fencing design-space alternatives considered before the bitmap-fixed-universe approach.

            TASK_2.md               # Pastures, slots, accommodation, Pareto frontier.

            TASK_3.md               # Cooking rates, modified pareto_frontier, breeding_frontier.

            TASK_4a_i.md            # State additions + atomic-space legality.

            TASK_4a_ii.md           # Atomic-space resolution.

            TASK_4a_iii.md          # Pasture cache scaffolding.

            TASK_4b_i.md            # Non-atomic legality (initial pass).

            TASK_5.md               # The `step` function + pending stack + Grain Utilization + Potter Ceramics.

            TASK_5B_DISPATCH_CLEANUP.md # Dispatch refactor + pending provenance.

            TASK_5C.md              # Eight non-atomic spaces + convention shifts.

            TASK_5D.md              # Farm Expansion + multi-shot sub-action pendings.

            TASK_6_pre.md           # Fencing universe enumeration.

            TASK_6.md               # Fencing + Build Fences + Farm Redevelopment.

            TASK_7.md               # Harvest phases + rounds 5–14.

    archive/                        # Fully superseded docs + retired scripts kept for historical reference. Not load-bearing.

        TESTS.md                    # Pre-TEST_DESCRIPTIONS.md per-test reference (170-test snapshot). Superseded.

        SWEEP_HANDOFF.md            # Retired handoff for the UCT c_uct-sweep plan (UCT-MACRO archetype, NN leaf). Bypassed by the joint shared-trunk pivot; kept for provenance.

        scripts/                    # Retired one-off / superseded scripts. Not on any current path; kept for provenance. Two groups: (a) separate-net + UCT-MACRO-archetype search drivers the joint-model pivot retired — `run_search_tournament.py` (+ its `analyze_tournament.py` Bradley-Terry analyzer), `eval_search_vs_ensemble.py`, `run_nn_search_matrix.py` (all fail-fast on a joint model; superseded by `scripts/nn/eval_vs_ensemble.py` + the C++ `run_cpp_match.py`/`run_cpp_sweep.py`); (b) V3-heuristic-leaf one-off instrumentation whose findings are already in the design docs — `measure_mcts_tree.py`, `measure_v3_prior_distribution.py`, `measure_exhaustive_leaves.py`, `run_exhaustive_vs_greedy_match.py`. Plus older V1/refactor artifacts (`play_mcts_v1_vs_*.py`, `port_pre_refactor_v3.py`, `_validate_fast_loader.py`).
```

For deeper per-file details, see **`FILE_DESCRIPTIONS.md`** (every `agricola/*.py` + the test-infrastructure files). For test-file coverage, see **`TEST_DESCRIPTIONS.md`**.
