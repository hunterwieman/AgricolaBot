# Task 5 — The `step` Function, Round Loop, and Non-Atomic Action Scaffolding

This task introduces the engine's transition function (`step`), the pending-decision stack that lets the engine pause mid-action for sub-decisions, the phase machinery that walks through Work → Returning Home → Preparation → Work between rounds, and the first non-atomic action space resolution (Grain Utilization). It also introduces a card-trigger framework with one concrete card implemented (Potter Ceramics) so the trigger-insertion mechanism is exercised end-to-end.

After this task, a random agent will be able to play rounds 1–4 of a Family game, exercising both atomic resolution and one non-atomic resolution, with one card-trigger path live.

## Scope

**In scope**
- New action types: `ChooseSubAction`, `CommitSow`, `CommitBake`, `FireTrigger`, `Stop`.
- New `PendingDecision` union and the pending-stack architecture.
- New module `agricola/engine.py` containing `step` and `_advance_until_decision`.
- New `Phase.PREPARATION` and `Phase.BEFORE_SCORING` enum values.
- `legal_actions(state)` as the top-level public legality entry point.
- Preparation-phase resolver and Returning-Home-phase resolver.
- Round transition logic for rounds 1 → 2 → 3 → 4, halting after round 4's RETURN_HOME (before the first harvest).
- Grain Utilization implemented as a non-atomic action (sow and/or bake bread).
- `agricola/cards/` subpackage with the trigger registry and Potter Ceramics.
- Migration of `PlayerState.future_food` → `PlayerState.future_resources: tuple[Resources, ...]`.
- New `PlayerState.minor_improvements: frozenset[str]` and `PlayerState.occupations: frozenset[str]` fields for card ownership.
- New test files: `tests/test_engine.py`, `tests/test_grain_utilization.py`, `tests/test_potter_ceramics.py`, `tests/test_utils.py`, `tests/factories.py`.
- Documentation updates in `CLAUDE.md` and `IMPLEMENTATION_CHOICES.md`.

**Out of scope**
- Harvest phases (HARVEST_FIELD / HARVEST_FEED / HARVEST_BREED resolution).
- Round 5 and onward — engine halts in `BEFORE_SCORING` after round 4's RETURN_HOME.
- Non-atomic resolution for any space other than Grain Utilization. The other ten non-atomic spaces (Farm Expansion, Farmland, Side Job, Sheep/Pig/Cattle Market, Major Improvement, House Redevelopment, Cultivation, Farm Redevelopment, and Fencing) remain as legal-only entries. Selecting them via `PlaceWorker(...)` should raise `NotImplementedError` from `step` for now.
- Any card other than Potter Ceramics.
- Action spaces that allow playing minor improvements or occupations (Lessons, Wish for Children's optional minor, House Redevelopment's optional Major-or-Minor, Major Improvement's "or play a minor" path). For Task 5, players acquire Potter Ceramics only by direct state construction in tests.
- A scoring call on a final state. Scoring already works; we just don't invoke it from the engine.

---

## First step: audit

Before writing any code, the coding agent must read:

1. `CLAUDE.md` — current project status and per-file descriptions. **Pay particular attention to the "Engine and Turn Resolution Architecture" section** (the three subsections on `step` / `legal_actions` / `_advance_until_decision`, the pending-decision stack, and card implementation status). That section is the conceptual frame for everything specified in this task doc; design decisions described there are settled and should not be relitigated.
2. `agricola/state.py` — current shape of every dataclass. Note especially:
   - `PlayerState.future_food: tuple` — this is being migrated.
   - `GameState` does not yet have a pending-stack field.
3. `agricola/constants.py` — current Phase enum. Note `PREPARATION` and `BEFORE_SCORING` are absent.
4. `agricola/legality.py` — note the public function is `legal_placements(state)`, which becomes an internal helper after Task 5.
5. `agricola/resolution.py` — note `resolve_atomic` exists with its `ATOMIC_HANDLERS` dict. The atomic handler set is preserved and reused by `step`.
6. `agricola/actions.py` — note `Action = PlaceWorker` is the current alias. This union is being expanded.

Then read `RULES.md` § "Action Spaces" for Grain Utilization, § "Bake Bread Action" for the baking mechanics, and `STEP_IMPLEMENTATION_OUTLINE.md` for context on what an earlier session proposed (much of which we have explicitly rejected; the task doc you are reading now supersedes it).

---

## Resolved design decisions (recap)

These were agreed in the design conversation that produced this task. Implement them as stated; do not relitigate them in code review.

1. **Frozen dataclasses end-to-end.** Every new type is a `@dataclass(frozen=True)`; `step` uses `dataclasses.replace` to produce new states.

2. **`step(state, action) -> GameState`** is the only public transition primitive. No `play_round`-style helper in the engine module. Tests get a `run_actions` helper in `tests/test_utils.py`.

3. **`step` performs no legality validation.** The agent's loop asserts `action in legal_actions(state)` before calling `step`. Reasoning: keeps `step`'s signature simple; tests construct actions deliberately and validate themselves; double-validation is wasted work.

4. **`step` auto-advances "system" transitions only.** Phase transitions (WORK → RETURN_HOME → PREP → WORK) and active-player alternation when the stack is empty happen inside `step` via `_advance_until_decision`. **Singleton agent decisions are NOT auto-applied** inside `step` — the agent loop is responsible for noticing `len(legal_actions(state)) == 1` and acting accordingly. `step` is always called with one action and applies one action plus its system follow-up.

5. **Actions are a flat tagged union of frozen dataclasses** under the `Action` alias. One dataclass per single decision (`PlaceWorker`, `ChooseSubAction`, `CommitSow`, `CommitBake`, `FireTrigger`, `Stop`). No compound action types. There is no `SkipTrigger`: declining a trigger is implicit — the player just doesn't fire it, and commits (or fires another trigger) to proceed.

6. **Pending decisions are a typed union of frozen dataclasses** under the `PendingDecision` alias, stored as a stack on `GameState.pending_stack: tuple[PendingDecision, ...]`. Each pending dataclass carries a `player_idx: int` field so out-of-turn trigger frames are expressible (none in Task 5; mechanism present).

   **Why a tuple for the stack?** Tuples are immutable (consistent with the frozen-dataclass invariant), hashable (required for state equality and MCTS deduplication), small (the stack rarely exceeds three frames in even the most exotic card interactions), and idiomatic Python for "small immutable sequence." Push/pop is O(n) in stack depth — for n ≤ 5 that's a handful of pointer copies, dominated by other per-step costs by orders of magnitude. Mutable lists would break the frozen invariant; linked structures would add allocation overhead per cons without practical benefit.

7. **Simple triggers do not get their own pending dataclass.** Potter Ceramics' fire-or-decline decision is presented as `FireTrigger("potter_ceramics")` (alongside the commit options if any are legal) in the top-of-stack pending's `legal_actions`. The player declines a trigger by simply not firing it (picking a commit or another trigger instead). A trigger gets its own pending only if it requires parameterized sub-decisions (none in Task 5).

8. **Two-step sub-actions: category then commit.** When a non-atomic space offers multiple sub-action categories (e.g., Grain Utilization offers Sow and Bake Bread), the player first picks a category via `ChooseSubAction("sow")` (which pushes a `PendingSow`-style frame), then commits parameters via e.g. `CommitSow(grain, veg)`. The middle layer is where before-X triggers fire and where the legality of commit parameters can be re-evaluated against post-trigger state.

9. **`legal_actions(state)` returns a deterministic order.** `Stop` is last when present. Otherwise, ordering is by space-id alphabetical (for placements), action-id canonical (for sub-actions and triggers).

10. **`future_food: tuple` → `future_resources: tuple[Resources, ...]`.** Each entry is a `Resources` object; length 14. Defaults to `(Resources(),) * 14`. Future animals and exotic future rewards are not implemented in Task 5; when they arrive, a `FutureRewards` wrapper will be introduced.

11. **`PlayerState.minor_improvements: frozenset[str]`** records which minor improvement cards the player has played. Set defaults to empty in `setup`. Potter Ceramics is the only card in scope; tests set this field directly.

12. **Card framework lives at `agricola/cards/`.** `__init__.py` imports all card modules to populate the registry at import time. `triggers.py` houses the event-keyed `TRIGGERS` registry and `register(...)` function. Each card has its own module (`potter_ceramics.py` in Task 5).

13. **Halt after round 4.** After RETURN_HOME of round 4, phase becomes `Phase.BEFORE_SCORING` (skipping the harvest entirely). `step` raises if called while phase is `BEFORE_SCORING`. Round 5 onward is unreachable in Task 5.

---

## State-shape changes

### `agricola/constants.py`

Add `PREPARATION` and `BEFORE_SCORING` to the `Phase` enum:

```python
class Phase(Enum):
    WORK = auto()
    RETURN_HOME = auto()
    PREPARATION = auto()       # new — preparation phase of each round (rounds 2+)
    HARVEST_FIELD = auto()
    HARVEST_FEED = auto()
    HARVEST_BREED = auto()
    BEFORE_SCORING = auto()    # new — terminal phase for Task 5 after round 4
```

`Phase.PREPARATION` is its own phase even though no agent decisions fire in it during Task 5. Future cards (various occupations with "at the start of each round" effects) DO trigger here, and a clean phase makes those drops-in trivial. `_advance_until_decision` walks `RETURN_HOME → PREPARATION → WORK` as three explicit phase transitions; the agent never observes the intermediate phases in Task 5 because no triggers push pendings during them.

Note: the Well major improvement's "place 1 food on each of the next 5 round spaces" is NOT a PREPARATION-phase trigger — it fires once at purchase time (Major Improvement action), writing `food=1` into the appropriate slots of the purchasing player's `future_resources` tuple. PREPARATION's existing job (distribute `future_resources[round_number - 1]` into the player's supply) handles the per-round delivery without any Well-specific code.

### `agricola/state.py`

`GameState` gains a `pending_stack` field:

```python
@dataclass(frozen=True)
class GameState:
    round_number:    int
    phase:           Phase
    current_player:  int
    starting_player: int
    players:         tuple
    board:           BoardState
    pending_stack:   tuple = ()   # tuple[PendingDecision, ...] — bottom-to-top, top is [-1]
```

`PlayerState` gains `minor_improvements` and migrates `future_food` to `future_resources`:

```python
@dataclass(frozen=True)
class PlayerState:
    resources:           Resources
    animals:             Animals
    farmyard:            Farmyard
    house_material:      HouseMaterial
    people_total:        int
    people_home:         int
    newborns:            int = 0
    begging_markers:     int = 0
    future_resources:    tuple = (Resources(),) * 14   # tuple[Resources, ...], length 14
    minor_improvements:  frozenset = frozenset()       # frozenset[str], minor improvement card ids
    occupations:         frozenset = frozenset()       # frozenset[str], occupation card ids
```

The `occupations` field is added now for symmetry with `minor_improvements`. No occupation cards are implemented in Task 5; the field defaults to empty. When the card system arrives, occupations will register the same way Potter Ceramics does.

**Migration note.** `future_food: tuple` is removed entirely. Any code that still references `future_food` must be updated. The Well major improvement (idx 4) will eventually populate `future_resources` entries; today no code writes to `future_resources`, so the empty-Resources default applies.

Update `agricola/setup.py:_make_player` to use the new defaults:

```python
return PlayerState(
    resources=Resources(food=food),
    animals=Animals(),
    farmyard=_make_farmyard(),
    house_material=HouseMaterial.WOOD,
    people_total=2,
    people_home=2,
    newborns=0,
    begging_markers=0,
    future_resources=(Resources(),) * NUM_ROUNDS,
    minor_improvements=frozenset(),
    occupations=frozenset(),
)
```

Update `setup` itself to initialize the `pending_stack=()` default explicitly:

```python
return GameState(
    round_number=1,
    phase=Phase.WORK,
    current_player=starting_player,
    starting_player=starting_player,
    players=players,
    board=board,
    pending_stack=(),
)
```

### Tests to update for the migration

`tests/test_state.py` references `future_food` in assertions. Find every such reference and change to `future_resources`, asserting tuple length 14 and each element equal to `Resources()`.

---

## New module: `agricola/actions.py` expansion

Replace the current contents of `agricola/actions.py` with the full expanded action union. Each is a frozen dataclass; the `Action` alias is the Union of all of them.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True)
class PlaceWorker:
    """Place the active player's worker on an action space."""
    space: str   # action space ID, e.g. "grain_utilization"


@dataclass(frozen=True)
class ChooseSubAction:
    """Pick a sub-action category at a non-atomic space's pending decision.

    Categories are space-specific strings: e.g. "sow", "bake_bread" at
    Grain Utilization. Pushing the corresponding Pending* onto the stack
    is the handler's job.
    """
    name: str


@dataclass(frozen=True)
class CommitSow:
    """Commit a sow with specific grain and veg counts."""
    grain: int
    veg: int


@dataclass(frozen=True)
class CommitBake:
    """Commit a Bake Bread with the chosen grain amount."""
    grain: int


@dataclass(frozen=True)
class FireTrigger:
    """Fire a specific card trigger that's currently eligible at the top pending."""
    card_id: str


@dataclass(frozen=True)
class Stop:
    """End the current non-atomic action (pop the top pending frame).

    Legal only at certain pending frames (currently: outer space pendings
    where at least one sub-action has been committed).
    """


Action = Union[
    PlaceWorker,
    ChooseSubAction,
    CommitSow,
    CommitBake,
    FireTrigger,
    Stop,
]
```

> **Note:** `ChooseSubAction` is parameterized by string, mirroring `PlaceWorker(space: str)`. We do NOT create separate `ChooseSow`, `ChooseBake` dataclasses. This keeps the action union slim and follows the established pattern.
>
> **Note:** There is no `SkipTrigger` action. Declining a trigger is implicit — the player just doesn't fire it. The trigger remains in `legal_actions` until either fired or the pending pops (via `CommitX` or `Stop`). This eliminates a redundant action type and the legality-lookahead helper that would have been needed to gate it. See "Trigger declination is implicit" in the architecture section below.

---

## New module: `agricola/pending.py`

The pending types live in their own module, like `actions.py`, to avoid circular imports between `state.py` (which holds the `pending_stack` field) and the resolution code that creates pendings.

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Union


@dataclass(frozen=True)
class PendingGrainUtilization:
    """Outer pending for Grain Utilization. Tracks which categories the
    player has used (rule: must take at least one sub-action) and is the
    frame on which Stop becomes legal after the first sub-action."""
    player_idx: int
    sow_done: bool = False
    bake_done: bool = False


@dataclass(frozen=True)
class PendingSow:
    """Inner pending pushed after the player chooses Sow at Grain Utilization
    (or, in the future, at any space that offers sowing).

    Stack invariant: when a PendingSow is popped (via CommitSow), the new
    top is the parent pending (PendingGrainUtilization in Task 5). Trigger
    frames always push on top of PendingSow, never between it and its
    parent — see the "Stack invariant: trigger frames push on top" note
    in the architecture section.
    """
    player_idx: int


@dataclass(frozen=True)
class PendingBakeBread:
    """Inner pending pushed after the player chooses Bake Bread.

    Carries the set of before-bake triggers that have already fired this
    action so each trigger fires at most once per Bake Bread action.

    TRIGGER_EVENT identifies the trigger-registry event this pending
    handles. Used by legal_actions enumerators to filter the TRIGGERS
    registry to the right event.
    """
    player_idx: int
    triggers_resolved: frozenset = frozenset()   # frozenset[str], card ids
    TRIGGER_EVENT: ClassVar[str] = "before_bake_bread"


PendingDecision = Union[
    PendingGrainUtilization,
    PendingSow,
    PendingBakeBread,
]
```

`TRIGGER_EVENT` is a `ClassVar`, not a dataclass field: it's a class-level constant identifying which trigger event this pending type manages. `ClassVar` keeps it out of `__init__`, `__eq__`, and `__hash__` (where it would be nonsensical — the event is determined by type, not by instance). Pending types that have no triggers (like `PendingSow` and `PendingGrainUtilization` in Task 5) simply don't declare `TRIGGER_EVENT`. Code that needs the event name reads `type(pending).TRIGGER_EVENT` or `pending.TRIGGER_EVENT` (same value).

Future tasks will add `PendingFarmExpansion`, `PendingBuildRoom`, `PendingBuildStable`, `PendingCultivation`, `PendingPlow`, `PendingBuildFences`, `PendingBuildMajor`, `PendingPlayMinor`, `PendingRenovate`, and per-card trigger pendings as needed.

### Why every pending carries `player_idx`

The field looks redundant in a 2-player game where every active-player frame's `player_idx` equals `state.current_player`. It is not. Two reasons:

1. **Out-of-turn triggers.** Cards like Casual Worker: "Each time another player uses a 'Quarry' accumulation space, you can choose to get 1 food or build a stable without paying wood." push a pending whose `player_idx` is the opponent. The engine consults the top frame's `player_idx`, not `state.current_player`, to identify the decider. Including the field from day one means we don't have to retrofit it onto every pending when the first such card arrives.

2. **Self-documenting frames.** Reading a stack snapshot during debugging is easier when each frame says explicitly whose decision it represents.

The Task 5 invariant is simpler: every pending's `player_idx` equals `state.current_player`, because no out-of-turn triggers exist. Assertions can enforce this in tests.

---

## The PendingActionStack architecture

This section is the load-bearing one for the rest of the design. Read it carefully.

### What the stack is

`GameState.pending_stack` is a tuple of `PendingDecision` objects, ordered bottom-to-top. `pending_stack[-1]` is the top of the stack. An empty stack (`()`) means no non-atomic action is in progress; the next agent decision is a worker placement (if a player has workers left) or the round has ended.

A non-empty stack means a sub-decision is awaiting agent input. The top frame names which sub-decision: its dataclass type identifies the kind of decision, its fields supply the context (which player, what's been done so far, which triggers have fired, etc.).

### Who is making the next decision

The rule for identifying the decider:

- If `pending_stack` is empty, the decider is `state.current_player`.
- If `pending_stack` is non-empty, the decider is `pending_stack[-1].player_idx`.

`state.current_player` always means "the player whose worker placement is currently being resolved." It does not change when an opponent-triggered frame is on the stack (none in Task 5). It does change when both players have placed all workers and the work phase ends. It is the engine's job to keep this distinction clean.

### What `legal_actions(state)` returns at a given moment

`legal_actions(state)` is the public legality entry point. It dispatches on stack state:

```python
def legal_actions(state: GameState) -> list[Action]:
    if state.phase == Phase.BEFORE_SCORING:
        return []                          # game over, no actions
    if state.pending_stack:
        return _enumerate_pending(state, state.pending_stack[-1])
    if state.phase == Phase.WORK:
        return legal_placements(state)     # existing function from legality.py
    # No other phase exposes decisions in Task 5; this is an unreachable
    # branch because _advance_until_decision always returns at a real
    # decision point or at game over.
    raise AssertionError(
        f"legal_actions called in unexpected state: phase={state.phase}, "
        f"stack={state.pending_stack}"
    )
```

The dispatch `_enumerate_pending(state, top)` is implemented per pending type, in the same module that defines that pending or in `agricola/legality.py`. Per-pending enumerators are detailed in the Grain Utilization section below.

The previously-public function `legal_placements(state)` does NOT disappear. It remains in `legality.py` and is now called by `legal_actions` for the stack-empty / phase=WORK branch. Tests that currently use `legal_placements` keep working; new tests use `legal_actions`.

### Push / pop discipline — what causes the stack to change

Stack changes happen inside `step` after an action is applied:

| Action picked at top frame | Stack change |
|---|---|
| `PlaceWorker(non_atomic_space)` (stack was empty) | Push `Pending<Space>(player_idx=current_player)` |
| `ChooseSubAction("category")` at a space pending | Push `Pending<Category>(player_idx=current_player)` |
| `CommitX(...)` at a category pending | Pop the category pending; mark `X_done = True` on the parent space pending |
| `FireTrigger(card_id)` | Apply card effect; mark `card_id` in top frame's `triggers_resolved`; no push or pop |
| `Stop` at a space pending | Pop the space pending (the only frame on the stack at this point); turn ends, alternate or transition phase |
| `PlaceWorker(atomic_space)` (stack was empty) | No stack change; effect applied directly |

The bookkeeping for these pushes / pops is centralized in `step` and its helpers, not delegated to individual handlers. Reasoning: it keeps the discipline structural rather than convention-based.

### What lives on a pending frame's fields

Each pending dataclass's fields encode three things:

1. **Progress tracking** — what has been done so far in this resolution that affects future legality. For `PendingGrainUtilization`, that's `sow_done` and `bake_done`. For non-atomic spaces with arbitrary sub-action counts (Farm Expansion's repeated room/stable builds, future Fencing), this would be a counter or set.

2. **Identity** — `player_idx` (whose decision this is).

3. **Trigger firing state** — `triggers_resolved: frozenset[str]` recording which card triggers have already fired during this pending's lifetime. Today only `PendingBakeBread` carries this (Potter Ceramics is the one card we implement). Once the card system is online, **almost every Pending\* will have a `triggers_resolved` field** because most events have at least one card that fires on them — "before X" / "after X" / "when X" triggers proliferate quickly once occupations and minor improvements are added.

**`triggers_resolved` is scoped to a single event instance.** The field lives on the pending frame; when the frame pops, the set goes with it. The next instance of the same trigger event creates a fresh pending with an empty `triggers_resolved`. So Potter Ceramics correctly becomes re-eligible on every new Bake Bread action; a hypothetical "at the start of each round" card will re-fire every round because each new round's PREPARATION pending (when added) gets its own empty set. **Don't put `triggers_resolved`-like state on `PlayerState`** — that would make a trigger fire once per game rather than once per event instance.

Per-card budgets that DO span multiple events (once-per-round, once-per-game, once-per-harvest) live on `PlayerState` (the eventual richer card state) or on `BoardState` (shared budgets), separate from any pending frame. The pending stack is a stack of *active* decisions, not a per-game scoreboard.

### Stack invariant: trigger frames push on top

A subtle but load-bearing invariant of this design: when a card-triggered sub-decision pushes its own pending frame onto the stack, it goes **on top of** the pending whose event it fires from. It never inserts between two existing frames.

So when `PendingSow` is popped by `CommitSow`, the new top of the stack is guaranteed to be the parent (`PendingGrainUtilization`) — even in the presence of intervening trigger frames during the sow. The intervening frames pushed themselves on top of `PendingSow`, resolved, and popped themselves before `CommitSow` ever fired. By the time `CommitSow` executes, the stack is back to `(..., PendingGrainUtilization, PendingSow)`.

This invariant matters for the "mark `sow_done` on the parent" step: `_apply_commit_sow` pops `PendingSow` and writes `sow_done=True` to `state.pending_stack[-1]` (the new top). That's always the parent.

The same logic applies to "after X" triggers: they fire *after* `CommitSow` has popped `PendingSow` and written `sow_done`, so they see the parent in a consistent state.

### Worked example A — Grain Utilization without cards

Two-player game, player 0's turn. Prefabricated state: player 0 has 3 grain, 1 vegetable, owns a Fireplace (idx 0), and has three empty (unsown) field cells. Both players have 2 workers at home. State is at `Phase.WORK`, `current_player = 0`, `pending_stack = ()`, round 1.

This example shows multi-option enumeration and sub-action ordering. Player 0 will sow 2 grain and 1 veg, then bake the remaining 1 grain.

**Step 1.** `legal_actions(state)`:
Pending stack empty, phase = WORK → returns `legal_placements(state)`. `PlaceWorker("grain_utilization")` is in the list because `_can_sow` is True (empty fields + seeds) and `_can_bake_bread` is True (Fireplace + grain).

**Step 2.** Agent picks `PlaceWorker("grain_utilization")`. `step` applies:
- `_apply_worker_placement`: `workers` on `grain_utilization` becomes `(1, 0)`; player 0's `people_home` decremented to 1.
- `_resolve_grain_utilization` pushes `PendingGrainUtilization(player_idx=0, sow_done=False, bake_done=False)`.
- Stack is now `(PendingGrainUtilization(...),)`. Non-empty, so no current-player alternation happens. `_advance_until_decision` returns.

**Step 3.** `legal_actions(state)`:
Top is `PendingGrainUtilization` → dispatch to `_enumerate_pending_grain_utilization`. Returns `[ChooseSubAction("bake_bread"), ChooseSubAction("sow")]`. (`Stop()` is not yet legal — neither `sow_done` nor `bake_done` is True.)

**Step 4.** Agent picks `ChooseSubAction("sow")`. `step` applies:
- Dispatch `CHOOSE_SUBACTION_HANDLERS[type(top)]` → `_choose_subaction_grain_utilization`. With `name="sow"`, it pushes `PendingSow(player_idx=0)`.
- Stack is now `(PendingGrainUtilization, PendingSow)`. Still non-empty, no alternation.

**Step 5.** `legal_actions(state)`:
Top is `PendingSow` → dispatch to `_enumerate_pending_sow`. Enumerate all `(grain, veg)` totals with `grain + veg ≥ 1`, `grain ≤ 3`, `veg ≤ 1`, `grain + veg ≤ 3` (number of empty fields). Sorted by `(g, v)` ascending: `[CommitSow(0, 1), CommitSow(1, 0), CommitSow(1, 1), CommitSow(2, 0), CommitSow(2, 1), CommitSow(3, 0)]`. (`CommitSow(3, 1)` would sum to 4 cells, exceeding empty fields.)

**Step 6.** Agent picks `CommitSow(2, 1)` (sow 2 grain + 1 veg, filling three fields: grain into the first two by canonical (row, col) order, then veg into the third).
- `_apply_commit_sow` executes the sow: subtract 2 grain and 1 veg from supply. Fill the first two empty fields with 3 grain each (1 from supply + 2 from general). Fill the third with 2 veg (1 from supply + 1 from general).
- Pop `PendingSow`. New top is `PendingGrainUtilization`.
- Set `sow_done=True` on the new top.
- Stack is now `(PendingGrainUtilization(player_idx=0, sow_done=True, bake_done=False),)`. Still non-empty, no alternation.

Player 0 now has 1 grain, 0 veg, three sown fields.

**Step 7.** `legal_actions(state)`:
Top is `PendingGrainUtilization` with `sow_done=True, bake_done=False`. Returns `[ChooseSubAction("bake_bread"), Stop()]`. (Sow not re-offered; `_can_bake_bread` returns True because player still has 1 grain + Fireplace.)

**Step 8.** Agent picks `ChooseSubAction("bake_bread")`. `step` pushes `PendingBakeBread(player_idx=0, triggers_resolved=frozenset())`.

**Step 9.** `legal_actions(state)`:
Top is `PendingBakeBread` → dispatch to `_enumerate_pending_bake_bread`. No cards in this example, so no triggers. Returns `[CommitBake(1)]` (only one legal commit since player has 1 grain).

**Step 10.** Agent picks `CommitBake(1)`.
- `_apply_commit_bake` executes: subtract 1 grain, add 2 food (Fireplace rate).
- Pop `PendingBakeBread`. New top is `PendingGrainUtilization`.
- Set `bake_done=True` on the new top.
- Stack: `(PendingGrainUtilization(sow_done=True, bake_done=True),)`. Non-empty, no alternation.

**Step 11.** `legal_actions(state)`:
Both sub-actions done. Returns `[Stop()]`.

**Step 12.** Agent picks `Stop()`.
- `_apply_stop` pops `PendingGrainUtilization`. Stack: `()`.
- Back in `step`: stack is now empty AND phase = WORK → `_advance_current_player` is called. Player 1 has `people_home > 0`, so `current_player` becomes 1.
- `_advance_until_decision`: stack empty, phase=WORK, player 1 has workers → return.

Final state of player 0's turn: 0 grain, 0 veg, +2 food. Three fields sown. `pending_stack=()`. Turn passes to player 1.

### Worked example B — Grain Utilization with Potter Ceramics

This example exercises the card-trigger machinery. Prefabricated state: player 0 has 0 grain, 1 clay, owns Fireplace (idx 0), has played the Potter Ceramics minor improvement (`"potter_ceramics" in p.minor_improvements`), has zero empty field cells (so sowing is impossible). Other state as before.

**Why this turn is legal at all.** With 0 grain in supply, the base `_can_bake_bread` predicate returns False (`grain >= 1` fails). But the predicate is structured to consult `BAKE_BREAD_ELIGIBILITY_EXTENSIONS` — a registry of card-supplied predicates that may broaden eligibility. Potter Ceramics registers a predicate named `_potter_can_bake_bread_extension` into that registry. Its check: "player owns Potter Ceramics, owns a baking improvement, has at least 1 clay." All three hold, so the extension returns True, so `_can_bake_bread` returns True, so `_legal_grain_utilization(state)` returns True (Bake Bread is a reachable sub-action), so `PlaceWorker("grain_utilization")` appears in `legal_placements(state)`.

In plain English: the player can take Grain Utilization because Potter Ceramics gives them a way to bake even with no grain on hand — they'll exchange clay for grain mid-action.

The walk-through:

**Step 1.** Agent picks `PlaceWorker("grain_utilization")`. `step` pushes `PendingGrainUtilization(player_idx=0)`.

**Step 2.** `legal_actions`: only `[ChooseSubAction("bake_bread")]` — sow is impossible (no fields).

**Step 3.** Agent picks `ChooseSubAction("bake_bread")`. `step` pushes `PendingBakeBread(player_idx=0, triggers_resolved=frozenset())`.

**Step 4.** `legal_actions` at `PendingBakeBread`:
- Iterate `TRIGGERS["before_bake_bread"]` (looked up via `type(pending).TRIGGER_EVENT`).
- Potter Ceramics is in this list. Its eligibility check passes (card owned, not yet fired this action, clay ≥ 1). So `FireTrigger("potter_ceramics")` is in the candidate list.
- There is no `SkipTrigger` action in this architecture (declining is implicit), so no skip-legality check is needed.
- Enumerate commit options: with 0 grain, no `CommitBake(n)` is legal in the base state.
- Final list: `[FireTrigger("potter_ceramics")]`. Only one legal action.

**Step 5.** Agent picks `FireTrigger("potter_ceramics")`. `step` applies:
- Direct lookup `CARDS["potter_ceramics"]` retrieves the trigger entry.
- The entry's `apply_fn` runs: subtract 1 clay, add 1 grain. Player 0 now has 0 clay, 1 grain.
- `triggers_resolved` on the top frame is updated to `frozenset({"potter_ceramics"})`.
- Stack is unchanged in shape; only the top frame's data is updated. `_replace_top` does this.

The Bake Bread action itself has NOT executed yet. The trigger is a side-decision that fired before the commit.

**Step 6.** `legal_actions` re-runs at `PendingBakeBread`:
- Potter Ceramics is in `triggers_resolved` now, so the iteration skips it.
- Commit options: with 1 grain, `CommitBake(1)` is legal.
- Final list: `[CommitBake(1)]`.

**Step 7.** Agent picks `CommitBake(1)`. `step` applies:
- `_apply_commit_bake` executes the bake: subtract 1 grain, add 2 food (Fireplace rate).
- Pop `PendingBakeBread`. New top is `PendingGrainUtilization`.
- Set `bake_done=True` on the new top.

Player 0 now has 0 clay, 0 grain, 2 food.

**Step 8.** `legal_actions` at `PendingGrainUtilization`: sow impossible, `bake_done=True`. Only `Stop()` is offered.

**Step 9.** Agent picks `Stop()`. `step` pops `PendingGrainUtilization`. Stack: `()`. Phase = WORK and stack is empty → `_advance_current_player` alternates to player 1. `_advance_until_decision` returns.

Final state of the turn: player 0's net change is -1 clay, +2 food. The trigger fired exactly once; the bake fired exactly once.

### Forward-compatibility notes embedded in the architecture

The stack's design accommodates several features we are not implementing in Task 5. Each is structurally present so future tasks don't require retrofitting.

- **Multiple stack frames at once.** Today the deepest stack is 2 frames (space pending + category pending). The architecture allows arbitrarily deep nesting. A future card that triggers a sub-decision during a sub-decision (e.g., "when you build a room, you may also build a stable for free") would push a third frame.

- **Out-of-turn triggers.** When the post-effect trigger sweep finds a card owned by a non-active player, it pushes a pending with `player_idx` set to that opponent. The engine consults `pending_stack[-1].player_idx` for decider identity, not `state.current_player`. No further architecture work needed.

- **Triggers with sub-decisions.** A card whose trigger has parameters (e.g., "convert up to N vegetables to food") would push its own pending dataclass. Potter Ceramics is a simple trigger (no parameters), so no pending is pushed — `FireTrigger` is one of the legal actions at `PendingBakeBread`.

- **`Stop` at deeper frames.** Today `Stop` is only legal at the outermost frame of a non-atomic action. Future card-driven scenarios where the player may abandon a partially-resolved sub-action (e.g., "you may build a fence; if you decline, the action ends") would have `Stop` legal at the inner frame, and it would pop just that frame.

---

## New module: `agricola/engine.py`

This module contains the core `step` function and the system auto-advance logic. It imports from `agricola.actions`, `agricola.pending`, `agricola.state`, `agricola.legality`, `agricola.resolution`, and `agricola.constants`.

### Public API

```python
def step(state: GameState, action: Action) -> GameState:
    """Apply one action and auto-advance through system transitions.

    Preconditions (caller's responsibility — see TASK_5.md):
      - action is in legal_actions(state).
      - state.phase != Phase.BEFORE_SCORING.

    Postconditions:
      - The action's effect has been applied.
      - The state has been auto-advanced through phase transitions and
        active-player switches until the next agent decision OR
        state.phase == Phase.BEFORE_SCORING.
      - state.pending_stack reflects any pending sub-decisions.

    Raises:
      - NotImplementedError if action is a PlaceWorker on a non-atomic
        space other than "grain_utilization" (Task 5 only implements
        atomic spaces + Grain Utilization).
      - RuntimeError if state.phase == Phase.BEFORE_SCORING (game is over).
    """
```

### Who calls `step`?

`step` is a pure transition function. It does not loop, query an agent, or drive a game itself — it applies exactly one action and returns. **The loop that drives a game lives outside the engine module.** Task 5 has two callers, both in test scaffolding; future tasks (MCTS, training drivers) will add more.

The general pattern is the same in every caller — enumerate, pick, step, repeat. The pseudocode below illustrates the shape; **it is NOT real code that lives in any module.** A close-to-final version of this loop will eventually be the body of a top-level "play one game" entry point (a CLI driver, a tournament harness, etc.), but writing that entry point is **out of scope for Task 5**.

```python
# Pseudocode — illustrates the loop shape, not actual module code.
# In real callers, pick() is the differentiating piece (random, MCTS, NN, human).

state = setup(seed=0)
while state.phase != Phase.BEFORE_SCORING:
    actions = legal_actions(state)
    if not actions:
        raise RuntimeError("no legal actions but game not over")
    action = pick(actions)            # caller-specific
    state = step(state, action)
```

Concretely in Task 5, the two real callers of `step` both live in `tests/test_utils.py` and are real Python functions, not free-standing scripts:

1. **`run_actions(state, actions)`** in `tests/test_utils.py`. Takes a pre-built sequence of actions and applies them one by one, validating each is legal. Used by scripted tests that walk through a specific scenario (e.g., the Grain Utilization sow-then-bake test). The "pick" is just "the next action in the scripted list."

2. **`random_agent_play(state, seed)`** in `tests/test_utils.py`. Drives a full random game to terminal state. The "pick" is uniform random selection from `filter_implemented(legal_actions(state))` (the implemented-action filter ensures the random agent never picks an unimplemented non-atomic space). Used by the end-to-end engine smoke test.

Both helpers live in `tests/test_utils.py`, not the engine module. The engine exports `step` and `legal_actions`; callers compose them.

### Why no `play_round` or `play_game` in the engine

We considered adding a higher-level helper like `play_round(state, agent_callback)` in the engine and decided against it for Task 5. The reasoning: those helpers are trivial compositions of `step` + `legal_actions`, and the right callback shape depends on the caller (random vs. MCTS vs. NN-with-batching vs. human). A premature `play_round` API would either be too rigid for future callers or too generic to be useful. Keep the engine minimal; let each caller compose what it needs. When the MCTS task arrives and we have a concrete rollout shape, we can factor a shared helper if it helps.

### Internal structure of `step`

`step` does three things in order: apply the action, alternate the active player if a worker placement just completed, then auto-advance phase transitions until the next decision point.

```python
def step(state: GameState, action: Action) -> GameState:
    if state.phase == Phase.BEFORE_SCORING:
        raise RuntimeError("step called on a terminated game")

    # 1. Apply the agent's action.
    state = _apply_action(state, action)

    # 2. If a worker placement just completed (stack is now empty in WORK),
    #    rotate to the next player who has workers. This is THE alternation
    #    point — it does not run at any other time.
    #
    #    The `state.phase == Phase.WORK` clause is a safety guard. In Task 5
    #    step is only ever called during WORK (no agent decisions during
    #    RETURN_HOME or PREPARATION), so the clause is redundant for Task 5.
    #    It matters once cards introduce mid-RETURN_HOME / mid-PREPARATION /
    #    mid-HARVEST triggers that require agent input: at that point step
    #    is called in those phases, and we do NOT want to alternate workers
    #    when the player resolves a return-home trigger — workers aren't
    #    being placed during RETURN_HOME. The clause guards against that.
    if state.phase == Phase.WORK and not state.pending_stack:
        state = _advance_current_player(state)

    # 3. Walk through any system-driven transitions (phase changes, etc.)
    #    until the next agent decision OR the game ends.
    state = _advance_until_decision(state)
    return state
```

#### Why alternation lives in `step` and not in `_advance_until_decision`

`_advance_until_decision` runs based on state alone. Two state snapshots can be identical but require different alternation behavior:

- **Just transitioned PREPARATION → WORK at round start.** `phase=WORK, stack=(), current_player=starting_player, both have workers.` We should NOT alternate — starting_player gets the first placement.
- **starting_player just completed an atomic placement.** Identical observable state. We SHOULD alternate.

Distinguishing these requires knowing what the caller just did. `step` knows it just applied an action; `_advance_until_decision` doesn't. Therefore alternation lives in `step`.

#### `_advance_current_player`

```python
def _advance_current_player(state: GameState) -> GameState:
    """Rotate current_player to the next player in turn order who has
    workers to place. If only the current player has workers, return state
    unchanged (they keep placing). If no player has workers, return state
    unchanged — `_advance_until_decision` then transitions to RETURN_HOME.

    Modular arithmetic generalizes to N-player games even though Task 5 has 2.
    """
    num_players = len(state.players)
    for offset in range(1, num_players):
        candidate = (state.current_player + offset) % num_players
        # TODO: when card effects allow placing with people_home == 0
        #       (e.g., certain occupations grant "free" placements), the
        #       predicate below will need to consult those card states.
        if state.players[candidate].people_home > 0:
            return dataclasses.replace(state, current_player=candidate)
    return state
```

#### `_apply_action`

Dispatch on action type:

```python
def _apply_action(state: GameState, action: Action) -> GameState:
    if isinstance(action, PlaceWorker):
        return _apply_place_worker(state, action)
    if isinstance(action, ChooseSubAction):
        return _apply_choose_sub_action(state, action)
    if isinstance(action, CommitSow):
        return _apply_commit_sow(state, action)
    if isinstance(action, CommitBake):
        return _apply_commit_bake(state, action)
    if isinstance(action, FireTrigger):
        return _apply_fire_trigger(state, action)
    if isinstance(action, Stop):
        return _apply_stop(state)
    raise TypeError(f"Unknown action type: {type(action).__name__}")
```

Each `_apply_<type>` handler has defensive assertions on the stack shape it expects (see individual handlers below). These are NOT legality checks — they catch caller misuse (e.g., passing a sub-action when the stack is empty) with clear error messages rather than the cryptic `IndexError` you'd get from `state.pending_stack[-1]` on an empty stack.

#### `_apply_place_worker`

```python
ATOMIC_HANDLERS = {  # imported from agricola.resolution
    "day_laborer": _resolve_day_laborer,
    "forest":       _resolve_forest,
    # ... all 12 atomic spaces
}

NONATOMIC_HANDLERS = {
    "grain_utilization": _resolve_grain_utilization,
    # Other non-atomic spaces added here as they're implemented in future tasks.
}


def _apply_place_worker(state: GameState, action: PlaceWorker) -> GameState:
    # Cross-cutting bookkeeping: workers, people_home.
    state = _apply_worker_placement(state, action.space)

    if action.space in ATOMIC_HANDLERS:
        return ATOMIC_HANDLERS[action.space](state)

    if action.space in NONATOMIC_HANDLERS:
        return NONATOMIC_HANDLERS[action.space](state)

    raise NotImplementedError(
        f"Non-atomic space {action.space!r} is not implemented in Task 5"
    )
```

`_apply_worker_placement` is imported from `agricola.resolution`.

#### `_apply_choose_sub_action`

Dispatch keyed by the type of the top-of-stack pending:

```python
CHOOSE_SUBACTION_HANDLERS = {
    PendingGrainUtilization: _choose_subaction_grain_utilization,
    # Other non-atomic pendings register here as they're added.
}


def _apply_choose_sub_action(state: GameState, action: ChooseSubAction) -> GameState:
    assert state.pending_stack, "ChooseSubAction called with empty pending_stack"
    top = state.pending_stack[-1]
    handler = CHOOSE_SUBACTION_HANDLERS.get(type(top))
    if handler is None:
        raise ValueError(
            f"No ChooseSubAction handler registered for pending type "
            f"{type(top).__name__}"
        )
    return handler(state, action)


def _choose_subaction_grain_utilization(state: GameState, action: ChooseSubAction):
    top = state.pending_stack[-1]
    if action.name == "sow":
        return _push(state, PendingSow(player_idx=top.player_idx))
    if action.name == "bake_bread":
        return _push(state, PendingBakeBread(player_idx=top.player_idx))
    raise ValueError(
        f"Unknown sub-action {action.name!r} for Grain Utilization"
    )
```

The `_push` helper:

```python
def _push(state: GameState, frame: PendingDecision) -> GameState:
    return dataclasses.replace(state, pending_stack=state.pending_stack + (frame,))
```

#### `_apply_commit_sow` and `_apply_commit_bake`

Both pop the top frame (the category pending) and mark the corresponding flag on the parent (space pending). The "find the parent" step is just reading `state.pending_stack[-1]` after the pop — the stack invariant guarantees the parent is exposed.

```python
def _apply_commit_sow(state: GameState, action: CommitSow) -> GameState:
    assert state.pending_stack, "CommitSow called with empty pending_stack"
    top = state.pending_stack[-1]
    assert isinstance(top, PendingSow), (
        f"CommitSow expected top=PendingSow, got {type(top).__name__}"
    )
    state = _execute_sow(state, top.player_idx, action.grain, action.veg)
    state = _pop(state)
    # New top is the parent space pending (per stack invariant).
    parent = state.pending_stack[-1]
    new_parent = dataclasses.replace(parent, sow_done=True)
    return _replace_top(state, new_parent)


def _apply_commit_bake(state: GameState, action: CommitBake) -> GameState:
    assert state.pending_stack, "CommitBake called with empty pending_stack"
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBakeBread), (
        f"CommitBake expected top=PendingBakeBread, got {type(top).__name__}"
    )
    state = _execute_bake(state, top.player_idx, action.grain)
    state = _pop(state)
    parent = state.pending_stack[-1]
    new_parent = dataclasses.replace(parent, bake_done=True)
    return _replace_top(state, new_parent)
```

The `dataclasses.replace(parent, sow_done=True)` call works because the parent class has a `sow_done` field. Currently only `PendingGrainUtilization` does. If future Sow-offering pendings exist (e.g., `PendingCultivation`), they'll need a `sow_done` field too — or `_apply_commit_sow` will need a parent-type dispatch.

Helpers:

```python
def _pop(state: GameState) -> GameState:
    return dataclasses.replace(state, pending_stack=state.pending_stack[:-1])

def _replace_top(state: GameState, new_top: PendingDecision) -> GameState:
    return dataclasses.replace(
        state,
        pending_stack=state.pending_stack[:-1] + (new_top,),
    )
```

#### `_apply_fire_trigger`

Looks up the trigger by `card_id` (direct lookup in the card-keyed `CARDS` registry — see the cards section), applies the card's effect, and marks the top frame's `triggers_resolved`. No push or pop.

```python
from agricola.cards.triggers import CARDS


def _apply_fire_trigger(state: GameState, action: FireTrigger) -> GameState:
    assert state.pending_stack, "FireTrigger called with empty pending_stack"
    top = state.pending_stack[-1]
    entry = CARDS[action.card_id]
    state = entry.apply_fn(state, top.player_idx)
    new_top = dataclasses.replace(
        top, triggers_resolved=top.triggers_resolved | {action.card_id},
    )
    return _replace_top(state, new_top)
```

Note: `step` does not verify that `action.card_id`'s registered event matches the top pending's `TRIGGER_EVENT`. Per the "step trusts callers" convention, this is `legal_actions`' job — and `legal_actions` only emits `FireTrigger` for triggers whose registered event matches the top pending's `TRIGGER_EVENT`. If a misuse slips through, the trigger's effect runs in the wrong context — which would manifest as an incorrect state, not a crash. Tests should catch this.

#### Trigger declination is implicit

There is no `_apply_skip_trigger` handler and no `SkipTrigger` action. A player declines a trigger by simply not firing it: they pick a `CommitX(...)` (which pops the pending and discards the unresolved triggers) or fire a different trigger. The trigger remains in `legal_actions` as long as it's eligible and unfired; once the pending pops, it vanishes.

This is the explicit deletion of an earlier design that had `SkipTrigger` and `_can_skip_trigger`. Reason: the SkipTrigger action didn't add expressive power — committing or firing another trigger achieves the same effect of "decline this trigger" — and removing it eliminates a thorny one-ply-lookahead helper. See the corresponding note in CLAUDE.md's "Engine and Turn Resolution Architecture" → "The pending-decision stack" subsection (the design philosophy "There is no `SkipTrigger` action").

#### `_apply_stop`

```python
def _apply_stop(state: GameState) -> GameState:
    assert state.pending_stack, "Stop called with empty pending_stack"
    return _pop(state)
```

`_apply_stop` does NOT assert the stack is empty after popping. Future cards may have pending stacks where `Stop` legitimately pops a non-bottom frame, leaving deeper frames intact. The "Stop only pops the top frame" semantics is the right invariant, not "Stop ends the whole non-atomic action."

In Task 5, the only frame where `Stop` is legal is the outermost (PendingGrainUtilization), and that's always the bottommost frame. So Stop happens to empty the stack — but that's a Task-5-specific coincidence, not a property `_apply_stop` should enforce.

#### A note on end-of-turn detection and at-any-time actions (forward compatibility)

In Task 5, `state.pending_stack == ()` after `step` in WORK phase unambiguously means "a worker placement just completed; alternate." This works because the only way for the stack to become empty mid-turn is via an atomic `PlaceWorker` or via `Stop` on a non-atomic action — both of which signify the player's turn is complete.

When cards introduce **at-any-time actions** (Mandoline's "exchange 1 vegetable for 1 bonus point" can fire whenever; Fireplace's at-any-time animal-to-food conversion likewise), this assumption breaks: an empty stack mid-turn no longer means "turn done." The player may want to use an at-any-time action before alternating, or place food on future round spaces (Mandoline), or trigger Fireplace conversions.

The forward-compatible resolution: when the card system arrives, `legal_actions` at empty stack / WORK phase returns `[<all currently-applicable at-any-time actions>, EndTurn()]` instead of jumping straight to alternation. The agent picks one. `EndTurn` is the action that triggers alternation; at-any-time actions don't. `step` is amended so it alternates on `EndTurn` rather than on "stack became empty."

For Task 5: no at-any-time actions, no `EndTurn` action; alternation triggers on "stack became empty in WORK phase." Note this in the implementation; future card task will widen `legal_actions` and introduce `EndTurn`.

### `_advance_until_decision`

This is the auto-advance loop. It runs at the end of every `step` call. The loop terminates when the state is at a real agent decision OR the game is over. It handles only phase transitions — current-player alternation is `step`'s job (see "Why alternation lives in `step`" above).

```python
def _advance_until_decision(state: GameState) -> GameState:
    while True:
        # Case 1: a pending frame is active. Decision is awaiting agent.
        if state.pending_stack:
            return state

        # Case 2: terminal phase. No more steps possible.
        if state.phase == Phase.BEFORE_SCORING:
            return state

        # Case 3: WORK phase. If any player has workers, an agent decision
        #         is awaiting. If neither does, the work phase ends.
        if state.phase == Phase.WORK:
            if all(p.people_home == 0 for p in state.players):
                state = dataclasses.replace(state, phase=Phase.RETURN_HOME)
                continue
            return state

        # Case 4: RETURN_HOME — perform end-of-round bookkeeping.
        if state.phase == Phase.RETURN_HOME:
            state = _resolve_return_home(state)
            continue

        # Case 5: PREPARATION — set up the new round.
        if state.phase == Phase.PREPARATION:
            state = _resolve_preparation(state)
            continue

        # TODO: when the harvest is implemented, add branches here for
        # HARVEST_FIELD, HARVEST_FEED, HARVEST_BREED. The harvest is
        # entered from _resolve_return_home on rounds 4, 7, 9, 11, 13, 14
        # (see HARVEST_ROUNDS in constants.py) and exits to PREPARATION
        # (for rounds < 14) or BEFORE_SCORING (for round 14).
        raise AssertionError(f"Unexpected phase in advance loop: {state.phase}")
```

### Phase resolvers

The two phase resolvers each do one phase's bookkeeping and transition to the next phase. They are pure functions over state.

#### `_resolve_return_home`

```python
def _resolve_return_home(state: GameState) -> GameState:
    """End-of-round bookkeeping: reset worker placements, return people
    home. Does NOT clear newborns (those need to survive to HARVEST_FEED
    for the 1-food discount; clearing happens in _resolve_preparation of
    the next round). Does NOT increment round_number (that happens in
    _resolve_preparation).

    Transitions to PREPARATION for ongoing rounds, or to BEFORE_SCORING
    after round 4 in Task 5.
    """
    # Future: card triggers fire here ("when you return home from
    # action space X, may do Y"). Stub for Task 5.
    # _check_return_home_triggers(state)

    # 1. Reset every action space's worker tuple. Unrevealed spaces
    #    already have workers=(0, 0); the reset is a no-op for them.
    new_spaces = {
        space_id: dataclasses.replace(action_space, workers=(0, 0))
        for space_id, action_space in state.board.action_spaces.items()
    }
    new_board = dataclasses.replace(state.board, action_spaces=new_spaces)

    # 2. Return all people home. Newborns NOT cleared here.
    new_players = tuple(
        dataclasses.replace(p, people_home=p.people_total)
        for p in state.players
    )

    state = dataclasses.replace(state, players=new_players, board=new_board)

    # 3. Decide next phase.
    # Task 5: halt after round 4 (harvest is unimplemented).
    if state.round_number >= 4:
        return dataclasses.replace(state, phase=Phase.BEFORE_SCORING)

    # TODO: when the harvest is implemented, on HARVEST_ROUNDS (4, 7, 9,
    # 11, 13, 14) this should transition to Phase.HARVEST_FIELD instead
    # of Phase.PREPARATION. The harvest itself (Field/Feed/Breed) is a
    # distinct multi-phase entity with its own resolvers and player
    # decisions; _resolve_return_home only triggers the transition, it
    # does NOT run any harvest logic. After the harvest completes, the
    # game transitions to Phase.PREPARATION for the next round (rounds
    # 1–13), or directly to Phase.BEFORE_SCORING (after round 14's
    # HARVEST_BREED).
    return dataclasses.replace(state, phase=Phase.PREPARATION)
```

The dict comprehension on line "new_spaces = ..." builds a fresh dict where every action space's `workers` field is zeroed. `state.board.action_spaces.items()` returns `(space_id, ActionSpaceState)` pairs; the loop unpacks each into `space_id` (string like `"forest"`) and `action_space` (the dataclass). `dataclasses.replace(action_space, workers=(0, 0))` returns a new `ActionSpaceState` identical to `action_space` except `workers` is now `(0, 0)`. The other fields (`accumulated`, `accumulated_amount`, `round_revealed`) are carried over unchanged. The result is a new dict with the same keys but updated values.

#### `_resolve_preparation`

```python
def _resolve_preparation(state: GameState) -> GameState:
    """Set up the new round: increment round_number, refill revealed
    accumulation spaces, distribute future_resources for this round,
    clear newborns (their harvest discount has already been applied),
    and reset current_player to starting_player.

    Not called for round 1 (setup pre-loads round-1 accumulation goods
    and the engine starts at Phase.WORK). Called for rounds 2+, after
    RETURN_HOME (or, in the future, after the harvest).
    """
    # Future: card triggers fire here ("at the start of each round, may
    # do X"). Stub for Task 5.
    # _check_preparation_triggers(state)

    new_round = state.round_number + 1

    # 1. Refill revealed accumulation spaces. After incrementing the
    #    round counter, the comparison `round_revealed <= new_round`
    #    correctly identifies the just-revealed stage card too.
    new_spaces = dict(state.board.action_spaces)
    for space_id, action_space in list(new_spaces.items()):
        if action_space.round_revealed > new_round:
            continue   # not yet revealed
        if space_id in BUILDING_ACCUMULATION_RATES:
            rate = BUILDING_ACCUMULATION_RATES[space_id]
            new_spaces[space_id] = dataclasses.replace(
                action_space, accumulated=action_space.accumulated + rate,
            )
        elif space_id in FOOD_ANIMAL_ACCUMULATION_RATES:
            _, rate = FOOD_ANIMAL_ACCUMULATION_RATES[space_id]
            new_spaces[space_id] = dataclasses.replace(
                action_space,
                accumulated_amount=action_space.accumulated_amount + rate,
            )
    new_board = dataclasses.replace(state.board, action_spaces=new_spaces)

    # 2. Per-player: distribute future_resources, clear newborns.
    idx = new_round - 1
    new_players = tuple(
        dataclasses.replace(
            p,
            resources=p.resources + p.future_resources[idx],
            future_resources=(p.future_resources[:idx]
                              + (Resources(),)
                              + p.future_resources[idx+1:]),
            newborns=0,
        )
        for p in state.players
    )

    # 3. Transition to WORK with starting_player as the active player.
    return dataclasses.replace(
        state,
        round_number=new_round,
        players=new_players,
        board=new_board,
        phase=Phase.WORK,
        current_player=state.starting_player,
    )
```

**Why newborns clear here, not in `_resolve_return_home`.** Per RULES.md, a newborn placed in round X requires only 1 food at the harvest at the end of round X (their "birth-round harvest"), then 2 food at every subsequent harvest. If RETURN_HOME cleared `newborns`, HARVEST_FEED would see 0 newborns and charge 2 food each — losing the discount. By clearing in PREPARATION (the start of the next round), `newborns` survives RETURN_HOME and the harvest, and is correctly cleared at the start of the following round.

**Round numbering.** `_resolve_preparation` is responsible for incrementing `round_number`. After RETURN_HOME of round X, `round_number` is still X. After PREPARATION runs, `round_number` is X+1. WORK then runs at round X+1.

**Why PREP isn't called for round 1.** `setup` already pre-loads round-1 accumulation goods and starts the engine at `Phase.WORK` with `round_number=1`. The first `_resolve_preparation` call happens after round 1's RETURN_HOME, incrementing `round_number` to 2 and refilling for round 2.

### Forward-compatibility note: phase resolvers and card triggers

The current `_resolve_return_home` and `_resolve_preparation` each do their entire phase's mechanical work as a single function call. This works for Task 5 because nothing during these phases requires an agent decision.

Once cards introduce triggers during these phases (e.g., various occupations have "at the start of each round" effects during PREPARATION; others have "when you return home" effects during RETURN_HOME), some triggers will require agent input — and a resolver that's "in the middle of doing its work" can't simply terminate and re-enter cleanly. If `_resolve_preparation` ran its refill, then encountered a trigger that needs the agent, and returned partway through, the next call would re-run the refill — accumulating goods twice.

The forward-compatible fix is to split each phase into **sub-phases**, each of which is its own `Phase` enum value (e.g. `Phase.RETURN_HOME_TRIGGER`, `Phase.RETURN_HOME_MECHANICAL`, `Phase.PREPARATION_TRIGGER_PRE`, `Phase.PREPARATION_REFILL`, `Phase.PREPARATION_FUTURE_RESOURCES`, `Phase.PREPARATION_TRIGGER_POST`, ...). Each sub-phase does exactly one piece of work and transitions to the next. The engine never re-enters a completed sub-phase because the sub-phase identity advances after each step.

We don't add these sub-phases now — they would clutter Task 5 without serving any purpose. The plan when cards arrive: split as needed, update `_advance_until_decision` to handle the new phases. Keep this note as a flag so the future session knows the design intent.

---

## Refactor: `agricola/resolution.py`

The current public function `resolve_atomic(state, action)` is removed. Its body is inlined into `step`'s atomic-handler dispatch via `ATOMIC_HANDLERS`. The handlers themselves (`_resolve_day_laborer`, `_resolve_forest`, etc.) and the cross-cutting `_apply_worker_placement` remain in `resolution.py` and are imported by `engine.py`.

The handlers are unchanged. Only the top-level public function is removed.

After the refactor, `resolution.py` contains:
- `_update_player`, `_update_space` (state-mutation helpers).
- `_apply_worker_placement` (cross-cutting bookkeeping).
- All `_resolve_*` atomic handlers.
- `_resolve_building_accumulation`, `_resolve_food_accumulation` (shared helpers).
- `_resolve_wish_for_children` (shared helper).
- `ATOMIC_HANDLERS` dict.

Tests that imported `resolve_atomic` are updated to import and use `step`. The `tests/test_resolution_atomic.py` test suite is largely preserved — each test wraps its `resolve_atomic(state, PlaceWorker("..."))` call with `step(state, PlaceWorker("..."))` and asserts the same postconditions, plus an additional assertion that `pending_stack == ()` (atomic placements do not push pendings).

---

## Implementation: Grain Utilization

### `_resolve_grain_utilization`

```python
def _resolve_grain_utilization(state: GameState) -> GameState:
    return _push(state, PendingGrainUtilization(player_idx=state.current_player))
```

That's the entire entry point. Cross-cutting worker placement is already done by `_apply_worker_placement` (called by `_apply_place_worker` before dispatching).

### Per-pending legality enumerators

**Two distinct legality functions for Grain Utilization exist.** They serve different roles and have different signatures:

- `_legal_grain_utilization(state) -> bool` — already exists in `legality.py`. Returns True iff `PlaceWorker("grain_utilization")` is a legal placement at the current state. Called during placement enumeration (when `pending_stack` is empty). Used as an entry in `NON_ATOMIC_LEGALITY`.

- `_enumerate_pending_grain_utilization(state, pending) -> list[Action]` — new in Task 5. Returns the list of legal sub-actions when `PendingGrainUtilization` is on top of the stack. Called from `_enumerate_pending` when the agent is mid-resolution of Grain Utilization.

Don't conflate them: the first answers "can the player take this worker placement?", the second answers "what sub-actions can the player pick now that they have?" Different return types (bool vs list), different callers, different purposes. The placement predicate doesn't need a `pending` argument because at placement-decision time the pending doesn't exist yet.

The per-pending enumerators below live in `agricola/legality.py` alongside the existing helpers, in a new section after the placement predicates.

```python
def _enumerate_pending_grain_utilization(state, pending: PendingGrainUtilization):
    p = state.players[pending.player_idx]
    actions = []
    # Sow category
    if not pending.sow_done and _can_sow(p):
        actions.append(ChooseSubAction("sow"))
    # Bake bread category
    if not pending.bake_done and _can_bake_bread(state, p):
        actions.append(ChooseSubAction("bake_bread"))
    # Stop: legal iff at least one sub-action has been completed
    if pending.sow_done or pending.bake_done:
        actions.append(Stop())
    return actions


def _enumerate_pending_sow(state, pending: PendingSow):
    p = state.players[pending.player_idx]
    # Enumerate all (grain, veg) commits that are physically achievable.
    # Constraints:
    #   - grain + veg >= 1 (must sow at least one field)
    #   - grain <= p.resources.grain
    #   - veg <= p.resources.veg
    #   - grain + veg <= number of empty field cells
    empty_fields = sum(
        1 for r in range(3) for c in range(5)
        if p.farmyard.grid[r][c].cell_type == CellType.FIELD
        and p.farmyard.grid[r][c].grain == 0
        and p.farmyard.grid[r][c].veg == 0
    )
    actions = []
    for g in range(p.resources.grain + 1):
        for v in range(p.resources.veg + 1):
            if g + v == 0 or g + v > empty_fields:
                continue
            actions.append(CommitSow(grain=g, veg=v))
    return actions


def _enumerate_pending_bake_bread(state, pending: PendingBakeBread):
    from agricola.cards.triggers import TRIGGERS

    p = state.players[pending.player_idx]
    actions = []

    # Enumerate eligible unfired triggers, filtered by the pending's event.
    # No SkipTrigger entry — declining is implicit (player picks a Commit
    # or a different trigger instead of firing this one).
    event = type(pending).TRIGGER_EVENT   # "before_bake_bread"
    for entry in TRIGGERS.get(event, []):
        if entry.card_id in pending.triggers_resolved:
            continue
        if not entry.eligibility_fn(state, pending.player_idx, pending.triggers_resolved):
            continue
        actions.append(FireTrigger(card_id=entry.card_id))

    # Enumerate commit options (positive grain amounts up to supply).
    # If a trigger is eligible and the player has no legal commit, the only
    # legal action will be the FireTrigger — the player is forced to fire
    # (no SkipTrigger to filter out, no lookahead needed).
    if _can_bake_bread(state, p):
        for n in range(1, p.resources.grain + 1):
            actions.append(CommitBake(grain=n))

    return actions
```

### Effect functions

`_execute_sow` and `_execute_bake` live in `agricola/resolution.py` (extending the existing handlers):

```python
def _execute_sow(state: GameState, player_idx: int, grain: int, veg: int) -> GameState:
    """Sow grain and/or veg onto empty field cells.

    Per RULES.md: 1 grain from supply → 3 grain on field (player's 1 + 2 from
    general supply). 1 veg from supply → 2 veg on field (player's 1 + 1 from
    general supply). Empty field cells are filled in canonical (row, col) order;
    grain is sown first if both grain and veg are committed in the same action.
    """
    p = state.players[player_idx]
    # Subtract from supply.
    new_resources = p.resources + Resources(grain=-grain, veg=-veg)

    # Walk the grid in canonical order, filling empty fields.
    new_grid_rows = []
    g_remaining, v_remaining = grain, veg
    for r in range(3):
        new_row = []
        for c in range(5):
            cell = p.farmyard.grid[r][c]
            if (cell.cell_type == CellType.FIELD
                and cell.grain == 0 and cell.veg == 0):
                if g_remaining > 0:
                    new_row.append(dataclasses.replace(cell, grain=3))
                    g_remaining -= 1
                elif v_remaining > 0:
                    new_row.append(dataclasses.replace(cell, veg=2))
                    v_remaining -= 1
                else:
                    new_row.append(cell)
            else:
                new_row.append(cell)
        new_grid_rows.append(tuple(new_row))

    assert g_remaining == 0 and v_remaining == 0, (
        "Sow targets exceeded empty field count; legality should have caught this"
    )

    new_farmyard = dataclasses.replace(p.farmyard, grid=tuple(new_grid_rows))
    new_player = dataclasses.replace(p, resources=new_resources, farmyard=new_farmyard)
    return _update_player(state, player_idx, new_player)


def _execute_bake(state: GameState, player_idx: int, grain: int) -> GameState:
    """Bake `grain` grain into food using the best owned baking improvement.

    Task 5 implements only Fireplace and Cooking Hearth rates. Per RULES.md:
    Cooking Hearth converts 1 grain → 3 food; Fireplace converts 1 grain → 2
    food. If the player owns both, Cooking Hearth's better rates apply.

    Clay Oven and Stone Oven are NOT yet supported by this function: their
    rates are parameterized differently ("exactly 1 grain → 5 food" for Clay
    Oven; "up to 2 grain → 4 food each" for Stone Oven) and don't fit the
    "any N grain at fixed rate per grain" shape used by Fireplace/Hearth.
    If a player owns ONLY Clay Oven or Stone Oven (no Fireplace, no Hearth)
    and triggers this code path, raise NotImplementedError with a clear
    message pointing at the deferred work.

    In Task 5 scope, Major Improvement (the only way to acquire any oven) is
    unimplemented, so this raise is purely defensive — no normal gameplay
    can reach it. The point is to fail loudly if a future test or REPL
    session manually constructs such a state.
    """
    p = state.players[player_idx]
    owns = state.board.major_improvement_owners
    if any(owns[i] == player_idx for i in (2, 3)):
        rate = 3
    elif any(owns[i] == player_idx for i in (0, 1)):
        rate = 2
    else:
        raise NotImplementedError(
            "Baking with only Clay Oven (idx 5) or Stone Oven (idx 6) "
            "is not yet implemented; their parameterized rates differ "
            "from Fireplace/Hearth and will be added in a later task. "
            f"Owned majors for player {player_idx}: "
            f"{[i for i, o in enumerate(owns) if o == player_idx]}"
        )

    new_resources = p.resources + Resources(grain=-grain, food=rate * grain)
    new_player = dataclasses.replace(p, resources=new_resources)
    return _update_player(state, player_idx, new_player)
```

**`_can_bake_bread` and `BAKING_IMPROVEMENTS` — no changes to scope.** `BAKING_IMPROVEMENTS = frozenset({0, 1, 2, 3, 5, 6})` is preserved as is — it matches the rules. Task 5's *only* change to `_can_bake_bread` is adding the `BAKE_BREAD_ELIGIBILITY_EXTENSIONS` registry hook for card-driven eligibility broadening (Potter Ceramics). The base predicate continues to say yes if any baking improvement is owned and grain ≥ 1.

The "I own only Clay/Stone Oven and want to bake" case is now gated by `_execute_bake` raising `NotImplementedError` rather than by `_can_bake_bread` returning False. This keeps legality rules-faithful and localizes the Task 5 implementation gap to where the gap actually exists.

---

## The card framework — design overview

This section explains the trigger architecture so future cards plug in cleanly. Potter Ceramics is the worked example; other cards with similar timings ("before X", "after X", "when you Y") follow the same pattern.

### Where cards live

```
agricola/
  cards/
    __init__.py        # imports every card module to populate the registry
    triggers.py        # the registry: TRIGGERS dict, TriggerEntry, register()
    potter_ceramics.py
    # future card modules
```

### The trigger registry — two-dict design

Two queries need to be fast:

- **Query A:** "What unfired triggers are eligible at the current top pending?" — used by `legal_actions` enumerators. The query is keyed by event name (e.g., `"before_bake_bread"`), retrieved from the top pending's `TRIGGER_EVENT` class attribute.
- **Query B:** "Given `card_id`, what's its trigger info?" — used by `_apply_fire_trigger` to apply the card's effect. Just a direct `card_id` lookup.

Two registries serve them naturally. `register()` populates both.

`agricola/cards/triggers.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class TriggerEntry:
    card_id: str
    event: str
    eligibility_fn: Callable   # (state, player_idx, triggers_resolved) -> bool
    apply_fn: Callable         # (state, player_idx) -> GameState


# Event-keyed registry — for Query A.
TRIGGERS: dict[str, list[TriggerEntry]] = {}

# Card-keyed registry — for Query B (direct lookup by card_id).
CARDS: dict[str, TriggerEntry] = {}


def register(event: str, card_id: str, eligibility_fn, apply_fn) -> None:
    """Called at import time by each card module."""
    entry = TriggerEntry(card_id, event, eligibility_fn, apply_fn)
    TRIGGERS.setdefault(event, []).append(entry)
    CARDS[card_id] = entry
```

`_apply_fire_trigger` uses `CARDS` for direct O(1) lookup; legal-actions enumerators iterate `TRIGGERS[event]` filtered by eligibility.

### Event names

Each event is a string identifying the trigger site. For Task 5 we only need:

- `"before_bake_bread"` — fires before a `CommitBake` is committed.

Future events will be added as needed. Suggested naming convention: `"before_<sub_action>"`, `"after_<sub_action>"`, `"when_<event>"`. Documenting each event's signature (when it fires, what `player_idx` means, what `triggers_resolved` is scoped to) is the card task's responsibility.

### Signature of `eligibility_fn` and `apply_fn`

For `"before_bake_bread"`:

- `eligibility_fn(state, player_idx, triggers_resolved) -> bool` — does the player own the card, has the card not yet fired this action, are the card's preconditions met (e.g., clay >= 1 for Potter's)?
- `apply_fn(state, player_idx) -> GameState` — apply the card's effect (exchange, gain, etc.).

Other events may have different signatures (e.g., out-of-turn triggers carry an `event_player_idx` to identify whose action triggered it). Each event documents its own signature.

### `__init__.py` populates the registry

`agricola/cards/__init__.py`:

```python
"""Card package. Imports every card module so their register() calls run."""
from agricola.cards import potter_ceramics   # noqa: F401
# Future card modules added here.
```

Importing `agricola.cards` triggers the registration. The engine module imports `agricola.cards` (perhaps via `agricola.cards.triggers`) to ensure the registry is populated before any trigger lookup.

### Known limitation: compound card interactions

The extension-registry pattern (`BAKE_BREAD_ELIGIBILITY_EXTENSIONS`) handles cards whose eligibility check fits the shape "yes if condition X is true *right now*." Potter Ceramics works because its check — "you have clay and a baker" — is satisfiable from the current state. Each extension predicate inspects the literal current `state`.

It does NOT handle cards whose effect fires *upstream* of the predicate being checked, such that the predicate would need to consider a hypothetical post-effect state. Concrete example: **Pan Baker** ("each time you use the Grain Utilization action space, you get 2 clay and 1 wood"). A player who owns Pan Baker AND Potter Ceramics, with 0 clay and 0 grain at the moment of placement, can in fact take Grain Utilization:

1. Place worker on Grain Utilization.
2. Pan Baker fires (on-placement effect): +2 clay, +1 wood. Player now has 2 clay.
3. Choose Bake Bread sub-action.
4. Potter Ceramics fires: -1 clay, +1 grain. Player now has 1 clay, 1 grain.
5. CommitBake(1): +2 food.

But the current `_can_bake_bread(state, p)` — even with the Potter Ceramics extension — reads the *literal* `state` (0 clay) and returns False. So `_legal_grain_utilization` would return False, and the placement is reported as illegal. Pan Baker's contribution is invisible to the predicate.

Resolving this correctly requires the legality system to simulate "on placement" card effects speculatively, then check sub-action predicates against the resulting hypothetical state. Two pieces would need to be added in the eventual card-system task:

1. **A category of cards registered as "on-placement state transformers"** (Pan Baker is the canonical example). These register an `apply_fn` against an event like `"on_take_space:grain_utilization"` in the same `TRIGGERS` registry we already have.

2. **A speculative legality check** that, when deciding whether `PlaceWorker(space)` is legal, applies all owned cards' "on-placement" transformations to the state and asks the existing sub-action predicates against the hypothetical. If any reachable hypothetical state has a legal sub-action commit path, the placement is legal.

The state-space search is small (each card's effect fires at most once per placement; few cards are owned at any time), so this is not a performance concern — just a generalization of the legality machinery.

**This is out of scope for Task 5.** Potter Ceramics alone doesn't exercise this complication because it has no on-placement effect — its trigger fires only during the Bake Bread sub-action, after the placement is settled. The extension-registry pattern correctly handles cards of the Potter Ceramics shape and will continue to work alongside the eventual speculative-legality machinery (the two pieces are orthogonal).

The trigger registry's `TRIGGERS` dict already supports arbitrary event names, so `"on_take_space:grain_utilization"` events can be registered today without any registry changes. The missing piece is the legality-side machinery to apply those effects speculatively. Flagging this here so the card-system task starts with the full picture.

---

## Implementation: Potter Ceramics

The Potter Ceramics card text: "Each time before you take a Bake Bread action, you can exchange exactly 1 clay for 1 grain."

### `agricola/cards/potter_ceramics.py`

```python
"""Potter Ceramics (minor improvement).

Effect: Each time before a Bake Bread action, the owner may exchange exactly
1 clay for 1 grain. Available at most once per Bake Bread action.
"""
from __future__ import annotations

import dataclasses

from agricola.cards.triggers import register
from agricola.resources import Resources
from agricola.state import GameState


CARD_ID = "potter_ceramics"


def _eligible(state: GameState, player_idx: int, triggers_resolved: frozenset) -> bool:
    if CARD_ID in triggers_resolved:
        return False
    p = state.players[player_idx]
    if CARD_ID not in p.minor_improvements:
        return False
    return p.resources.clay >= 1


def _apply(state: GameState, player_idx: int) -> GameState:
    p = state.players[player_idx]
    new_resources = p.resources + Resources(clay=-1, grain=1)
    new_player = dataclasses.replace(p, resources=new_resources)
    # Inline update — avoid circular import with resolution.py's _update_player.
    new_players = tuple(
        new_player if i == player_idx else state.players[i]
        for i in range(2)
    )
    return dataclasses.replace(state, players=new_players)


register("before_bake_bread", CARD_ID, _eligible, _apply)
```

### The legality cascade — how Potter's affects `_can_bake_bread`

The base predicate `_can_bake_bread(state, p)` is:

```python
def _can_bake_bread(state, p):
    if p.resources.grain >= 1 and _owns_baker(state, p):
        return True
    # Card extension: a card may broaden eligibility.
    for ext in BAKE_BREAD_ELIGIBILITY_EXTENSIONS:
        if ext(state, p):
            return True
    return False
```

with `BAKE_BREAD_ELIGIBILITY_EXTENSIONS: list[Callable]` populated by card modules via registration. Potter Ceramics registers:

```python
def _can_bake_bread_extension(state, p):
    # Player can bake if they can swap clay→grain via Potter's AND owns a baker.
    if CARD_ID not in p.minor_improvements:
        return False
    if p.resources.clay < 1:
        return False
    return _owns_baker(state, p)


register_bake_bread_extension(_can_bake_bread_extension)
```

`register_bake_bread_extension` is the wrapper function defined in `agricola/legality.py`:

```python
# agricola/legality.py
def register_bake_bread_extension(fn: Callable) -> None:
    """Add a card-supplied predicate that may broaden _can_bake_bread."""
    BAKE_BREAD_ELIGIBILITY_EXTENSIONS.append(fn)
```

Using a `register_*` wrapper rather than mutating the list directly matches the pattern in `agricola/cards/triggers.py` (`register(event, card_id, ...)`), gives us a single point to add validation later (e.g., reject duplicate registrations), and keeps the mutation surface explicit.

`_owns_baker` is a small helper:

```python
def _owns_baker(state, p):
    player_idx = 0 if p is state.players[0] else 1
    return any(state.board.major_improvement_owners[i] == player_idx
               for i in BAKING_IMPROVEMENTS)
```

### Putting it all together

For the full step-by-step walk-through of how Potter Ceramics interacts with Grain Utilization in a zero-grain state, see **Worked example B** in the PendingActionStack architecture section above. It covers the same scenario in more detail: setup, legality decisions, trigger insertion, state transitions, and turn termination.

The Potter Ceramics implementation contributes three things to that walk-through:

- **`_can_bake_bread_extension`** (registered via `register_bake_bread_extension`) — broadens `_can_bake_bread` to return True when the player has clay + a baker + Potter Ceramics. This is what makes `PlaceWorker("grain_utilization")` legal in the zero-grain state at step 0.
- **The `before_bake_bread` trigger entry** (registered via `register("before_bake_bread", ...)` in `triggers.py`) — appears in the candidate trigger list when `_enumerate_pending_bake_bread` runs.
- **The trigger's `apply_fn`** — performs the `-1 clay, +1 grain` exchange when `_apply_fire_trigger` calls it.

All three are registered at import time via the standard plugin pattern documented earlier.

---

## Legality changes

### `agricola/legality.py`

Add to the top of the file:

```python
# Registry of card-extending eligibility predicates. Each card that may
# broaden _can_bake_bread (and analogous helpers, when added) registers a
# predicate via register_bake_bread_extension().
BAKE_BREAD_ELIGIBILITY_EXTENSIONS: list[Callable] = []


def register_bake_bread_extension(fn: Callable) -> None:
    """Append fn to the bake-bread eligibility extension registry."""
    BAKE_BREAD_ELIGIBILITY_EXTENSIONS.append(fn)
```

Modify `_can_bake_bread` as shown above (extension registry hook). Do NOT narrow `BAKING_IMPROVEMENTS` — keep it as `frozenset({0, 1, 2, 3, 5, 6})` to remain rules-faithful. The Task 5 limitation on oven baking lives in `_execute_bake`, which raises `NotImplementedError` when no Fireplace or Hearth is owned.

Add the per-pending enumerators (`_enumerate_pending_grain_utilization`, `_enumerate_pending_sow`, `_enumerate_pending_bake_bread`).

Replace `legal_placements` with a `legal_actions` top-level function that dispatches on stack state. `legal_placements` remains as an internal helper (renamed if you prefer).

```python
def legal_actions(state: GameState) -> list[Action]:
    if state.phase == Phase.BEFORE_SCORING:
        return []
    if state.pending_stack:
        return _enumerate_pending(state, state.pending_stack[-1])
    if state.phase == Phase.WORK:
        return legal_placements(state)
    raise AssertionError(f"legal_actions called in unexpected state: {state.phase}")


PENDING_ENUMERATORS = {
    PendingGrainUtilization: _enumerate_pending_grain_utilization,
    PendingSow:              _enumerate_pending_sow,
    PendingBakeBread:        _enumerate_pending_bake_bread,
    # Future pending types register here.
}


def _enumerate_pending(state: GameState, top: PendingDecision) -> list[Action]:
    enumerator = PENDING_ENUMERATORS.get(type(top))
    if enumerator is None:
        raise AssertionError(f"No enumerator for pending type {type(top).__name__}")
    return enumerator(state, top)
```

### Ordering of returned actions

`legal_actions` returns a deterministic order. For placements, the existing alphabetical-by-space-id ordering is preserved. For pending enumerators, the order is documented per enumerator:

- `_enumerate_pending_grain_utilization`: `[ChooseSubAction("bake_bread")?, ChooseSubAction("sow")?, Stop()?]` — sub-actions alphabetically by name, then Stop last.
- `_enumerate_pending_sow`: `CommitSow(g, v)` entries sorted by `(g, v)` ascending.
- `_enumerate_pending_bake_bread`: `[FireTrigger(card)..., CommitBake(n)...]` — eligible triggers alphabetically by card_id, then commits in ascending order of grain amount.

---

## Test plan

### Testing principle: prefabricated states

Tests construct whatever state they need by direct dataclass construction, **not** by playing through a sequence of moves that happens to reach the desired state. This applies even — especially — to states that are not currently reachable through gameplay.

Rationale: many useful test scenarios depend on game configurations that Task 5 cannot produce. A player owning Potter Ceramics requires the Major Improvement / Lessons paths that Task 5 doesn't implement. A player with four plowed fields and a Cooking Hearth requires multiple rounds of Farmland and a Major Improvement purchase. A player mid-turn through a non-atomic action requires walking through prior `step` calls. Forcing tests to reach these states through play would (a) make the tests fragile to gameplay changes, (b) bloat each test with setup boilerplate, and (c) make it impossible to test certain behaviors before their gameplay prerequisites are implemented.

Instead, tests build the exact state they need using `dataclasses.replace` (or the helpers below) and assert on the behavior of the function under test against that state.

This principle is not new to the codebase — `tests/test_legality_non_atomic.py` already uses helpers like `_set_grid`, `_set_resources`, `_set_owner` to prefabricate states. Task 5 promotes this into an explicit, project-wide convention and adds a shared factories module so future test files don't reinvent the helpers.

### New file: `tests/factories.py`

Shared state-construction helpers used across test files.

```python
"""Test state factories.

Construct prefabricated GameState objects for testing, bypassing gameplay
constraints (round limits, unimplemented action spaces, etc.). Each helper
returns a NEW state — none mutate their input.
"""
from __future__ import annotations

import dataclasses
from typing import Optional

from agricola.constants import CellType, HouseMaterial, Phase
from agricola.pending import PendingDecision
from agricola.resources import Animals, Resources
from agricola.state import (
    ActionSpaceState, BoardState, Cell, Farmyard, GameState, PlayerState,
)


def with_resources(state, player_idx, **resource_kwargs):
    """Replace player_idx's resources with the given amounts (others zero).

    Example: with_resources(s, 0, grain=1, clay=2) sets player 0 to have
    exactly 1 grain and 2 clay, nothing else.
    """
    p = state.players[player_idx]
    return _replace_player(state, player_idx,
                            dataclasses.replace(p, resources=Resources(**resource_kwargs)))


def add_resources(state, player_idx, **resource_kwargs):
    """Add to player_idx's existing resources (does not replace)."""
    p = state.players[player_idx]
    new_res = p.resources + Resources(**resource_kwargs)
    return _replace_player(state, player_idx, dataclasses.replace(p, resources=new_res))


def with_animals(state, player_idx, **animal_kwargs):
    """Replace player_idx's animals with the given amounts."""
    p = state.players[player_idx]
    return _replace_player(state, player_idx,
                            dataclasses.replace(p, animals=Animals(**animal_kwargs)))


def with_house(state, player_idx, material: HouseMaterial):
    """Set player_idx's house material (does not change which cells are ROOMs)."""
    p = state.players[player_idx]
    return _replace_player(state, player_idx,
                            dataclasses.replace(p, house_material=material))


def with_majors(state, *, owner_by_idx: dict[int, int]):
    """Set major-improvement ownership. Keys are major-improvement indices
    (0..9); values are owning player_idx. Indices not in the dict remain None.

    Example: with_majors(s, owner_by_idx={0: 0}) gives player 0 a Fireplace.
    """
    owners = list(state.board.major_improvement_owners)
    for idx, player_idx in owner_by_idx.items():
        owners[idx] = player_idx
    new_board = dataclasses.replace(state.board, major_improvement_owners=tuple(owners))
    return dataclasses.replace(state, board=new_board)


def with_minors(state, player_idx, card_ids: frozenset[str]):
    """Set player_idx's played minor improvements."""
    p = state.players[player_idx]
    return _replace_player(state, player_idx,
                            dataclasses.replace(p, minor_improvements=card_ids))


def with_grid(state, player_idx, cell_overrides: dict[tuple[int, int], Cell]):
    """Replace specific cells in player_idx's farmyard grid.

    Example: with_grid(s, 0, {(0, 2): Cell(cell_type=CellType.FIELD)})
    plows a field at row 0, column 2 for player 0.
    """
    p = state.players[player_idx]
    grid = p.farmyard.grid
    new_grid = tuple(
        tuple(cell_overrides.get((r, c), grid[r][c]) for c in range(5))
        for r in range(3)
    )
    new_farmyard = dataclasses.replace(p.farmyard, grid=new_grid)
    # Note: pasture cache must be recomputed if fence-relevant cells change.
    # This helper does not change fences; pastures cache unaffected.
    return _replace_player(state, player_idx,
                            dataclasses.replace(p, farmyard=new_farmyard))


def with_fields(state, player_idx, field_cells: list[tuple[int, int]]):
    """Plow the given cells (all become empty FIELDs)."""
    overrides = {(r, c): Cell(cell_type=CellType.FIELD) for (r, c) in field_cells}
    return with_grid(state, player_idx, overrides)


def with_sown_fields(state, player_idx, *,
                     grain_fields: list[tuple[int, int]] = (),
                     veg_fields: list[tuple[int, int]] = ()):
    """Plow the given cells AND fill them with 3 grain or 2 veg respectively."""
    overrides = {}
    for (r, c) in grain_fields:
        overrides[(r, c)] = Cell(cell_type=CellType.FIELD, grain=3)
    for (r, c) in veg_fields:
        overrides[(r, c)] = Cell(cell_type=CellType.FIELD, veg=2)
    return with_grid(state, player_idx, overrides)


def with_space(state, space_id: str, **kwargs):
    """Replace fields on a specific action space.

    Example: with_space(s, "fishing", round_revealed=1, accumulated_amount=3)
    """
    action_space = state.board.action_spaces[space_id]
    new_action_space = dataclasses.replace(action_space, **kwargs)
    new_spaces = dict(state.board.action_spaces)
    new_spaces[space_id] = new_action_space
    new_board = dataclasses.replace(state.board, action_spaces=new_spaces)
    return dataclasses.replace(state, board=new_board)


def with_pending_stack(state, frames: tuple[PendingDecision, ...]):
    """Replace the pending stack entirely."""
    return dataclasses.replace(state, pending_stack=frames)


def with_phase(state, phase: Phase):
    return dataclasses.replace(state, phase=phase)


def with_round(state, round_number: int):
    return dataclasses.replace(state, round_number=round_number)


def with_current_player(state, player_idx: int):
    return dataclasses.replace(state, current_player=player_idx)


def with_people(state, player_idx, *, total: Optional[int] = None,
                home: Optional[int] = None, newborns: Optional[int] = None):
    """Set people counts for a player. Omitted args keep current value."""
    p = state.players[player_idx]
    return _replace_player(state, player_idx, dataclasses.replace(
        p,
        people_total=total if total is not None else p.people_total,
        people_home=home if home is not None else p.people_home,
        newborns=newborns if newborns is not None else p.newborns,
    ))


# Internal:
def _replace_player(state, player_idx, new_player):
    new_players = tuple(
        new_player if i == player_idx else state.players[i] for i in range(2)
    )
    return dataclasses.replace(state, players=new_players)
```

The helpers are deliberately small and composable. Each test starts with `state = setup(seed=...)` and chains a handful of `with_*` calls to reach the desired prefabricated state. The factories don't try to enforce game-rule consistency (e.g., they let you put a player at `people_home > people_total`); tests are responsible for constructing states that make sense for what they're testing.

### New file: `tests/test_utils.py`

Two helpers go here: `run_actions` for scripted multi-step tests, and `random_agent_play` / its building blocks for the end-to-end random-game test.

```python
import numpy as np

from agricola.actions import PlaceWorker
from agricola.constants import Phase
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.resolution import ATOMIC_HANDLERS


def run_actions(state, actions):
    """Apply a sequence of actions in order; validate each is legal.

    Used by scripted tests (e.g., walking through a specific Grain
    Utilization scenario). Raises AssertionError if any action is illegal
    at the moment it's applied.
    """
    for action in actions:
        legal = legal_actions(state)
        assert action in legal, (
            f"Action {action!r} not in legal_actions: {legal!r}"
        )
        state = step(state, action)
    return state


# Non-atomic spaces whose resolution `step` knows how to apply in Task 5.
# All other non-atomic spaces would cause `step` to raise NotImplementedError.
IMPLEMENTED_NON_ATOMIC_SPACES = frozenset({"grain_utilization"})


def _is_implemented_action(action):
    """Return True if `step` can apply this action under Task 5 scope."""
    if isinstance(action, PlaceWorker):
        return (
            action.space in ATOMIC_HANDLERS
            or action.space in IMPLEMENTED_NON_ATOMIC_SPACES
        )
    return True   # all sub-action types are implemented when reachable


def filter_implemented(actions):
    """Filter a legal_actions output to those `step` knows how to apply."""
    return [a for a in actions if _is_implemented_action(a)]


def random_agent_play(state, seed: int):
    """Play to BEFORE_SCORING using a random agent that only picks
    implemented actions. Returns the terminal state and the action trace.

    Raises RuntimeError if the random agent reaches a state with no
    implemented legal actions (would indicate a bug in `step` or in the
    implemented-action filter).
    """
    rng = np.random.default_rng(seed)
    trace = []
    while state.phase != Phase.BEFORE_SCORING:
        actions = filter_implemented(legal_actions(state))
        if not actions:
            raise RuntimeError(
                f"Random agent stuck: no implemented legal actions. "
                f"State: phase={state.phase}, current_player={state.current_player}, "
                f"pending_stack={state.pending_stack}"
            )
        action = actions[rng.integers(len(actions))]
        trace.append(action)
        state = step(state, action)
    return state, trace
```

The `filter_implemented` helper is the answer to "random agent picks an unimplemented non-atomic space and `step` raises." By construction, the random agent only sees actions `step` can handle. When the next non-atomic resolver is added (Task 6 or later), `IMPLEMENTED_NON_ATOMIC_SPACES` gains a member and the filter widens automatically.

### New file: `tests/test_engine.py`

Tests are split between (a) gameplay-reachable scenarios that exercise the engine end-to-end and (b) prefabricated-state unit tests that target specific behaviors of `step` and `_advance_until_decision`.

#### Step on atomic placements

- `test_step_day_laborer_basic`:
  Prefabricated state from `setup(seed=0)`. Apply `step(state, PlaceWorker("day_laborer"))`. Assert: active player got +2 food, `people_home` decremented, `workers` tuple on day_laborer reflects the placement, `pending_stack == ()`, `current_player` alternated to the other player.

- `test_step_atomic_then_atomic_alternates`:
  Apply two consecutive `step` calls for Day Laborer (player 0 then player 1). Assert alternation works.

#### Stack invariants

- `test_step_on_atomic_leaves_empty_stack`:
  After any atomic placement, `pending_stack == ()`.

- `test_advance_until_decision_idempotent`:
  For any state returned by `step`, `_advance_until_decision(state) == state` (one-line invariant test exercising several states from prior tests).

#### Round transitions

- `test_work_phase_ends_when_both_players_zero_workers`:
  Prefabricated state via factories: both players at `people_home=0`, phase=WORK, pending_stack empty, round_number=1. Apply `step(state, ...)` is not possible (no legal actions). Instead test `_advance_until_decision(state)` directly: it should transition to RETURN_HOME, then PREP for round 2, return at phase=WORK / round_number=2 / both players at `people_home=people_total=2`.

- `test_return_home_resets_workers_and_newborns`:
  Prefabricated state: phase=RETURN_HOME, round_number=1, some action spaces have non-zero `workers` tuples, one player has `newborns=1`. Apply `_advance_until_decision`. Assert all action spaces' `workers` are `(0, 0)`, both players have `people_home=people_total`, `newborns=0`.

- `test_prep_refills_accumulation_spaces`:
  Prefabricated state at the boundary of round 1 → round 2 (just after RETURN_HOME). Apply `_resolve_preparation` directly. Assert: Forest's `accumulated` gained +3 wood, Clay Pit gained +1 clay, etc. Spaces not yet revealed (round_revealed > 2) are NOT refilled. The newly-revealed round-2 stage card IS refilled if it's an accumulation space.

- `test_round_4_return_home_transitions_to_before_scoring`:
  Prefabricated state at end of round 4 work phase: round_number=4, phase=WORK, both players' `people_home=0`. Apply `_advance_until_decision`. Assert final phase is `Phase.BEFORE_SCORING`, round_number=4 (not advanced).

#### Error behaviors

- `test_step_raises_on_before_scoring`:
  Prefabricated state with `phase=Phase.BEFORE_SCORING`. Apply `step(state, PlaceWorker("day_laborer"))`. Assert it raises `RuntimeError`.

- `test_step_raises_on_unimplemented_non_atomic`:
  Setup state where `PlaceWorker("farm_expansion")` is legal (e.g., 5 wood, 2 reed available). Apply `step`. Assert `NotImplementedError` with a message naming the space.

#### End-to-end random-agent

- `test_random_agent_plays_four_rounds` (parameterized over seeds 0..9):
  `state, trace = random_agent_play(setup(seed=s), seed=s)`. Assert: terminal state has `phase == Phase.BEFORE_SCORING`, `round_number == 4`, both players' `people_home == people_total`, `pending_stack == ()`, all action spaces have `workers == (0, 0)`. No exception raised. The trace contains at least one `PlaceWorker("grain_utilization")` for some seeds (probabilistic; not a hard assertion).

- `test_random_agent_invariants`:
  Across the same seeds, assert that at every state in the trace, `current_player` is consistent with stack state (empty stack → current_player decider; non-empty stack → top.player_idx decider). This is a meta-test that the engine maintains the decider rule under random play.

### New file: `tests/test_grain_utilization.py`

These tests build prefabricated states using `tests/factories.py`. They do NOT rely on multi-round play to reach interesting configurations.

#### Basic walk-throughs (no cards)

- `test_grain_util_sow_only_walk`:
  Prefabricated state: player 0 has 1 grain, one empty field at (0, 2), owns Fireplace (so baking would also be legal). Walk `PlaceWorker → ChooseSubAction("sow") → CommitSow(1, 0) → Stop`. Assert final resources have 0 grain, field (0, 2) has 3 grain, `pending_stack == ()`, `current_player == 1` (alternated).

- `test_grain_util_bake_only_walk`:
  Prefabricated state: player 0 has 1 grain, no empty field cells (so sow is illegal), owns Fireplace. Walk `PlaceWorker → ChooseSubAction("bake_bread") → CommitBake(1) → Stop`. Assert resources have 0 grain, +2 food.

- `test_grain_util_both_sub_actions_walk`:
  Prefabricated state: 3 grain, two empty fields, owns Fireplace. Walk sow-then-bake: `PlaceWorker → ChooseSubAction("sow") → CommitSow(2, 0) → ChooseSubAction("bake_bread") → CommitBake(1) → Stop`. Assert 0 grain in supply, 3 grain on each of two fields, +2 food.

- `test_grain_util_both_sub_actions_reverse_order`:
  Same prefabricated state as above. Walk bake-then-sow: `PlaceWorker → ChooseSubAction("bake_bread") → CommitBake(1) → ChooseSubAction("sow") → CommitSow(2, 0) → Stop`. Assert identical final state (resources and fields) as the sow-then-bake walk — order doesn't affect end state when both sub-actions are independently legal and resources suffice for both.

#### Stop legality

- `test_grain_util_stop_illegal_at_start`:
  Prefabricated state with `pending_stack = (PendingGrainUtilization(player_idx=0),)` (no sub-actions yet completed). Assert `Stop()` is NOT in `legal_actions(state)`.

- `test_grain_util_stop_legal_after_one_sub_action`:
  Prefabricated state with `pending_stack = (PendingGrainUtilization(player_idx=0, sow_done=True),)`. Assert `Stop()` IS in `legal_actions(state)`.

- `test_grain_util_only_stop_when_both_done`:
  Prefabricated state with `pending_stack = (PendingGrainUtilization(player_idx=0, sow_done=True, bake_done=True),)`. Assert `legal_actions(state) == [Stop()]` exactly — neither category is offered again.

#### Mid-turn legality recomputation

These verify that `legal_actions` re-evaluates between sub-actions, correctly handling resource depletion. This is the load-bearing test for the "category-then-commit" architecture.

- `test_sow_becomes_illegal_after_baking_depletes_grain`:
  Prefabricated state: player 0 has exactly 1 grain, one empty field at (0, 2), owns Fireplace. Walk: `PlaceWorker("grain_utilization") → ChooseSubAction("bake_bread") → CommitBake(1)`.
  At this point: resources have 0 grain, field (0, 2) is still empty. Assert `legal_actions(state) == [Stop()]` — `ChooseSubAction("sow")` is NOT offered because `_can_sow` requires grain ≥ 1 or veg ≥ 1.
  Finish: `Stop`. Assert turn ends cleanly.

- `test_bake_becomes_illegal_after_sowing_depletes_grain`:
  Mirror of the above. Prefabricated state: 1 grain, one empty field, owns Fireplace, no clay. Walk: `PlaceWorker → ChooseSubAction("sow") → CommitSow(1, 0)`.
  At this point: resources have 0 grain, field (0, 2) has 3 grain (3 from sowing). Assert `legal_actions(state) == [Stop()]` — `ChooseSubAction("bake_bread")` is NOT offered because `_can_bake_bread` requires grain ≥ 1 in personal supply (crops on fields don't count).
  Finish: `Stop`.

- `test_sow_remains_legal_after_partial_bake`:
  Prefabricated state: 3 grain, two empty fields, owns Fireplace. Walk: `PlaceWorker → ChooseSubAction("bake_bread") → CommitBake(1)`. Resources now: 2 grain. Assert `ChooseSubAction("sow")` is still in `legal_actions`. (`CommitSow(2, 0)` and `CommitSow(1, 0)` are the available commits if sow is chosen.)

- `test_partial_field_fills_after_partial_sow`:
  Prefabricated state: 3 grain, three empty fields, owns Fireplace. Walk: `PlaceWorker → ChooseSubAction("sow") → CommitSow(2, 0)`. Two fields fill, one remains empty. Assert resources have 1 grain, two fields have 3 grain, one field is still empty. Assert `ChooseSubAction("bake_bread")` is in `legal_actions` (grain ≥ 1 still).
  At this point `ChooseSubAction("sow")` is NOT in `legal_actions` because `sow_done` is set. (Sowing across multiple `CommitSow` calls in one Grain Utilization action is not allowed; the player commits sow once with `(grain, veg)` totals.)

#### Sow distribution semantics

- `test_sow_fills_grain_fields_first_then_veg`:
  Prefabricated state: 1 grain, 1 veg, two empty fields at (0, 2) and (1, 2). Player owns Fireplace (so baking still legal, but tested separately). Walk: `PlaceWorker → ChooseSubAction("sow") → CommitSow(1, 1) → Stop`. Per the `_execute_sow` rule, grain is sown first in canonical (row, col) order. Assert field (0, 2) has 3 grain, field (1, 2) has 2 veg.

- `test_sow_canonical_order`:
  Prefabricated state with empty fields at (2, 0), (0, 2), (1, 4). 3 grain in supply. Walk: `PlaceWorker → ChooseSubAction("sow") → CommitSow(3, 0) → Stop`. All three fields filled with 3 grain each. Assert each is filled regardless of which cell came "first" — `_execute_sow` walks (r, c) in canonical order.

- `test_legal_sow_commits_respect_field_count`:
  Prefabricated state: 3 grain, 1 empty field. Walk to `PendingSow`. Assert `legal_actions` contains `CommitSow(1, 0)` but NOT `CommitSow(2, 0)` or `CommitSow(3, 0)` — sowing more than the empty-field count is illegal.

#### Cooking rate tests

- `test_bake_uses_cooking_hearth_rate_when_owned`:
  Prefabricated state: 1 grain, Cooking Hearth (idx 2), no Fireplace. Walk: `PlaceWorker → ChooseSubAction("bake_bread") → CommitBake(1) → Stop`. Assert +3 food (Hearth rate), not +2.

- `test_bake_uses_hearth_rate_when_both_owned`:
  Prefabricated state: 1 grain, both Fireplace (idx 0) and Cooking Hearth (idx 2). Walk through a bake. Assert +3 food (Hearth's better rate wins).

- `test_bake_raises_with_only_clay_oven`:
  Prefabricated state: 1 grain, owns Clay Oven (idx 5) and nothing else. `_can_bake_bread` returns True (base check passes — Clay Oven is in BAKING_IMPROVEMENTS), so `PlaceWorker("grain_utilization")` is legal and `ChooseSubAction("bake_bread")` is legal. Walk into `CommitBake(1)`. Assert `step(state, CommitBake(1))` raises `NotImplementedError` with a message identifying Clay Oven as the unsupported case.

#### "Grain Utilization is unreachable" tests

- `test_grain_util_illegal_when_cannot_sow_or_bake`:
  Prefabricated state: 0 grain, 0 veg, no empty fields, no baking improvement. Assert `PlaceWorker("grain_utilization")` is NOT in `legal_actions(state)`.

- `test_grain_util_legal_with_only_bake_path`:
  Prefabricated state: 1 grain, no empty fields, Fireplace owned. Assert `PlaceWorker("grain_utilization")` IS in `legal_actions(state)`.

- `test_grain_util_legal_with_only_sow_path`:
  Prefabricated state: 1 grain, one empty field, no baking improvement. Assert `PlaceWorker("grain_utilization")` IS in `legal_actions(state)`.

#### Sub-action ordering and the parent pending

- `test_sow_pop_marks_parent_sow_done`:
  Prefabricated state with `pending_stack = (PendingGrainUtilization(player_idx=0), PendingSow(player_idx=0))`, 1 grain, one empty field. Apply `step(state, CommitSow(1, 0))`. Assert `pending_stack == (PendingGrainUtilization(player_idx=0, sow_done=True, bake_done=False),)` — `PendingSow` popped, parent's `sow_done` set to True.

- `test_bake_pop_marks_parent_bake_done`:
  Mirror of the above: `pending_stack = (PendingGrainUtilization, PendingBakeBread)`, 1 grain, Fireplace owned. Apply `CommitBake(1)`. Assert top frame becomes `PendingGrainUtilization(bake_done=True)`.

### New file: `tests/test_potter_ceramics.py`

All tests use prefabricated states. The card cannot be acquired through Task 5 gameplay (no action space plays minor improvements), so every test starts by directly setting `PlayerState.minor_improvements`.

A local convenience wrapper (or just inline factory calls):

```python
from tests.factories import (
    with_resources, with_majors, with_minors, with_fields, with_pending_stack,
)

def _potter_setup(state, player_idx, *, grain=0, clay=1, veg=0,
                  with_fireplace=True, with_hearth=False, empty_fields=0):
    """One-line helper composing factory calls for the Potter scenarios."""
    state = with_resources(state, player_idx, grain=grain, clay=clay, veg=veg)
    state = with_minors(state, player_idx, frozenset({"potter_ceramics"}))
    majors = {}
    if with_fireplace:
        majors[0] = player_idx
    if with_hearth:
        majors[2] = player_idx
    state = with_majors(state, owner_by_idx=majors)
    if empty_fields > 0:
        # Plow `empty_fields` cells starting at (0, 2), (0, 3), ...
        cells = [(0, 2 + i) for i in range(empty_fields)]
        state = with_fields(state, player_idx, cells)
    return state
```

Coverage:

**Predicate-level tests** — verify `_can_bake_bread` with the Potter Ceramics extension:

- `test_can_bake_bread_potter_clay_no_grain`: player owns Potter Ceramics + Fireplace, has 1 clay and 0 grain. `_can_bake_bread(state, p)` returns True (via the extension). This is the headline behavioral change the card enables.
- `test_can_bake_bread_potter_no_clay`: player owns Potter Ceramics + Fireplace, has 0 clay and 0 grain. `_can_bake_bread` returns False (extension requires clay ≥ 1).
- `test_can_bake_bread_potter_no_baker`: player owns Potter Ceramics, has 1 clay and 0 grain, owns no baking improvement. `_can_bake_bread` returns False (extension requires a baker).
- `test_can_bake_bread_no_potter`: player has 1 clay and 0 grain, owns Fireplace, does NOT own Potter Ceramics. `_can_bake_bread` returns False (base check fails, no extension fires).
- `test_can_bake_bread_potter_with_grain_already`: player owns Potter Ceramics + Fireplace, has 1 clay and 1 grain. `_can_bake_bread` returns True (base check passes; the extension doesn't need to fire, but its presence doesn't break anything).

**Full Grain Utilization walk-through with the trigger**:

- `test_grain_utilization_potter_zero_grain_full_walk`:
  Setup: Potter Ceramics played, Fireplace owned, 1 clay, 0 grain, 0 empty fields.
  Walk: `PlaceWorker("grain_utilization") → ChooseSubAction("bake_bread") → FireTrigger("potter_ceramics") → CommitBake(1) → Stop`.
  Assertions:
    - After `PlaceWorker`: `pending_stack == (PendingGrainUtilization(player_idx=ap),)`.
    - After `ChooseSubAction("bake_bread")`: top is `PendingBakeBread(player_idx=ap, triggers_resolved=frozenset())`.
    - At `PendingBakeBread`, `legal_actions == [FireTrigger("potter_ceramics")]` — no `CommitBake(n)` is legal (0 grain), and there's no `SkipTrigger` in this architecture. The Fire is the only legal action; the player is forced to fire.
    - After `FireTrigger`: resources have 0 clay, 1 grain; `triggers_resolved == frozenset({"potter_ceramics"})`.
    - At post-trigger pending, `legal_actions == [CommitBake(1)]`.
    - After `CommitBake(1)`: resources have 0 clay, 0 grain, 2 food (Fireplace rate).
    - After `Stop`: `pending_stack == ()`, turn passes to other player.

**Single-fire-per-action invariant**:

- `test_potter_fires_at_most_once_per_action`: setup with 2 clay, 0 grain, Potter + Fireplace. Walk to `PendingBakeBread`, fire Potter. After fire, assert `FireTrigger("potter_ceramics") not in legal_actions(state)` even though `clay >= 1` still holds — `triggers_resolved` blocks re-firing.

**Re-eligibility on a new action**:

- `test_potter_re_eligible_next_bake_action`: construct a state mid-round-2 where the player previously fired Potter Ceramics on a round-1 Grain Utilization. Set them up to take Grain Utilization again with 1 clay and 0 grain. Walk to `PendingBakeBread`, assert `FireTrigger("potter_ceramics")` is in `legal_actions` (a new `PendingBakeBread` starts with empty `triggers_resolved`).

**Implicit declination of a trigger**:

- `test_potter_implicitly_declined_via_commit`: setup with 1 clay AND 1 grain (so the player could bake without firing Potter). Walk: `PlaceWorker("grain_utilization") → ChooseSubAction("bake_bread") → CommitBake(1) → Stop`. Assert: `FireTrigger("potter_ceramics")` was in `legal_actions` at `PendingBakeBread` but was not chosen; final state has 1 clay (unchanged, trigger didn't fire) and +2 food (1 grain baked). The trigger was declined implicitly by committing.
- `test_potter_listed_alongside_commit_when_both_legal`: setup with 1 clay AND 1 grain. At `PendingBakeBread`, assert `legal_actions` contains both `FireTrigger("potter_ceramics")` and `CommitBake(1)`. The player has both options.
- `test_only_fire_legal_when_no_commit_possible`: setup with 1 clay AND 0 grain. At `PendingBakeBread`, assert `legal_actions == [FireTrigger("potter_ceramics")]` exactly. With no `SkipTrigger` action in this architecture, the Fire is the only choice — the player is forced to fire.

### Updates to existing test files

- `tests/test_state.py`: replace `future_food` references with `future_resources`. Confirm `minor_improvements` defaults to `frozenset()`.
- `tests/test_resolution_atomic.py`: replace `resolve_atomic(state, ...)` with `step(state, ...)`. Add `assert state.pending_stack == ()` after each atomic placement.
- `tests/test_legality_atomic.py`, `tests/test_legality_non_atomic.py`: no functional changes; they use `legal_placements` which remains a valid internal helper. Optionally migrate to `legal_actions` if you want to exercise the new dispatch.

---

## Documentation updates

### `CLAUDE.md` updates

CLAUDE.md already contains a substantial new section — **"Engine and Turn Resolution Architecture"** — written during the Task 5 design conversation. That section (the three subsections on `step` / `legal_actions` / `_advance_until_decision`, the pending-decision stack, and card implementation status) is **already correct and complete**. **Do NOT re-write it.** The implementing agent should leave it untouched.

What the implementing agent DOES need to update in CLAUDE.md:

1. **Current Status table** (under "## Current Status"): add rows for the `step` function and round/phase machinery, for non-atomic Grain Utilization resolution, and for Potter Ceramics. Update the test count from `170` to whatever the new total is.
2. **Directory Structure** (under "## Directory Structure"): add the new files and subpackages — `agricola/engine.py`, `agricola/pending.py`, the `agricola/cards/` subpackage (with `__init__.py`, `triggers.py`, `potter_ceramics.py`), and the new test files (`tests/test_engine.py`, `tests/test_grain_utilization.py`, `tests/test_potter_ceramics.py`, `tests/test_utils.py`, `tests/factories.py`).
3. **Python File Descriptions** (under "## Python File Descriptions"): write a per-file description for each new module. Update the existing `state.py` description to reflect `pending_stack`, `future_resources`, `minor_improvements`, `occupations`. Update `resolution.py` to note removal of the public `resolve_atomic` and the addition of `_execute_sow` and `_execute_bake`. Update `legality.py` to reflect the new `legal_actions` entry point, the per-pending enumerators, the `BAKE_BREAD_ELIGIBILITY_EXTENSIONS` registry, and the `register_bake_bread_extension` wrapper. Update `constants.py` to mention `Phase.PREPARATION` and `Phase.BEFORE_SCORING`.
4. **"Not yet implemented" line** (in the Current Status section): trim — non-atomic resolution for Grain Utilization is now implemented; Potter Ceramics is implemented. The other non-atomic resolvers (Farm Expansion, Farmland, Side Job, Sheep/Pig/Cattle Market, Major Improvement, House Redevelopment, Cultivation, Farm Redevelopment, Fencing) and harvest remain unimplemented. Round 5 onward also remains unimplemented (engine halts after round 4's RETURN_HOME).
5. **Documentation Files table**: optionally add an explicit row for `TASK_5.md` if you want a specific entry (the existing generic `TASK_*.md` row already covers it).

### `IMPLEMENTATION_CHOICES.md` updates

Add two new sections:

**Section: Future-Resources field shape.**
> `PlayerState.future_resources: tuple[Resources, ...]` of length 14 covers all 7 goods (food, wood, clay, reed, stone, grain, veg) that may be promised to a player at future rounds. Future animals (e.g., a card that promises 1 pig at round 5) and future actions (e.g., a card that grants a free plow at round 5) are NOT supported by this field. When cards introducing them arrive, a `FutureRewards` dataclass wrapping `Resources + Animals + ...` will be introduced. Migration cost is low.

**Section: Card-extension pattern for legality helpers.**
> Each legality helper that a card may broaden (`_can_bake_bread`, eventually `_can_sow`, `_can_plow`, `_can_renovate`, `_can_afford_room`, etc.) is structured as `base_check(state, p) or any(ext(state, p) for ext in <HELPER>_EXTENSIONS)`. Each `<HELPER>_EXTENSIONS` is a module-level list populated by card modules at import time via a `register_<helper>_extension(fn)` wrapper. The pattern is intentionally similar to the trigger registry but distinct: triggers fire at specific points during action resolution; legality extensions widen the set of states in which the action is legal in the first place.
>
> Helpers expected to receive extensions: all the `_can_*` predicates in `agricola/legality.py`. Helpers that probably won't: `_is_available`, `_has_room_placement`, `_has_stable_placement` (cards modify costs, not geometric placement).

**Section: Compound card interactions — known unhandled case.**
> The extension-registry pattern above handles single-card eligibility broadening cleanly (Potter Ceramics' "I can bake with clay instead of grain"). It does NOT handle *compound* interactions where one card's effect enables another card's eligibility. Canonical example: Pan Baker ("when you take Grain Utilization, get 2 clay + 1 wood") + Potter Ceramics ("before Bake Bread, exchange 1 clay for 1 grain") makes Grain Utilization legal even with 0 clay and 0 grain initially — Pan Baker fires on placement, providing clay, which Potter Ceramics then converts to grain.
>
> The current `_can_bake_bread` reads literal current state and would return False in this scenario, marking the placement illegal. The fix requires the legality system to apply "on placement" card effects speculatively before checking sub-action predicates. The trigger registry already supports arbitrary event names (e.g., `"on_take_space:grain_utilization"`); the missing piece is the legality-side speculative-application machinery.
>
> Out of scope for Task 5. Flagged here, and in TASK_5.md's "Known limitation: compound card interactions" section, for whoever implements the broader card system.

### `SESSION_HISTORY.md`

Not updated as part of Task 5 by default — the user has indicated session-history entries are added selectively. The coding agent should ask after implementation whether to add a Task 5 entry.

---

## Acceptance criteria

A Task 5 implementation is complete when ALL of the following hold:

1. All existing tests pass (after migration to `future_resources` and `step`).
2. New tests in `tests/test_engine.py`, `tests/test_grain_utilization.py`, `tests/test_potter_ceramics.py`, and `tests/test_utils.py` all pass.
3. A random-agent loop can play rounds 1–4 to completion (state reaches `Phase.BEFORE_SCORING`) without raising, choosing among the `filter_implemented(legal_actions(state))` subset at each step. Add this as `tests/test_engine.py::test_random_agent_plays_four_rounds`, parameterized over multiple seeds (e.g., 0–9).
4. `step(state, PlaceWorker("farm_expansion"))` (and the other unimplemented non-atomic spaces) raises `NotImplementedError`, not a silent corruption.
5. CLAUDE.md and IMPLEMENTATION_CHOICES.md reflect the new state.
6. No code outside `agricola/cards/` references the Potter Ceramics card by name; all references go through the trigger registry.

---

## Suggested order of work

1. **State migrations.** Update `state.py` (`pending_stack`, `future_resources`, `minor_improvements`), `setup.py` (initialize new fields), `constants.py` (`BEFORE_SCORING`). Update `tests/test_state.py` to match. Confirm existing tests still pass.

2. **Action union expansion.** Update `actions.py` with the full set of action dataclasses and the `Action` Union alias.

3. **Pending types.** Create `agricola/pending.py` with the three Task-5 pending dataclasses and the `PendingDecision` Union.

4. **Card framework scaffolding.** Create `agricola/cards/__init__.py` and `agricola/cards/triggers.py`. Empty `TRIGGERS` is fine at this point.

5. **Engine module.** Create `agricola/engine.py` with `step`, `_advance_until_decision`, `_resolve_return_home`, `_resolve_preparation`, and the action-dispatch helpers (`_apply_place_worker`, `_apply_choose_sub_action`, `_apply_commit_sow`, `_apply_commit_bake`, `_apply_fire_trigger`, `_apply_stop`, plus `_push`, `_pop`, `_replace_top`). For non-atomic spaces other than Grain Utilization, raise `NotImplementedError`. Trigger registry lookups should work even though no cards are registered yet — `TRIGGERS.get("before_bake_bread", [])` returns `[]`.

6. **legal_actions and per-pending enumerators.** Update `legality.py`: add the `BAKE_BREAD_ELIGIBILITY_EXTENSIONS` list (empty), add the extension-hook branch to `_can_bake_bread`, add the per-pending enumerators, add `_enumerate_pending`, add `legal_actions`. `legal_placements` becomes an internal helper. `BAKING_IMPROVEMENTS` is unchanged.

7. **Resolution refactor.** Remove `resolve_atomic` from `resolution.py`. Add `_execute_sow` and `_execute_bake`. Update `tests/test_resolution_atomic.py` to use `step`.

8. **Grain Utilization tests.** Implement `tests/test_grain_utilization.py`. Pass all the sow-only, bake-only, and combined scenarios without cards.

9. **Potter Ceramics implementation.** Create `agricola/cards/potter_ceramics.py`. Wire its `register()` call into both `TRIGGERS` and `BAKE_BREAD_ELIGIBILITY_EXTENSIONS`. Update `agricola/cards/__init__.py` to import it.

10. **Potter Ceramics tests.** Implement `tests/test_potter_ceramics.py`. All paths covered.

11. **Engine end-to-end test.** Implement the random-agent test that plays rounds 1–4 to completion.

12. **Documentation.** Update `CLAUDE.md` and `IMPLEMENTATION_CHOICES.md`. Ask the user whether to record a `SESSION_HISTORY.md` entry.

Each step is a small, testable piece. Run the full test suite after each step.

---

## Glossary

- **Atomic space.** A worker placement whose full effect is determined by the placement alone, with no follow-up sub-decisions. Twelve in the Family game.
- **Non-atomic space.** A worker placement that initiates a chain of sub-decisions before the player's turn ends. Thirteen in the Family game (one of which, Lessons, is permanently illegal in the Family variant).
- **Sub-action.** A decision made during a non-atomic action's resolution, after the worker placement but before the next player's turn. Examples: choosing whether to sow or bake at Grain Utilization, committing how many grain to bake, firing or skipping a trigger.
- **Pending decision.** A frozen dataclass instance on the `pending_stack` representing an in-progress sub-action and the context needed to resolve it.
- **Trigger.** A card effect that fires at a specific point during action resolution. Potter Ceramics' "before Bake Bread" trigger fires when the player has chosen the Bake Bread sub-action but before committing the grain amount.
- **System transition.** A state change driven by the engine, not by an agent decision: phase changes, active-player alternation when the stack is empty, accumulation refills, returning workers home. Handled by `_advance_until_decision`.
- **Decider.** The player whose decision is currently awaited. Equal to `state.current_player` when the pending stack is empty; equal to `pending_stack[-1].player_idx` otherwise.
