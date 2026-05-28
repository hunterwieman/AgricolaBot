# AgricolaBot

A from-scratch Python implementation of the board game Agricola, with the long-term goal of training a strong AI agent using Monte Carlo Tree Search and reinforcement learning.

> **For new sessions:** This file (`CLAUDE.md`) is read automatically. It covers project status, key design principles, code conventions, engine architecture, and an enriched directory tree. For deeper per-file descriptions see **`FILE_DESCRIPTIONS.md`**; for per-test-file coverage see **`TEST_DESCRIPTIONS.md`**. For the full architecture spec, game rules reference, and original dataclass definitions see **`task_files/ARCHITECTURE.md`**. For significant cross-cutting refactors see **`CHANGES.md`**. For small targeted fixes see **`CLEANUP.md`**.

---

## Project Goal

Build a complete, deterministic game engine for the 2-player Family variant of Agricola, then use it as the environment for self-play AI training. The project proceeds in phases:

1. **Game engine** — fast, correct, fully playable (current phase)
2. **Baseline agents** — random agent + heuristic agent
3. **Card system** — full game with occupation and minor improvement cards
4. **Imitation learning** — train on human game data to bootstrap the agent
5. **Self-play RL** — AlphaZero-style MCTS + neural network
6. **Evaluation and tooling**

The Family game variant (no hand cards) is implemented first to validate the full pipeline before card complexity is added.

For the full strategic rationale behind each phase and the key algorithm choices (action space structure, animal accommodation model, neural network design, etc.), see **`STRATEGY.md`**.

---

## Key Design Principles

These are the foundational architectural decisions for the project. The first three (immutable frozen dataclasses, functional core, determinism after setup) are near-absolute — they are load-bearing for MCTS and self-play, and deviating from them would break the AI training pipeline. The fourth ("derived data, not cached data") and fifth ("preserving optionality") are defaults with explicit guidance for when to deviate; "derived data" has one current accepted exception, "preserving optionality" has none. Read each principle for its own framing rather than treating the bundle as a single rule.

- **Immutable frozen dataclasses.** Every piece of game state is a `@dataclass(frozen=True)`. State is never modified in place; every transition produces a new state object using `dataclasses.replace(...)`. This makes tree search safe and cheap — MCTS branches share unchanged subtrees with no copying required.

- **Functional core.** Game logic lives in plain functions (`setup`, `legal_actions`, `resolve`, `score`). State objects have no methods that modify state.

- **Determinism after setup.** All randomness (starting player, stage card ordering) is resolved in `setup(seed)` using a seeded NumPy RNG. After `setup` returns, the engine is fully deterministic.

- **Derived data, not cached data (default).** Default to recomputing derived quantities (animal capacity, fences remaining, stables remaining, enclosed-cell membership, pasture count, etc.) on demand from ground-truth state rather than storing them separately. The reason: any cached value introduces a sync invariant — every code path that mutates the underlying state must also keep the cache consistent. In a frozen-dataclass codebase with millions of state objects flowing through MCTS, a single missed update creates silently-wrong states that are hard to debug. Recomputing is microseconds and trivially correct.

  **When to deviate.** This is a default, not a prohibition. Caching is sometimes the right call, and proposing one is welcome. Three factors make a cache safer to adopt; the more of them apply, the stronger the case:
  1. The derived value is genuinely expensive, or read often enough in hot paths (e.g. inside MCTS rollouts or legality enumeration) that the per-call cost is meaningful.
  2. The cache invariant can be enforced *structurally*, not by convention. The strongest form is auto-fill in `__post_init__` on a frozen dataclass: every constructor call (including `dataclasses.replace`) recomputes the cache, so there is no caller-discipline rule that can be forgotten.
  3. The cache lives on the same object that owns its inputs, so the only code paths that can produce a new cache value are the same ones that can produce a new input value.

  When caching, prefer the *most fundamental* form of the data and derive everything else from it. Don't cache multiple representations of the same underlying fact.

  **Note for future sessions.** If you find yourself instinctively rejecting a caching proposal because "the design doc says no," reread this principle: the doc describes a default and a set of analytical factors, not a hard rule. A well-reasoned caching proposal that addresses the three factors above (or that articulates why a different framing is appropriate) can override this default. The user has good instincts about hot paths the engine will hit later; engage with the proposal on its merits rather than treating the doc as a gate.

  **Current exception:** `Farmyard.pastures` (the pasture decomposition) is cached on `Farmyard`. All higher-level pasture-derived quantities (`enclosed_cells`, capacities, count, fenced-stable count) remain on-demand derivations from this one cached value. The cache is maintained by caller discipline: the two pasture-changing effect functions — `_execute_build_stable` (used by Side Job and Farm Expansion via `CommitBuildStable`) and `_execute_build_pasture` (used by Fencing and Farm Redevelopment via `CommitBuildPasture`) — pass `pastures=compute_pastures_from_arrays(...)` explicitly when constructing a new `Farmyard`; all other `Farmyard` mutations leave `pastures` alone (it rides along correctly via `dataclasses.replace`). This is a deliberate weakening of factor 2 (structural enforcement) — auto-fill via `__post_init__` was the obvious structural alternative, and was the original mechanism, but is not used today; see CHANGES.md Change 2 and Change 3 for the rationale.

- **Preserving optionality.** Never surface an action that is *both* irreversible and "at any time" (deferrable to any future moment) as a standalone bot decision unless the proceeds are needed at that moment (e.g., during harvest feeding, when food is owed). The reasoning: an irreversible "at any time" action can always be deferred to the exact moment its proceeds are needed; doing it earlier can only lose strategic optionality, because the converted goods could have been used for something else and that decision is permanent. So any "convert now if you don't have to" choice is strategically dominated for a rational player, and surfacing it inflates `legal_actions` with options the agent should never pick — bloating MCTS branching and policy-head width without adding anything the agent can learn. Out of scope: actions bound to a specific game event whose timing is fixed — "on Bake Bread" conversions, once-per-harvest crafts (Joinery / Pottery / Basketmaker's Workshop), and similar event-bound effects — which must surface at the event's resolution because the decision can't be deferred past it.

  **Implementation pattern.** "At any time" conversions never appear as standalone actions in `legal_actions`. Instead, the conversion is *bundled* into the resolution of decision points where the proceeds are actually needed (or where deferral would otherwise lose the goods entirely). The agent picks a configuration that includes the conversion as a side effect; it never picks "convert" by itself. Current moments-of-need: overflow at animal-market acquisition (release-or-convert is part of choosing the accommodation configuration); capacity-blocked newborn at breeding (pre-breed eating is part of choosing the post-breed end-state); food owed at harvest feeding (future, Task 7); card food-cost triggers (future, full-game scope).

  **Specific implication: Pareto dominance over upstream goods.** When a decision point returns a frontier of configurations to choose from, Pareto dominance is computed over the upstream goods only — crops, animals — never over the downstream conversion proceeds (food). Reasoning: food is a one-way downstream derivative of upstream goods. If configuration B dominates A on upstream goods, then B achieved the same or better outcome with strictly more goods preserved; choosing A therefore means having converted at least one good beyond what the configuration required — exactly the irreversible-conversion-without-immediate-need the principle prohibits. A naïve "Pareto over (goods, food)" filter falsely retains those configurations and reintroduces the dominated options the principle is meant to prune. Food is still computed and returned alongside each frontier point as the deterministic consequence of the chosen configuration. One refinement in the feeding context: begging markers *are* included as a Pareto dimension (fewer-is-better polarity) because they represent a strategic cost the player has a genuine choice to incur — pay food and avoid the marker, or preserve goods and take the −3 scoring penalty. Excluding them would let any full-feed configuration dominate any partial-feed configuration on a phantom "food-paid" axis, suppressing the goods-preservation-vs-begging tradeoff. The asymmetry: downstream costs the player chose to incur are Pareto dimensions; downstream byproducts of over-conversion are not.

  **Current applications.** `breeding_frontier` (post-breed configuration — canonical worked example: a naïve food-as-Pareto-dim filter would explode the frontier with release-for-food options that all violate the principle); `pareto_frontier` (animal acquisition); and (Task 7) `food_payment_frontier` and `harvest_feed_frontier` (food payment / harvest feeding).

  **Note for future sessions.** Don't reflexively reject a proposal to surface an "at any time" conversion as a standalone action. Engage with the rationale: is there a moment of need not already covered by the existing bundling pattern (e.g., a new card effect creating a new strategic moment)? If yes, the proposal is in-scope — it's a new bundling point. If no, the deviation needs strong justification. No current exceptions.

For the complete architecture specification, see **`task_files/ARCHITECTURE.md`**, the initial design document.

---

## Additional Design Principles

Secondary conventions — narrower in scope than the five Key Design Principles, but worth following consistently because the failure modes are silent (wrong answer, no crash) and the right choice is non-obvious.

### Player parameter convention

Two-step rule for any function that needs information about a player:

**Step 1 — Decide whether to take a `PlayerState` parameter.**

Take `p: PlayerState` as a parameter when the function could *plausibly* be called for any player, not only the active one. When in doubt during design, ask the user — this decision is hard to revise later because it shapes the call sites.

- **Take `p` as a parameter when** the function answers a per-player question that callers may legitimately ask about either player (e.g. "can this player bake bread?", "can this player afford this major improvement?"). Legality helpers fit this shape because MCTS rollouts, opponent-affecting card triggers, and tests may all want to query a non-active player.
- **Do NOT take `p` as a parameter when** the function is intrinsically about whoever is currently acting (e.g. resolution handlers — applying a worker placement always operates on the active player by definition; the per-space legality predicates in `legality.py` only ask "is this space currently legal for the active player?"). Such functions should derive `ap = state.current_player` and `p = state.players[ap]` together, locally, as a single unit.
- **When the answer is "this function operates on a known specific player but `state.current_player` isn't the right way to identify them"** (e.g. `score(state, player_idx)`, `cooking_rates(state, player_idx)`), prefer an explicit `player_idx: int` parameter rather than `p`. This avoids the identity-derivation question entirely.

**Step 2 — If you took `p`, never reference `state.current_player` for player-keyed lookups.**

Once a function accepts `p`, it must derive any required player index from `p` itself, not from `state.current_player`. Mixing in `state.current_player` for some lookups silently couples the function to "p must be the active player" — defeating the purpose of the parameter. The standard implementation is `player_idx = 0 if p is state.players[0] else 1`. Identity (`is`) requires callers to pass the canonical reference (`state.players[idx]`) rather than a freshly-replaced object held against an older `state`; this matches the natural usage pattern in this codebase.

**Concrete examples in this codebase:**

| Function | Shape | Why |
|---|---|---|
| `_can_bake_bread(state, p)` | `(state, p)` | A future opponent-affecting card may legitimately ask "does the opponent have a baking improvement and grain?" |
| `_can_sow(p)` | `(p,)` | Reads only the player's farmyard and resources; no board context needed. |
| `_resolve_day_laborer(state)` | `(state,)` | Resolution applies the active player's worker placement. By definition operates only on `state.current_player`. |
| `score(state, player_idx)` | `(state, player_idx)` | Scoring runs at game end for a specific player, but neither player is "active" in the work-phase sense. Explicit index is clearer than `p`. |
| `legal_placements(state)` | `(state,)` | Top-level query about the active player's placement options. Doesn't need any player parameter at all — derives `ap` once internally. |

**Disclaimer.** Some future card effects may legitimately need both `state.current_player` (e.g. who triggered an effect) and `p` (e.g. whose state is being checked or modified) within the same function, with the two roles genuinely distinct. That is a real exception, not a violation, and should be called out explicitly in the function's docstring when it occurs. Other unforeseen game interactions may surface similar legitimate cross-references; treat each on its merits and document the reasoning.

### Reusable sub-action pendings

Many action spaces call one or more primitive sub-actions. For example: Farmland calls Plow; Cultivation calls Plow and Sow; Grain Utilization calls Sow and Bake Bread. Several full-game cards will call Plow as well.

Implementing the primitive sub-actions directly — once per primitive, with the pending shape and effect function defined in one place — lets us express a much wider range of action-space and card effects as compositions of those primitives. The engine needs only the primitive set plus a way for callers to invoke them; there is no bespoke per-space implementation of plowing, sowing, baking, etc.

**Default:** when designing a new sub-action, default to a single reusable pending pushable from any caller, with caller-supplied `initiated_by_id` for provenance, rather than a space-specific specialization.

**Current reusable sub-action pendings:**

| Pending | Callers |
|---|---|
| `PendingPlow` | Farmland, Cultivation |
| `PendingSow` | Grain Utilization, Cultivation |
| `PendingBakeBread` | Grain Utilization, Side Job, Clay Oven, Stone Oven |
| `PendingRenovate` | House Redev, Farm Redev |
| `PendingBuildStables` | Side Job (`max_builds=1`), Farm Expansion (`max_builds=None`) |
| `PendingBuildFences` | Fencing, Farm Redev |

**Caller-supplied state on the pending.** The pending's fields capture per-call variance — set at push time by the caller. This is what enables one shared pending to serve different callers without specialization:

- `cost: Resources` (bucket 2): Side Job pushes `PendingBuildStables` with `cost=Resources(wood=1)`; Farm Expansion pushes the same pending with `cost=Resources(wood=2)`.
- `max_builds: int | None`: Side Job pushes with `max_builds=1` (caller-imposed cap); Farm Expansion pushes with `max_builds=None` (uncapped).
- `initiated_by_id: str`: provenance string lets future code (especially card triggers) gate on entry point, e.g. "fires only when Bake Bread is reached via Grain Utilization."

The reusable pending stays generic; entry-point semantics live in the caller's pushed metadata.

**Exceptions.** If a future sub-action genuinely doesn't generalize across callers, document the reasoning when the specialization is introduced — but default to reusable until proven otherwise.

**See also.** The pending-stack mechanism (push / pop / ChooseSubAction handlers / `COMMIT_SUBACTION_HANDLERS` dispatch) is covered in "Engine and Turn Resolution Architecture" → "The pending-decision stack."

### Function-name prefix taxonomy

Resolution-layer functions follow a small set of prefix conventions so the role of any function is identifiable from its name:

| Prefix | Meaning |
|---|---|
| `_resolve_<atomic_space>` | atomic worker placement — fully applies effect |
| `_initiate_<nonatomic_space>` | non-atomic worker placement — pushes pending, awaits sub-actions |
| `_choose_subaction_<space>` | handles `ChooseSubAction` at that space's pending |
| `_execute_<sub_action>` | applies a committed sub-action's effect |
| `_resolve_<phase>` | phase bookkeeping (in `engine.py`, not `resolution.py`) |

### Sub-action cost handling

Sub-actions that debit resources fall into four buckets based on where the cost lives. When adding a new sub-action pending that debits resources, choose the bucket that fits — pick bucket 2 by default; reach for bucket 3 when the cost is a function of a commit-time parameter chosen from a small fixed table; reach for bucket 4 when the cost is a function of state plus commit parameters together (the multi-step Build Fences case).

1. **No cost.** The sub-action doesn't debit resources (e.g., `PendingPlow`). No `cost` field. Effect function applies its non-resource effect and returns.

2. **Caller-parameterizable cost — field on the pending.** The cost varies by who pushed the sub-action: different spaces specify different costs, and cards may inject alternate costs or formula choices. The choose handler (or trigger / `_initiate_*` / card effect that pushes the pending) computes the cost at push time and stores it on the pending as `cost: Resources`. The effect function reads `pending.cost` and debits via `p.resources - pending.cost`. Cards that modify cost can update `pending.cost` either at push time (by computing differently) or via a trigger between push and commit (by `replace_top`-ing the pending). `PendingBuildStables` (Side Job: 1 wood; Farm Expansion: 2 wood), `PendingBuildRooms` (Farm Expansion: `ROOM_COSTS[material]`), and `PendingRenovate` are the current examples.

3. **Commit-time-parameterizable cost — keyed lookup at execute time.** The cost varies by a parameter on the commit action itself, chosen at commit time rather than push time. No `cost` field on the pending — the effect function looks up the cost from the commit's parameters against a const table. `PendingBuildMajor` is the canonical example: cost depends on `commit.major_idx`, looked up in `MAJOR_IMPROVEMENT_COSTS`. This pattern fits when the commit-time parameter space is small and pre-defined.

4. **Pure-function-of-state-and-commit cost — shared helper at execute time.** The cost is neither fixed at push time (bucket 2) nor a const-table lookup keyed on commit parameters (bucket 3); it is a deterministic function of `(state, commit_parameters)` together. No `cost` field on the pending and no const table; instead a shared helper computes the cost on demand. Both the enumerator (for affordability filtering) and the effect function (for the debit) call the same helper. `PendingBuildFences` / `CommitBuildPasture` is the canonical example: cost = 1 wood × popcount(boundary edges of `commit.cells`, minus current fences on the farmyard). The helper is `compute_new_fence_edges(farmyard, cells_bm)` in `fences.py`. This bucket fits multi-shot actions where each commit's cost depends on the farm state left by prior commits — a push-time cost doesn't capture that. The commit object stays the minimal source of truth for *action identity*; the helper stays the single source of truth for the *cost formula*. When cards modify cost later, only the helper changes — commit objects never lie about cost.

Bucket 2 is the most flexible for card extensions because the cost can be set or modified anywhere along the push → commit path. Bucket 3 trades flexibility for a single source of truth (the const table) and is appropriate when the cost variations *are* the action's identity (each major improvement is fundamentally a distinct item with a distinct cost). Bucket 4 fits multi-step actions where the per-commit cost depends on the current farm state.

### Multi-shot sub-action pendings

Some sub-action categories allow multiple commits within a single category invocation (Farm Expansion's build_rooms and build_stables; Side Job's build_stable as a degenerate cap=1 case). The pattern:

- The pending carries two integer fields: `max_builds: int | None` (caller-imposed cap, set at push time; `None` means no cap) and `num_built: int = 0` (increments on each commit).
- `max_builds` encodes only the **caller's intent**, not global constraints. Affordability, supply, and cell/placement availability are checked separately in the per-pending enumerator. Side Job pushes with `max_builds=1` (the space's rule). Farm Expansion pushes with `max_builds=None` — the dynamic constraints in the enumerator do all the bounding.
- The effect function is registered with `auto_pop=False` in `COMMIT_SUBACTION_HANDLERS`. Each commit applies its effect, increments `num_built`, and `replace_top`s — but does **not** pop the pending.
- `Stop` is the explicit exit. `Stop` is legal at `num_built >= 1` (the "must do at least one when entering a category" rule); not legal at `num_built == 0`.
- Per-pending legality offers `Commit*` actions only while `(max_builds is None or num_built < max_builds)` AND remaining affordability/placement/supply constraints permit. When no commit is legal but `num_built >= 1`, `Stop` becomes the only legal action and the agent explicitly Stops. This singleton-`Stop` state arises uniformly whether the cap, supply, affordability, or cell-availability constraint is the binding one.

Side Job's stable build is a multi-shot pending with `max_builds=1`: after the single commit, `Stop` is the only legal action. There is no auto-pop optimization for `max_builds=1` cases — surfacing the singleton `Stop` keeps trace consistency uniform across multi-shot pendings and aligns with the engine's "no auto-resolved singleton player decisions" principle.

Card-trigger fields (`triggers_resolved`, `TRIGGER_EVENT`) are intentionally absent from the multi-shot pendings introduced in Task 5D. They will be added per-pending when the first card needs them. When added, the question of whether `triggers_resolved` persists across commits or resets per commit will be settled per the rules interpretation ("one action with multiple builds" suggests persistence across commits; per-individual-build cards would attach to a different event like `"after_build_stable"` on each commit).

### Action-pruning wrapper

Strategic action-pruning lives in `agricola/agents/restricted.py` as a wrapper over `legal_actions(state)` — **not** in `legality.py` or anywhere else in the engine. Reasoning: many priors that look loss-less in the Family game (e.g. "always plow before sow on Cultivation") become lossy once cards are introduced (a card that converts X → grain before Bake Bread changes the dominance argument for sow-before-bake on Grain Utilization). Putting priors in a wrapper keeps the engine an honest source of all mechanically-legal actions while letting agents opt into narrower action spaces.

**Three kinds of priors live in the wrapper:**
- **Sub-action ordering** (rooms-before-stables, plow-before-sow, sow-before-bake) — implemented at `ChooseSubAction`-level filters that drop dominated branches.
- **Cell priorities** (stables / rooms / plow priority lists, first-pasture cells) — implemented at `Commit*`-level filters that keep the highest-priority legal cell from a list. The list defines both *which cells* are allowed AND *in what order* to fill them.
- **Hard caps and value filters** (5-room cap, min-begging at `CommitConvert`) — implemented at the appropriate pending type.

**The always-≥1 invariant.** Every filter routes through `_safe_narrow(filtered, fallback)`: if narrowing would empty the action set, the filter is skipped and the original options stand. This guarantees the wrapper never strands the engine — any state with ≥1 legal action under `legal_actions` has ≥1 legal action under `restricted_legal_actions`.

**Agent wiring.** Agents (`RandomAgent`, `HeuristicAgent`, all heuristic subclasses) accept a `legal_actions_fn` kwarg that defaults to the engine's unrestricted `legal_actions`. Passing `restricted_legal_actions` swaps in the pruned variant uniformly across the agent's top-level pick, singleton-skip, and rollout. The training pipeline (`scripts/tune_heuristic.py`, `scripts/run_iterative_v3.py`) and the browser-UI driver (`play_web.py`) all carry a `--restricted` / `--no-restricted` flag (default ON). AI seats in every interactive and training context use the wrapper by default, so the agent the user plays against in the browser is the same one CMA-ES is optimizing.

**Not in scope:** the wrapper is at the *agent* layer, not the engine. `legal_actions(state)` continues to enumerate every mechanically-legal action regardless. Tests, and any consumer that wants the full action space, get it unchanged.

**The strict variant for MCTS.** `agricola/agents/restricted.py` also exports `strict_restricted_legal_actions(state)` — a sibling wrapper that layers four additional MCTS-specific filters on top of `restricted_legal_actions`: Cultivation sow-max (collapse to the (grain, veg) commit maximizing grain+veg, ties favoring more grain), Grain-Utilization veggie auto-max (require `veg_sown == min(veggies, empty_fields − grain_sown)` for each surviving commit so the agent's choice space collapses to grain only), 9 hand-curated Fencing patterns keyed on `(existing pastures, wood count)` that collapse the legal pasture-build set to specific openers and extensions, and a harvest-feed cap (when `PendingHarvestFeed` enumerates > 7 `CommitConvert` options, keep the top-5 by `evaluate_hubris_v3` ranking plus 2 random samples; crafts always kept). MCTS uses the strict variant via the `make_strict_restricted_legal_actions(*, config, rng)` factory so the harvest-feed cap's randomness is deterministic per `MCTSSearch` instance. The heuristic agents and the web UI use the *regular* `restricted_legal_actions` — strict is reserved for tree-search consumers where the smaller branching factor pays off more than the lost expressivity. See `MCTS_DESIGN.md` §7 for the spec and `agricola/agents/mcts.py` for the consumer.

See `CHANGES.md` Change 11 for the regular-wrapper design rationale, the 1000-game V3_T1 paired-match validation (no win-rate effect at 1000 games), and the seat-asymmetry open question. See `V3_TRAINING_PIPELINE.md` §11 for the operational interaction with V3 tuning.

---

## Code Conventions

Syntactic and style patterns followed across the codebase. Architectural conventions — frozen-dataclass rules, the player-parameter convention, function-name prefix taxonomy, pending provenance metadata, sub-action cost handling — live in "Key Design Principles" and "Additional Design Principles" above. This section covers smaller-grained patterns about how code is *written*.

### Dataclass field ordering

In any frozen dataclass that mixes `ClassVar` and instance fields (e.g., the pending dataclasses with `PENDING_ID` and `TRIGGER_EVENT`), place ClassVar declarations first, instance fields after. `ClassVar` declarations are class-level identifiers / tags, not `__init__` parameters; they belong with class metadata, not with per-instance state.

### Action constructor calls — keyword form

Every action-type instantiation uses keyword arguments:

- `PlaceWorker(space="forest")` ✓ not `PlaceWorker("forest")`
- `ChooseSubAction(name="sow")` ✓ not `ChooseSubAction("sow")`
- `FireTrigger(card_id="potter_ceramics")` ✓
- `CommitSow(grain=1, veg=0)` ✓
- `CommitBuildMajor(major_idx=5, return_fireplace_idx=None)` ✓

Applies uniformly across single-field and multi-field action classes. Robust to dataclass field changes (a new defaulted field added later would silently break positional callers but not keyword callers).

### Per-pending enumerator signatures

Enumerators in `legality.py` take `(state, pending: PendingX) -> list[Action]`. The dispatcher (`_enumerate_pending`) passes `pending` explicitly; use `pending.X` directly, don't re-read `state.pending_stack[-1]`. Benefits: testability without setting up a stack, type narrowing to `PendingX`-specific fields, no redundant lookups.

### Effect function signatures

Sub-action effect functions in `resolution.py` take `(state, player_idx, commit: CommitX) -> GameState`. `player_idx` is explicit — do not derive from `state.current_player`, since the active player may differ from the commit's owner for out-of-turn trigger frames. Effect functions MAY read `state.pending_stack[-1]` to access their own pending frame (the dispatcher guarantees it is still on top during effect execution).

### Resource arithmetic

For pure resource subtraction, use `__sub__` (e.g., `p.resources - cost`). For mixed subtract-and-add in one operation, keep a single `Resources` literal with negative components (e.g., `p.resources + Resources(grain=-commit.grain, food=rate * commit.grain)`). Splitting a mixed operation into `(p.resources + Resources(food=...)) - Resources(grain=...)` adds operands without clarity gain. `__sub__` is reserved for pure-subtraction sites where it is strictly cleaner.

### Use `fast_replace`, not `dataclasses.replace`, in production code

All state-mutation sites in `agricola/` use `fast_replace(obj, **changes)` from `agricola.replace` rather than the stdlib `dataclasses.replace(obj, **changes)`. It's a drop-in faster equivalent (~20% per-call speedup, microbenched) with the same signature. See CHANGES.md Change 9 for the rationale and `agricola/replace.py` for the implementation.

Test code (`tests/`) continues to use `dataclasses.replace` — test setup is not a hot path, and stdlib `replace` is the reference implementation used by the equivalence tests in `tests/test_replace.py`.

### `replace_top` call form

Prefer the one-line form when the inner `fast_replace` fits on a single line (e.g., `state = replace_top(state, fast_replace(top, sow_chosen=True))`). Use a named variable when the replace would exceed comfortable line length or has many fields:

```python
new_top = fast_replace(
    top, triggers_resolved=top.triggers_resolved | {action.card_id},
)
return replace_top(state, new_top)
```

### Variable naming for replaced `PlayerState`

When you bind the result of `fast_replace(p, ...)` to a variable, name it `new_player` (not `new_p` or `np`). The replaced player flows into `_update_player(state, ap, new_player)`.

### Choose-time parent-flag setting

Every `_choose_subaction_*` handler sets the parent pending's `<action>_chosen` field to `True` **before** pushing the sub-action pending. The commit dispatcher (`_apply_commit_subaction`) does NOT set the flag; its sole job is assert, effect, and pop (conditionally, per `auto_pop`). The choose-time setting keeps flag management adjacent to the push that creates the sub-action, making each parent's chosen-tracking visible in one function.

### `actions: list[Action] = []`

Always type the actions list inside enumerators (`actions: list[Action] = []`, not `actions: list = []`). Typed lists catch accidental `actions.append(some_pending)` at type-check time.

### Variable binding at the top of handlers

At the top of any handler that reads from `state`, bind locals once (`ap = state.current_player; p = state.players[ap]`). Subsequent code reads from `ap` and `p`, not from `state.current_player` or `state.players[X]` repeatedly. For effect functions, the equivalent local is `p = state.players[player_idx]`.

### `_update_player` / `_update_space` helpers preferred

When modifying state from resolution code, prefer `_update_player(state, player_idx, new_player)` and `_update_space(state, space_id, **kwargs)` over constructing the full state replacement manually. Card modules (which can't easily import these helpers from `resolution.py` due to module ordering) construct the players tuple themselves; this is the accepted exception.

---

## Engine and Turn Resolution Architecture

This section describes the engine's transition model, the pending-decision stack that supports multi-action turns, and the card-implementation status. The full design and pseudocode are in **`task_files/TASK_5.md`**; what follows is the conceptual summary every session should internalize.

### The engine: `step`, `legal_actions`, `_advance_until_decision`

**`step(state, action) -> GameState`** is the engine's only transition function. It is a pure function: takes a state and an action, returns a new state. It does not loop, does not query an agent, does not drive a game. The loop that drives a game lives outside the engine (the standard call pattern is `actions = legal_actions(state); action = pick(actions); state = step(state, action)`, written into each caller).

**`legal_actions(state) -> list[Action]`** is the engine's only legality entry point. It dispatches on stack state: empty stack returns the legal worker placements via the existing `legal_placements`; non-empty stack returns the top pending frame's legal sub-actions via a per-pending enumerator.

**`_advance_until_decision(state)`** is an internal helper called at the end of every `step`. It walks *system* transitions — phase changes (WORK → RETURN_HOME → PREPARATION → WORK), terminal-phase detection — until the state is at a real agent decision point or game-over. It does NOT advance the current player and does NOT auto-resolve agent decisions.

Five design philosophies govern the engine:

- **`step` does not verify legality.** Callers are responsible for ensuring `action in legal_actions(state)` (typically via an explicit `assert` in the agent loop). Reason: single source of truth for legality; no double work between caller and `step`.
- **`step` does not auto-resolve singleton player decisions.** Even when `len(legal_actions(state)) == 1`, the agent loop is free to skip the NN prompt, but the singleton action still appears as an observed `step` boundary. Reason: trace consistency for MCTS, replay, and debugging.
- **Player alternation lives in `step`, not in `_advance_until_decision`.** Reason: alternation requires knowing "an action was just applied," which only `step` has access to. `_advance_until_decision` is state-only and can't distinguish "round just started" from "placement just finished" — both can present as `phase=WORK, stack=()`.
- **The engine exports only `step` + `legal_actions`.** No `play_round`, no `play_game`, no MCTS driver. Reason: those are trivial compositions of `step` and depend on the caller (random rollout vs. MCTS vs. NN-with-batching vs. human); premature high-level helpers lock callers in.
- **`_advance_until_decision` is state-driven, not history-driven, and idempotent.** Any state returned by `step` is stable: re-running `_advance_until_decision` on it produces the same state. This is a useful invariant for tests.

For the full implementation including dispatch tables, phase resolvers, and the engine module layout, see **`task_files/TASK_5.md`**.

### The pending-decision stack

Many worker placements are *non-atomic*: a single placement initiates a chain of sub-decisions before the player's turn ends. Cards add even more sub-decisions via triggers ("before X, you may do Y"). The engine pauses mid-action and resumes — driven entirely by agent choices, not by the engine itself.

**Structure.** `GameState.pending_stack: tuple[PendingDecision, ...]`, bottom-to-top; the top is `pending_stack[-1]`. Each frame is a frozen dataclass typed-tagged by sub-action shape: `PendingGrainUtilization`, `PendingSow`, `PendingBakeBread`, etc. `PendingDecision` is a `Union` alias over those dataclasses. The stack is a tuple (immutable, hashable, idiomatic Python for a small immutable sequence).

**Pending provenance metadata.** Every pending class carries two pieces of identity:

- `initiated_by_id: str` — mandatory instance field. Identifies the entity or event that pushed this frame onto the stack.
- `PENDING_ID: ClassVar[str]` — class attribute. Identifies the kind of pending (the flow or event it represents).

Three shapes of pending class, each with a corresponding `PENDING_ID` style:

| Pending class | `PENDING_ID` |
|---|---|
| `PendingGrainUtilization` (space parent) | `"grain_utilization"` |
| `PendingBakeBread` (generic sub-action) | `"bake_bread"` |
| `PendingCardName` (card-specific, template) | `"<card_id>"` |

`PendingCardName` is a stand-in for the shape future card-specific pendings will take when a card is complex enough to need its own dataclass: the class name is `Pending<CardName>` in PascalCase, the `PENDING_ID` is the card's id in snake_case (matching the card's id elsewhere in the codebase). No `Pending*` of this shape exists today — Potter Ceramics is a parameter-free trigger and doesn't push its own pending.

Three categories of value for `initiated_by_id`, using a namespaced prefix scheme so the two cross-cutting namespaces (spaces and cards) cannot collide:

| Pending pushed by | `initiated_by_id` value | Example |
|---|---|---|
| `ChooseSubAction` at a parent pending | parent's `PENDING_ID` | `PendingSow.initiated_by_id = "grain_utilization"` |
| `PlaceWorker` (top-level pending) | `"space:<space_id>"` | `PendingGrainUtilization.initiated_by_id = "space:grain_utilization"` |
| A phase resolver (currently the harvest sub-phases) | `"phase:<phase_id>"` | `PendingHarvestFeed.initiated_by_id = "phase:harvest_feed"` |
| A card trigger's effect | `"card:<card_id>"` | `PendingPlow.initiated_by_id = "card:swing_plow"` |

The `"space:"`, `"phase:"`, and `"card:"` prefixes make the namespaces disjoint by construction — no reserved-string carve-out is needed. Sub-action pendings pushed by `ChooseSubAction` use the parent's `PENDING_ID` directly (no prefix).

The generic commit dispatcher (`_apply_commit_subaction` in `engine.py`) asserts that the expected pending type is on top, applies the effect function, and conditionally pops (per `auto_pop`). It does not touch parent state — parent `*_chosen` flags are set earlier by the `_choose_subaction_*` handler that pushed the sub-action pending. See "Code Conventions" → "Choose-time parent-flag setting".

When a pending hosts card trigger events, the event names follow the convention `"before_<PENDING_ID>"` and `"after_<PENDING_ID>"`. So `PendingBakeBread.TRIGGER_EVENT = "before_bake_bread"` is the canonical form.

**The decider rule.** Whose decision is awaited right now:

- Empty stack → `state.current_player` is the decider.
- Non-empty stack → `pending_stack[-1].player_idx` is the decider.

`state.current_player` records "whose worker placement is currently being resolved." A pending frame's `player_idx` records "whose decision this frame is for." They are usually the same. They diverge when an out-of-turn trigger pushes a frame whose `player_idx` is the opponent — that's how the architecture expresses opponent decisions during the active player's resolution, without special-casing.

**Lifecycle of a non-atomic turn.** The stack evolves predictably:

- `PlaceWorker(non_atomic_space)` pushes the space's pending.
- `ChooseSubAction("category")` writes `<category>_chosen=True` on the parent pending AND pushes a category pending on top (both in the same handler).
- `CommitX(...)` pops the category pending. The parent flag was set earlier, at choose-time. *(Exception for multi-shot pendings — `PendingBuildStables`, `PendingBuildRooms`: `CommitX(...)` increments `num_built` and leaves the pending on top via `replace_top`; `Stop` is the explicit exit and pops. See "Multi-shot sub-action pendings" below.)*
- `FireTrigger(card_id)` modifies the top frame's `triggers_resolved` set; no push or pop.
- `Stop` pops the top frame.
- Card-triggered sub-decisions push their pending **on top of** the pending whose event they fire from (never between existing frames). This invariant guarantees that when a sub-action commit pops its pending, the new top is always the parent — no stack walking required.

Ten design philosophies govern the stack:

- **One pending object per sub-action category.** No separate "intent" and "execution" frames. Reason: collapses an unnecessary dimension; the presence of a category pending IS the recording of intent.
- **Simple triggers don't push their own pending.** Fire decisions for parameter-free triggers are actions at the parent pending's level (e.g., `FireTrigger("potter_ceramics")` at `PendingBakeBread`). A trigger gets its own pending only if it requires parameterized sub-decisions.
- **There is no `SkipTrigger` action.** Declining a trigger is implicit: the player just doesn't fire it. Picking a commit (or firing another trigger) implicitly skips. Reason: SkipTrigger adds no expressive power — committing achieves the same — and removing it eliminates a thorny one-ply-lookahead helper.
- **Every pending carries `player_idx`.** Always set, never derived. Reason: enables out-of-turn trigger frames without retrofitting.
- **Non-atomic spaces push a parent pending.** Every non-atomic action space, when used via `PlaceWorker`, pushes a parent pending — even spaces that offer only one sub-action. The parent serves two purposes: (1) tracking which sub-action categories have been chosen (via `*_chosen` boolean fields, used by Stop-legality), and (2) hosting the trigger event for cards that attach to that space (via `TRIGGER_EVENT` / `triggers_resolved`). Both purposes are forward-compat for the card system.

- **`PlaceWorker` and each `ChooseSubAction` push exactly one pending frame.** This invariant ensures card triggers fire cleanly between frames (each trigger event corresponds to a specific stack-state, not an ambiguous "somewhere mid-push").

- **Parent `*_chosen` flags are set at choose-time, not at commit-time.** Each `_choose_subaction_*` handler does `replace_top(state, fast_replace(parent, <action>_chosen=True))` before pushing the sub-action pending. The commit dispatcher (`_apply_commit_subaction`) is responsible only for assert + effect + conditional pop; it does not touch parent state. See "Code Conventions" → "Choose-time parent-flag setting" for rationale.
- **Commit sub-actions inherit from `CommitSubAction`.** All `Commit*` action types (`CommitSow`, `CommitBake`, future `CommitPlow`, …) inherit from a frozen-dataclass base `CommitSubAction`. The engine dispatches them uniformly through `_apply_commit_subaction` and the `COMMIT_SUBACTION_HANDLERS` metadata table. Adding a new sub-action type does not require editing `_apply_action`.
- **`TRIGGER_EVENT` is a `ClassVar` on pending types that fire triggers.** Read by `legal_actions` enumerators to filter the trigger registry. Reason: type-derived event identity, no field bloat.
- **`triggers_resolved` is scoped to a pending frame's lifetime.** It records which triggers have fired during this specific instance of the trigger event. Next instance (e.g., next Bake Bread action, next round's PREPARATION) creates a fresh pending with an empty `triggers_resolved`. **Do not put `triggers_resolved`-like state on `PlayerState`** — that would make a trigger fire once per game instead of once per event instance.

**Per-card budgets that DO span multiple events** (once-per-round, once-per-game, once-per-harvest) live on `PlayerState` or `BoardState`, separate from pending frames. The stack is a stack of *active* decisions, not a per-game scoreboard.

**The architecture is built with cards in mind.** Several pieces accommodate future card patterns without retrofitting:

- Out-of-turn triggers via `player_idx` on each frame.
- Triggers with sub-decisions via arbitrary stack depth.
- Card-aware legality via `*_EXTENSIONS` registries on `_can_*` predicates (e.g., `BAKE_BREAD_ELIGIBILITY_EXTENSIONS`).
- Once-per-action trigger budgets via the `triggers_resolved` field on relevant pendings — most pending types will eventually carry one.
- Pending provenance via `initiated_by_id` + `PENDING_ID`, used for debugging breadcrumbs and for cards to choose, at push time, whether (and which) parent to flag. The commit dispatcher itself no longer touches parent state — flag-setting moved to the `_choose_subaction_*` handlers — so card-pushed cross-cutting sub-actions land harmlessly on unrelated parents by virtue of the pushing card explicitly deciding what to flag.
- Atomic spaces will follow the "push a parent pending" pattern when card triggers begin attaching to them — the pending hosts the trigger event(s) for that space, with no `*_done` fields. The `ATOMIC_HANDLERS` / `NONATOMIC_HANDLERS` split will collapse at that point.
- Two trigger events per space (`"before_<space>"` and `"after_<space>"`), enforcing the rules-faithful timing of card triggers (e.g., Cottager fires before Day Laborer's food is received; Hardware Store fires after).

For worked examples (a Grain Utilization sow + bake walk-through with and without Potter Ceramics' trigger) and the full implementation breakdown, see **`task_files/TASK_5.md`**.

### Fencing and Build Fences

Fencing is the most complex action in Agricola. The farmyard has ~38 fence-edge primitives (4×5 horizontal + 3×6 vertical edges), and the legal subset of final fence configurations is plausibly in the hundreds to low thousands per state. The total space of fencing actions is enormous, and enumerating all legal final configurations — both all possible ones in principle and all legal ones in a given state — is non-trivial. Spatial outcomes interact with future room/field/stable placement so single-axis Pareto pruning is unsafe. AI training needs a stable action representation here — changing it later invalidates trained models.

**Build Fences as a primitive sub-action.** Build Fences is a primitive sub-action (`PendingBuildFences`) called by the Fencing and Farm Redevelopment action spaces, and by some card effects.

Rather than choosing one final fence configuration from the enormous full-action space in a single decision, the player makes a sequence of smaller "build one pasture" commits (`CommitBuildPasture`). Each commit names one pasture cell-set; the engine applies the implied new fences and debits the cost; the player either commits another pasture or stops. This is the same multi-shot pattern used by Farm Expansion's room and stable builds.

Building *pastures* rather than individual *fences* shrinks the action space further. A 1×1 pasture at `(0, 3)` might require 4 new fence edges, or 3, or fewer depending on which adjacent fences already exist — and across many different fence-arrangements that all yield the same pasture. All of those collapse to one commit naming the cell-set `{(0, 3)}`. The agent commits semantic intent (which cells the pasture covers); the engine derives the fence delta.

The **builds-before-subdivisions ordering rule** keeps the search tree from inflating across commit-order permutations: once any subdivision commit lands (`subdivision_started=True` on `PendingBuildFences`), new-pasture commits drop out of `legal_actions` for the remainder of the action. See task_files/TASK_6.md Part 2.3 for the reachability argument behind this direction rather than the reverse.

**How `legal_actions` enumerates legal pasture commits.** Per call, the enumerator converts the player's farmyard into a bundle of bitmaps (current horizontal/vertical fences, enclosable cells, existing-pasture cells, wood and supply scalars). It then iterates through the universe of candidate pastures and checks each candidate for legality — meaning the candidate is unenclosed and a legal addition to the existing farmyard, OR enclosed within an existing pasture and a legal subdivision. The per-candidate check is a sequence of cheap bitwise ops against precomputed boundary and adjacency bitmaps stored on the universe entry.

**Cost handling.** Each commit's wood cost is computed at commit time as a pure function of `(farm state, commit cells)` by the shared helper `compute_new_fence_edges` in `fences.py`, and debited by `_execute_build_pasture`. The cost varies per commit because earlier commits may have placed fences that bound a later commit's pasture; see "Sub-action cost handling" → bucket 4.

**Two load-bearing implementation choices:**

- **Fixed list of legal pastures.** The eventual policy network's output head selects from a fixed enumerable list of actions per state; this works cleanly when the action space has a stable structure. We construct the universe of candidate pastures once at `fences.py` import, and per-state legality is a filter over that fixed list rather than an enumerate-from-scratch traversal at runtime. The policy head's output dimension is a stable property of the universe — one slot per pasture — and per-call legality cost stays predictable across MCTS rollouts.

- **Hand-curated RESTRICTED universe.** The runtime default is not the full 1518-entry universe of all rules-permissible pastures — it's `UNIVERSE_RESTRICTED`, a strategist-curated 109-entry subset that omits pastures never plausibly optimal (extremely small, pathologically-shaped, or obviously-wasteful configurations). Reducing the policy-head output dimension by ~14× speeds learning and shrinks MCTS branching without removing meaningful strategic options. The universes are layered (`RESTRICTED ⊆ EXTENDED ⊆ FAMILY ⊆ FULL`) so a restriction can be loosened across experiments — or globally swapped via the `active_universe(...)` context manager in `agricola.fence_universe` (or by reassigning the `ACTIVE_FENCE_UNIVERSE_*` constants directly) — without retraining the engine. Custom universes can be derived by filtering through `restrict_to(predicate, base=...)`.

Implementation lives in `agricola/fences.py` (universes + edge metadata + cost helper), `agricola/legality.py` (`_legal_fencing`, the three new enumerators, `_any_legal_pasture_commit`), and `agricola/resolution.py` (`_initiate_fencing`, `_choose_subaction_fencing`, `_execute_build_pasture`). Design rationale: **task_files/FENCE_IDEAS.md** (broader design space and alternatives), **task_files/TASK_6_pre.md** (universe construction), **task_files/TASK_6.md** (this task).

### Harvest sub-phases

The harvest fires at the end of rounds 4, 7, 9, 11, 13, 14 (`HARVEST_ROUNDS`). It is the only multi-phase span outside the WORK phase where players make strategic decisions. `_resolve_return_home` routes to `Phase.HARVEST_FIELD` instead of `Phase.PREPARATION` on harvest rounds.

**FIELD → FEED → BREED progression.**

- **`HARVEST_FIELD`** is mechanical — `_resolve_harvest_field` takes 1 crop from each planted field, resets `PlayerState.harvest_conversions_used` on both players (the once-per-harvest budget), pushes one `PendingHarvestFeed` per player via `_initiate_harvest_feed`, and transitions to `HARVEST_FEED`. No agent decisions.

- **`HARVEST_FEED`** is the strategic core. Each adult requires 2 food; newborns from the just-ended round require 1. Food payment is **deferred to the final `CommitConvert`** — `_initiate_harvest_feed` pushes the per-player pendings without touching `p.resources.food`. The player then opts into any subset of owned once-per-harvest craft conversions (`CommitHarvestConversion` for joinery / pottery / basketmaker — and future card-registered entries; `use=True` pays the input cost and adds the full `food_out` to the player's supply) and commits one final `CommitConvert` whose `(grain, veg, sheep, boar, cattle)` consumed amounts are picked from the Pareto-optimal frontier returned by `harvest_feed_frontier`. `_execute_convert` is the sole payment site: it adds `food_produced` to supply, pays `min(need, supply + food_produced)` to feeding (the "Cannot withhold food tokens" rule is enforced structurally by this formula — the player has no knob to keep food while begging), leaves surplus in supply, and assigns the shortfall as begging markers (assigned in `_execute_convert`, not by `Stop`, preserving the Stop-only-pops convention). `Stop` pops the frame.

  **Why deferred.** Pre-debiting food at feed-start would let the engine eat food the player might later want to spend on a card chain that ends in more food — e.g. an "exchange food for a building resource" card feeding into Pottery (1 clay → 2 food) would be blocked because the food required to start the chain was already taken. In the Family game without cards both models produce identical outcomes; the deferred model preserves the option for future card support without retrofitting. `food_owed` is a derived value (`max(0, need - p.resources.food)`), recomputed on each `legal_actions` call from the live player state per the "Derived data, not cached data" Key Design Principle. Not stored on `PendingHarvestFeed`.

- **`HARVEST_BREED`** uses the existing `breeding_frontier` helper. `_initiate_harvest_breed` pushes one `PendingHarvestBreed` per player; the agent commits a single `CommitBreed(sheep, boar, cattle)` chosen from the frontier (which already encodes pre-breed eating + per-type breed rules). The food formula owned by `breeding_frontier` is the single source of truth; `_execute_breed` looks up the chosen point's `food_gained` rather than recomputing. `Stop` pops the frame.

**Gratuitous Stop for every player in every sub-phase.** Each player gets a pending frame in HARVEST_FEED and HARVEST_BREED even when no strategic decision exists (no convertibles, no breeding animals). Three reasons: matches the engine's "no auto-resolved singleton player decisions" principle (trace uniformity for MCTS, replay, debugging); provides stable trigger-event hosts for future cards (e.g. Conjurer at breeding); and symmetric with the parent-pending pattern atomic spaces will eventually adopt.

**Pareto frontier as the legality filter.** `legal_actions` returns only Pareto-optimal payment configurations from `harvest_feed_frontier`, not every (grain, veg, sheep, boar, cattle) tuple. This collapses the action space from O(thousands) to O(tens) while preserving every strategically meaningful end-state. Pareto dimensions are upstream goods (and -begging in `harvest_feed_frontier`); food surplus is excluded per the "Preserving optionality" Key Design Principle.

**Dual-meaning phase pattern.** Both `HARVEST_FEED` and `HARVEST_BREED` carry two meanings depending on stack state: stack non-empty = a player is deciding; stack empty = phase-exit signal. The discriminator works because the only way to reach phase=HARVEST_X with empty stack is for the entry-resolver to have pushed pendings (now drained by Stop). `_advance_until_decision` checks the stack inside each phase branch and either returns (non-empty) or transitions (empty → push next phase's pendings, or BEFORE_SCORING after round 14).

**Implementation lives in** `agricola/engine.py` (`_resolve_harvest_field`, `_initiate_harvest_feed`, `_initiate_harvest_breed`, plus the three harvest branches in `_advance_until_decision`), `agricola/resolution.py` (`_execute_harvest_conversion`, `_execute_convert`, `_execute_breed`), `agricola/legality.py` (`_enumerate_pending_harvest_feed`, `_enumerate_pending_harvest_breed`), `agricola/helpers.py` (the 4-tuple `cooking_rates` + `food_payment_frontier` + `harvest_feed_frontier`), and `agricola/cards/harvest_conversions.py` (the `HARVEST_CONVERSIONS` registry). See **task_files/TASK_7.md** for the full design.

### Card implementation status

The full card system is **not implemented**. Task 5 introduces one card — **Potter Ceramics** (a minor improvement: "Each time before you take a Bake Bread action, you can exchange exactly 1 clay for 1 grain") — solely to exercise and validate the pending-stack's trigger machinery end-to-end. Without a concrete card, the trigger architecture would be untested scaffolding.

Card infrastructure pieces introduced by Task 5:

- `agricola/cards/` subpackage.
- `agricola/cards/triggers.py` with two registries: `TRIGGERS` (event-keyed, used by `legal_actions` enumerators to find eligible triggers at the current event) and `CARDS` (card-id-keyed, used by `_apply_fire_trigger` for direct lookup). Both populated at import time via the `register(event, card_id, eligibility_fn, apply_fn)` function.
- `agricola/cards/potter_ceramics.py` — the one card, registered against `"before_bake_bread"` and against the `BAKE_BREAD_ELIGIBILITY_EXTENSIONS` registry (so `_can_bake_bread` returns True for a Potter Ceramics owner with clay even at 0 grain).
- `PlayerState.minor_improvements: frozenset[str]` records the cards a player has played. `PlayerState.occupations: frozenset[str]` is added in parallel for symmetry (no occupation cards implemented yet).

Task 7 extended this with:

- `agricola/cards/harvest_conversions.py` — a parallel `HARVEST_CONVERSIONS` registry hosting the three once-per-harvest craft majors (joinery / pottery / basketmaker) and exposing `register_harvest_conversion(spec)` for future card extensions. Imported from `agricola.cards.__init__` so entries register at package load. Each entry is a `HarvestConversionSpec(conversion_id, input_cost, food_out, is_owned_fn, side_effect_fn)`; `side_effect_fn` accommodates effects like a hypothetical future Stone Sculptor's "+1 point" alongside the food yield.
- `PlayerState.harvest_conversions_used: frozenset[str]` — the once-per-harvest "decided" set (records both `use=True` and `use=False`). Cleared in `_resolve_harvest_field`.
- `PendingHarvestFeed`'s shape — trigger-style opt-in sub-decisions (the three craft majors via `CommitHarvestConversion`) followed by one main `CommitConvert` — is the same shape future card triggers will use across most pendings: opportunities to take `Commit*` actions for triggering effects, then the main commit. Once the full card system lands, almost every pending will host trigger-style opt-in sub-decisions in this shape.

The full card system (the other ~470 cards in the Family + full game) is a separate future task. Several known design questions are deferred to that task:

- **Compound card interactions.** The current extension-registry pattern handles single-card eligibility broadening (Potter Ceramics) cleanly, but does not handle cases where one card's effect enables another card's eligibility (canonical example: Pan Baker + Potter Ceramics — Pan Baker's on-placement clay grant enables Potter Ceramics' clay-to-grain conversion, which together let the player bake from a 0-clay-0-grain state). Resolving this requires speculative-legality machinery (apply on-placement card effects to a hypothetical state, then check sub-action predicates against the hypothetical). The trigger registry already supports arbitrary event names; the missing piece is the legality-side speculative-application. See **`task_files/TASK_5.md`**'s "Known limitation: compound card interactions" for the detailed framing.

- **Atomic-space trigger hosting: phase tracking.** When atomic spaces convert to push trigger-host pendings (so cards like Cottager and Hardware Store can attach to Day Laborer, etc.), the pending needs at least one piece of state to indicate "primary effect applied yet?" Two modeling options to weigh: a uniform `primary_effect_applied: bool` on every space pending (simplest dispatcher), or a `phase: Literal["before", "after"]` field (extensible to a hypothetical third trigger point).

- **Atomic-space trigger hosting: phase-transition mechanism.** Something has to flip the phase bit AND apply the primary effect between the before and after trigger phases. Three candidate mechanisms, none locked in: (1) an explicit transition action (e.g., `ApplyPrimaryEffect()` / `Proceed()`) that's legal during the before-phase — keeps `Stop` unambiguous; (2) overloading `Stop` so that `Stop` during the before-phase advances the phase and `Stop` during the after-phase pops the pending — fewer action types but context-dependent semantics; (3) nested pendings — push a `PendingBefore<Space>` on top of `Pending<Space>`, with the inner pending hosting before-triggers and popping on Stop to trigger the primary effect via a hook on `_apply_stop`. Decision deferred.

- **Trigger events on harvest pendings.** `PendingHarvestFeed` and `PendingHarvestBreed` deliberately omit `triggers_resolved` / `TRIGGER_EVENT` fields today (Task 5D precedent — added per-pending when the first card needs them). Natural future events: `before_harvest_feed`, `after_harvest_feed`, `before_harvest_breed`, `after_harvest_breed`.

---

## Current Status

All 636 tests pass. The following pieces are complete:

| Component | Status | Task file(s) |
|---|---|---|
| State dataclasses + setup | Complete | `task_files/ARCHITECTURE.md` |
| Resource types (`Resources`, `Animals`) | Complete | `CHANGES.md` Change 1 |
| `Resources.__sub__` operator | Complete | `CHANGES.md` Change 5 |
| Helper functions (pastures, animal accommodation, pareto frontiers, cooking rates) | Complete | `task_files/TASK_2.md`, `task_files/TASK_3.md` |
| Scoring and tiebreaker | Complete | `task_files/TASK_2.md` |
| Action type (`PlaceWorker`) | Complete | `task_files/TASK_4a_i.md` |
| Atomic-space legality (12 spaces) | Complete | `task_files/TASK_4a_i.md` |
| Atomic-space resolution (12 spaces) | Complete | `task_files/TASK_4a_ii.md` |
| Pasture cache on `Farmyard` (`agricola/pasture.py`) | Complete | `CHANGES.md` Change 2, `CHANGES.md` Change 3, `task_files/TASK_4a_iii.md` |
| Non-atomic legality (all 12 non-atomic spaces) | Complete | — |
| Engine: `step` + `_advance_until_decision` + pending stack | Complete | `task_files/TASK_5.md` |
| Round transitions (rounds 1 → 14, all 6 harvests resolved) | Complete | `task_files/TASK_5.md`, `task_files/TASK_7.md` |
| `Phase.PREPARATION` and `Phase.BEFORE_SCORING` | Complete | `task_files/TASK_5.md` |
| Action union (`ChooseSubAction`, `CommitSow`, `CommitBake`, `FireTrigger`, `Stop`) | Complete | `task_files/TASK_5.md` |
| Grain Utilization non-atomic resolution | Complete | `task_files/TASK_5.md` |
| Card framework (`cards/__init__.py`, `cards/triggers.py`) | Complete | `task_files/TASK_5.md` |
| Potter Ceramics card (the one card in scope) | Complete | `task_files/TASK_5.md` |
| `legal_actions` top-level dispatch | Complete | `task_files/TASK_5.md` |
| Test scaffolding (`factories.py`, `test_utils.py`) | Complete | `task_files/TASK_5.md` |
| `CommitSubAction` hierarchy + generic commit dispatch | Complete | `task_files/TASK_5B_DISPATCH_CLEANUP.md`, `CHANGES.md` Change 4 |
| Pending provenance metadata (`initiated_by_id`, `PENDING_ID`) | Complete | `task_files/TASK_5B_DISPATCH_CLEANUP.md`, `CHANGES.md` Change 4 |
| Dispatch table relocation (`NONATOMIC_HANDLERS` / `CHOOSE_SUBACTION_HANDLERS` in `resolution.py`; stack helpers in `pending.py`) | Complete | `task_files/TASK_5B_DISPATCH_CLEANUP.md` |
| Farmland non-atomic resolution | Complete | `task_files/TASK_5C.md` |
| Cultivation non-atomic resolution | Complete | `task_files/TASK_5C.md` |
| Side Job non-atomic resolution | Complete | `task_files/TASK_5C.md` |
| Sheep / Pig / Cattle Market non-atomic resolution | Complete | `task_files/TASK_5C.md` |
| Major Improvement non-atomic resolution (incl. Cooking Hearth payment options, Clay/Stone Oven free Bake) | Complete | `task_files/TASK_5C.md` |
| House Redevelopment non-atomic resolution | Complete | `task_files/TASK_5C.md` |
| Choose-time flag-setting convention (`*_chosen` fields) | Complete | `task_files/TASK_5C.md`, `CHANGES.md` Change 5 |
| Provenance prefix scheme (`"space:<id>"` / `"card:<id>"`) | Complete | `task_files/TASK_5C.md`, `CHANGES.md` Change 5 |
| Major improvement costs and baking specs in `constants.py` | Complete | `task_files/TASK_5C.md` |
| Bake Bread support for Clay Oven and Stone Oven (greedy-by-rate over all owned baking improvements) | Complete | `task_files/TASK_5C.md` |
| `auto_pop` flag on `COMMIT_SUBACTION_HANDLERS` + `CommitBuildMajor` absorbed into generic dispatcher | Complete | `task_files/TASK_5D.md`, `CHANGES.md` Change 6 |
| Multi-shot sub-action pending pattern (`PendingBuildStables`, `PendingBuildRooms`) | Complete | `task_files/TASK_5D.md`, `CHANGES.md` Change 6 |
| Farm Expansion non-atomic resolution | Complete | `task_files/TASK_5D.md` |
| Side Job migrated to `PendingBuildStables`; `PendingBuildStable` (singular) retired | Complete | `task_files/TASK_5D.md` |
| `ROOM_COSTS` constant + `_can_afford(p, cost)` + predicate-enumerator deduplication (`_can_build_stable`, `_legal_room_cells`) | Complete | `task_files/TASK_5D.md`, `CHANGES.md` Change 6 |
| `_new_grid_with_cell` helper in `resolution.py` | Complete | `task_files/TASK_5D.md` |
| Pasture cache recompute on stable build (fixes latent Task 5C bug) | Complete | `task_files/TASK_5D.md`, `CHANGES.md` Change 6 |
| Fencing pasture-shape universe (`agricola/fences.py` — four layered universes, four filter primitives) | Complete | `task_files/TASK_6_pre.md` |
| Edge metadata on `agricola/fences.py` (`PastureCandidate`, parallel `*_ENTRIES`, `*_SMALLEST_ENTRIES`, `ENTRIES_BY_BM`, pack/apply helpers, `compute_new_fence_edges`) | Complete | `task_files/TASK_6.md` |
| 1×1-at-(0, 0) addition to RESTRICTED (108→109) and EXTENDED (192→193) universes | Complete | `task_files/TASK_6.md` |
| Build Fences sub-action (`PendingBuildFences`, `CommitBuildPasture`, `_execute_build_pasture`) — reusable across entry points | Complete | `task_files/TASK_6.md` |
| Builds-before-subdivisions ordering rule (`subdivision_started` on `PendingBuildFences`) | Complete | `task_files/TASK_6.md` |
| Fencing non-atomic resolution (`PendingFencing` + Build Fences entry point) | Complete | `task_files/TASK_6.md` |
| Farm Redevelopment non-atomic resolution (renovate-then-optional-Build-Fences) | Complete | `task_files/TASK_6.md` |
| Sub-action cost handling: 4th bucket (pure-function-of-state-and-commit) | Documented | `task_files/TASK_6.md` |
| Runtime active-universe selector (`ACTIVE_FENCE_UNIVERSE_*` constants + per-call kwargs) | Complete | `task_files/TASK_6.md` |
| Fence-universe restriction tooling (`agricola/fence_universe.py` — `active_universe(spec)` context manager, `restrict_to(predicate, base=...)` builder, `NAMED_UNIVERSES`, `current_universe()`) + call-time resolution of universe defaults in `_any_legal_pasture_commit` / `_enumerate_pending_build_fences` | Complete | `POSSIBLE_NEXT_STEPS.md` item D |
| `cooking_rates` 4-tuple `(sheep, boar, cattle, veg)` with veg raw-1:1 fallback | Complete | `task_files/TASK_7.md`, `CHANGES.md` Change 7 |
| `food_payment_frontier` and `harvest_feed_frontier` in `helpers.py` | Complete | `task_files/TASK_7.md`, `CHANGES.md` Change 7 |
| `HARVEST_CONVERSIONS` registry in `agricola/cards/harvest_conversions.py` | Complete | `task_files/TASK_7.md`, `CHANGES.md` Change 7 |
| `PlayerState.harvest_conversions_used: frozenset[str]` once-per-harvest budget | Complete | `task_files/TASK_7.md`, `CHANGES.md` Change 7 |
| `PendingHarvestFeed` / `PendingHarvestBreed` + `CommitHarvestConversion` / `CommitConvert` / `CommitBreed` | Complete | `task_files/TASK_7.md`, `CHANGES.md` Change 7 |
| Dual-meaning `HARVEST_FEED` / `HARVEST_BREED` phase pattern; `"phase:<id>"` provenance namespace | Complete | `task_files/TASK_7.md`, `CHANGES.md` Change 7 |
| Harvest sub-phases — `_resolve_harvest_field`, `_initiate_harvest_feed`, `_initiate_harvest_breed` in `engine.py` | Complete | `task_files/TASK_7.md`, `CHANGES.md` Change 7 |
| Rounds 5–14, all 6 harvests | Complete | `task_files/TASK_7.md`, `CHANGES.md` Change 7 |
| `BoardState.action_spaces` canonical-tuple refactor (`GameState` hashable) | Complete | `CHANGES.md` Change 8 |
| Engine performance pass: `fast_replace`, `legal_actions_cache()`, `__debug__` gate, round-end-reset guard | Complete | `CHANGES.md` Change 9, `PROFILING.md` |
| `agricola/agents/` package: `Agent` protocol, `HeuristicAgent` infrastructure, `RandomAgent`, `play_game` driver | Complete | `HEURISTIC_TUNING_PLAN.md`, `FILE_DESCRIPTIONS.md` |
| `SimpleHeuristic` (MVP) and `HubrisHeuristic` (full-spec) heuristic agents with `HeuristicConfig` (~50 coefficients), 1-turn lookahead, singleton-skip, softmax-with-temperature | Complete | `HEURISTIC_TUNING_PLAN.md` |
| Hubris V1 / V2 versioning (`HubrisHeuristicV1`, `HubrisHeuristicV2`); V2 uses `harvest_feed_frontier` for joint goods-or-food optimization but loses to V1 head-to-head (the "won't actually convert if game ends first" effect) | Complete | `HEURISTIC_TUNING_PLAN.md` |
| `play_heuristic_game.py` top-level driver (`random` / `simple` / `hubris` / `hubris_v1` / `hubris_v2` / `hubris_v3` matchups) | Complete | `FILE_DESCRIPTIONS.md` |
| `play_web.py` AI-vs-AI + per-seat agent picker (`--seats AGENT AGENT`); `/api/step_ai` for manual step-through; Enter-key advance; `--v3-config <json>` to load tuned V3 config | Complete | `FILE_DESCRIPTIONS.md` |
| **`CONFIG_V1_T2`** — round-2 tuned V1 config (58 params, +8.85 holdout vs V1 default, 90-1-9 record). Promoted to module-level constant; `hubris` seat alias in all drivers. | Complete | `V3_TRAINING_PIPELINE.md`, `tuned_configs/1779468329.json` |
| **`HubrisHeuristicV3` architecture** — `HeuristicConfigV3` (~250 params), `evaluate_hubris_v3`. Three combination styles (blend / additive / joint-alpha), three-component resource pattern, V1 carry-overs preserved. | Complete | `V3_DESIGN.md`, `CHANGES.md` Change 10 |
| **V3 category-tuning pipeline** — `scripts/tune_heuristic.py` (CMA-ES per-category, save/resume via pickle, x0 fallback) + `scripts/run_iterative_v3.py` (block-coordinate descent orchestrator across 4 V3 categories). | Complete | `V3_TRAINING_PIPELINE.md`, `CHANGES.md` Change 10 |
| **`tuned_configs/v3_best.json`** — pointer to the current V3 baseline. Currently `alphas_gen_7` (manually promoted; holdout vs t2 100-0-0 +15.32 margin at n=100). Beats prior champion `panel_gen16` in round-robin 38-2. Stable mirror at `tuned_configs/alphas_gen_7.json` so the data-gen ensemble's references survive future `v3_best.json` overwrites. Loaded by `play_web.py --v3-config` and `scripts/play_mcts_match.py --v3-config`. See V3_TRAINING_PIPELINE.md for the auto-update mechanism. | Complete | `V3_TRAINING_PIPELINE.md` |
| **V3 per-stage major-value refactor** — 8 majors × 6 stages = 48 new scalars on `HeuristicConfigV3`; `_hubris_major_value_v3` replaces V1's helper. Extra cooking implements = flat +1 each (drops `cooking_secondary_vp`). Well's per-stage value only (drops `well_food_per_future`). New `_hubris_pasture_location_bonus_v3` credits only c≥3 cells (vs V1's c≥2). Legacy fields kept for JSON backwards-compat. Not yet tuned. | Complete | `V3_DESIGN.md`, `V3_TRAINING_PIPELINE.md` §8 |
| **`restricted_legal_actions` wrapper** (`agricola/agents/restricted.py`) — pure wrapper over `legal_actions(state)` applying strategic priors: sub-action ordering (plow-before-sow / sow-before-bake / rooms-before-stables), cell priorities (stables / rooms / plow), first-pasture opener cells, 5-room cap, min-begging at `CommitConvert`. Never empties a non-empty action set. | Complete | `CHANGES.md` Change 11 |
| **`legal_actions_fn` parameter on agents** — `HeuristicAgent` / `RandomAgent` (and V1/V2/V3 subclasses) accept a `legal_actions_fn` kwarg threaded through top-level pick, singleton-skip, and rollout. Default = unrestricted. | Complete | `CHANGES.md` Change 11 |
| **Training pipeline `--restricted` flag (default ON)** — `scripts/tune_heuristic.py` and `scripts/run_iterative_v3.py` both gain `--restricted` / `--no-restricted` (default ON); `scripts/play_match.py` gains per-seat `--p0-restricted` / `--p1-restricted`. JSON output records `"restricted": bool`. | Complete | `V3_TRAINING_PIPELINE.md` §11, `CHANGES.md` Change 11 |
| **`lookahead="exhaustive"` mode on `HeuristicAgent`** — full sub-action subtree search with per-top-action leaf cap (default 1000) and greedy-descent fallback above the cap. Empirically WORSE than greedy 1-turn lookahead (margin −4.49 ± 1.05 over 800 games vs greedy at the current `v3_best`); kept as opt-in for experimentation but not the default. The negative finding indicates the heuristic's bottleneck is evaluator quality, not chain-expansion strategy — argues for MCTS over deeper deterministic search. | Complete (negative result) | `agricola/agents/base.py`; `V3_DESIGN.md` §8.9, `V3_TRAINING_PIPELINE.md` §8.3 |
| **Terminal-margin-value evaluator semantics** — all four evaluators (`evaluate_simple`, `evaluate_hubris_v1/v2/v3`) now return `own_score − opponent_score` at `Phase.BEFORE_SCORING` (was: just `own_score`). Implementation via shared `_terminal_margin_value(state, player_idx)` helper. Matches the game's actual payoff; late-round-14 decisions may shift when candidate actions affect opponent score differently. Tuning fitness unaffected. | Complete | `agricola/agents/heuristic.py`; `V3_DESIGN.md` §6 |
| **MCTS design spec** (`MCTS_DESIGN.md`) — comprehensive design for the upcoming MCTS phase. Vanilla UCT + FPU + DAG-with-transpositions + leaf-evaluation (no rollouts) + macro-enumeration for Fencing + strict-restriction wrapper + shared/separate-tree modes for self-play and head-to-head matches. Includes the new `strict_restricted_legal_actions` spec (Cultivation sow-max, Grain-Util veggie rule, fencing patterns, harvest-feed cap) + the `restricted_legal_actions` use=False filter. | Complete | `MCTS_DESIGN.md` |
| **`use=False` craft filter on `restricted_legal_actions`** (§7.0) — drops every `CommitHarvestConversion(use=False)` from the action set. Lives in the *regular* wrapper (not strict) because it's a correctness-preserving simplification (skip-the-craft is achievable via direct `CommitConvert`) that benefits all agents, not just MCTS. | Complete | `MCTS_DESIGN.md` §7.0, `agricola/agents/restricted.py` |
| **`strict_restricted_legal_actions` wrapper** (`agricola/agents/restricted.py`) — layers four MCTS-specific filters atop `restricted_legal_actions`: Cultivation sow-max (collapse to max grain+veg, ties favor grain), Grain-Util veggie auto-max (`veg_sown == min(veggies, empty_fields − grain_sown)`), 9 hand-curated Fencing patterns keyed on (existing pastures, wood count) — pasture-identity vs cell-set-union semantics distinguish rule 7 from rules 8/9, Harvest-feed cap (>7 commits → top-5 by `evaluate_hubris_v3` + 2 random; crafts always kept). Module-level callable uses `DEFAULT_CONFIG_V3` + seed-0 RNG; `make_strict_restricted_legal_actions(*, config, rng)` factory builds closures with injected config/RNG (MCTS uses this so the harvest-feed cap's randomness is deterministic per `MCTSSearch` instance). | Complete | `MCTS_DESIGN.md` §7, `agricola/agents/restricted.py` |
| **MCTS scaffolding** (`agricola/agents/mcts.py`) — `MCTSAgent`, `MCTSSearch`, `MCTSNode`, `MacroFencingAction`. Vanilla UCT + FPU (`parent_mean_q + c · √(ln(N_p+1))` for unvisited; standard UCB with sign-flip for visited), DAG with transposition table keyed on `GameState.__hash__`, path-only backprop along the SELECT path (NOT via `node.parents`), leaf evaluation via `evaluate_hubris_v3` margin (own − opp; raw score margin at `BEFORE_SCORING`), macro-fencing for both trigger points (`PlaceWorker("fencing")` and `ChooseSubAction("build_fences")` at `PendingFarmRedevelopment`). Chain body uses `_pbf_on_top(state)` predicate per MCTS_DESIGN §5.4, with explicit entry/exit phases handling the outer `PendingFencing` wrapper for trigger 1. Tree reuse: `re_root(new_root)` walks reachable descendants and prunes `transpositions` to the live subtree. Three usage modes: separate trees (default for matches), shared tree via shared agent (self-play), shared tree via shared `MCTSSearch` (different agent configs per seat). Defaults: `sims_per_move=500`, `c_uct=1.4`, `fpu_offset=0.0`, `n_random_fencing=4`, action-selection softmax `T=0.2`. | Complete (Phase 2) | `MCTS_DESIGN.md` §4-5, `agricola/agents/mcts.py` |
| **MCTS match driver** (`scripts/play_mcts_match.py`) — MCTS-vs-opponent CLI. `--opponent {hubris_v3, random, mcts}`, `--v3-config <json>` to load the V3 evaluator's tuned config, per-MCTS knobs (`--sims`, `--c-uct`, `--n-random-fencing`, `--fpu-offset`, `--temperature`), `--mcts-as-p1` to swap seats. `--jobs N` (default `cpu_count()`) parallelizes via `multiprocessing.Pool`; workers construct agents in-process (avoids pickling `MCTSSearch` transposition tables). Streams a per-game line as each game completes (running win tally + ETA). Heuristic opponent uses the same strict-restricted legality as MCTS (matches training-pipeline convention). | Complete (Phase 3) | `MCTS_DESIGN.md` §8 Phase 3, `scripts/play_mcts_match.py` |
| **MCTS empirical finding** — at the current 200-500 sim budgets with vanilla UCT and the existing V1 / V3 heuristics as leaf evaluators, MCTS **loses ~3-5 points** vs the same heuristic used standalone (e.g. MCTS-V1 vs V1-heuristic: -3.88 at 500 sims; MCTS-V3-ported vs V3-ported-heuristic: -5.58 at 200 sims). The earlier "MCTS-V3 beats V3-heuristic by +2.7" result was MCTS partially compensating for V3's weakness at the time, not an absolute lift — MCTS-V3 still lost to V1-heuristic. **MCTS remains the project's long-term direction** (Phase 5 AlphaZero-style self-play); this finding scopes what the current implementation does *now* with the current evaluators, not whether MCTS will eventually pay off (PUCT + learned-value NN + higher sims are the natural follow-ups). | Empirical | session matches; `POSSIBLE_NEXT_STEPS.md` |
| **`HubrisHeuristicV1` + `CONFIG_V1_T2` is the current standalone-strongest agent** — V1 (round-2-tuned via CMA-ES) beats V3 in head-to-head (~10 margin vs current V3) and is also the strongest seat in matches vs MCTS variants at 200-500 sims. Use it as the strong reference in any new comparison or as the `--baselines` / `--regression-baseline` target in further tuning. | Empirical | session matches |
| **Multi-baseline tuning + regression detector** (`scripts/tune_heuristic.py`) — `--baselines PATH1 PATH2 ...` aggregates margin across multiple opponents into the CMA-ES fitness (preventing the "chained baseline drift" that silently degraded V3 in iter2). `--regression-baseline PATH` measured per-generation on session-best, recorded in `regression_history` (drift detector, not in fitness). Per-baseline holdout breakdown also recorded. Old `--baseline` flag preserved as backwards-compat single-element alias. Default `--regression-baseline t2`. New `v3_all` TUNABLE category combines all 6 V3 categories (312 params) for single-call CMA-ES. | Complete | `V3_TRAINING_PIPELINE.md` |
| **Alternative fitness metrics** (`scripts/tune_heuristic.py`) — `--fitness {margin,sublinear,truncated,win_rate}` + `--fitness-k` choose how per-game outcomes aggregate into the CMA-ES objective (raw margin / sign·sqrt(|m|) / clipped to ±k / win-rate). Recorded in the output JSON. | Complete | `V3_TRAINING_PIPELINE.md` |
| **Seed rotation + validation pool** (`scripts/tune_heuristic.py`) — `--rotate-seeds` / `--rotate-start` rotates evaluation seeds across generations to combat seed-overfitting; `--validation-pool` / `--validation-pool-start` defines a held-out seed pool for session-best regression checks. Cache invalidation made rotation-aware. | Complete | `V3_TRAINING_PIPELINE.md` |
| **`HeuristicConfigV3` opt-in fields**: `wood_flat_bonus`, `temperature`, `r1_force_forest_bonus` (all default 0). `r1_force_forest_bonus` available standalone via the `r1_force_forest_bonus` helper or set via config; `--candidate-r1-force-forest` flag on `tune_heuristic.py` wires it into candidate evaluation. `compose_evaluators(*evaluators)` sums callables for additive wrapping. | Complete | `agricola/agents/heuristic.py`, `V3_TRAINING_PIPELINE.md` |
| **Differential evaluator wrappers** (`agricola/agents/heuristic.py`) — `make_differential_evaluator(base)` + `evaluate_hubris_v3_differential` / `evaluate_hubris_v1_differential` + `HubrisHeuristicV3Differential` / `HubrisHeuristicV1Differential`. Evaluates own − opp via the base evaluator. | Complete | `agricola/agents/heuristic.py` |
| **`v3_best.json` auto-promotion gating** — comparison metric switched from raw holdout margin to `holdout.regression.avg_margin` (with min-n=30 gate and same-baseline check); graceful fallback for files predating regression. Per-baseline diagnostic now stores W-D-L (not just margin) and is parallelized via worker pool. `gen_best_x` persisted in history alongside `session_best_x`. `--no-promote` disables auto-update. | Complete | `V3_TRAINING_PIPELINE.md` |
| **Heuristic-tuning data-gen ensemble** — 8-config ensemble used for self-play data generation to bootstrap NN training, spanning ~5-15% to 86.4% round-robin win-rate for state-distribution diversity. Current strongest: `alphas_gen_7` (also `v3_best.json`). See `tuned_configs/DATA_GEN_ENSEMBLE.md` for the full list. | Complete | `tuned_configs/DATA_GEN_ENSEMBLE.md`, `V3_TRAINING_PIPELINE.md` |
| **NN value-function design spec** (`FIRST_NN.md`) — phase-(a) supervised value NN with V3-superset inputs (~170 features), terminal-margin supervision target, multi-step derived feature inclusion criteria, mid-action encoding via `subaction_available` + `stop_is_legal`, terminal-state encoding via zeros + `game_end_indicator`, dual schema-versioning protocol (`DATA_VERSION` + `ENCODING_VERSION`) with hard-fail load checks, data-generation pipeline (8-config ensemble, bimodal per-agent T, resume-on-existing, validation), architecture/training/evaluation as placeholders pending subsequent design rounds. | Complete (data pipeline spec); architecture/training TBD | `FIRST_NN.md` |
| **NN data subpackage** (`agricola/agents/nn/`) — `schema.py` (`DATA_VERSION`, `DecisionSnapshot`, `GameRecord`, `DataVersionMismatch`, `load_game_records`, `compute_winner`), `recording.py` (`play_recording_game` — single-game driver capturing non-singleton snapshots + terminal state + final scoring + winner into a `GameRecord`), `encoder.py` (`ENCODING_VERSION` constant; `encode_state` TBD), `__init__.py` (public-surface re-exports). No PyTorch dependency in schema/recording (kept torch-free so data-generation scripts don't pay the import cost). | Complete (schema + recording); encoder TBD | `agricola/agents/nn/`, `FIRST_NN.md` §11.1 |
| **NN data-generation pipeline** (`scripts/generate_nn_training_data.py`) — multiprocessing-pool batch generator with deterministic plan computation, balanced contiguous worker slicing, atomic per-game pickle writes, resume-on-existing (loads existing worker pickle + skips completed game_idxs), bimodal per-agent T draws (95% uniform [0.3, 1.0] + 5% T=4), config-spec dispatch (`"random"` / `"t2"` sentinels + JSON paths). Default ensemble = 8 configs from `DATA_GEN_ENSEMBLE.md`. Per-game errors caught and logged, run continues. CLI `--n-games / --n-workers / --out-dir / --base-seed / --approved-configs / --restricted`. Empirically: 1000 games in 131s on 8 workers, 5000 games projected at ~11 min. | Complete | `scripts/generate_nn_training_data.py`, `FIRST_NN.md` §6 |
| **NN dataset validation script** (`scripts/validate_nn_dataset.py`) — post-generation invariant checker per FIRST_NN.md §6.6. Loads all (or `--sample-size N` random subset of) records from a run dir; checks `data_version`, `chosen_action ∈ legal_actions(state)`, non-singleton snapshots, `state.phase != BEFORE_SCORING`, non-empty `decisions`, `decider_idx == decider_of(state)`, `terminal_state.phase == BEFORE_SCORING`, stored-vs-recomputed final scores. Failure reports group by check type + locate offending game_idx + snapshot. Exit codes 0/1/2 (pass/fail/invalid). | Complete | `scripts/validate_nn_dataset.py`, `FIRST_NN.md` §6.6 |

As of now, the heuristic-tuning process has produced an 8-config ensemble used for NN training data generation. The ensemble is spread across the win-rate spectrum (from t2 at ~5-15% up to `alphas_gen_7` at 86.4% round-robin) so that self-play trajectories cover a diverse state distribution rather than collapsing onto one playstyle. The current strongest config (`alphas_gen_7`) is the contents of `tuned_configs/v3_best.json`; a stable copy lives at `tuned_configs/alphas_gen_7.json` so ensemble references don't break when `v3_best.json` is overwritten. See **`tuned_configs/DATA_GEN_ENSEMBLE.md`** for the full list with one-line descriptions per config; deeper pipeline details (fitness metrics, seed rotation, regression detector, promotion gating) live in **`V3_TRAINING_PIPELINE.md`**.

**Not yet implemented:**

- Cards other than Potter Ceramics, and the action-space paths that would let players play minor improvements or occupations (`lessons` remains permanently illegal in the Family game; the optional minor / improvement paths at Basic Wish for Children, House Redevelopment, Major Improvement, and Farm Redevelopment depend on minor-card support arriving).

Every action space surfaced by `legal_placements` now has a working initiate path; the `NotImplementedError` branch in `_apply_place_worker` is a defensive guard for unknown space IDs (e.g., `lessons`), no longer used for any normal placement.

A full history of what was built in each session, including design decisions made along the way and bugs caught and fixed, is in **`SESSION_HISTORY.md`**.

---

## Rules Reference

The complete rules for the 2-player Family game are in **`RULES.md`**. This includes the full action space descriptions, major improvement effects, harvest rules, animal accommodation rules, and scoring tables. Clarifications established during design sessions are marked with an asterisk.

---

## Implementation Notes

Design choices that worked well for the Family game but may need revisiting when cards are introduced (e.g. how workers are stored on action spaces, why animal locations are not tracked per-pasture) are documented in **`IMPLEMENTATION_CHOICES.md`**.

Significant cross-cutting refactors that touched many files at once are documented in **`CHANGES.md`**.

---

## Documentation Files

Top-level docs (live alongside CLAUDE.md and are kept current as the project evolves):

| File | Description |
|---|---|
| `RULES.md` | Complete rules reference for the 2-player Family game, including action space descriptions, major improvement effects, harvest rules, animal accommodation, and scoring tables. |
| `STRATEGY.md` | AI strategy and algorithm decisions: action space structure, MCTS approach, neural network design, and the rationale behind each project phase. |
| `CHANGES.md` | Significant cross-cutting refactors that touched many files at once (Resources extraction; two-track pasture cache model; dispatch refactor + pending provenance; harvest phases; `BoardState.action_spaces` canonical-tuple refactor; engine performance pass with `fast_replace` + `legal_actions_cache()`; HubrisHeuristicV3 architecture + iterative tuning pipeline). |
| `CLEANUP.md` | Three small targeted field-level fixes (house material location, field rename, field removal). |
| `SESSION_HISTORY.md` | Full record of what was built each session, including design decisions made and bugs caught. |
| `IMPLEMENTATION_CHOICES.md` | Fine-grained design decisions that worked well for the Family game but may need revisiting when cards are added. |
| `POSSIBLE_NEXT_STEPS.md` | Living planning doc — directions the project could take next, organized by scope and effort. Updated as the project progresses. |
| `POSSIBLE_SPEEDUPS.md` | Living catalog of performance optimizations — both ideas surfaced by profiling and not yet acted on, and forward-looking candidates. Sibling to POSSIBLE_NEXT_STEPS.md, scoped to performance specifically. |
| `HEURISTIC_TUNING_PLAN.md` | V1-era plan for self-play tuning. Thread A (tuning harness) has been implemented and run; Threads B and C are partially superseded by V3. See `V3_TRAINING_PIPELINE.md` for the current pipeline. |
| `HUBRIS_V1_NOTES.md` | Design reference for HubrisHeuristic V1: per-term function/motivation/shape/magnitude for every component of `evaluate_hubris_v1`, the V1-vs-V2 finding with worked example, deferred alternatives (renovation bonus, newborn discount) with reasoning, known limitations and failure modes. Read before modifying V1; V3 has its own design doc. |
| `V3_DESIGN.md` | Comprehensive design reference for HubrisHeuristicV3: three combination styles (blend / additive / joint-alpha), per-category specs (fields/crops/pastures/animals/resources/food/joint-alpha), three-component resource pattern (wood/clay/reed/stone), V1 carry-overs and what V3 deletes, known limitations. Read before modifying V3. |
| `V3_TRAINING_PIPELINE.md` | Operational guide for the V3 tuning pipeline: CMA-ES basics, `scripts/tune_heuristic.py` semantics (CLI flags, multi-baseline + regression-detector tooling, save/resume, x0 fallback, `<arch>_best.json` auto-update), the `scripts/run_iterative_v3.py` orchestrator (block-coordinate descent), `v3_best.json` convention (currently the ported iter1 config), current training state, next steps. |
| `MCTS_DESIGN.md` | Design spec for the MCTS phase (project phase 5). Architecture decisions (vanilla UCT + FPU + DAG-with-transpositions + leaf-evaluation + macro-enumeration for Fencing); data structures (MCTSNode / MCTSSearch / MCTSAgent); algorithm details (per-sim flow, UCB, sign-flip backprop, transposition table); strict-restrictions spec (new filters added to `agricola/agents/restricted.py`); implementation phases; open questions. Read before starting MCTS implementation. |
| `FIRST_NN.md` | Design spec for the first NN value function (project phase 5b). Sections: goals/non-goals, strategic context, design principles (input-encoding philosophy, pre-compute selectively, mid-action encoding, terminal-margin target), input encoding (~170 features split across per-player ×2 / shared / mid-action / terminal-state handling), supervision target (terminal margin + terminal-state training pairs), data generation pipeline (fully specified: 8-config ensemble, bimodal per-agent T, snapshot semantics, file layout, resume protocol, validation), architecture (TBD), training (TBD), evaluation (TBD), open questions, implementation notes (file layout + schema versioning `DATA_VERSION` + `ENCODING_VERSION`), status. Read before working on the NN. |
| `PROFILING.md` | Findings from the item-C profiling pass: hot paths identified, workloads defined, and the R1-R6 recommendation list. The infrastructure (`scripts/profile_engine.py`, `scripts/profile_states.py`, `scripts/count_replaces.py`, `scripts/bench_replace.py`) is re-runnable; this doc captures the snapshot interpretation. |
| `FILE_DESCRIPTIONS.md` | Detailed per-file descriptions for every `agricola/*.py` and the test-infrastructure files (`tests/factories.py`, `tests/test_utils.py`). |
| `TEST_DESCRIPTIONS.md` | Per-file coverage descriptions for each `tests/test_*.py`. |
| `SESSION_INTRODUCTION.md` | Standard prompt to give a new coding agent at the start of a session. |

Historical task specs and design artifacts (in `task_files/`, frozen at the time of their task's landing):

| File | Description |
|---|---|
| `task_files/ARCHITECTURE.md` | Original full architecture spec, game rules reference, and original dataclass definitions. Field names may diverge from current code — inline annotations flag known discrepancies. |
| `task_files/FENCE_IDEAS.md` | Design conversation artifact from Task 6 — explores the broader Fencing action-space design alternatives. |
| `task_files/TASK_2.md` … `task_files/TASK_7.md` | Implementation task files, one per development task. Frozen at landing time; cross-referenced from CLAUDE.md's status table and from SESSION_HISTORY.md. |

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
    agricola/                       # Game engine package.
        __init__.py                 # Empty package marker.
        constants.py                # Named enums (Phase, HouseMaterial, CellType) plus lookup tables: action-space accumulation rates, MAJOR_IMPROVEMENT_COSTS, ROOM_COSTS, BAKING_IMPROVEMENT_SPECS, FIREPLACE/COOKING_HEARTH_INDICES, BAKING_IMPROVEMENTS. SPACE_IDS / SPACE_INDEX (canonical 25-entry ordering of all action spaces) index BoardState.action_spaces.
        resources.py                # Resources (wood/clay/reed/stone/food/grain/veg) and Animals (sheep/boar/cattle) frozen dataclasses with __add__/__sub__/__bool__ operators. Extracted from state.py to avoid circular imports with constants.py.
        pasture.py                  # Pasture dataclass (cells, num_stables, precomputed capacity) + compute_pastures_from_arrays BFS that flood-fills from outside the grid to find enclosed connected components. Independent of state.py via duck typing.
        replace.py                  # fast_replace(obj, **changes) — a drop-in faster equivalent of dataclasses.replace, ~20% faster per call (timeit-measured). Used at every state-mutation site in engine.py / resolution.py / pending.py / cards/. See CHANGES.md Change 9.
        state.py                    # All frozen state dataclasses: Cell, Farmyard (with cached pastures), ActionSpaceState, PlayerState, BoardState, GameState — plus get_space / with_space free-function helpers for keyed access to BoardState.action_spaces (a canonical-ordered tuple). The top-level GameState snapshot — every transition produces a new one via dataclasses.replace — is fully hashable.
        setup.py                    # setup(seed) -> GameState — builds the initial 2-player Family game state. All randomness (starting player, stage card shuffle per stage) is resolved here via a seeded NumPy RNG; engine is fully deterministic afterward.
        helpers.py                  # Pure derived-quantity functions (fences_in_supply, stables_in_supply, cooking_rates 4-tuple, enclosed_cells) and the Pareto frontier helpers (extract_slots, can_accommodate, pareto_frontier, breeding_frontier, food_payment_frontier, harvest_feed_frontier).
        actions.py                  # All Action dataclasses (PlaceWorker, ChooseSubAction, the full Commit* family, FireTrigger, Stop) plus the CommitSubAction marker base used by the generic commit dispatcher.
        pending.py                  # All Pending* frozen dataclasses (sub-action + parent + wrapper variants), the PendingDecision union alias, and the three pure stack ops (push, pop, replace_top).
        legality.py                 # Top-level legal_actions (stack-state dispatch) + legal_placements + per-space placement predicates + shared helpers (_can_bake_bread, _can_build_stable, …) + per-pending sub-action enumerators + card extension registries.
        resolution.py               # Atomic _resolve_<space> handlers, non-atomic _initiate_<space> + _choose_subaction_<space> handlers, sub-action _execute_<sub_action> effect functions, and the function-pointer dispatch tables (ATOMIC_HANDLERS, NONATOMIC_HANDLERS, CHOOSE_SUBACTION_HANDLERS).
        scoring.py                  # score(state, player_idx) -> (total, ScoreBreakdown) and tiebreaker — end-game evaluation across all categories (fields, pastures, animals, rooms, people, majors, craft bonuses, begging penalties).
        engine.py                   # The transition engine: step + _apply_action dispatch + _advance_until_decision + phase resolvers (_resolve_return_home, _resolve_preparation, _resolve_harvest_field, _initiate_harvest_feed, _initiate_harvest_breed) + the COMMIT_SUBACTION_HANDLERS metadata table for generic commit dispatch.
        fences.py                   # Four layered pasture-shape universes (FULL=1518 / FAMILY=762 / EXTENDED=193 / RESTRICTED=109) with PastureCandidate edge-metadata entries, fence-array pack/apply helpers, and the compute_new_fence_edges cost helper. Standalone module, no engine dependencies.
        fence_universe.py           # Experimental tooling for swapping the active fence universe: the active_universe(spec) context manager (named universes or explicit triples), restrict_to(predicate, base=...) builder for derived universes, NAMED_UNIVERSES registry, and current_universe() accessor.
        cards/                      # Card framework + concrete card modules + harvest-conversion registry.
            __init__.py             # Imports each card module + harvest_conversions so their register() calls fire at load time, populating TRIGGERS / CARDS / HARVEST_CONVERSIONS and BAKE_BREAD_ELIGIBILITY_EXTENSIONS.
            triggers.py             # Two parallel registries — TRIGGERS (event-keyed list, used by enumerators) and CARDS (card-id-keyed direct lookup, used by _apply_fire_trigger) — plus the register() function called by card modules at import time.
            potter_ceramics.py      # The one card in scope: "exchange 1 clay for 1 grain before each Bake Bread action, at most once per action." Exercises the trigger machinery end-to-end.
            harvest_conversions.py  # HARVEST_CONVERSIONS registry + HarvestConversionSpec dataclass + register_harvest_conversion(). Three built-in entries: joinery (1 wood -> 2 food), pottery (1 clay -> 2 food), basketmaker (1 reed -> 3 food).
        agents/                     # Agent implementations: random + heuristics. Built atop the engine's pure `step` / `legal_actions` interface.
            __init__.py             # Re-exports Agent / HeuristicAgent / RandomAgent / SimpleHeuristic / HubrisHeuristic[V1,V2,V3] / HubrisHeuristicV1Differential / HubrisHeuristicV3Differential / HeuristicConfig / HeuristicConfigV3 / DEFAULT_CONFIG / DEFAULT_CONFIG_V3 / CONFIG_V1_T2 / evaluator functions (+ differential variants + `compose_evaluators`, `make_differential_evaluator`, `r1_force_forest_bonus`) / play_game / restricted_legal_actions / strict_restricted_legal_actions / make_strict_restricted_legal_actions / MCTSAgent / MCTSSearch / MCTSNode / MacroFencingAction + priority constants.
            base.py                 # `Agent` Protocol, decider_of helper, RandomAgent, generic HeuristicAgent (1-turn or 1-action lookahead, singleton-skip always on, softmax-with-temperature action selection), play_game(initial, agents) game-driver. Both agent classes accept a `legal_actions_fn` kwarg (default = unrestricted `legal_actions`) threaded through every legality consultation.
            heuristic.py            # All heuristic agent code. HeuristicConfig + evaluate_simple/evaluate_hubris_v1/_v2 + SimpleHeuristic / HubrisHeuristicV1 / V2 (V1-era). CONFIG_V1_T2 (round-2-tuned V1 constant). HeuristicConfigV3 + evaluate_hubris_v3 + HubrisHeuristicV3 (current main heuristic). Opt-in V3 config fields default 0: `wood_flat_bonus`, `temperature`, `r1_force_forest_bonus`. `compose_evaluators(*evaluators)` sums callables additively. Standalone `r1_force_forest_bonus(state, p, cfg)` helper available alongside the config field. Differential wrappers: `make_differential_evaluator(base)`, `evaluate_hubris_v3_differential`, `evaluate_hubris_v1_differential`, `HubrisHeuristicV3Differential`, `HubrisHeuristicV1Differential`. All V1 helpers (family-future, empty-room, location bonuses, SP, renovation, major-override, food/begging) are shared duck-typed across V1/V3 configs. Subclasses forward the `legal_actions_fn` kwarg to the base. See V3_DESIGN.md and HUBRIS_V1_NOTES.md.
            restricted.py           # Action-pruning wrappers over `legal_actions(state)`. Exports `restricted_legal_actions(state)` (regular: ordering / cell-priority / room-cap / first-pasture / min-begging / drop-`use=False`-craft), `strict_restricted_legal_actions(state)` (strict MCTS variant adding Cultivation sow-max, Grain-Util veggie auto-max, 9 fencing patterns, harvest-feed cap of top-5-V3 + 2 random), and `make_strict_restricted_legal_actions(*, config, rng)` factory for injected RNG/config. Priority constants (STABLE_PRIORITY, ROOM_PRIORITY, PLOW_PRIORITY, FIRST_PASTURE_REQUIRED_CELLS, MAX_TOTAL_ROOMS). Every filter routes through `_safe_narrow` so neither wrapper empties a non-empty input. See CHANGES.md Change 11 (regular wrapper) and MCTS_DESIGN.md §7 (strict additions).
            mcts.py                 # MCTS agent. `MCTSNode` (identity equality, lazy `_legal_actions` cache, `macro_sequences` on fencing-trigger parents), `MCTSSearch` (transposition table + per-search RNG + cached HubrisHeuristicV3 for greedy macros), `MCTSAgent` (vanilla UCT with FPU, path-only backprop, softmax action selection at T=0.2). Macro-fencing for both trigger points (PlaceWorker("fencing") + ChooseSubAction("build_fences") at PendingFarmRedev), with explicit entry/exit phases handling the outer PendingFencing wrapper. Tree reuse via `re_root(new_root)` (prunes transpositions to live subtree). `MacroFencingAction` is the MCTS-internal action type; the engine never sees it. See MCTS_DESIGN.md §4-5.
            nn/                     # NN value-function infrastructure (subpackage). No PyTorch dependency in schema/recording — kept torch-free so data-generation scripts don't pay the import cost. See FIRST_NN.md §11.1 for the file-by-file rationale.
                __init__.py         # Re-exports the public surface (`DATA_VERSION`, `ENCODING_VERSION`, `DecisionSnapshot`, `GameRecord`, `DataVersionMismatch`, `compute_winner`, `load_game_records`, `play_recording_game`) so external code can `from agricola.agents.nn import X` regardless of internal layout.
                schema.py           # On-disk dataset schema. `DATA_VERSION` constant + hard-fail load check (`DataVersionMismatch`). Frozen dataclasses: `DecisionSnapshot` (state + chosen_action + decider_idx), `GameRecord` (game-level metadata + final scores + winner + terminal_state + decisions tuple). `load_game_records(path)` loader + `compute_winner(s0, s1, tb0, tb1)` helper.
                recording.py        # `play_recording_game(initial_state, p0_agent, p1_agent, *, metadata, legal_actions_fn=restricted_legal_actions)` — plays one full game, captures every non-singleton state as a `DecisionSnapshot` (state recorded BEFORE the agent call so the snapshot matches what the agent saw), then captures terminal state + final scores + tiebreakers + winner into a complete `GameRecord`. Deterministic given pre-seeded agents.
                encoder.py          # `ENCODING_VERSION` constant only today (encoder itself is TBD pending architecture decisions). Will host `encode_state(state, player_idx) -> torch.Tensor` once the model architecture is locked in.
    tests/                          # pytest test suite — per-file coverage descriptions in TEST_DESCRIPTIONS.md.
        __init__.py                 # Empty package marker.
        factories.py                # Prefabricated-state helpers (with_resources, with_animals, with_majors, with_grid, with_pending_stack, etc.) for composing test states — including states unreachable through gameplay. Project-wide convention for test setup.
        test_utils.py               # Test infrastructure (not a test file): run_actions for scripted multi-action walks, random_agent_play driver, and the IMPLEMENTED_NON_ATOMIC_SPACES / filter_implemented action filter (forward-compat as new action types land).
        test_state.py
        test_helpers.py
        test_scoring.py
        test_legality_atomic.py
        test_legality_non_atomic.py
        test_resolution_atomic.py
        test_engine.py
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
        test_nn_records.py
        test_generate_nn_training_data.py
        test_validate_nn_dataset.py
    scripts/                        # Out-of-tree utilities — profiling, benchmarking, tuning. Re-runnable; not imported by `agricola/` or `tests/`. Used to produce / update PROFILING.md and the tuned-config JSONs in `tuned_configs/`.
        profile_engine.py           # Three-workload runner (A: random from setup; B: random from wealthy prefab; C: micro-bench across 9 prefab states) with cProfile + wall-clock.
        profile_states.py           # 9 prefab `GameState` factories covering early/mid/late game; the round-14 state alone makes every non-`lessons` space legal (the coverage requirement for Workload C).
        count_replaces.py           # Monkey-patch counter for `dataclasses.replace` / `fast_replace` call shapes.
        bench_replace.py            # `timeit`-based microbenchmark comparing stdlib replace vs `fast_replace`.
        play_match.py               # Match-runner library + CLI. `play_match(p0_factory, p1_factory, seeds)` returns `MatchResult` (win/draw/loss counts, score sums, per-game records). Used by `tune_heuristic.py` and as a standalone head-to-head tool (CLI: `--p0 hubris_v3 --p1 hubris --n 100`). Per-seat `--p0-restricted` / `--p1-restricted` flags wrap each seat's agent in `restricted_legal_actions` independently.
        tune_heuristic.py           # CMA-ES tuner for one TUNABLE category at a time. Supports V1 and V3 configs via `--category` + `--arch`-derived dispatch. Save/resume via pickle (`.cma.pkl` per generation). x0 fallback prevents chain-forward regression. Auto-updates `tuned_configs/<arch>_best.json` when holdout improves (`--no-promote` disables; comparison metric is `holdout.regression.avg_margin` with min-n=30 + same-baseline gate). Parallel across `--jobs` cores; per-baseline diagnostic also parallelized. `--restricted` / `--no-restricted` (default ON), `--fitness {margin,sublinear,truncated,win_rate}` + `--fitness-k`, `--rotate-seeds` / `--rotate-start`, `--validation-pool` / `--validation-pool-start`, `--candidate-r1-force-forest` all recorded in the output JSON. `gen_best_x` persisted in history alongside `session_best_x`. See V3_TRAINING_PIPELINE.md.
        run_iterative_v3.py         # Orchestrator chaining V3 category tunings as block-coordinate descent. Per pass: fields_crops → food → resources → pastures_animals. On passes 2+, each category resumes its previous CMA-ES state. Supports `--start-step N` and `--initial-pickles "cat:path,..."` for resuming partial iterations. `--restricted` / `--no-restricted` (default ON) is forwarded to every tune_heuristic.py subprocess so candidate and baseline both consult `restricted_legal_actions`.
        play_mcts_match.py          # MCTS-vs-opponent match driver. `--opponent {hubris_v3, random, mcts}`, `--v3-config <json>` for the V3 evaluator's tuned config, per-MCTS knobs (`--sims`, `--c-uct`, `--n-random-fencing`, `--fpu-offset`, `--temperature`), `--mcts-as-p1` to swap seats. `--jobs N` (default `cpu_count()`) parallelizes via `multiprocessing.Pool`; workers construct agents in-process (avoids pickling `MCTSSearch` transposition tables — they hold node back-refs to the search). Streams per-game lines as games complete (running win tally + ETA, `flush=True`). Heuristic opponent uses the same strict-restricted legality as MCTS. For best throughput pick `--n` as a multiple of `--jobs` (a 10-seed run on 8 cores wastes 6 cores on the trailing batch of 2).
        generate_nn_training_data.py # NN training-data batch generator. Plays many games between agents drawn from an approved-config ensemble (default: 8 configs from `tuned_configs/DATA_GEN_ENSEMBLE.md`); writes `GameRecord`s to per-worker pickle files under `data/nn_training/runs/<run_id>/games/`. Multiprocessing pool, deterministic plan computation from (n_games, base_seed, approved_configs), balanced contiguous worker slicing, atomic per-game pickle writes, resume-on-existing (loads existing pickle + skips completed game_idxs), bimodal per-agent T draws (95% uniform [0.3, 1.0] + 5% T=4 — independently per agent). Config dispatch: `"random"` / `"t2"` sentinels + JSON paths. Per-game errors caught, logged in metadata.json's `errored_games`, run continues. CLI `--n-games / --n-workers / --out-dir (resume if exists) / --base-seed / --approved-configs / --restricted`. See FIRST_NN.md §6.
        validate_nn_dataset.py      # Post-generation invariant checker per FIRST_NN.md §6.6. Loads all (or `--sample-size N` random subset of) records from a run dir's worker pickles; runs invariants: `data_version` matches, `chosen_action ∈ legal_actions(state)`, non-singleton snapshots, `state.phase != BEFORE_SCORING`, non-empty `decisions`, `decider_idx == decider_of(state)`, `terminal_state.phase == BEFORE_SCORING`, stored-vs-recomputed final scores. Continues past individual failures to report all issues. Failure summary groups by check type + locates offending game_idx + snapshot. Exit codes 0/1/2 (pass / fail / invalid run dir).
    tuned_configs/                  # Persistent artifacts from tuning runs. Each completed run writes `<timestamp>.json` (best config, history, holdout), `<timestamp>.log` (human-readable progress mirror), and `<timestamp>.cma.pkl` (full CMA-ES state for resume). `v1_best.json` and `v3_best.json` are auto-maintained pointers to the strongest config per architecture. The 8-config data-gen ensemble (alphas_gen_1, alphas_gen_7, panel_gen16, panel_gen_25, panel_gen47, panel_gen47_wood020, panel_wood_r1 + t2) plus `panel_gen16_temp05.json` (panel-only diversity baseline) live here as named JSONs alongside the timestamped run outputs. `DATA_GEN_ENSEMBLE.md` describes the ensemble. See V3_TRAINING_PIPELINE.md.
    data/nn_training/runs/          # NN training-data datasets (gitignored — regenerable from the deterministic plan). Each generation invocation produces one run directory `<run_id>/` containing `games/worker_NN.pkl` (one per worker, holding `list[GameRecord]`) plus `metadata.json` (run-level metadata: code SHA, host, approved configs, T distribution, restricted flag, base_seed, planned/completed/errored game counts, data_version). See FIRST_NN.md §6.3.
    task_files/                     # Historical task specs and design artifacts — frozen at the time their task landed; referenced from CLAUDE.md's status table and from SESSION_HISTORY.md / CHANGES.md as the design-rationale anchors. Not auto-read; consult when a status-table row or a session-history entry points here.
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
