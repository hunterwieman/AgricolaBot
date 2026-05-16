# AgricolaBot

A from-scratch Python implementation of the board game Agricola, with the long-term goal of training a strong AI agent using Monte Carlo Tree Search and reinforcement learning.

> **For new sessions:** This file (`CLAUDE.md`) is read automatically. It covers project status, per-file descriptions, and key design principles. For the full architecture spec, game rules reference, and original dataclass definitions see **`ARCHITECTURE.md`**. For significant cross-cutting refactors see **`CHANGES.md`**. For small targeted fixes see **`CLEANUP.md`**.

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

These are the foundational architectural decisions for the project. The first three (immutable frozen dataclasses, functional core, determinism after setup) are near-absolute — they are load-bearing for MCTS and self-play, and deviating from them would break the AI training pipeline. The fourth ("derived data, not cached data") is a default with explicit guidance for when to deviate; it has one current accepted exception. Read each principle for its own framing rather than treating the bundle as a single rule.

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

  **Current exception:** `Farmyard.pastures` (the pasture decomposition) is cached on `Farmyard`. All higher-level pasture-derived quantities (`enclosed_cells`, capacities, count, fenced-stable count) remain on-demand derivations from this one cached value. The cache is maintained by caller discipline: the four pasture-changing resolvers (Fencing, Farm Expansion's stable build, Side Job's stable build, Farm Redevelopment's fence build) pass `pastures=compute_pastures_from_arrays(...)` explicitly when constructing a new `Farmyard`; all other `Farmyard` mutations leave `pastures` alone (it rides along correctly via `dataclasses.replace`). This is a deliberate weakening of factor 2 (structural enforcement) — auto-fill via `__post_init__` was the obvious structural alternative, and was the original mechanism, but is not used today; see CHANGES.md Change 2 and Change 3 for the rationale.

For the complete architecture specification, see **`ARCHITECTURE.md`**, the initial design document.

---

## Additional Design Principles

Secondary conventions — narrower in scope than the four Key Design Principles, but worth following consistently because the failure modes are silent (wrong answer, no crash) and the right choice is non-obvious.

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

Sub-actions that debit resources fall into three buckets based on where the cost lives. When adding a new sub-action pending that debits resources, choose the bucket that fits — pick bucket 2 by default; reach for bucket 3 only when the cost is genuinely a function of a commit-time parameter.

1. **No cost.** The sub-action doesn't debit resources (e.g., `PendingPlow`). No `cost` field. Effect function applies its non-resource effect and returns.

2. **Caller-parameterizable cost — field on the pending.** The cost varies by who pushed the sub-action: different spaces specify different costs, and cards may inject alternate costs or formula choices. The choose handler (or trigger / `_initiate_*` / card effect that pushes the pending) computes the cost at push time and stores it on the pending as `cost: Resources`. The effect function reads `pending.cost` and debits via `p.resources - pending.cost`. Cards that modify cost can update `pending.cost` either at push time (by computing differently) or via a trigger between push and commit (by `replace_top`-ing the pending). `PendingBuildStables` (Side Job: 1 wood; Farm Expansion: 2 wood), `PendingBuildRooms` (Farm Expansion: `ROOM_COSTS[material]`), and `PendingRenovate` are the current examples; `PendingBuildFences` will follow the same pattern when introduced.

3. **Commit-time-parameterizable cost — keyed lookup at execute time.** The cost varies by a parameter on the commit action itself, chosen at commit time rather than push time. No `cost` field on the pending — the effect function looks up the cost from the commit's parameters against a const table. `PendingBuildMajor` is the canonical example: cost depends on `commit.major_idx`, looked up in `MAJOR_IMPROVEMENT_COSTS`. This pattern fits when the commit-time parameter space is small and pre-defined.

Bucket 2 is the most flexible for card extensions because the cost can be set or modified anywhere along the push → commit path. Bucket 3 trades flexibility for a single source of truth (the const table) and is appropriate when the cost variations *are* the action's identity (each major improvement is fundamentally a distinct item with a distinct cost).

### Multi-shot sub-action pendings

Some sub-action categories allow multiple commits within a single category invocation (Farm Expansion's build_rooms and build_stables; Side Job's build_stable as a degenerate cap=1 case). The pattern:

- The pending carries two integer fields: `max_builds: int | None` (caller-imposed cap, set at push time; `None` means no cap) and `num_built: int = 0` (increments on each commit).
- `max_builds` encodes only the **caller's intent**, not global constraints. Affordability, supply, and cell/placement availability are checked separately in the per-pending enumerator. Side Job pushes with `max_builds=1` (the space's rule). Farm Expansion pushes with `max_builds=None` — the dynamic constraints in the enumerator do all the bounding.
- The effect function is registered with `auto_pop=False` in `COMMIT_SUBACTION_HANDLERS`. Each commit applies its effect, increments `num_built`, and `replace_top`s — but does **not** pop the pending.
- `Stop` is the explicit exit. `Stop` is legal at `num_built >= 1` (the "must do at least one when entering a category" rule); not legal at `num_built == 0`.
- Per-pending legality offers `Commit*` actions only while `(max_builds is None or num_built < max_builds)` AND remaining affordability/placement/supply constraints permit. When no commit is legal but `num_built >= 1`, `Stop` becomes the only legal action and the agent explicitly Stops. This singleton-`Stop` state arises uniformly whether the cap, supply, affordability, or cell-availability constraint is the binding one.

Side Job's stable build is a multi-shot pending with `max_builds=1`: after the single commit, `Stop` is the only legal action. There is no auto-pop optimization for `max_builds=1` cases — surfacing the singleton `Stop` keeps trace consistency uniform across multi-shot pendings and aligns with the engine's "no auto-resolved singleton player decisions" principle.

Card-trigger fields (`triggers_resolved`, `TRIGGER_EVENT`) are intentionally absent from the multi-shot pendings introduced in Task 5D. They will be added per-pending when the first card needs them. When added, the question of whether `triggers_resolved` persists across commits or resets per commit will be settled per the rules interpretation ("one action with multiple builds" suggests persistence across commits; per-individual-build cards would attach to a different event like `"after_build_stable"` on each commit).

---

## Code Conventions

Syntactic and style patterns followed across the codebase. Architectural conventions — frozen-dataclass rules, the player-parameter convention, function-name prefix taxonomy, pending provenance metadata, sub-action cost handling — live in "Key Design Principles" and "Additional Design Principles" above. This section covers smaller-grained patterns about how code is *written*.

### Dataclass field ordering

In any frozen dataclass that mixes `ClassVar` and instance fields (e.g., the pending dataclasses with `PENDING_ID` and `TRIGGER_EVENT`), place ClassVar declarations first, instance fields after:

```python
@dataclass(frozen=True)
class PendingPlow:
    PENDING_ID: ClassVar[str] = "plow"            # ClassVars first
    TRIGGER_EVENT: ClassVar[str] = "before_plow"
    player_idx: int                                # then instance fields
    initiated_by_id: str
    triggers_resolved: frozenset = frozenset()
```

`ClassVar` declarations are class-level identifiers / tags, not `__init__` parameters; they belong with class metadata, not with per-instance state.

### Action constructor calls — keyword form

Every action-type instantiation uses keyword arguments:

- `PlaceWorker(space="forest")` ✓ not `PlaceWorker("forest")`
- `ChooseSubAction(name="sow")` ✓ not `ChooseSubAction("sow")`
- `FireTrigger(card_id="potter_ceramics")` ✓
- `CommitSow(grain=1, veg=0)` ✓
- `CommitBuildMajor(major_idx=5, return_fireplace_idx=None)` ✓

Applies uniformly across single-field and multi-field action classes. Robust to dataclass field changes (a new defaulted field added later would silently break positional callers but not keyword callers).

### Per-pending enumerator signatures

Enumerators in `legality.py` take `(state, pending: PendingX) -> list[Action]`:

```python
def _enumerate_pending_X(
    state: GameState, pending: PendingX,
) -> list[Action]:
    p = state.players[pending.player_idx]
    actions: list[Action] = []
    ...
```

The dispatcher (`_enumerate_pending`) passes `pending` explicitly. Use `pending.X` directly; do not re-read `state.pending_stack[-1]`. Benefits: testability without setting up a stack, type narrowing to `PendingX`-specific fields, no redundant lookups.

### Effect function signatures

Sub-action effect functions in `resolution.py` take `(state, player_idx, commit: CommitX) -> GameState`:

```python
def _execute_X(
    state: GameState, player_idx: int, commit: CommitX,
) -> GameState:
    p = state.players[player_idx]
    ...
```

`player_idx` is explicit. Do not derive from `state.current_player` — the active player may differ from the commit's owner for out-of-turn trigger frames. Effect functions MAY read `state.pending_stack[-1]` to access their own pending frame (the dispatcher guarantees it is still on top during effect execution).

### Resource arithmetic

For pure resource subtraction, use `__sub__`:

```python
new_resources = p.resources - cost
```

For mixed subtract-and-add in one operation, keep a single `Resources` literal with negative components:

```python
new_resources = p.resources + Resources(grain=-commit.grain, food=rate * commit.grain)
```

Splitting a mixed operation into `(p.resources + Resources(food=...)) - Resources(grain=...)` adds operands without clarity gain. `__sub__` is reserved for pure-subtraction sites where it is strictly cleaner.

### `replace_top` call form

Prefer the one-line form when the inner `dataclasses.replace` fits on a single line:

```python
state = replace_top(state, dataclasses.replace(top, sow_chosen=True))
```

Use a named variable when the replace would exceed comfortable line length or has many fields:

```python
new_top = dataclasses.replace(
    top, triggers_resolved=top.triggers_resolved | {action.card_id},
)
return replace_top(state, new_top)
```

### Variable naming for replaced `PlayerState`

When you bind the result of `dataclasses.replace(p, ...)` to a variable, name it `new_player` (not `new_p` or `np`):

```python
new_player = dataclasses.replace(p, resources=..., farmyard=...)
return _update_player(state, ap, new_player)
```

### Choose-time parent-flag setting

Every `_choose_subaction_*` handler sets the parent pending's `<action>_chosen` field to `True` **before** pushing the sub-action pending:

```python
def _choose_subaction_X(state, action):
    top = state.pending_stack[-1]
    if action.name == "sow":
        state = replace_top(state, dataclasses.replace(top, sow_chosen=True))
        return push(state, PendingSow(
            player_idx=top.player_idx, initiated_by_id=top.PENDING_ID,
        ))
    ...
```

The commit dispatcher (`_apply_commit_subaction`) does NOT set the flag; its sole job is assert, effect, and pop (conditionally, per `auto_pop`). The choose-time setting keeps flag management adjacent to the push that creates the sub-action, making each parent's chosen-tracking visible in one function.

### `actions: list[Action] = []`

Always type the actions list inside enumerators:

```python
actions: list[Action] = []
if ...:
    actions.append(ChooseSubAction(name="sow"))
return actions
```

Not `actions: list = []`. Typed lists catch accidental `actions.append(some_pending)` at type-check time.

### Variable binding at the top of handlers

At the top of any handler that reads from `state`, bind locals once:

```python
def _resolve_X(state):
    ap = state.current_player
    p = state.players[ap]
    ...
```

Subsequent code reads from `ap` and `p`, not from `state.current_player` or `state.players[X]` repeatedly. For effect functions, the equivalent local is `p = state.players[player_idx]`.

### `_update_player` / `_update_space` helpers preferred

When modifying state from resolution code, prefer `_update_player(state, player_idx, new_player)` and `_update_space(state, space_id, **kwargs)` over constructing the full state replacement manually. Card modules (which can't easily import these helpers from `resolution.py` due to module ordering) construct the players tuple themselves; this is the accepted exception.

---

## Engine and Turn Resolution Architecture

This section describes the engine's transition model, the pending-decision stack that supports multi-action turns, and the card-implementation status. The full design and pseudocode are in **`TASK_5.md`**; what follows is the conceptual summary every session should internalize.

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

For the full implementation including dispatch tables, phase resolvers, and the engine module layout, see **`TASK_5.md`**.

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
| A card trigger's effect | `"card:<card_id>"` | `PendingPlow.initiated_by_id = "card:swing_plow"` |

The `"space:"` and `"card:"` prefixes make the namespaces disjoint by construction — no reserved-string carve-out is needed. Sub-action pendings pushed by `ChooseSubAction` use the parent's `PENDING_ID` directly (no prefix).

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

- **Parent `*_chosen` flags are set at choose-time, not at commit-time.** Each `_choose_subaction_*` handler does `replace_top(state, dataclasses.replace(parent, <action>_chosen=True))` before pushing the sub-action pending. The commit dispatcher (`_apply_commit_subaction`) is responsible only for assert + effect + conditional pop; it does not touch parent state. See "Code Conventions" → "Choose-time parent-flag setting" for rationale.
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

For worked examples (a Grain Utilization sow + bake walk-through with and without Potter Ceramics' trigger) and the full implementation breakdown, see **`TASK_5.md`**.

### Card implementation status

The full card system is **not implemented**. Task 5 introduces one card — **Potter Ceramics** (a minor improvement: "Each time before you take a Bake Bread action, you can exchange exactly 1 clay for 1 grain") — solely to exercise and validate the pending-stack's trigger machinery end-to-end. Without a concrete card, the trigger architecture would be untested scaffolding.

Card infrastructure pieces introduced by Task 5:

- `agricola/cards/` subpackage.
- `agricola/cards/triggers.py` with two registries: `TRIGGERS` (event-keyed, used by `legal_actions` enumerators to find eligible triggers at the current event) and `CARDS` (card-id-keyed, used by `_apply_fire_trigger` for direct lookup). Both populated at import time via the `register(event, card_id, eligibility_fn, apply_fn)` function.
- `agricola/cards/potter_ceramics.py` — the one card, registered against `"before_bake_bread"` and against the `BAKE_BREAD_ELIGIBILITY_EXTENSIONS` registry (so `_can_bake_bread` returns True for a Potter Ceramics owner with clay even at 0 grain).
- `PlayerState.minor_improvements: frozenset[str]` records the cards a player has played. `PlayerState.occupations: frozenset[str]` is added in parallel for symmetry (no occupation cards implemented yet).

The full card system (the other ~470 cards in the Family + full game) is a separate future task. Several known design questions are deferred to that task:

- **Compound card interactions.** The current extension-registry pattern handles single-card eligibility broadening (Potter Ceramics) cleanly, but does not handle cases where one card's effect enables another card's eligibility (canonical example: Pan Baker + Potter Ceramics — Pan Baker's on-placement clay grant enables Potter Ceramics' clay-to-grain conversion, which together let the player bake from a 0-clay-0-grain state). Resolving this requires speculative-legality machinery (apply on-placement card effects to a hypothetical state, then check sub-action predicates against the hypothetical). The trigger registry already supports arbitrary event names; the missing piece is the legality-side speculative-application. See **`TASK_5.md`**'s "Known limitation: compound card interactions" for the detailed framing.

- **Atomic-space trigger hosting: phase tracking.** When atomic spaces convert to push trigger-host pendings (so cards like Cottager and Hardware Store can attach to Day Laborer, etc.), the pending needs at least one piece of state to indicate "primary effect applied yet?" Two modeling options to weigh: a uniform `primary_effect_applied: bool` on every space pending (simplest dispatcher), or a `phase: Literal["before", "after"]` field (extensible to a hypothetical third trigger point).

- **Atomic-space trigger hosting: phase-transition mechanism.** Something has to flip the phase bit AND apply the primary effect between the before and after trigger phases. Three candidate mechanisms, none locked in: (1) an explicit transition action (e.g., `ApplyPrimaryEffect()` / `Proceed()`) that's legal during the before-phase — keeps `Stop` unambiguous; (2) overloading `Stop` so that `Stop` during the before-phase advances the phase and `Stop` during the after-phase pops the pending — fewer action types but context-dependent semantics; (3) nested pendings — push a `PendingBefore<Space>` on top of `Pending<Space>`, with the inner pending hosting before-triggers and popping on Stop to trigger the primary effect via a hook on `_apply_stop`. Decision deferred.

---

## Current Status

All 343 tests pass. The following pieces are complete:

| Component | Status | Task file(s) |
|---|---|---|
| State dataclasses + setup | Complete | `TASK_1.md`, `ARCHITECTURE.md` |
| Resource types (`Resources`, `Animals`) | Complete | `CHANGES.md` Change 1 |
| `Resources.__sub__` operator | Complete | `CHANGES.md` Change 5 |
| Helper functions (pastures, animal accommodation, pareto frontiers, cooking rates) | Complete | `TASK_2.md`, `TASK_3.md` |
| Scoring and tiebreaker | Complete | `TASK_2.md` |
| Action type (`PlaceWorker`) | Complete | `TASK_4a_i.md` |
| Atomic-space legality (12 spaces) | Complete | `TASK_4a_i.md` |
| Atomic-space resolution (12 spaces) | Complete | `TASK_4a_ii.md` |
| Pasture cache on `Farmyard` (`agricola/pasture.py`) | Complete | `CHANGES.md` Change 2, `CHANGES.md` Change 3, `TASK_4a_iii.md` |
| Non-atomic legality (11 spaces, `fencing` deferred) | Complete | — |
| Engine: `step` + `_advance_until_decision` + pending stack | Complete | `TASK_5.md` |
| Round transitions (rounds 1 → 4, halts before harvest) | Complete | `TASK_5.md` |
| `Phase.PREPARATION` and `Phase.BEFORE_SCORING` | Complete | `TASK_5.md` |
| Action union (`ChooseSubAction`, `CommitSow`, `CommitBake`, `FireTrigger`, `Stop`) | Complete | `TASK_5.md` |
| Grain Utilization non-atomic resolution | Complete | `TASK_5.md` |
| Card framework (`cards/__init__.py`, `cards/triggers.py`) | Complete | `TASK_5.md` |
| Potter Ceramics card (the one card in scope) | Complete | `TASK_5.md` |
| `legal_actions` top-level dispatch | Complete | `TASK_5.md` |
| Test scaffolding (`factories.py`, `test_utils.py`) | Complete | `TASK_5.md` |
| `CommitSubAction` hierarchy + generic commit dispatch | Complete | `TASK_5B_DISPATCH_CLEANUP.md`, `CHANGES.md` Change 4 |
| Pending provenance metadata (`initiated_by_id`, `PENDING_ID`) | Complete | `TASK_5B_DISPATCH_CLEANUP.md`, `CHANGES.md` Change 4 |
| Dispatch table relocation (`NONATOMIC_HANDLERS` / `CHOOSE_SUBACTION_HANDLERS` in `resolution.py`; stack helpers in `pending.py`) | Complete | `TASK_5B_DISPATCH_CLEANUP.md` |
| Farmland non-atomic resolution | Complete | `TASK_5C.md` |
| Cultivation non-atomic resolution | Complete | `TASK_5C.md` |
| Side Job non-atomic resolution | Complete | `TASK_5C.md` |
| Sheep / Pig / Cattle Market non-atomic resolution | Complete | `TASK_5C.md` |
| Major Improvement non-atomic resolution (incl. Cooking Hearth payment options, Clay/Stone Oven free Bake) | Complete | `TASK_5C.md` |
| House Redevelopment non-atomic resolution | Complete | `TASK_5C.md` |
| Choose-time flag-setting convention (`*_chosen` fields) | Complete | `TASK_5C.md`, `CHANGES.md` Change 5 |
| Provenance prefix scheme (`"space:<id>"` / `"card:<id>"`) | Complete | `TASK_5C.md`, `CHANGES.md` Change 5 |
| Major improvement costs and baking specs in `constants.py` | Complete | `TASK_5C.md` |
| Bake Bread support for Clay Oven and Stone Oven (greedy-by-rate over all owned baking improvements) | Complete | `TASK_5C.md` |
| `auto_pop` flag on `COMMIT_SUBACTION_HANDLERS` + `CommitBuildMajor` absorbed into generic dispatcher | Complete | `TASK_5D.md`, `CHANGES.md` Change 6 |
| Multi-shot sub-action pending pattern (`PendingBuildStables`, `PendingBuildRooms`) | Complete | `TASK_5D.md`, `CHANGES.md` Change 6 |
| Farm Expansion non-atomic resolution | Complete | `TASK_5D.md` |
| Side Job migrated to `PendingBuildStables`; `PendingBuildStable` (singular) retired | Complete | `TASK_5D.md` |
| `ROOM_COSTS` constant + `_can_afford(p, cost)` + predicate-enumerator deduplication (`_can_build_stable`, `_legal_room_cells`) | Complete | `TASK_5D.md`, `CHANGES.md` Change 6 |
| `_new_grid_with_cell` helper in `resolution.py` | Complete | `TASK_5D.md` |
| Pasture cache recompute on stable build (fixes latent Task 5C bug) | Complete | `TASK_5D.md`, `CHANGES.md` Change 6 |

**Not yet implemented:**

- Non-atomic resolution for the two remaining spaces: **Farm Redevelopment**, **Fencing** (selecting them via `PlaceWorker(...)` still raises `NotImplementedError`).
- `fencing` legality (still missing entirely).
- Harvest phases (HARVEST_FIELD / HARVEST_FEED / HARVEST_BREED).
- Rounds 5–14 (engine halts in `Phase.BEFORE_SCORING` after round 4's RETURN_HOME).
- Cards other than Potter Ceramics, and the action-space paths that would let players play minor improvements or occupations (`lessons` remains permanently illegal in the Family game; the optional minor / improvement paths at Basic Wish for Children, House Redevelopment, Major Improvement, and Farm Redevelopment depend on minor-card support arriving).

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

| File | Description |
|---|---|
| `ARCHITECTURE.md` | Original full architecture spec, game rules reference, and original dataclass definitions. Field names may diverge from current code — inline annotations flag known discrepancies. |
| `RULES.md` | Complete rules reference for the 2-player Family game, including action space descriptions, major improvement effects, harvest rules, animal accommodation, and scoring tables. |
| `STRATEGY.md` | AI strategy and algorithm decisions: action space structure, MCTS approach, neural network design, and the rationale behind each project phase. |
| `CHANGES.md` | Significant cross-cutting refactors that touched many files at once (Resources extraction; two-track pasture cache model; dispatch refactor + pending provenance). |
| `CLEANUP.md` | Three small targeted field-level fixes (house material location, field rename, field removal). |
| `SESSION_HISTORY.md` | Full record of what was built each session, including design decisions made and bugs caught. |
| `IMPLEMENTATION_CHOICES.md` | Fine-grained design decisions that worked well for the Family game but may need revisiting when cards are added. |
| `POSSIBLE_NEXT_STEPS.md` | Living planning doc — directions the project could take next, organized by scope and effort. Updated as the project progresses. |
| `TASK_*.md` | Implementation task files, one per development task. |
| `SESSION_INTRODUCTION.md` | Standard prompt to give a new coding agent at the start of a session. |

---

## Directory Structure

```
AgricolaBot/
    agricola/                   # Game engine package
        __init__.py
        constants.py
        resources.py
        pasture.py
        state.py
        setup.py
        helpers.py
        actions.py
        pending.py              # frozen pending-decision dataclasses (Task 5)
        legality.py
        resolution.py
        scoring.py
        engine.py               # step + _advance_until_decision (Task 5)
        cards/                  # card framework + concrete cards
            __init__.py
            triggers.py         # TRIGGERS / CARDS registries + register()
            potter_ceramics.py  # the one card implemented in Task 5
    tests/                      # pytest test suite
        __init__.py
        factories.py            # prefabricated-state helpers (Task 5)
        test_utils.py           # run_actions, random_agent_play (Task 5)
        test_state.py
        test_helpers.py
        test_scoring.py
        test_legality_atomic.py
        test_legality_non_atomic.py
        test_resolution_atomic.py
        test_engine.py          # step, phase resolvers, random-agent (Task 5)
        test_grain_utilization.py    # non-atomic resolution tests (Task 5)
        test_potter_ceramics.py      # card-trigger tests (Task 5)
        test_bake_bread.py           # _execute_bake / spec-extension registry (Task 5C)
        test_farmland.py             # Task 5C
        test_cultivation.py          # Task 5C
        test_side_job.py             # Task 5C; updated for multi-shot in Task 5D
        test_animal_markets.py       # Task 5C
        test_major_improvement.py    # Task 5C
        test_house_redevelopment.py  # Task 5C
        test_farm_expansion.py       # Task 5D — multi-shot pending pattern
```

---

## Python File Descriptions

### `agricola/__init__.py`

Empty package marker. Makes `agricola` importable as a Python package. No code here.

---

### `agricola/resources.py`

Defines two small data containers that hold quantities of things:

- **`Resources`** — holds counts of the seven goods a player can have in their personal supply: `wood`, `clay`, `reed`, `stone`, `food`, `grain`, `veg`. Supports addition (`r1 + r2`), subtraction (`r1 - r2`), and truthiness (`bool(r)` is `True` if any field is nonzero). All three operators return new instances; nothing mutates. Subtraction is used at pure-subtraction cost-debit sites (e.g. `p.resources - cost`); mixed subtract-and-add operations stay in the `r + Resources(field=-x, ...)` form (see "Code Conventions" → "Resource arithmetic").

- **`Animals`** — holds counts of the three animal types: `sheep`, `boar`, `cattle`.

Both are frozen dataclasses (immutable). They were originally in `state.py` but were extracted here so that `constants.py` could import them without creating a circular import.

---

### `agricola/constants.py`

All the named enumerations and lookup tables the engine uses. Nothing in here is computed at runtime — it is all fixed game data.

- **`Phase`** enum — the seven phases a `GameState` can be in: `WORK`, `RETURN_HOME`, `PREPARATION`, `HARVEST_FIELD`, `HARVEST_FEED`, `HARVEST_BREED`, `BEFORE_SCORING`. (`PREPARATION` and `BEFORE_SCORING` added in Task 5; harvest phases remain unused until the harvest task.)
- **`HouseMaterial`** enum — `WOOD`, `CLAY`, `STONE`.
- **`CellType`** enum — `EMPTY`, `ROOM`, `FIELD`, `STABLE`.
- **`PERMANENT_ACTION_SPACES`** — ordered list of the 11 action space IDs that are always on the board.
- **`STAGE_CARDS`** — dict mapping stage number (1–6) to the list of action space IDs that appear in that stage (in random order within the stage).
- **`BUILDING_ACCUMULATION_RATES`** — maps the 5 building-resource accumulation space IDs (`forest`, `clay_pit`, etc.) to a `Resources` object representing how much accumulates per round. Using `Resources` objects here (rather than plain integers) is what allows cards like the Geologist occupation to change what accumulates on a space without special-casing in resolution.
- **`FOOD_ANIMAL_ACCUMULATION_RATES`** — maps the 5 food/animal accumulation space IDs (`fishing`, `sheep_market`, etc.) to `(field_name, rate)` tuples. These use a plain integer scalar instead of a `Resources` object because they are never modified by cards in the same way.
- **`ACCUMULATION_SPACES`** — a frozenset of all 10 accumulation space IDs, derived as the union of the two dicts above.
- **`HARVEST_ROUNDS`**, **`NUM_ROUNDS`**, **`NUM_MAJOR_IMPROVEMENTS`** — numeric constants.
- **`STAGE_ROUNDS`** — convenience dict mapping stage number to its `(first_round, last_round)` inclusive, used in tests.
- **`MAJOR_IMPROVEMENT_COSTS`** — tuple of length 10, indexed by major_idx, giving each major improvement's standard cost as a `Resources` object. The Cooking Hearth alternate-payment path (return a Fireplace) is handled in resolution code, not encoded here.
- **`ROOM_COSTS`** — dict keyed by `HouseMaterial` (WOOD / CLAY / STONE) giving each material's per-room cost as a `Resources` object (5 of the material + 2 reed). Mirrors the `MAJOR_IMPROVEMENT_COSTS` shape. Used by both `_can_afford_room` in `legality.py` and `_choose_subaction_farm_expansion` in `resolution.py`.
- **`BAKING_IMPROVEMENT_SPECS`** — dict keyed by major_idx (0, 1, 2, 3, 5, 6) giving each baking improvement's per-action `(max_grain_per_action, food_per_grain)` tuple. `None` cap means "any amount" (Fireplace, Cooking Hearth). Used by the greedy-by-rate allocator in `_execute_bake` and the per-action grain-cap computation in `_enumerate_pending_bake_bread`.
- **`FIREPLACE_INDICES`**, **`COOKING_HEARTH_INDICES`** — tuples of the two indices for each cookware family. Used in legality predicates for Cooking Hearth's alternate payment (return a Fireplace).
- **`BAKING_IMPROVEMENTS`** — frozenset of all major-improvement indices that grant a Bake Bread capability. Derived from `BAKING_IMPROVEMENT_SPECS.keys()`. Previously lived in `legality.py`; migrated to `constants.py` in Change 5 for centralized constants.

---

### `agricola/pasture.py`

Small standalone module that owns the `Pasture` dataclass and the BFS that turns raw `(grid, horizontal_fences, vertical_fences)` arrays into a tuple of `Pasture` objects.

- **`Pasture`** — frozen dataclass with three fields: `cells: frozenset[(row, col)]` (the cells that make up this pasture), `num_stables: int` (stables inside the pasture), and `capacity: int` (precomputed as `2 × num_cells × (2 ** num_stables)`).
- **`compute_pastures_from_arrays(grid, horizontal_fences, vertical_fences) -> tuple[Pasture, ...]`** — the public function. Implements the flood-fill from outside the grid, identifies enclosed connected components, and packages each as a `Pasture`. Returns the tuple sorted canonically by `min(p.cells)` (lexicographic on `(row, col)`) so equivalent farmyards always produce equal `pastures` tuples — required for `Farmyard.__eq__` and hashing across MCTS.
- **`_are_connected(horizontal_fences, vertical_fences, r1, c1, r2, c2)`** — private helper used by the BFS. Returns `True` if two orthogonally adjacent cells have no fence between them.

`pasture.py` imports only from `agricola.constants` (for `CellType`) and reads `grid[r][c].cell_type` via duck typing rather than importing `Cell` — a deliberate module-layering choice that keeps `pasture.py` independent of `state.py`.

---

### `agricola/state.py`

All the frozen dataclasses that together represent a complete snapshot of a game in progress. Nothing is ever mutated; all transitions use `dataclasses.replace(...)` to produce new objects.

- **`Cell`** — one cell of a player's 3×5 farmyard grid. Stores the cell type (`EMPTY`, `ROOM`, `FIELD`, `STABLE`) and any grain/veg counts if it is a field. House material is stored on `PlayerState`, not on `Cell` (see CLEANUP.md Cleanup 1).

- **`Farmyard`** — the complete farmyard for one player. Contains the 3×5 `grid` of `Cell` objects (stored as a tuple of tuples), two fence arrays, and a cached `pastures: tuple[Pasture, ...]` decomposition. The two fence arrays are: `horizontal_fences` (shape 4×5, one bool per horizontal edge between rows) and `vertical_fences` (shape 3×6, one bool per vertical edge between columns). See `ARCHITECTURE.md` for the exact index conventions. The `pastures` cache is canonically ordered by `min(p.cells)` so equivalent farmyards always compare equal — required for `Farmyard.__eq__` and hashing across MCTS. The cache is maintained by caller discipline: the four pasture-changing resolvers (Fencing, Farm Expansion's stable build, Side Job's stable build, Farm Redevelopment's fence build) construct the new `Farmyard` with an explicit `pastures=compute_pastures_from_arrays(new_grid, new_h, new_v)` kwarg; all other `Farmyard` mutations use `dataclasses.replace(farmyard, ...)` and leave `pastures` alone, which is correct because these mutations cannot change pastures. A fresh `Farmyard` constructed without any fences or stables (e.g. by `setup`) correctly has `pastures=()` via the placeholder default. This is the first accepted exception to "Derived data, not cached data" — see CHANGES.md Change 2 (and CHANGES.md Change 3 for why auto-fill in `__post_init__`, the obvious structural alternative, is not used).

- **`ActionSpaceState`** — the state of one action space on the board. Tracks how many workers each player has placed on it (`workers`, a 2-tuple of ints), any accumulated building resources (`accumulated`, a `Resources` object — used for the 5 building-resource spaces), any accumulated food/animals (`accumulated_amount`, a plain int — used for the 5 food/animal spaces), and which round the space is first revealed (`round_revealed`, 0 for permanent spaces).

- **`PlayerState`** — everything about one player: their `Resources`, their `Animals`, their `Farmyard`, how many people they have in total and how many are currently at home, how many newborns were born during the current round (cleared by `_resolve_preparation` of the next round; if a harvest immediately follows, these newborns cost 1 food at that harvest instead of 2), begging markers, a `future_resources: tuple[Resources, ...]` of length 14 (per-round promised goods — populated by the Well major improvement when implemented), and frozensets `minor_improvements` and `occupations` recording played card IDs.

- **`BoardState`** — the shared board: a dict mapping action space ID strings to `ActionSpaceState` objects, a tuple recording who owns each of the 10 major improvements, and the `round_card_order` tuple (the randomly-ordered stage cards).

- **`GameState`** — the top-level snapshot. Holds the round number, phase, which player is currently acting (`current_player`: whose worker placement is currently being resolved), who holds the starting player token, the two `PlayerState` objects, the `BoardState`, and `pending_stack: tuple[PendingDecision, ...]` (the stack of in-progress sub-decisions). (A `next_starting_player` field was briefly present but removed as redundant — `starting_player` is updated immediately when Meeting Place is taken. See CLEANUP.md Cleanup 3.)

---

### `agricola/setup.py`

Contains the single public function `setup(seed: int) -> GameState`, which builds the initial game state for a 2-player Family game.

Internally it uses a seeded NumPy RNG (`numpy.random.default_rng(seed)`) to determine the starting player and shuffle the stage cards within each stage. All randomness is resolved here; after `setup` returns the engine is fully deterministic.

The private helpers inside this file are:
- `_make_round_card_order(rng)` — shuffles cards within each stage and concatenates them into a 14-element tuple.
- `_make_action_spaces(round_card_order)` — builds the initial `ActionSpaceState` for all 25 spaces, pre-loading round-1 accumulated goods onto the accumulation spaces.
- `_make_farmyard()` — builds a fresh farmyard with wood rooms at cells (1,0) and (2,0) and all fences False.
- `_make_player(food)` — builds a starting `PlayerState` with the given food amount, 2 people, and an empty farmyard.

---

### `agricola/helpers.py`

Pure functions for derived quantities and the animal accommodation logic. These are the computational workhorses that other modules call; none of them mutate state.

**Simple derived quantities:**
- `fences_in_supply(farmyard)` — counts True values in both fence arrays, subtracts from 15.
- `stables_in_supply(farmyard)` — counts `STABLE` cells, subtracts from 4.
- `cooking_rates(state, player_idx)` — returns a `(sheep_rate, boar_rate, cattle_rate)` tuple based on which cooking improvement the player owns. Cooking Hearth returns `(2, 3, 4)`, Fireplace returns `(2, 2, 3)`, neither returns `(0, 0, 0)`.

**Pasture-derived helpers:**

The `Pasture` dataclass and the BFS that builds the pasture decomposition live in `agricola/pasture.py`. The decomposition itself is cached on `Farmyard.pastures` (see the `Farmyard` description above for how the cache is maintained), so reading it is O(1). Helpers in `helpers.py` derive from that cache:

- `enclosed_cells(farmyard) -> frozenset[(row, col)]` — returns the union of all cells inside any pasture. Used by legality code that needs membership lookups (e.g. "can a field be placed at this cell?").

**Animal accommodation:**
- `extract_slots(player_state)` — returns `(pasture_capacities, num_flexible)`. Reads `player_state.farmyard.pastures` (the cached decomposition) and returns the list of pasture capacities plus the count of single-animal flexible slots (one per standalone (unfenced) stable, plus one always for the house pet).
- `can_accommodate(pasture_capacities, num_flexible, sheep, boar, cattle)` — checks whether a given animal count is physically accommodatable on the farm. Each pasture holds exactly one animal type. The algorithm tries all possible type-to-pasture assignments (brute force over the small number of pastures) and returns `True` if any assignment leaves no more overflow animals than there are flexible slots.
- `pareto_frontier(player_state, gained, rates)` — used when a player gains animals (e.g. takes the Sheep Market). Enumerates all achievable `(sheep, boar, cattle)` configurations (bounded by current inventory + gained, and by farm capacity), removes dominated configurations, and returns a list of `(Animals, food_gained)` pairs. The food is what the player earns by converting excess animals to food at the given cooking rates. The agent picks one point from this frontier.
- `breeding_frontier(player_state, rates)` — the same Pareto frontier logic, but for the breeding phase of harvest. The upper bound for each animal type is `current + 1` if the player has ≥ 2 (breeding fires), otherwise `current`. The food formula accounts for whether breeding fired when computing how many animals were consumed pre-breeding.

---

### `agricola/actions.py`

Defines the action types the engine's `step` accepts. Every action is a frozen dataclass. Dispatched via `isinstance` checks in `engine._apply_action`.

- **`PlaceWorker(space: str)`** — place the active player's worker on a named action space. For atomic spaces this is the complete action. For non-atomic spaces this initiates the chain of sub-decisions.
- **`ChooseSubAction(name: str)`** — pick a sub-action category at a non-atomic space's pending decision. Categories are space-specific strings (e.g., `"sow"`, `"bake_bread"` at Grain Utilization).
- **`CommitSubAction`** — frozen-dataclass marker base for all `Commit*` sub-action types. Empty (no fields). Concrete subclasses inherit from it. All are dispatched uniformly by `_apply_commit_subaction` in `engine.py` via the `COMMIT_SUBACTION_HANDLERS` table (post-Task-5D: `CommitBuildMajor` was absorbed into the generic path with `auto_pop=False`).
- **`CommitSow(grain: int, veg: int)`** — commit a sow. Pops `PendingSow`.
- **`CommitBake(grain: int)`** — commit a Bake Bread with the chosen grain amount. Pops `PendingBakeBread`.
- **`CommitPlow(row: int, col: int)`** — commit a plow at the chosen cell. Pops `PendingPlow`.
- **`CommitBuildStable(row: int, col: int)`** — commit a stable build at the chosen cell. The cost paid is read from the host `PendingBuildStables.cost` field. Does NOT pop `PendingBuildStables` (multi-shot pattern, `auto_pop=False`); `Stop` pops it.
- **`CommitBuildRoom(row: int, col: int)`** — commit a room build at the chosen cell. The cost paid is read from the host `PendingBuildRooms.cost` field (set from `ROOM_COSTS[p.house_material]` at push time). Does NOT pop `PendingBuildRooms` (multi-shot pattern, `auto_pop=False`); `Stop` pops it.
- **`CommitBuildMajor(major_idx: int, return_fireplace_idx: int | None = None)`** — purchase a major improvement. For Cooking Hearth, `return_fireplace_idx` may be 0 or 1 to pay by returning that Fireplace. Dispatched via the generic commit dispatcher with `auto_pop=False`; the effect function owns the conditional stack manipulation (pop for non-ovens, push wrapper for Clay/Stone Oven).
- **`CommitRenovate()`** — commit a renovation (parameterless; the cost and material transition are derived from current state and `pending.cost`). Pops `PendingRenovate`.
- **`CommitAccommodate(sheep: int, boar: int, cattle: int)`** — commit the final animal configuration after taking from a market. Lands directly on `PendingSheepMarket` / `PendingPigMarket` / `PendingCattleMarket` (no separate sub-action pending). Dispatcher entry uses a tuple of pending types.
- **`FireTrigger(card_id: str)`** — fire a specific card trigger that's currently eligible at the top pending.
- **`Stop()`** — end the current non-atomic action (pop the top pending frame). Legal at parent pendings once at least one sub-action has been chosen.
- **`Action`** — the union alias listing the concrete subclasses (`PlaceWorker | ChooseSubAction | CommitSow | CommitBake | CommitPlow | CommitBuildStable | CommitBuildRoom | CommitBuildMajor | CommitRenovate | CommitAccommodate | FireTrigger | Stop`). The `CommitSubAction` base is intentionally not in the union — concrete subclasses are listed so legality enumerators and type checkers see the real options. There is no `SkipTrigger`: declining a trigger is implicit.

---

### `agricola/pending.py`

Frozen pending-decision dataclasses *and* the stack operations on them. The stack itself lives on `GameState.pending_stack`; this module owns both the element types and the three pure functions for manipulating the stack. Imports `GameState` from `state.py` (no cycle: `state.py` stores `pending_stack: tuple` without parameterizing the type).

**Pending dataclasses.** Every pending class carries:
- `player_idx: int` — whose decision this frame is for.
- `initiated_by_id: str` (mandatory, no default) — what pushed this frame onto the stack. See CLAUDE.md "Pending provenance metadata".
- `PENDING_ID: ClassVar[str]` — the kind of pending (flow or event it represents).

**Sub-action pendings** host a single `CommitX` action; pushed by `ChooseSubAction` at a parent or by a card trigger; popped when the commit fires.

- **`PendingSow(player_idx, initiated_by_id)`** — `PENDING_ID = "sow"`. Pushed by `ChooseSubAction("sow")`. Pops on `CommitSow`.
- **`PendingBakeBread(player_idx, initiated_by_id, triggers_resolved=frozenset())`** — `PENDING_ID = "bake_bread"`, `TRIGGER_EVENT = "before_bake_bread"`. `triggers_resolved` is scoped to this frame's lifetime.
- **`PendingPlow(player_idx, initiated_by_id, triggers_resolved=frozenset())`** — `PENDING_ID = "plow"`, `TRIGGER_EVENT = "before_plow"`. Used by Farmland and Cultivation.
- **`PendingBuildStables(player_idx, initiated_by_id, cost, max_builds, num_built=0)`** — `PENDING_ID = "build_stables"`. Multi-shot pending: each `CommitBuildStable` increments `num_built` and leaves the pending on top (`auto_pop=False`); `Stop` is the explicit exit. `cost: Resources` is per-commit (1 wood for Side Job; 2 wood for Farm Expansion; future cards may inject other costs). `max_builds: int | None` is a caller-imposed cap (`None` = no cap; Side Job sets 1; Farm Expansion sets None). Supply/affordability/cell checks live in the enumerator. No card-trigger fields yet (`triggers_resolved` / `TRIGGER_EVENT` deferred until a card needs them). See "Sub-action cost handling" → bucket 2, and "Multi-shot sub-action pendings".
- **`PendingBuildRooms(player_idx, initiated_by_id, cost, max_builds, num_built=0)`** — `PENDING_ID = "build_rooms"`. Multi-shot pending mirroring `PendingBuildStables`. `cost: Resources` is set at push time from `ROOM_COSTS[p.house_material]`. Farm Expansion pushes with `max_builds=None`; future cards may set integer caps.
- **`PendingBuildMajor(player_idx, initiated_by_id, build_chosen=False, triggers_resolved=frozenset())`** — `PENDING_ID = "build_major"`, `TRIGGER_EVENT = "before_build_major"`. `build_chosen` is set by `_execute_build_major` and matters only for oven majors (Clay/Stone Oven), where `PendingBuildMajor` lingers below the oven wrapper while the optional free bake resolves. Cost is NOT on this pending — it's looked up in `MAJOR_IMPROVEMENT_COSTS` by `commit.major_idx`. See "Sub-action cost handling" → bucket 3.
- **`PendingRenovate(player_idx, initiated_by_id, cost, triggers_resolved=frozenset())`** — `PENDING_ID = "renovate"`, `TRIGGER_EVENT = "before_renovate"`. `cost: Resources` is set at push time by `_choose_subaction_house_redevelopment` based on current house material and room count.

**Parent pendings** host `ChooseSubAction` and (after a flag flips) `Stop`. Include both top-level pendings pushed by `PlaceWorker` and non-top-level wrapper pendings pushed by special-case commit handlers.

- **`PendingGrainUtilization(player_idx, initiated_by_id, sow_chosen=False, bake_chosen=False)`** — `PENDING_ID = "grain_utilization"`. Stop-legality requires `sow_chosen or bake_chosen`.
- **`PendingFarmExpansion(player_idx, initiated_by_id, room_chosen=False, stable_chosen=False)`** — `PENDING_ID = "farm_expansion"`. Stop-legality requires `room_chosen or stable_chosen`. Once-per-category: a player who chooses build_rooms, exits via Stop, and returns to the parent cannot re-enter build_rooms. No `triggers_resolved` / `TRIGGER_EVENT` yet (deferred until cards need them).
- **`PendingFarmland(player_idx, initiated_by_id, plow_chosen=False, triggers_resolved=frozenset())`** — `PENDING_ID = "farmland"`. Stop-legality requires `plow_chosen`.
- **`PendingCultivation(player_idx, initiated_by_id, plow_chosen=False, sow_chosen=False, triggers_resolved=frozenset())`** — `PENDING_ID = "cultivation"`. Stop-legality requires at least one of `plow_chosen`/`sow_chosen`.
- **`PendingSideJob(player_idx, initiated_by_id, stable_chosen=False, bake_chosen=False, triggers_resolved=frozenset())`** — `PENDING_ID = "side_job"`. Stop-legality requires at least one of `stable_chosen`/`bake_chosen`.
- **`PendingSheepMarket`, `PendingPigMarket`, `PendingCattleMarket(player_idx, initiated_by_id, gained, triggers_resolved=frozenset())`** — `PENDING_ID`s `"sheep_market"`, `"pig_market"`, `"cattle_market"`. The `gained: int` field stages animals taken from the market (not yet on the player) until `CommitAccommodate` finalizes the configuration. No ChooseSubAction; `CommitAccommodate` lands directly on the parent and pops it.
- **`PendingMajorMinorImprovement(player_idx, initiated_by_id, major_chosen=False, minor_chosen=False, triggers_resolved=frozenset())`** — `PENDING_ID = "major_minor_improvement"`. `minor_chosen` is forward-compat (no path to set it in Family scope).
- **`PendingHouseRedevelopment(player_idx, initiated_by_id, renovate_chosen=False, improvement_chosen=False, triggers_resolved=frozenset())`** — `PENDING_ID = "house_redevelopment"`. `Stop` is legal only after `renovate_chosen` is True (renovate is mandatory first).
- **`PendingClayOven(player_idx, initiated_by_id, bake_chosen=False)`** — non-top-level wrapper pending pushed by `_execute_build_major` when `major_idx == 5`. Hosts the optional free Bake Bread offered by Clay Oven purchase. No `TRIGGER_EVENT` — cards that trigger on oven-purchase-bake attach to the inner `PendingBakeBread`'s `"before_bake_bread"` event.
- **`PendingStoneOven(player_idx, initiated_by_id, bake_chosen=False)`** — mirror of `PendingClayOven` for Stone Oven (`major_idx == 6`).

- **`PendingDecision`** — the union alias over all pending types above. Future pending types are added here as more non-atomic spaces' resolutions are implemented.

**Stack operations.** Pure functions; all return new `GameState` objects (never mutate). Used by `engine.py` and `resolution.py`.
- `push(state, frame)` — append a frame to `state.pending_stack`.
- `pop(state)` — drop the top frame.
- `replace_top(state, new_top)` — replace the top frame.

---

### `agricola/legality.py`

Determines which actions are legal from a given game state. Covers all 12 **atomic** action spaces and 11 of the 13 **non-atomic** action spaces. `fencing` legality is deferred (requires enumerating valid fence configurations); `lessons` is permanently illegal in the Family game and is intentionally absent from every dispatch table. Also provides per-pending sub-action enumerators (Task 5).

- The 12 atomic spaces: `day_laborer`, `fishing`, `forest`, `clay_pit`, `reed_bank`, `grain_seeds`, `meeting_place`, `western_quarry`, `vegetable_seeds`, `eastern_quarry`, `basic_wish_for_children`, `urgent_wish_for_children`.
- The 11 non-atomic spaces with legality predicates: `farm_expansion`, `farmland`, `side_job`, `grain_utilization`, `sheep_market`, `pig_market`, `cattle_market`, `major_improvement`, `house_redevelopment`, `cultivation`, `farm_redevelopment`. After Task 5D, only `farm_redevelopment` and `fencing` remain without resolution; the other 10 + Farm Expansion are fully implemented.

Internal structure:
- `_is_available(state, space)` — the cross-cutting check shared by all spaces: the space must be unoccupied (`workers == (0, 0)`) and currently revealed (`round_revealed <= round_number`).
- One private predicate function per space, adding space-specific checks on top of `_is_available`. Most accumulation spaces require at least one accumulated good to be present (it is illegal to take an empty accumulation space). The Wish for Children spaces additionally require that the current player has fewer than 5 people and (for Basic Wish) has more rooms than people. Non-atomic predicates check the player can actually execute at least one of the space's effects.
- Shared helpers used across non-atomic predicates: `_owns_baker(state, p)`, `_can_bake_bread(state, p)`, `_can_sow(p)`, `_can_plow(p)`, `_can_build_stable(p, cost)`, `_can_afford(p, cost)`, `_can_afford_room(p)`, `_has_room_placement(p)`, `_can_build_room(p)`, `_can_renovate(p)`, `_can_afford_major(state, p, idx)`, `_can_afford_any_major_improvement(state, p)`. These follow the player-parameter convention in the Additional Design Principles section above. `BAKING_IMPROVEMENTS` lives in `constants.py`. `ROOM_COSTS` (per-material room cost dict) lives in `constants.py`. `_can_afford_room` is a one-liner over `_can_afford(p, ROOM_COSTS[p.house_material])`. `_can_build_stable(p, cost)` combines supply + cell-availability + affordability and replaces the deleted `_has_stable_placement` (which had no cost dimension).
- Cell-enumeration helpers: `_legal_plow_cells(p)` (used by `_enumerate_pending_plow` and by `_can_plow`, which is now a one-liner over it), `_legal_stable_cells(p)` (used by `_enumerate_pending_build_stables` and by `_can_build_stable`), `_legal_room_cells(p)` (used by `_enumerate_pending_build_rooms` and by `_has_room_placement`, which is now a one-liner over it).
- **Card extension registries**:
  - `BAKE_BREAD_ELIGIBILITY_EXTENSIONS: list[Callable]` — card-supplied predicates that may broaden `_can_bake_bread`. Cards register via `register_bake_bread_extension(fn)`. (Potter Ceramics registers an extension that accepts clay >= 1 as a valid baking precondition.)
  - `BAKING_SPEC_EXTENSIONS: list[Callable]` — card-supplied baking source contributors. Each registered fn takes `(state, player_idx)` and returns a list of `(max_grain_per_action, food_per_grain)` tuples. Cards register via `register_baking_spec_extension(fn)`. The helper `baking_specs_for_player(state, player_idx)` combines major-improvement specs (from `BAKING_IMPROVEMENT_SPECS`) with card-driven contributions; both `_execute_bake` and `_enumerate_pending_bake_bread` consume this combined list.
- Per-pending enumerators: `_enumerate_pending_X` for each pending type, dispatched via `PENDING_ENUMERATORS`. Signature `(state, pending: PendingX) -> list[Action]` — see "Code Conventions" → "Per-pending enumerator signatures".
- Dispatch dicts: `ATOMIC_LEGALITY`, `NON_ATOMIC_LEGALITY`, the combined `ALL_LEGALITY = {**ATOMIC_LEGALITY, **NON_ATOMIC_LEGALITY}`, and `PENDING_ENUMERATORS`.
- `legal_placements(state)` — internal helper. Returns a list of `PlaceWorker` actions, one for each space (atomic or non-atomic) whose predicate returns `True`. Returns an empty list if the current player has no workers left. Never returns `fencing` or `lessons`.
- **`legal_actions(state)`** — the top-level public legality entry point. Dispatches on stack state: empty stack + WORK phase → `legal_placements`; non-empty stack → `_enumerate_pending` on the top frame; `BEFORE_SCORING` → empty list. All callers (agent loops, tests) should use `legal_actions` rather than `legal_placements` directly.

---

### `agricola/resolution.py`

Per-space resolution code. Atomic and non-atomic space handlers, sub-action effect functions, and the function-pointer dispatch tables for them. Imported by `agricola.engine` for dispatch. Never mutates state — always uses `dataclasses.replace(...)`.

Three utility wrappers:
- `_update_player(state, ap, new_player)` — new `GameState` with one player replaced.
- `_update_space(state, space_id, **kwargs)` — new `GameState` with one action space's fields updated.
- `_new_grid_with_cell(grid, row, col, cell)` — new 3×5 grid identical to `grid` except at `(row, col)`, which is replaced. Used by `_execute_plow`, `_execute_build_stable`, and `_execute_build_room` instead of inline nested tuple-comprehensions.

**Cross-cutting bookkeeping.**
- `_apply_worker_placement(state, space_id)` — increments `workers[ap]` on the space and decrements `people_home` on the active player. Run for every worker placement.

**Atomic handlers.** Per-space `_resolve_<space>` functions for the 12 atomic spaces, each receiving the state *after* `_apply_worker_placement` and applying the space's specific effect (adding goods to the player's supply, resetting accumulated goods, updating the starting player token, etc.). Two shared helpers — `_resolve_building_accumulation` (for `forest`, `clay_pit`, `reed_bank`, `western_quarry`, `eastern_quarry`) and `_resolve_food_accumulation` (for `fishing` and `meeting_place`) — avoid repetition.

**Non-atomic initiators.** `_initiate_<space>` functions push the space's parent pending. Implemented for: `grain_utilization`, `farmland`, `cultivation`, `side_job`, `sheep_market`, `pig_market`, `cattle_market`, `major_improvement`, `house_redevelopment`, `farm_expansion`. Each pushes its respective `Pending<Space>` with `initiated_by_id="space:<space_id>"`. The three market initiators additionally read `accumulated_amount` off the action space, zero it, and stage the count on the pending as `gained`. The two still-deferred spaces (`farm_redevelopment`, `fencing`) raise `NotImplementedError` at `_apply_place_worker`.

**Choose-sub-action handlers.** `_choose_subaction_<space>` functions handle `ChooseSubAction` at that space's parent pending. Each follows the choose-time convention: set the corresponding `*_chosen` flag on the parent via `replace_top`, then push the sub-action pending with `initiated_by_id=top.PENDING_ID`. Implemented for: grain_utilization, farmland, cultivation, side_job, major_minor_improvement, clay_oven, stone_oven, house_redevelopment, farm_expansion. (Animal markets have no choose step — commit lands directly on the parent.)

**Sub-action effect functions.** `_execute_<sub_action>(state, player_idx, commit)` functions apply the effect of a committed sub-action. Each takes the commit action object as the third argument so a single dispatcher can call any effect uniformly. Effect functions MAY read `state.pending_stack[-1]` to access their own pending frame (the dispatcher guarantees it is still on top during effect execution); this is how cost-on-pending sub-actions (`_execute_build_stable`, `_execute_build_room`, `_execute_renovate`) recover their cost.
- `_execute_sow(state, player_idx, commit)` — fills empty fields with grain or veg.
- `_execute_bake(state, player_idx, commit)` — greedy-by-rate allocation across all owned baking improvements. Consults `baking_specs_for_player` (in `legality.py`) to collect `(cap, rate)` tuples from `BAKING_IMPROVEMENT_SPECS` plus any card-registered sources, processes sources in rate-descending order.
- `_execute_plow(state, player_idx, commit)` — places a `FIELD` cell at `(commit.row, commit.col)`.
- `_execute_build_stable(state, player_idx, commit)` — multi-shot stable effect. Places a `STABLE` cell at `(commit.row, commit.col)`, debits `pending.cost`, increments `pending.num_built`. Does NOT pop (`auto_pop=False`); `Stop` is the explicit exit. Recomputes `Farmyard.pastures` explicitly via `compute_pastures_from_arrays` — required because a stable placed inside an existing pasture changes that pasture's `num_stables`/`capacity`. (Post-Task-5D rewrite; the body was renamed in from `_execute_build_stables` during step 7's atomic swap.)
- `_execute_build_room(state, player_idx, commit)` — multi-shot room effect. Places a `ROOM` cell at `(commit.row, commit.col)`, debits `pending.cost`, increments `pending.num_built`. Does NOT pop. No pasture recompute needed — rooms cannot legally land in enclosed cells (`_legal_room_cells` enforces). `people_total` unchanged; new rooms are empty until a Wish for Children populates them.
- `_execute_renovate(state, player_idx, commit)` — advances the player's `house_material` and debits `pending.cost`. Material transition (WOOD→CLAY, CLAY→STONE) derived from current material.
- `_execute_build_major(state, player_idx, commit)` — pays cost (either standard or via Fireplace-return for Cooking Hearth), assigns ownership, writes Well's `+1 food` into the next 5 future-resource entries if applicable, sets `build_chosen=True` on `PendingBuildMajor`, then either pops `PendingBuildMajor` (non-oven) or pushes `PendingClayOven`/`PendingStoneOven` (oven majors). Dispatched via the generic `COMMIT_SUBACTION_HANDLERS` path with `auto_pop=False` — the dispatcher does not pop after the effect; the function owns its own conditional pop/push.
- `_execute_accommodate(state, player_idx, commit)` — sets the player's animals to the chosen frontier point and converts excess to food at the player's cooking rates. Lands on any of the three animal-market pendings via tuple-of-types dispatch in `COMMIT_SUBACTION_HANDLERS`.

**Function-pointer dispatch tables**, each keyed by space-id or pending-type:
- `ATOMIC_HANDLERS: dict[str, callable]` — `space_id → _resolve_<space>`.
- `NONATOMIC_HANDLERS: dict[str, callable]` — `space_id → _initiate_<space>`. Now contains 10 entries.
- `CHOOSE_SUBACTION_HANDLERS: dict[type, callable]` — `pending_type → _choose_subaction_<space>`. Now contains 9 entries (animal markets have no entry because they have no choose step).

The metadata dispatch table for `Commit*` sub-actions (`COMMIT_SUBACTION_HANDLERS`) lives in `engine.py` — it's metadata for the engine's generic commit dispatcher, not a function-pointer table.

---

### `agricola/engine.py`

The state-transition engine. Public API: `step(state, action) -> GameState`. Pure transition function; the loop that drives a game lives outside this module (typically the agent loop in tests).

- **`step(state, action)`** — apply one action and auto-advance through system transitions. Raises `RuntimeError` if called with `Phase.BEFORE_SCORING`. Raises `NotImplementedError` for `PlaceWorker` on `farm_redevelopment` or `fencing` (the two still-deferred non-atomic spaces). Does NOT validate legality — callers assert via `legal_actions`.
- **`_apply_action(state, action)`** — dispatches on action type via five `isinstance` branches: `PlaceWorker`, `ChooseSubAction`, `CommitSubAction` (matches every concrete commit subclass including `CommitBuildMajor` post-Task-5D), `FireTrigger`, `Stop`. (Pre-Task-5D had a special-case branch for `CommitBuildMajor`; absorbed into the generic dispatcher when `auto_pop=False` was added.)
- **`_apply_place_worker(state, action)`** — runs `_apply_worker_placement` (from `resolution.py`) then dispatches via `ATOMIC_HANDLERS` (atomic spaces) or `NONATOMIC_HANDLERS` (non-atomic spaces). The two deferred non-atomic spaces (`farm_redevelopment`, `fencing`) raise `NotImplementedError`.
- **`_apply_choose_sub_action(state, action)`** — dispatches via `CHOOSE_SUBACTION_HANDLERS` keyed by the top pending's type.
- **`_apply_commit_subaction(state, action)`** — generic handler for any `CommitSubAction` subclass. Dispatches via `COMMIT_SUBACTION_HANDLERS` (defined in this module). For each commit type the table holds `(expected_pending_type, effect_fn, auto_pop)` — `expected_pending_type` may be a single type or a tuple of types (animal markets use a tuple). The handler asserts the expected pending is on top, applies the effect, and pops the sub-action pending only if `auto_pop=True`. When `auto_pop=False` the effect function owns any stack manipulation (multi-shot pendings leave themselves on top via `replace_top`; `_execute_build_major` pops for non-ovens or pushes the oven wrapper). The dispatcher does NOT touch parent state — parent `*_chosen` flags are set earlier, at choose-time, by the `_choose_subaction_*` handler that pushed the sub-action pending.
- **`_apply_fire_trigger`** — looks up the trigger via `CARDS[card_id]` (direct O(1) lookup), applies its `apply_fn`, adds `card_id` to the top frame's `triggers_resolved`.
- **`_apply_stop`** — pops the top pending frame. Does NOT assert the stack becomes empty afterward (future cards may have deeper stacks).
- **`_advance_current_player(state)`** — rotates `current_player` to the next player with workers, using modular arithmetic. Called inside `step` only when the stack is empty AND phase is WORK (i.e., a worker placement just completed). NOT called from `_advance_until_decision`.
- **`_advance_until_decision(state)`** — auto-advance loop. Walks system-driven phase transitions until the next agent decision or game-over. Pure state-driven and idempotent. Phase handling: stack non-empty → return; `BEFORE_SCORING` → return; WORK with workers remaining → return; WORK with both players at 0 workers → transition to `RETURN_HOME`; `RETURN_HOME` → `_resolve_return_home`; `PREPARATION` → `_resolve_preparation`. Harvest phases (HARVEST_*) are unimplemented (TODO comment in place).
- **`_resolve_return_home(state)`** — end-of-round bookkeeping: reset every action space's `workers` to `(0, 0)`; set each player's `people_home = people_total`. Does NOT clear `newborns` (those must survive to HARVEST_FEED for the discount). Transitions to `PREPARATION` for rounds < 4, or to `BEFORE_SCORING` for round 4 (current halt point).
- **`_resolve_preparation(state)`** — set up the new round: increment `round_number`, refill every revealed accumulation space, distribute each player's `future_resources[round_number - 1]` into their supply, clear `newborns`, set `current_player = starting_player`, transition to WORK.

**Dispatch table in this module.**
- `COMMIT_SUBACTION_HANDLERS: dict[type, tuple]` — `CommitX → (PendingX_or_tuple_of_types, _execute_x, auto_pop: bool)`. Metadata table for the generic commit dispatcher; co-located with its sole consumer rather than placed alongside the function-pointer dispatch tables in `resolution.py`. Includes `CommitBuildMajor` (with `auto_pop=False`), `CommitBuildStable` (with `PendingBuildStables` and `auto_pop=False` for the multi-shot pattern), and `CommitBuildRoom` (with `PendingBuildRooms` and `auto_pop=False`).

**Stack operations** (`push`, `pop`, `replace_top`) are imported from `pending.py`.

See CLAUDE.md "Engine and Turn Resolution Architecture" for the design philosophies and TASK_5.md / TASK_5B_DISPATCH_CLEANUP.md for the full implementation breakdown.

---

### `agricola/cards/__init__.py`

Card package marker. Imports each card module so their `register()` calls run at module load time, populating the registries in `agricola.cards.triggers` and `BAKE_BREAD_ELIGIBILITY_EXTENSIONS` in `agricola.legality`. Currently imports `potter_ceramics`; future card modules are added here.

---

### `agricola/cards/triggers.py`

The card-trigger registry. Two parallel dicts populated at import time:

- **`TRIGGERS: dict[str, list[TriggerEntry]]`** — event-keyed registry. `TRIGGERS["before_bake_bread"]` returns the list of entries for cards that fire on that event. Used by `legal_actions` enumerators at pending frames to find eligible unfired triggers.
- **`CARDS: dict[str, TriggerEntry]`** — card-id-keyed registry. Direct O(1) lookup by `card_id`. Used by `_apply_fire_trigger` to apply a chosen trigger's effect.
- **`TriggerEntry`** — frozen dataclass with `card_id`, `event`, `eligibility_fn`, `apply_fn`. The same entry appears in both registries.
- **`register(event, card_id, eligibility_fn, apply_fn)`** — called at import time by each card module. Adds the entry to both `TRIGGERS[event]` and `CARDS[card_id]`.

---

### `agricola/cards/potter_ceramics.py`

The one card implemented in Task 5. Effect: "Each time before a Bake Bread action, the owner may exchange exactly 1 clay for 1 grain. At most once per Bake Bread action."

Module contents:
- `CARD_ID = "potter_ceramics"`.
- `_eligible(state, player_idx, triggers_resolved)` — eligibility predicate: card played + clay >= 1 + not already fired this action.
- `_apply(state, player_idx)` — effect: `-1 clay, +1 grain`.
- `_can_bake_bread_extension(state, p)` — broadens `_can_bake_bread` to accept "owns Potter Ceramics + owns baker + clay >= 1" as sufficient (the trigger will swap clay for grain mid-action).
- Module-level `register(...)` and `register_bake_bread_extension(...)` calls fire at import time.

See CLAUDE.md "Card implementation status" for the broader card-system design and the known limitation around compound card interactions.

---

### `agricola/scoring.py`

Computes a player's end-of-game score.

- **`ScoreBreakdown`** dataclass — holds a separate integer for each scoring category (field tiles, pastures, grain, vegetables, sheep, boar, cattle, unused spaces, fenced stables, clay rooms, stone rooms, people, begging markers, major improvement points, craft building bonus points) plus the total. Not frozen — it is only used as a return value, not stored in game state.
- `score(state, player_idx)` — returns `(total_score, ScoreBreakdown)`. Computes each category by reading from the player's farmyard, resources, animals, and the board's major improvement ownership record. Reads `farmyard.pastures` (the cached decomposition) directly for the pasture, fenced-stables, and unused-cell categories.
- `tiebreaker(state, player_idx)` — returns the tiebreaker value: total building resources (wood + clay + reed + stone) in the player's personal supply, after subtracting any resources consumed by craft building end-game bonuses (Joinery, Pottery, Basketmaker's Workshop).
- `_craft_bonus_spending(state, player_idx)` — private helper shared by both `score` and `tiebreaker`. Computes how many bonus points the player earns from their craft buildings and how many resources are consumed in the process.

The scoring tables (how many points for 0 fields, 1 field, 2 fields, etc.) are implemented as small private lookup functions at the top of the file. See **`RULES.md`** for the complete scoring table.

---

### `tests/__init__.py`

Empty package marker. Makes `tests` importable as a Python package. No code here.

---

### `tests/factories.py`

Prefabricated-state helpers used across test files. Each helper takes a state and returns a NEW state (no mutation). Helpers include `with_resources`, `add_resources`, `with_animals`, `with_house`, `with_majors`, `with_minors`, `with_grid`, `with_fields`, `with_sown_fields`, `with_space`, `with_pending_stack`, `with_phase`, `with_round`, `with_current_player`, `with_people`. Tests compose them to reach any state — including states unreachable through gameplay (e.g., a player who has played Potter Ceramics, which requires action spaces not implemented in Task 5). This is the project-wide convention for test state construction; see TASK_5.md "Testing principle: prefabricated states" for rationale.

### `tests/test_utils.py`

Test-side multi-action helpers and the random-agent driver. NOT a test file despite the `test_` prefix — pytest collects no test functions from it because none start with `test_`.

- `run_actions(state, actions)` — apply a scripted sequence of actions; validate each is legal before applying. Used by tests that walk through a specific scenario.
- `IMPLEMENTED_NON_ATOMIC_SPACES`, `_is_implemented_action`, `filter_implemented(actions)` — filter `legal_actions` output to actions `step` can apply (atomic placements + Grain Utilization + all sub-action types). When new non-atomic resolvers land, `IMPLEMENTED_NON_ATOMIC_SPACES` widens automatically.
- `random_agent_play(state, seed)` — plays a random-action game to `Phase.BEFORE_SCORING`. Returns `(terminal_state, trace)`. Raises if the agent gets stuck (would indicate a bug). Used by the end-to-end engine smoke test.

---

### `tests/test_state.py`

Tests for the state dataclasses and the `setup` function. Covers: correct starting food amounts, correct starting room positions, all fences starting False, fresh farmyards have an empty `pastures` cache, correct people counts, all major improvements starting unowned, correct number of stage cards and their correct stage-ordering, determinism (same seed → identical state), `Resources.__add__` / `Resources.__bool__` behaviour, and the Task 5 state fields (empty `pending_stack`, default-empty `future_resources`, `minor_improvements`, `occupations`).

### `tests/test_helpers.py`

Tests for everything in `helpers.py` and the `Farmyard.pastures` cache. Covers: `fences_in_supply` and `stables_in_supply` on fresh and modified farmyards; the pasture decomposition on a range of fence configurations (single-cell pasture, multi-cell, stables inside, subdivided); canonical pasture ordering and structural equality/hashing of equivalent farmyards (the property MCTS subtree sharing depends on); the `enclosed_cells` helper; `extract_slots` including the standalone stable path; `can_accommodate` for feasible and infeasible configurations; `pareto_frontier` for single and multi-type gains with and without cooking rates; `breeding_frontier` for all the breeding food formula branches. All frontier tests assert the complete frontier dict, not just membership of a specific point.

### `tests/test_scoring.py`

Tests for `scoring.py`. Covers: baseline score on a fresh game state (Wood rooms, 2 people, no resources — expected score is deeply negative due to unused spaces and few resources), individual scoring categories in isolation (fields, pastures, animals, major improvements, craft bonuses), and the tiebreaker function.

### `tests/test_legality_atomic.py`

Tests `legal_placements` for the 12 atomic spaces. One or more tests per space. Covers: legal when conditions met, illegal when space is occupied, illegal when space is not yet revealed, illegal when accumulation space is empty (for accumulation spaces), illegal when the player has no workers left to place, and the Wish-specific conditions (room count vs. people count, 5-person cap).

### `tests/test_legality_non_atomic.py`

Tests `legal_placements` for the 11 implemented non-atomic spaces, plus direct tests of every shared helper in `legality.py` (`_can_bake_bread`, `_can_sow`, `_can_plow`, `_has_stable_placement`, `_can_afford_room`, `_has_room_placement`, `_can_build_room`, `_can_renovate`, `_can_afford_any_major_improvement`). Cross-cutting checks confirm `fencing` and `lessons` never appear in `legal_placements` output.

### `tests/test_resolution_atomic.py`

Atomic-space resolution tests via `engine.step` (migrated from the removed `resolve_atomic` in Task 5). One or more tests per atomic space. Covers: goods added correctly, accumulated goods reset to zero after taking an accumulation space, worker placed on the space, `people_home` decremented, `starting_player` updated when Meeting Place is taken, Wish-specific checks (`people_total` incremented, `newborns` incremented, `people_home` not incremented for newborn), and Task 5 properties (atomic placements leave `pending_stack == ()`, `current_player` alternates).

### `tests/test_engine.py`

Tests for the engine module: `step`, `_advance_current_player`, `_advance_until_decision`, `_resolve_return_home`, `_resolve_preparation`. Covers:

- Atomic placement basics: effect applied, `people_home` decremented, workers updated, stack stays empty, current_player alternates.
- Stack invariants: atomic placements leave the stack empty; `_advance_until_decision` is idempotent on states returned by `step`.
- `_advance_current_player`: alternates when other player has workers; stays put when other has none.
- Round transitions: WORK ends when both players are at 0 workers; RETURN_HOME resets all action-space workers; RETURN_HOME returns people home but does NOT clear newborns; PREPARATION clears newborns, refills revealed accumulation spaces, increments `round_number`, resets `current_player` to `starting_player`; round-4 RETURN_HOME transitions to `BEFORE_SCORING`.
- Error behaviors: `step` raises on `BEFORE_SCORING`; raises `NotImplementedError` on unimplemented non-atomic spaces.
- End-to-end: random-agent plays rounds 1–4 to `BEFORE_SCORING` for 10 different seeds without raising.
- A meta-invariant test confirming the decider rule (`pending_stack[-1].player_idx == state.current_player` when stack non-empty) holds throughout a deterministic play-through.

### `tests/test_grain_utilization.py`

Tests for the one non-atomic resolution implemented in Task 5. Uses prefabricated states from `factories.py`. Covers:

- Basic walks: sow-only, bake-only, both-sub-actions in either order yields identical end state.
- Stop legality: illegal before any sub-action committed; legal after sow or bake done; the only legal action when both are done.
- Mid-turn legality recomputation: sow becomes illegal after baking depletes grain; bake becomes illegal after sowing depletes grain; sow remains legal after a partial bake.
- Sow distribution semantics: grain fills earliest fields first, then veg; canonical (row, col) order across non-contiguous fields; `CommitSow(g, v)` with `g+v > empty_fields` is filtered from legal options.
- Cooking rates: Hearth uses 3 food/grain; Hearth wins over Fireplace when both owned; Clay-Oven-only owner reaches `CommitBake` and gets `NotImplementedError`.
- Placement legality: illegal when neither sow nor bake is possible; legal when only one path is open.
- Stack invariants: under the choose-time convention, `ChooseSubAction("sow")` writes `sow_chosen=True` on `PendingGrainUtilization` and pushes `PendingSow`; `CommitSow` pops `PendingSow` without modifying the parent. Symmetric for `bake_chosen` / `CommitBake`.

### `tests/test_potter_ceramics.py`

Tests for the one card implemented in Task 5. Uses prefabricated states; the card cannot be acquired through Task 5 gameplay, so every test sets `minor_improvements` directly.

- `_can_bake_bread` predicate broadening: True when 0 grain + 1 clay + Potter + baker (the headline behavior); False when missing any of {clay, baker, Potter}; True via base check when grain >= 1 (extension doesn't need to fire).
- Full Grain Utilization walk-through with the trigger: setup at 0 grain + 1 clay + Fireplace + Potter, no fields; verify each step (PlaceWorker → ChooseSubAction → FireTrigger → CommitBake → Stop) produces the expected state.
- Single-fire invariant: even with 2 clay, Potter still fires at most once per Bake Bread action.
- Re-eligibility on a fresh `PendingBakeBread` (validates that `triggers_resolved` is frame-scoped, not persistent player state).
- Implicit declination via commit: with 1 grain + 1 clay + Potter, the player can `CommitBake` without firing Potter — the trigger doesn't fire, clay is preserved.
- Both options coexistence: with 1 grain + 1 clay + Potter, both `FireTrigger` and `CommitBake(1)` appear in `legal_actions`.
- Forced fire when no commit possible: with 0 grain + 1 clay + Potter, `legal_actions` returns exactly `[FireTrigger("potter_ceramics")]` (no `SkipTrigger` in this architecture).

### `tests/test_bake_bread.py`

Unit-level coverage of `_execute_bake` and `_enumerate_pending_bake_bread` across the matrix of `(owned_majors, grain_in_supply)` cases. Parametrized test with 13 cases covering each baking improvement in isolation, capped + uncapped combinations, capped-only combinations (cap-sum bounds the legal range), all four owned, and zero-grain edge cases. A separate test exercises the `BAKING_SPEC_EXTENSIONS` registry by registering a synthetic `(cap=1, rate=6)` source under a fixture and verifying the cap computation and greedy allocation pick it up.

### `tests/test_farmland.py`

Tests for the Farmland action space. Covers: basic walk (PlaceWorker → ChooseSubAction → CommitPlow → Stop); Stop legality before/after `plow_chosen`; cell-choice enumeration (non-empty cells, enclosed cells, non-adjacent cells filtered out); placement illegality when no plow target exists; choose-time flag invariant.

### `tests/test_cultivation.py`

Tests for the Cultivation action space. Covers: plow-only, sow-only, plow-then-sow on newly plowed field, sow-then-plow; Stop legality requires at least one chosen; choose-time flag invariants.

### `tests/test_side_job.py`

Tests for the Side Job action space. Post-Task-5D: uses `PendingBuildStables(max_builds=1)` (the multi-shot pending in its cap=1 degenerate case). Covers: stable-only, bake-only, both; 1-wood stable cost (debited from `PendingBuildStables.cost`); `PendingBuildStables.cost == Resources(wood=1)` and `max_builds == 1` invariants; Potter Ceramics integration; Stop legality; placement illegality when neither sub-action is possible; singleton-Stop state after the single commit (only Stop is legal because `max_builds=1` saturates).

### `tests/test_animal_markets.py`

Tests for the three animal markets (Sheep, Pig, Cattle), parametrized where structure is shared. Covers: PlaceWorker stages animals on `pending.gained` and zeroes the space's `accumulated_amount`; CommitAccommodate pops the parent directly (no Stop step); release-to-food with Cooking Hearth; no food gained without a cooking improvement; the `Stop` action is never in the legal list at a market parent pending; Pareto-dominated configurations are excluded from the legal-actions list; existing animals combine with gained animals in the frontier search.

### `tests/test_major_improvement.py`

Integration tests for the full Major Improvement purchase-then-bake chain. Covers: building each individual major; Cooking Hearth pay-clay vs return-Fireplace payment modes (both options appear in legal actions when both Fireplaces are owned); Well's future_resources update; Clay Oven purchase + free bake (1 grain → 5 food); Clay Oven purchase + skip bake; Stone Oven purchase + free bake (2 grain → 8 food); Clay Oven + Potter Ceramics 0-grain chain (Potter swaps clay for grain before the bake).

### `tests/test_house_redevelopment.py`

Tests for the House Redevelopment action space. Covers: renovate-only and renovate-then-improvement walks; improvement step requires `renovate_chosen` first; Stop legality before / after each step; material progression WOOD→CLAY→STONE; STONE house cannot renovate; renovation cost on `PendingRenovate.cost` for both transitions (1 reed total, not per-room); inner `PendingMajorMinorImprovement.initiated_by_id == "house_redevelopment"` (provenance check).

### `tests/test_farm_expansion.py`

Tests for the Farm Expansion action space — first space using the multi-shot sub-action pending pattern from Task 5D. 25 tests covering: basic walks (rooms-only, stables-only, rooms-then-stables); within-action adjacency chaining for rooms; 4-stable build saturating supply; singleton-Stop states for both supply-exhausted and affordability-exhausted constraints (Approach 2: Stop is always the explicit exit); Stop legality at num_built=0 (illegal in `PendingBuildStables` / `PendingBuildRooms`) and at the parent before any category is chosen; cost on pending parametrized over house material (wood / clay / stone); Farm Expansion's 2-wood stable cost (distinct from Side Job's 1-wood); room adjacency rule + room-inside-pasture exclusion; pasture-cache recompute when a stable lands inside an existing pasture (directly exercises the fix for the latent bug in Task 5C's `_execute_build_stable`); once-per-category rule parametrized over rooms/stables; placement legality (none / rooms-only / stables-only cases); stack invariants (choose-time flag set, no-pop on commit, Stop pops).
