# Task 5B — Dispatch Cleanup

A focused follow-up to Task 5. The document is split into two halves:

- **Part 1 — Changes to implement now.** Concrete edits to the existing
  codebase. Behavior is unchanged; all 236 existing tests should pass after
  the work, modulo construction-call updates for a new mandatory field.
- **Part 2 — Conventions for future code.** Naming and structural rules to
  follow as new spaces, sub-actions, and cards are added. Most of these slot
  into work that hasn't been started yet (the other 10 non-atomic spaces,
  the card system).

The Scope and Motivation sections at the top, and the Implementation
Logistics sections at the bottom (Tests, Documentation Updates, Suggested
Order of Work, Acceptance Criteria), are meta to the changes — they don't
fit cleanly into Part 1 or Part 2 and are kept as bookends.

---

## Scope

Six changes:

1. Rename `_resolve_grain_utilization` → `_initiate_grain_utilization`.
2. Relocate `NONATOMIC_HANDLERS` and `CHOOSE_SUBACTION_HANDLERS` dispatch
   tables (plus their handler functions) from `engine.py` to
   `resolution.py`.
3. Move stack helpers `_push` / `_pop` / `_replace_top` from `engine.py` to
   `pending.py`, renamed `push` / `pop` / `replace_top`.
4. Introduce `CommitSubAction` frozen-dataclass base; unify `_execute_*`
   signatures to take the commit action object.
5. Add provenance fields to pending classes: `initiated_by_id` (mandatory
   instance field on every pending) and `PENDING_ID` (ClassVar on every
   pending class).
6. Collapse `_apply_commit_sow` / `_apply_commit_bake` into a single
   generic `_apply_commit_subaction` in `engine.py`. Add the
   `COMMIT_SUBACTION_HANDLERS` dispatch table in `engine.py` (co-located
   with its sole consumer; the table is metadata for the dispatcher, not a
   function-pointer table parallel to the ones in `resolution.py`). The
   dispatcher uses both field-existence and identity checks before
   writing to the parent.

---

## Motivation

After Task 5 the engine module had picked up several pieces of code that
belong elsewhere:

- `_resolve_grain_utilization` and `NONATOMIC_HANDLERS` lived in
  `engine.py`, but they're per-space resolution code — the parallel of
  `ATOMIC_HANDLERS`, which already lives in `resolution.py`. The same is
  true of `_choose_subaction_grain_utilization` and
  `CHOOSE_SUBACTION_HANDLERS`.
- `_resolve_grain_utilization` is misnamed: it doesn't resolve anything, it
  pushes a pending frame and exits. Future non-atomic spaces will have the
  same shape — they all *initiate* a sub-decision chain.
- Stack helpers `_push` / `_pop` / `_replace_top` live in `engine.py` but
  are needed by relocated per-space resolution code too. A neutral home
  (`pending.py` — which already owns the data structure) avoids
  resolution.py-imports-from-engine cycles.
- `_apply_action` enumerates each `CommitX` action by name. Today that's
  six `isinstance` branches (`PlaceWorker`, `ChooseSubAction`, `CommitSow`,
  `CommitBake`, `FireTrigger`, `Stop`); every new sub-action type adds
  another. A hierarchy + dispatch table collapses the per-`Commit*`
  branches into one (`CommitSubAction`), keeping `_apply_action` at a
  fixed five branches regardless of how many sub-action types exist —
  growth happens in the dispatch table instead.
- Pending frames carry no provenance metadata. Once cards introduce
  cross-cutting sub-actions (e.g., a card that lets a player plow after
  building a room during Farm Expansion), the dispatcher needs a way to
  recognize "the frame underneath me is *not* my architectural owner."
  Provenance metadata enables this.

After the refactor:

- **`engine.py`** is purely action dispatch (`_apply_*`), stack
  advancement (`_advance_until_decision`), player alternation
  (`_advance_current_player`), and phase resolvers (`_resolve_return_home`,
  `_resolve_preparation`). It also hosts `COMMIT_SUBACTION_HANDLERS` as
  metadata for its own commit dispatcher.
- **`resolution.py`** holds all space-specific resolution code: atomic
  handlers, non-atomic initiators, choose-sub-action handlers,
  commit-effect functions, and the three function-pointer dispatch tables
  (`ATOMIC_HANDLERS`, `NONATOMIC_HANDLERS`, `CHOOSE_SUBACTION_HANDLERS`).
- **`pending.py`** holds the pending dataclasses *and* the stack
  operations on them.
- **`actions.py`** gains a `CommitSubAction` base class for the existing
  and future `Commit*` actions.

---

# Part 1 — Changes to implement now

## Change 1 — Rename `_resolve_grain_utilization` → `_initiate_grain_utilization`

**Files:** `agricola/engine.py` (then moved to `resolution.py` in Change 2).

```python
def _initiate_grain_utilization(state: GameState) -> GameState:
    return push(state, PendingGrainUtilization(
        player_idx=state.current_player,
        initiated_by_id="worker_placement",
    ))
```

**Rationale.** "Resolve" is overloaded: atomic handlers (`_resolve_day_laborer`,
…) fully apply their effect, and phase resolvers (`_resolve_return_home`,
`_resolve_preparation`) execute a phase's bookkeeping. Non-atomic initiators do
neither — they push a pending frame and return, deferring the actual work to
subsequent `step` calls. `_initiate_*` is honest about that.

The `initiated_by_id="worker_placement"` kwarg is mandatory under Change 5.
Top-level pendings pushed by `PlaceWorker` use `"worker_placement"` as their
initiator; sub-action pendings use their parent's `PENDING_ID`. The full
convention lives in Part 2.

## Change 2 — Relocate non-atomic dispatch to `resolution.py`

**Move** the following from `engine.py` to `resolution.py`:

- `_initiate_grain_utilization` (renamed in Change 1).
- `_choose_subaction_grain_utilization`.
- The `NONATOMIC_HANDLERS` dict.
- The `CHOOSE_SUBACTION_HANDLERS` dict.

**Imports.** `resolution.py` now imports `PendingGrainUtilization`,
`PendingSow`, `PendingBakeBread` from `pending.py`, and `push` from
`pending.py` (post-Change 3). `engine.py` continues to import three
function-pointer dispatch dicts (`ATOMIC_HANDLERS`, `NONATOMIC_HANDLERS`,
`CHOOSE_SUBACTION_HANDLERS`) from `resolution.py`. `COMMIT_SUBACTION_HANDLERS`
stays in `engine.py` (Change 6).

**Dispatcher functions stay in `engine.py`** — only the per-space handlers
and their tables move. So after Change 2:

```python
# engine.py
from agricola.resolution import (
    ATOMIC_HANDLERS, NONATOMIC_HANDLERS, CHOOSE_SUBACTION_HANDLERS,
)

def _apply_place_worker(state, action):
    state = _apply_worker_placement(state, action.space)
    if action.space in ATOMIC_HANDLERS:
        return ATOMIC_HANDLERS[action.space](state)
    if action.space in NONATOMIC_HANDLERS:
        return NONATOMIC_HANDLERS[action.space](state)
    raise NotImplementedError(...)

def _apply_choose_sub_action(state, action):
    assert state.pending_stack, ...
    top = state.pending_stack[-1]
    handler = CHOOSE_SUBACTION_HANDLERS.get(type(top))
    if handler is None: raise ValueError(...)
    return handler(state, action)
```

## Change 3 — Move stack helpers to `pending.py`

**Rename and move** from `engine.py` to `pending.py`:

- `_push` → `push`
- `_pop` → `pop`
- `_replace_top` → `replace_top`

Underscores dropped because they cross module boundaries.

**Imports.** `pending.py` adds `from agricola.state import GameState`. No
cycle: `state.py` stores `pending_stack: tuple` without parameterizing the
type, so it doesn't need to import from `pending.py`.

```python
# pending.py — added at the bottom, after the dataclass definitions.

import dataclasses
from agricola.state import GameState


def push(state: GameState, frame: PendingDecision) -> GameState:
    return dataclasses.replace(
        state, pending_stack=state.pending_stack + (frame,),
    )


def pop(state: GameState) -> GameState:
    return dataclasses.replace(
        state, pending_stack=state.pending_stack[:-1],
    )


def replace_top(state: GameState, new_top: PendingDecision) -> GameState:
    return dataclasses.replace(
        state,
        pending_stack=state.pending_stack[:-1] + (new_top,),
    )
```

**Callers updated.** `engine.py` and `resolution.py` import these from
`pending.py` and drop the leading underscore in call sites.

**Dependency direction after Change 3:**

```
state            ← pending (pending imports GameState)
resolution       → pending (handlers push frames, sub-action effects)
engine           → pending (apply handlers, push/pop/replace_top)
engine           → resolution (dispatch tables)
```

No cycles.

## Change 4 — `CommitSubAction` hierarchy and effect-function signature

### 4a. Base class in `actions.py`

```python
@dataclass(frozen=True)
class CommitSubAction:
    """Marker base for all Commit* sub-action types. Empty by design —
    concrete commit dataclasses inherit from this so `_apply_commit_subaction`
    can dispatch them uniformly.
    """
    pass


@dataclass(frozen=True)
class CommitSow(CommitSubAction):
    grain: int
    veg: int


@dataclass(frozen=True)
class CommitBake(CommitSubAction):
    grain: int
```

The base is itself a frozen dataclass for consistency with the project's
"every action object is a frozen dataclass" principle. The base has no
fields, so its generated `__init__` takes no args. Python's dataclass
rules require parent and child to agree on `frozen=True`, which they do.

**The `Action` union alias continues to list the concrete subclasses**, not
the base. Legality enumerators return concrete instances, and tools that
read the union benefit from seeing the real options:

```python
Action = Union[
    PlaceWorker,
    ChooseSubAction,
    CommitSow,
    CommitBake,
    FireTrigger,
    Stop,
]
```

The isinstance check in `_apply_action` (Change 6) uses the base, which
matches any subclass.

### 4b. Effect-function signature change

`_execute_sow` and `_execute_bake` are changed to take the commit action
object directly, rather than its individual fields. This lets a single
dispatcher call any effect function uniformly:

```python
# Before
def _execute_sow(state, player_idx, grain, veg) -> GameState: ...
def _execute_bake(state, player_idx, grain) -> GameState: ...

# After
def _execute_sow(state, player_idx, commit: CommitSow) -> GameState: ...
def _execute_bake(state, player_idx, commit: CommitBake) -> GameState: ...
```

Each function unpacks its commit at the top of the body. Bodies are
otherwise unchanged.

## Change 5 — Pending provenance fields

Two pieces of metadata land on the pending classes. Their dual purpose:
(a) make state dumps legible (debugging) and (b) enable the identity check
in the dispatcher (Change 6) for forward-compatibility with card-driven
cross-cutting sub-actions.

### 5a. `initiated_by_id: str` — mandatory instance field on every pending

Identifies the entity or event that caused this pending frame to exist on
the stack. The value's shape varies by how the pending got pushed (see the
Part 2 "`initiated_by_id` namespace and matching" section for the full
convention).

**Mandatory (no default)** so a forgotten value raises `TypeError` at
construction time rather than producing a silent bug downstream.

```python
# The full post-Change-5 shape of each pending class is shown in 5b
# below. This snippet highlights only the new mandatory instance field.

@dataclass(frozen=True)
class PendingSow:
    player_idx: int
    initiated_by_id: str   # mandatory; no default — added in Change 5a


@dataclass(frozen=True)
class PendingBakeBread:
    player_idx: int
    initiated_by_id: str   # mandatory — added in Change 5a
    triggers_resolved: frozenset = frozenset()
    TRIGGER_EVENT: ClassVar[str] = "before_bake_bread"


@dataclass(frozen=True)
class PendingGrainUtilization:
    player_idx: int
    initiated_by_id: str   # mandatory — added in Change 5a
    sow_done: bool = False
    bake_done: bool = False
```

**Update all construction sites:**

- `_initiate_grain_utilization` pushes
  `PendingGrainUtilization(player_idx=..., initiated_by_id="worker_placement")`
  — top-level pending pushed by `PlaceWorker`, so the initiator is the
  event class, not the space id.
- `_choose_subaction_grain_utilization` pushes
  `PendingSow(player_idx=..., initiated_by_id=top.PENDING_ID)` and
  `PendingBakeBread(player_idx=..., initiated_by_id=top.PENDING_ID)` —
  read dynamically from the top frame rather than hardcoded. The
  dispatch table routes to this handler only when the parent type is
  `PendingGrainUtilization`, so `top.PENDING_ID` is always the parent's
  id; reading it dynamically is functionally identical to hardcoding
  the string but DRY and rename-robust.
- Test code that constructs pendings directly needs to specify
  `initiated_by_id`. See the Tests subsection below for which files are
  affected.

### 5b. `PENDING_ID: ClassVar[str]` on every pending class

Identifies the *kind* of pending — what flow or event it represents. Lives
on the class (ClassVar), not instances. Matches the style of the existing
`TRIGGER_EVENT: ClassVar[str]` on `PendingBakeBread`.

Every pending class has one: parents get their space-id, generic
sub-actions get their sub-action name, card-specific pendings get their
card name.

```python
@dataclass(frozen=True)
class PendingGrainUtilization:
    PENDING_ID: ClassVar[str] = "grain_utilization"
    player_idx: int
    initiated_by_id: str
    sow_done: bool = False
    bake_done: bool = False


@dataclass(frozen=True)
class PendingSow:
    PENDING_ID: ClassVar[str] = "sow"
    player_idx: int
    initiated_by_id: str


@dataclass(frozen=True)
class PendingBakeBread:
    PENDING_ID: ClassVar[str] = "bake_bread"
    player_idx: int
    initiated_by_id: str
    triggers_resolved: frozenset = frozenset()
    TRIGGER_EVENT: ClassVar[str] = "before_bake_bread"
```

**Defensive read in the dispatcher.** The dispatcher reads it via
`getattr(parent, "PENDING_ID", None)`. The convention says every pending
has one, but the `getattr` form is kept as insurance — a future pending
class lacking the ClassVar wouldn't crash the dispatcher, and `None`
never matches a real initiator id.

## Change 6 — Unified commit dispatcher

Replace `_apply_commit_sow` and `_apply_commit_bake` with a single
`_apply_commit_subaction`. Add the `COMMIT_SUBACTION_HANDLERS` dispatch
table **in `engine.py`** (co-located with its sole consumer; the table is
metadata for the dispatcher, not a function-pointer table parallel to the
others).

### 6a. Dispatch table in `engine.py`

```python
# engine.py
from agricola.actions import CommitSow, CommitBake
from agricola.pending import PendingSow, PendingBakeBread
from agricola.resolution import _execute_sow, _execute_bake

COMMIT_SUBACTION_HANDLERS = {
    CommitSow:  (PendingSow,       "sow_done",  _execute_sow),
    CommitBake: (PendingBakeBread, "bake_done", _execute_bake),
}
```

Each value is a 3-tuple `(expected_pending_type, parent_flag, effect_fn)`:

- **`expected_pending_type`**: the pending dataclass that must be on top of
  the stack when this commit fires. The generic handler asserts on this.
- **`parent_flag`**: the *name* of the boolean field on the parent pending
  that must be set to `True` once the commit applies. For `CommitSow` the
  parent's flag is `"sow_done"`; for `CommitBake` it's `"bake_done"`.
  Setting it tells subsequent `legal_actions` calls "this sub-action
  category is complete; don't offer it again, and `Stop()` is now legal."
- **`effect_fn`**: the function that applies the sub-action's effect (see
  4b for the unified signature).

### 6b. Generic apply handler

```python
def _apply_commit_subaction(
    state: GameState, action: CommitSubAction,
) -> GameState:
    assert state.pending_stack, (
        f"{type(action).__name__} called with empty pending_stack"
    )
    pending_type, parent_flag, effect_fn = COMMIT_SUBACTION_HANDLERS[type(action)]
    top = state.pending_stack[-1]
    assert isinstance(top, pending_type), (
        f"{type(action).__name__} expected top={pending_type.__name__}, "
        f"got {type(top).__name__}"
    )
    initiator = top.initiated_by_id          # capture before pop
    state = effect_fn(state, top.player_idx, action)
    state = pop(state)

    if state.pending_stack:
        parent = state.pending_stack[-1]
        parent_id = getattr(parent, "PENDING_ID", None)
        parent_owns_subaction = (
            parent_id == initiator
            and parent_flag in type(parent).__dataclass_fields__
        )
        if parent_owns_subaction:
            new_parent = dataclasses.replace(parent, **{parent_flag: True})
            state = replace_top(state, new_parent)

    return state
```

**Three cases handled:**

| Scenario | Stack after pop | Identity match? | Field present? | Outcome |
|---|---|---|---|---|
| Single-frame chain (no parent) | empty | n/a | n/a | return |
| Standard sub-action (sow in Grain Utilization) | parent | yes | yes | set `parent_flag` on parent |
| Card cross-cutting (card-pushed plow inside Farm Expansion) | unrelated parent | no | likely no | don't touch parent |

**Why `__dataclass_fields__` directly.** The field-existence check uses
`parent_flag in type(parent).__dataclass_fields__` — an O(1) dict
membership test. `__dataclass_fields__` includes ClassVars (which
`dataclasses.fields()` would filter out), so this would false-positive
if a `parent_flag` value collided with a ClassVar name like
`"PENDING_ID"` or `"TRIGGER_EVENT"`. Our `parent_flag` values follow a
`*_done` lowercase pattern that doesn't collide with the `ALL_CAPS`
ClassVar convention, so the collision risk is structural-not-incidental
— maintained by naming convention.

`getattr(parent, "PENDING_ID", None)` is a defensive read — every pending
class is expected to carry `PENDING_ID`, but using `getattr` with a `None`
default means a future pending class that omits the ClassVar wouldn't
crash the dispatcher. `None` never matches a real initiator id, so the
identity check correctly returns False in that case.

### 6c. `_apply_action` collapses to five branches

```python
def _apply_action(state: GameState, action: Action) -> GameState:
    if isinstance(action, PlaceWorker):
        return _apply_place_worker(state, action)
    if isinstance(action, ChooseSubAction):
        return _apply_choose_sub_action(state, action)
    if isinstance(action, CommitSubAction):
        return _apply_commit_subaction(state, action)
    if isinstance(action, FireTrigger):
        return _apply_fire_trigger(state, action)
    if isinstance(action, Stop):
        return _apply_stop(state)
    raise TypeError(f"Unknown action type: {type(action).__name__}")
```

---

# Part 2 — Conventions for future code

These are not edits to existing code. They are rules to follow as new
spaces, sub-actions, and cards are added.

## Function-name prefix taxonomy

| Prefix | Meaning |
|---|---|
| `_resolve_<atomic_space>` | atomic worker placement — fully applies effect |
| `_initiate_<nonatomic_space>` | non-atomic worker placement — pushes pending, awaits sub-actions |
| `_choose_subaction_<space>` | handles `ChooseSubAction` at that space's pending |
| `_execute_<sub_action>` | applies a committed sub-action's effect |
| `_resolve_<phase>` (in `engine.py`) | phase bookkeeping |

`NONATOMIC_HANDLERS` keeps its current name — `HANDLERS` is intentionally
generic and matches `ATOMIC_HANDLERS`. The asymmetry between "fully
resolves" and "initiates" is captured in the per-function names; the
dispatch dicts don't encode it.

## Pending-class naming and `PENDING_ID`

**Class naming.** Python class names use PascalCase: `PendingCultivation`,
`PendingFarmExpansion`, `PendingSwingPlow`. `PENDING_ID` values use
snake_case: `"cultivation"`, `"farm_expansion"`, `"swing_plow"`.

**One namespace for `PENDING_ID`.** Space-ids and card-ids share a single
namespace. There is no `"card:"` prefix to distinguish them — uniqueness is
enforced by validation at card-registration time: the registry checks that
no card's id collides with a known space id and raises if it would.

| Pending class | `PENDING_ID` |
|---|---|
| `PendingCultivation` (space parent) | `"cultivation"` |
| `PendingFarmExpansion` (space parent) | `"farm_expansion"` |
| `PendingFarmland` (space parent) | `"farmland"` |
| `PendingSwingPlow` (card-specific) | `"swing_plow"` |
| `PendingPlow` (generic sub-action) | `"plow"` |
| `PendingSow` (generic sub-action) | `"sow"` |
| `PendingBakeBread` (generic sub-action) | `"bake_bread"` |

**Every pending class has a `PENDING_ID`.** Parents identify the space
they belong to; generic sub-action pendings identify the sub-action they
represent; card-specific pendings identify the card. The dispatcher
treats all of them uniformly via the identity check, which means deeper
nested stacks (e.g., card sub-decisions on top of a `PendingPlow`) work
without special-casing.

**Derived `TRIGGER_EVENT` naming.** When a pending hosts card trigger
events, the event names follow the convention
`"before_<PENDING_ID>"` and `"after_<PENDING_ID>"`. So
`PendingBakeBread.TRIGGER_EVENT = "before_bake_bread"` (existing) is the
canonical form, not a special case. Future trigger-event ClassVars on
other pendings should follow the same shape.

## `initiated_by_id` namespace and matching

`initiated_by_id` identifies *the entity or event that caused this pending
to exist on the stack*. Three push categories, three value shapes:

| Pending pushed by | `initiated_by_id` value | Example |
|---|---|---|
| `ChooseSubAction` at a parent pending | parent's `PENDING_ID` | `PendingSow.initiated_by_id = "grain_utilization"` |
| `PlaceWorker` (top-level pending) | event class `"worker_placement"` | `PendingGrainUtilization.initiated_by_id = "worker_placement"` |
| A card trigger's effect | the card's id | `PendingPlow.initiated_by_id = "swing_plow"` |

**Rationale.** The field's semantic is "why am I on the stack?", not "who
am I?". A top-level `PendingGrainUtilization` IS the Grain Utilization
frame (its class name says so, and `PENDING_ID` says so) — using
`initiated_by_id="grain_utilization"` would be redundant. Using
`"worker_placement"` instead tells you something new: this pending
appeared because of a worker placement, not because of a card. The
distinction matters once card-pushed top-level pendings exist.

**Same namespace for sub-action and card values** (the second and third
rows). Space-ids and card-ids share a single namespace; uniqueness is
enforced by card-registry validation. `"worker_placement"` is a reserved
event-class string and cannot collide with any space-id or card-id.

**The dispatcher's identity check** compares `top.initiated_by_id` to
`parent.PENDING_ID`. Match → parent architecturally owns this sub-action
→ set its `parent_flag`. Mismatch → leave the parent alone.

Note that the identity check never fires for top-level pendings (because
`"worker_placement"` is never a `PENDING_ID`). That's structurally fine:
when a top-level pending pops via `Stop()`, the stack is empty and the
`if state.pending_stack:` guard short-circuits the check anyway. A future
reader should not interpret the absence of a match as a bug.

## When to push a parent pending

**Convention:** Non-atomic action spaces push a parent pending. There is
no exception for single-sub-action spaces (Farmland, Grain Seeds and
Vegetable Seeds are atomic and don't apply; Farmland's plow would be the
relevant case).

The parent pending serves two purposes:

1. **Sub-action progress tracking.** For and/or spaces with multiple
   sub-actions (Grain Utilization, Cultivation, Farm Expansion, Side Job),
   the parent's boolean flags (`sow_done`, `bake_done`, …) gate which
   sub-actions are still legal and when `Stop()` becomes legal.
2. **Trigger event host.** The parent carries `TRIGGER_EVENT: ClassVar[str]`
   and `triggers_resolved: frozenset` so card triggers attached to that
   space fire through the existing `legal_actions` → `TRIGGERS[event]` →
   `FireTrigger` machinery, with no custom per-space code.

Both purposes are forward-compatible needs even genuinely single-sub-action
spaces will eventually require — at minimum, the second one. The cost (one
extra frame, one extra `Stop()` in the action trace) is small; the
architectural uniformity is large.

## Future extension for cards

These are forward-compat notes for the card task: the architecture is
already prepared, but the actual implementation is deferred. Track each
as a known future restructuring rather than something to preempt now.

### Atomic spaces too

When card triggers begin attaching to action spaces, atomic spaces will
follow the same pattern: push a pending whose job is to host the trigger
event(s) for that space. The pending has no `*_done` fields (no
sub-actions to track) but does have `triggers_resolved` plus whatever
state is needed to sequence the before/after trigger phases (see below).
At that point the `ATOMIC_HANDLERS` / `NONATOMIC_HANDLERS` split stops
being meaningful; the real distinction becomes "does this pending offer
`ChooseSubAction` options?", which is a pending-class property, not a
space-resolution-function property.

### Two trigger events per space

The Agricola rules encode timing in trigger phrasing: "Each time you use
[X]" means *before* the primary effect; "Each time after you use [X]"
means *after*. The distinction is rules-faithful, not cosmetic — e.g.,
Cottager (fires before Day Laborer) gives a room build, Hardware Store
(fires after Day Laborer) gives resources, and the rules forbid using
Hardware Store's resources to satisfy Cottager's room cost. Enforcing
that means each space exposes two trigger events (`"before_<space>"` and
`"after_<space>"`) and the pending tracks which side of the primary
effect it's currently on.

### Phase tracking on the space pending

The pending needs at least one piece of state to indicate "primary
effect applied yet?" Two modeling options worth weighing when the card
task starts:

1. **Generic `primary_effect_applied: bool`** on every space pending.
   Uniform; dispatcher reads one well-known field name. Likely the
   simplest forward-compat surface.
2. **A `phase` enum/string** field — `phase: Literal["before", "after"]`.
   Extensible if a card ever introduces a third trigger point ("during",
   mid-effect, etc.). Probably YAGNI for the base game.

### Phase-transition mechanism — open design question

Something has to flip the phase bit AND apply the primary effect between
the before and after trigger phases. Three candidate mechanisms, none
locked in:

- **Explicit transition action** — add an action like
  `ApplyPrimaryEffect()` or `Proceed()` that's legal during the
  before-phase. The agent picks it; the engine applies the primary
  effect and flips the flag. Keeps `Stop` unambiguous.
- **Stop-overloaded** — `Stop()` in the before-phase advances the phase;
  `Stop()` in the after-phase pops the pending. Fewer action types;
  `Stop`'s semantics become context-dependent.
- **Nested pendings** — push `PendingBefore<Space>` on top of
  `Pending<Space>`. The inner pending hosts the before-triggers and pops
  on Stop; the pop triggers the primary effect via a hook on
  `_apply_stop`. Outer pending hosts the after-triggers.

### Parallel to phase resolvers

This is the same architectural shape as the forward-compat note in
`TASK_5.md` for phase resolvers ("split a phase into sub-phases when
triggers need agent input mid-phase"). The space-resolution layer faces
the same problem and likely gets the same answer.

### Card-specific pending classes: `PENDING_ID` vs `initiated_by_id` redundancy

For card-pushed top-level pendings with their own pending class
(e.g., a hypothetical `PendingSwingPlow` with `PENDING_ID = "swing_plow"`),
the current convention sets `initiated_by_id` to the card's id —
`"swing_plow"` — which duplicates `PENDING_ID` on the same class. That
redundancy isn't present for `PlaceWorker`-pushed pendings, which use
the event class `"worker_placement"` instead of the space id.

The cleaner parallel would be a reserved event class for card-pushed
top-level pendings (e.g., `"card_trigger"`), mirroring
`"worker_placement"`. Generic sub-action pendings pushed by a card
(e.g., a `PendingPlow` pushed as a side effect of a card) would still
carry the card's id, since the dispatcher's identity check needs it to
distinguish card-initiated sub-actions from space-initiated ones.

Deferred to the card task, when card-specific pending classes are first
introduced. Resolution doesn't matter today — no Task-5-era card pushes
its own pending class.

## Adding a new `Commit*` sub-action

1. Define `@dataclass(frozen=True) class CommitX(CommitSubAction): …` in
   `actions.py`; add it to the `Action` union.
2. Define `_execute_x(state, player_idx, commit: CommitX)` in
   `resolution.py`.
3. Add `CommitX: (PendingX, "x_done", _execute_x)` to
   `COMMIT_SUBACTION_HANDLERS` in `engine.py`.
4. Ensure the parent pending(s) that offer this sub-action have an
   `x_done: bool = False` field.

No edits to `_apply_action` or any other dispatcher. The hierarchy +
dispatch table makes adding sub-actions a four-step extension.

## Caveats worth knowing for future debugging

**`parent_flag` is a string, coupled by convention.** The dispatch table
stores `"sow_done"`, `"bake_done"`, etc. as plain strings. There is no
compile-time check that the named field exists on the parent dataclass; a
typo would manifest at runtime — but the field-existence check in
`_apply_commit_subaction` now absorbs that into a no-op rather than a
crash. Tests cover the live paths.

**The dispatcher's `if state.pending_stack:`, identity check, and
field-existence check are NOT defensive cruft.** They are load-bearing for
forward-compat cases: (a) sub-action chains where there is no parent, (b)
card-triggered cross-cutting sub-actions where the immediate stack frame
underneath is not the architectural owner of this sub-action. Future
readers should NOT refactor them back to strict assertions.

**Every pending has a `PENDING_ID`.** Parents and sub-actions alike.
The dispatcher still uses `getattr(parent, "PENDING_ID", None)` defensively
— a future pending class lacking the ClassVar wouldn't crash the
dispatcher, and `None` never matches a real initiator id.

**`initiated_by_id` is mandatory.** Every `Pending*` construction must
specify it. The mandatory-no-default form was chosen specifically so that
omitting it raises `TypeError` at construction time — a loud failure
mode, not a silent one.

**Field-existence check uses `type(parent).__dataclass_fields__`
directly.** The dispatcher does
`parent_flag in type(parent).__dataclass_fields__` — an O(1) dict
membership test on the class's field-metadata dict.

The semantically-purer alternative is
`{f.name for f in dataclasses.fields(parent)}`, which filters out
ClassVars and InitVars. `__dataclass_fields__` doesn't filter, so a
`parent_flag` value that collided with a ClassVar name (e.g.,
`"PENDING_ID"` or `"TRIGGER_EVENT"`) would false-positive: the
dispatcher would try `dataclasses.replace(parent, PENDING_ID=True)`,
which raises because ClassVars aren't replaceable. The collision is
prevented by naming convention — `parent_flag` values follow a
lowercase `*_done` pattern that doesn't overlap with the `ALL_CAPS`
ClassVar convention. If a future pending class introduces a `parent_flag`
that breaks this pattern, switch to the `dataclasses.fields()`-filtered
form (and accept the per-commit O(n) cost, or memoize via
`functools.lru_cache`).

---

# Implementation logistics

These sections are meta to the changes above; they don't fit Part 1 or
Part 2.

## Tests

**No behavior change expected.** All existing tests should pass unchanged
after each step, modulo construction-call updates for `initiated_by_id`
(now mandatory) and import-path updates if any test reaches a moved
private symbol.

**Pending construction-site updates.** Any test code that constructs a
`Pending*` instance directly needs to specify `initiated_by_id`. The
construction happens in test bodies and in `tests/test_utils.py`'s
scripted-scenario paths, not in `tests/factories.py` itself —
`factories.py` only manipulates pre-built pendings via helpers like
`with_pending_stack`, so it's not a construction site. A quick

```
grep -rn 'Pending\(Grain\|Sow\|BakeBread\)(' tests/
```

will catch every `Pending*(...)` construction call that needs a new
`initiated_by_id=` kwarg.

**Specific test files to verify pass after each step:**

- `tests/test_grain_utilization.py` — the full sow/bake walk-throughs
  still pass (validates Change 6 end-to-end).
- `tests/test_potter_ceramics.py` — the trigger machinery still works
  (validates the `FireTrigger` branch is untouched).
- `tests/test_engine.py` — the random-agent smoke test still drives rounds
  1–4 to `BEFORE_SCORING` without raising.
- `tests/test_resolution_atomic.py` — atomic placements unaffected.

A quick `grep -rn "_push\|_pop\|_replace_top\|_resolve_grain_utilization\|_apply_commit_sow\|_apply_commit_bake\|NONATOMIC_HANDLERS\|CHOOSE_SUBACTION_HANDLERS" tests/`
will catch any test that imports a moved private symbol.

**No new tests required.** This is pure refactor; the behavior surface is
unchanged.

## Documentation updates

The following proposed prose is written as it would appear in
`CLAUDE.md` and `CHANGES.md` after the work lands. It describes the code
and principles in their final form, not the discussion that produced
them. Review here before any edits land in the real docs.

### Proposed CLAUDE.md changes

#### New top-level convention: function-name prefix taxonomy

Add this as a small section under "Additional Design Principles" (or as
a new sub-section at the start of "Engine and Turn Resolution
Architecture"):

> **Function-name prefix taxonomy.** Resolution-layer functions follow
> a small set of prefix conventions so the role of any function is
> identifiable from its name:
>
> | Prefix | Meaning |
> |---|---|
> | `_resolve_<atomic_space>` | atomic worker placement — fully applies effect |
> | `_initiate_<nonatomic_space>` | non-atomic worker placement — pushes pending, awaits sub-actions |
> | `_choose_subaction_<space>` | handles `ChooseSubAction` at that space's pending |
> | `_execute_<sub_action>` | applies a committed sub-action's effect |
> | `_resolve_<phase>` | phase bookkeeping (in `engine.py`, not `resolution.py`) |

#### New sub-section: "Pending provenance metadata"

Insert under "The pending-decision stack" after the "Structure" paragraph
and before "The decider rule":

> **Pending provenance metadata.** Every pending class carries two
> pieces of identity:
>
> - `initiated_by_id: str` — mandatory instance field. Identifies the
>   entity or event that pushed this frame onto the stack.
> - `PENDING_ID: ClassVar[str]` — class attribute. Identifies the kind
>   of pending (the flow or event it represents).
>
> Three categories of value for `initiated_by_id`:
>
> | Pending pushed by | `initiated_by_id` value | Example |
> |---|---|---|
> | `ChooseSubAction` at a parent pending | parent's `PENDING_ID` | `PendingSow.initiated_by_id = "grain_utilization"` |
> | `PlaceWorker` (top-level pending) | `"worker_placement"` | `PendingGrainUtilization.initiated_by_id = "worker_placement"` |
> | A card trigger's effect | the card's id | `PendingPlow.initiated_by_id = "swing_plow"` |
>
> Space-ids and card-ids share a single namespace (snake_case strings).
> Uniqueness is enforced at card-registration time. `"worker_placement"`
> is a reserved event-class string and cannot collide with any space-id
> or card-id.
>
> The generic commit dispatcher (`_apply_commit_subaction` in
> `engine.py`) uses these to decide whether to update the parent pending
> after a sub-action commits. After popping the sub-action's frame, it
> compares the popped frame's `initiated_by_id` to the new top frame's
> `PENDING_ID` and checks that the named `parent_flag` field exists on
> the new top. Both checks must pass to write the flag — a structural
> guard that lets card-driven cross-cutting sub-actions land harmlessly
> on parents that don't architecturally own them.
>
> When a pending hosts card trigger events, the event names follow the
> convention `"before_<PENDING_ID>"` and `"after_<PENDING_ID>"`. So
> `PendingBakeBread.TRIGGER_EVENT = "before_bake_bread"` is the
> canonical form.

#### Updated bullet in "Six design philosophies of the stack"

Add a new bullet (after the existing "Every pending carries
`player_idx`" bullet):

> - **Non-atomic spaces push a parent pending.** Every non-atomic action
>   space, when used via `PlaceWorker`, pushes a parent pending — even
>   spaces that offer only one sub-action. The parent serves two
>   purposes: (1) tracking which sub-action categories have been
>   completed (via `*_done` boolean fields, used by Stop-legality), and
>   (2) hosting the trigger event for cards that attach to that space
>   (via `TRIGGER_EVENT` / `triggers_resolved`). Both purposes are
>   forward-compat for the card system.

And add another bullet:

> - **Commit sub-actions inherit from `CommitSubAction`.** All `Commit*`
>   action types (`CommitSow`, `CommitBake`, future `CommitPlow`, …)
>   inherit from a frozen-dataclass base `CommitSubAction`. The engine
>   dispatches them uniformly through `_apply_commit_subaction` and the
>   `COMMIT_SUBACTION_HANDLERS` metadata table. Adding a new sub-action
>   type does not require editing `_apply_action`.

#### Updated bullets in "The architecture is built with cards in mind"

Replace the existing bullet list with this expanded version (the
existing bullets remain; new ones at the end):

> - Out-of-turn triggers via `player_idx` on each frame.
> - Triggers with sub-decisions via arbitrary stack depth.
> - Card-aware legality via `*_EXTENSIONS` registries on `_can_*`
>   predicates (e.g., `BAKE_BREAD_ELIGIBILITY_EXTENSIONS`).
> - Once-per-action trigger budgets via the `triggers_resolved` field on
>   relevant pendings — most pending types will eventually carry one.
> - Pending provenance via `initiated_by_id` + `PENDING_ID`, used by the
>   generic commit dispatcher to recognize when a sub-action's
>   architectural owner is or is not the immediate stack frame
>   underneath. Card-pushed cross-cutting sub-actions land harmlessly on
>   unrelated parents.
> - Atomic spaces will follow the "push a parent pending" pattern when
>   card triggers begin attaching to them — the pending hosts the
>   trigger event(s) for that space, with no `*_done` fields. The
>   `ATOMIC_HANDLERS` / `NONATOMIC_HANDLERS` split will collapse at
>   that point.
> - Two trigger events per space (`"before_<space>"` and
>   `"after_<space>"`), enforcing the rules-faithful timing of card
>   triggers (e.g., Cottager fires before Day Laborer's food is
>   received; Hardware Store fires after).

#### Per-file description: `agricola/pending.py`

Replace the existing entry with:

> Frozen pending-decision dataclasses *and* the stack operations on them.
> The stack itself lives on `GameState.pending_stack`; this module owns
> both the element types and the three pure functions for manipulating
> the stack. Imports `GameState` from `state.py` (no cycle: `state.py`
> stores `pending_stack: tuple` without parameterizing the type).
>
> **Pending dataclasses.** Every pending class carries:
> - `player_idx: int` — whose decision this frame is for.
> - `initiated_by_id: str` (mandatory, no default) — what pushed this
>   frame onto the stack. See CLAUDE.md "Pending provenance metadata".
> - `PENDING_ID: ClassVar[str]` — the kind of pending (flow or event it
>   represents).
>
> Concrete classes:
> - **`PendingGrainUtilization(player_idx, initiated_by_id, sow_done=False, bake_done=False)`**
>   — outer pending for the Grain Utilization action.
>   `PENDING_ID = "grain_utilization"`. Stop-legality requires
>   `sow_done or bake_done`.
> - **`PendingSow(player_idx, initiated_by_id)`** — pushed by
>   `ChooseSubAction("sow")`. `PENDING_ID = "sow"`. Pops on `CommitSow`,
>   writing `sow_done=True` to the parent.
> - **`PendingBakeBread(player_idx, initiated_by_id, triggers_resolved=frozenset())`**
>   — pushed by `ChooseSubAction("bake_bread")`. `PENDING_ID =
>   "bake_bread"`, `TRIGGER_EVENT = "before_bake_bread"`.
>   `triggers_resolved` is scoped to this frame's lifetime.
> - **`PendingDecision`** — the union alias.
>
> **Stack operations.** Pure functions; all return new `GameState`
> objects.
> - `push(state, frame)` — append a frame to `state.pending_stack`.
> - `pop(state)` — drop the top frame.
> - `replace_top(state, new_top)` — replace the top frame.

#### Per-file description: `agricola/resolution.py`

Replace the existing entry with:

> Per-space resolution code. Atomic and non-atomic space handlers,
> sub-action effect functions, and the function-pointer dispatch tables
> for them. Imported by `agricola.engine` for dispatch. Never mutates
> state — always uses `dataclasses.replace(...)`.
>
> Two utility wrappers:
> - `_update_player(state, ap, new_player)` — new `GameState` with one
>   player replaced.
> - `_update_space(state, space_id, **kwargs)` — new `GameState` with
>   one action space's fields updated.
>
> **Cross-cutting bookkeeping.**
> - `_apply_worker_placement(state, space_id)` — increments
>   `workers[ap]` on the space, decrements `people_home` on the active
>   player. Run for every worker placement.
>
> **Atomic handlers.** Per-space `_resolve_<space>` functions for the
> 12 atomic spaces, each receiving the state *after*
> `_apply_worker_placement` and applying the space's specific effect.
> Two shared helpers — `_resolve_building_accumulation` (for the five
> Resources-accumulation spaces) and `_resolve_food_accumulation` (for
> `fishing` and `meeting_place`) — avoid repetition.
>
> **Non-atomic initiators.** `_initiate_<space>` functions push the
> space's parent pending. Currently:
> - `_initiate_grain_utilization(state)` — pushes
>   `PendingGrainUtilization(initiated_by_id="worker_placement", ...)`.
>
> **Choose-sub-action handlers.** `_choose_subaction_<space>` functions
> handle `ChooseSubAction` at that space's parent pending. The pushed
> sub-action pending takes `initiated_by_id=top.PENDING_ID` (read
> dynamically from the top frame). Currently:
> - `_choose_subaction_grain_utilization(state, action)` — pushes
>   `PendingSow` or `PendingBakeBread` depending on the action's name.
>
> **Sub-action effect functions.**
> `_execute_<sub_action>(state, player_idx, commit)` functions apply
> the effect of a committed sub-action. Each takes the commit action
> object as the third argument so a single dispatcher can call any
> effect uniformly.
> - `_execute_sow(state, player_idx, commit: CommitSow)` — subtracts
>   grain and veg from supply and fills empty fields in canonical
>   (row, col) order. Per RULES.md: 1 grain → 3 grain on field; 1 veg →
>   2 veg on field.
> - `_execute_bake(state, player_idx, commit: CommitBake)` — converts
>   grain → food at the player's best baking-improvement rate
>   (Cooking Hearth: 3; Fireplace: 2). Raises `NotImplementedError` for
>   Clay-Oven-only or Stone-Oven-only owners (parameterized rates
>   deferred).
>
> **Function-pointer dispatch tables**, each keyed by space-id or
> pending-type:
> - `ATOMIC_HANDLERS: dict[str, callable]` —
>   `space_id → _resolve_<space>`.
> - `NONATOMIC_HANDLERS: dict[str, callable]` —
>   `space_id → _initiate_<space>`.
> - `CHOOSE_SUBACTION_HANDLERS: dict[type, callable]` —
>   `pending_type → _choose_subaction_<space>`.
>
> The metadata dispatch table for `Commit*` sub-actions
> (`COMMIT_SUBACTION_HANDLERS`) lives in `engine.py` — it's metadata
> for the engine's generic commit dispatcher, not a function-pointer
> table.

#### Per-file description: `agricola/engine.py`

Replace the existing entry with:

> The state-transition engine. Public API: `step(state, action) ->
> GameState`. Pure transition function; the loop that drives a game
> lives outside this module.
>
> - **`step(state, action)`** — apply one action and auto-advance
>   through system transitions. Raises `RuntimeError` on
>   `Phase.BEFORE_SCORING`. Raises `NotImplementedError` for non-atomic
>   spaces other than `grain_utilization` (current scope). Does NOT
>   validate legality — callers assert via `legal_actions`.
> - **`_apply_action(state, action)`** — dispatches on action type via
>   five `isinstance` branches: `PlaceWorker`, `ChooseSubAction`,
>   `CommitSubAction` (matches any concrete commit subclass),
>   `FireTrigger`, `Stop`.
> - **`_apply_place_worker(state, action)`** — runs
>   `_apply_worker_placement` (from `resolution.py`) then dispatches via
>   `ATOMIC_HANDLERS` or `NONATOMIC_HANDLERS`. Non-atomic spaces other
>   than `grain_utilization` raise `NotImplementedError`.
> - **`_apply_choose_sub_action(state, action)`** — dispatches via
>   `CHOOSE_SUBACTION_HANDLERS` keyed by the top pending's type.
> - **`_apply_commit_subaction(state, action)`** — generic handler for
>   any `CommitSubAction` subclass. Dispatches via
>   `COMMIT_SUBACTION_HANDLERS` (defined in this module). For each
>   commit type the table holds `(expected_pending_type, parent_flag,
>   effect_fn)`. The handler asserts the expected pending is on top,
>   applies the effect, pops the sub-action pending, and (if the new
>   top frame's `PENDING_ID` matches the popped frame's
>   `initiated_by_id` and the named `parent_flag` field exists on the
>   new top) sets `parent_flag=True` on the parent. The two checks are
>   load-bearing for forward compatibility with card-driven
>   cross-cutting sub-actions.
> - **`_apply_fire_trigger`** — looks up the trigger via
>   `CARDS[card_id]`, applies its `apply_fn`, adds `card_id` to the top
>   frame's `triggers_resolved`.
> - **`_apply_stop`** — pops the top pending frame.
> - **`_advance_current_player(state)`** — rotates `current_player`
>   to the next player with workers. Called inside `step` only when the
>   stack is empty AND phase is WORK.
> - **`_advance_until_decision(state)`** — auto-advance loop. Walks
>   system-driven phase transitions until the next agent decision or
>   game-over. Pure state-driven and idempotent.
> - **`_resolve_return_home(state)`** and **`_resolve_preparation(state)`**
>   — phase resolvers (see CLAUDE.md "Engine and Turn Resolution
>   Architecture" for the lifecycle).
>
> **Dispatch table in this module.**
> - `COMMIT_SUBACTION_HANDLERS: dict[type, tuple]` —
>   `CommitX → (PendingX, "x_done", _execute_x)`. Metadata table for
>   the generic commit dispatcher; co-located with its sole consumer.
>
> **Stack operations** (`push`, `pop`, `replace_top`) are imported from
> `pending.py`.

#### Per-file description: `agricola/actions.py`

Replace the existing entry with:

> Defines the action types the engine's `step` accepts. Every action is
> a frozen dataclass. Dispatched via `isinstance` checks in
> `engine._apply_action`.
>
> - **`PlaceWorker(space: str)`** — place the active player's worker on
>   a named action space.
> - **`ChooseSubAction(name: str)`** — pick a sub-action category at a
>   non-atomic space's pending decision.
> - **`CommitSubAction`** — frozen-dataclass marker base for all
>   `Commit*` types. Empty (no fields). Concrete subclasses inherit
>   from it and are dispatched uniformly by `_apply_commit_subaction`
>   in `engine.py` via the `COMMIT_SUBACTION_HANDLERS` table.
> - **`CommitSow(grain: int, veg: int)`** — commit a sow. Pops
>   `PendingSow` and marks `sow_done` on parent.
> - **`CommitBake(grain: int)`** — commit a Bake Bread. Pops
>   `PendingBakeBread` and marks `bake_done` on parent.
> - **`FireTrigger(card_id: str)`** — fire a specific card trigger
>   that's currently eligible at the top pending.
> - **`Stop()`** — end the current non-atomic action (pop the top
>   pending frame).
> - **`Action`** — union alias listing the concrete subclasses
>   (`PlaceWorker | ChooseSubAction | CommitSow | CommitBake |
>   FireTrigger | Stop`). The `CommitSubAction` base is intentionally
>   not in the union — concrete subclasses are listed so legality
>   enumerators and type checkers see the real options. There is no
>   `SkipTrigger`: declining a trigger is implicit.

#### Documentation Files list

Add a row for `TASK_5B_DISPATCH_CLEANUP.md`:

> | `TASK_5B_DISPATCH_CLEANUP.md` | Dispatch refactor follow-up to Task 5: relocates per-space resolution code, introduces the `CommitSubAction` hierarchy, adds pending provenance metadata, and codifies forward-compat conventions for the card system. |

#### Current Status table

Add the following rows (or amend existing ones):

> | Dispatch refactor (per-space code, `CommitSubAction` hierarchy, provenance metadata) | Complete | `TASK_5B_DISPATCH_CLEANUP.md` |

### Proposed CHANGES.md entry

Add as Change 4:

> ## Change 4 — Dispatch refactor and pending provenance
>
> Reorganized resolution-layer code, replaced the per-`Commit*` apply
> handlers with a single generic dispatcher, and added provenance
> metadata to pending dataclasses. Touched five modules; behavior is
> unchanged.
>
> **Code relocations.** Per-space resolution code now lives uniformly
> in `agricola/resolution.py` — atomic handlers (already there),
> non-atomic initiators (`_initiate_<space>`), choose-sub-action
> handlers (`_choose_subaction_<space>`), and sub-action effect
> functions (`_execute_<sub_action>`). The function-pointer dispatch
> tables `NONATOMIC_HANDLERS` and `CHOOSE_SUBACTION_HANDLERS` moved
> from `engine.py` to `resolution.py` to sit with their handler
> functions (joining the existing `ATOMIC_HANDLERS`). Stack helpers
> (`push`, `pop`, `replace_top`) moved from `engine.py` to
> `pending.py`, where they sit with the dataclasses they manipulate;
> underscores were dropped since they now cross module boundaries.
> `_resolve_grain_utilization` was renamed `_initiate_grain_utilization`
> to honestly describe what it does (push a pending and exit; the
> actual resolution happens later via committed sub-actions).
>
> **`CommitSubAction` hierarchy.** Added a frozen-dataclass marker base
> `CommitSubAction` in `agricola/actions.py`. `CommitSow` and
> `CommitBake` inherit from it. The engine dispatches them uniformly
> through a single `_apply_commit_subaction` handler driven by a new
> `COMMIT_SUBACTION_HANDLERS` metadata table in `engine.py` (co-located
> with the dispatcher; the table's values are
> `(expected_pending_type, parent_flag, effect_fn)` tuples, not raw
> function pointers). `_apply_action` now has exactly five branches.
> Adding a new `Commit*` sub-action requires no changes to
> `_apply_action` — only a new dataclass, a new effect function, and a
> new row in the table.
>
> **Pending provenance fields.** Every pending class now carries an
> `initiated_by_id: str` mandatory instance field (identifies what
> pushed this frame) and a `PENDING_ID: ClassVar[str]` class attribute
> (identifies the kind of pending). The generic commit dispatcher uses
> these for an identity check when writing to the parent: it sets
> `parent_flag=True` on the new top frame only if the popped frame's
> `initiated_by_id` matches the new top's `PENDING_ID` and the named
> field exists on the new top. The check lets card-driven
> cross-cutting sub-actions land harmlessly on unrelated parents in
> the future card system.
>
> **Conventions established.** Function-name prefixes
> (`_resolve_<atomic>` / `_initiate_<nonatomic>` /
> `_choose_subaction_<space>` / `_execute_<sub_action>`); non-atomic
> spaces always push a parent pending (for sub-action progress
> tracking and for hosting the space's card trigger event); space-ids
> and card-ids share a single namespace with collision validated at
> card-registration time; trigger event names follow
> `"before_<PENDING_ID>"` / `"after_<PENDING_ID>"`. See
> `TASK_5B_DISPATCH_CLEANUP.md` Part 2 for the full conventions and
> forward-compat notes for the card system.

## Suggested order of work

Each step ends with a green test run. Steps are ordered so each diff is
small and reviewable in isolation.

1. **Change 3 first.** Move `_push` / `_pop` / `_replace_top` to
   `pending.py`, rename to `push` / `pop` / `replace_top`, update all
   callers. Run tests.
2. **Change 1 + Change 2 together.** Rename `_resolve_grain_utilization`
   → `_initiate_grain_utilization` and move it (plus
   `_choose_subaction_grain_utilization`, `NONATOMIC_HANDLERS`,
   `CHOOSE_SUBACTION_HANDLERS`) to `resolution.py`. Update `engine.py`
   imports. Run tests.
3. **Change 5.** Add `initiated_by_id` mandatory field to all pending
   classes; add `PENDING_ID` ClassVar to every pending class. Update
   all construction sites in code and tests. Run tests.
4. **Change 4.** Add `CommitSubAction` to `actions.py`. Update
   `_execute_sow` and `_execute_bake` to take a commit object. Update
   their two current callers (still per-type at this point). Run tests.

   After Step 4, the per-type apply handlers `_apply_commit_sow` and
   `_apply_commit_bake` still exist; they're just calling effect
   functions with the new commit-object signature. Step 5 removes them
   in favor of the generic dispatcher.
5. **Change 6.** Add `COMMIT_SUBACTION_HANDLERS` to `engine.py`. Replace
   `_apply_commit_sow` and `_apply_commit_bake` with
   `_apply_commit_subaction` (using both field-existence and identity
   checks). Update `_apply_action` to dispatch on `CommitSubAction`. Run
   tests.
6. **Documentation pass.** Update `CLAUDE.md` per-file descriptions and
   the architecture section. Optionally add the Change 4 entry to
   `CHANGES.md`.

## Acceptance criteria

- All 236 existing tests pass; only updates allowed are constructor-call
  changes for the new mandatory `initiated_by_id` and import-path updates
  for moved private symbols.
- `engine.py` no longer defines `NONATOMIC_HANDLERS`,
  `CHOOSE_SUBACTION_HANDLERS`, `_resolve_grain_utilization`,
  `_choose_subaction_grain_utilization`, `_push`, `_pop`, or
  `_replace_top`.
- `engine.py` defines `COMMIT_SUBACTION_HANDLERS` and
  `_apply_commit_subaction`.
- `_apply_action` contains exactly five `isinstance` branches plus the
  `TypeError` fallback.
- `_apply_commit_sow` and `_apply_commit_bake` are removed.
- `CommitSow` and `CommitBake` inherit from `CommitSubAction`, which is a
  frozen dataclass.
- `pending.py` exports `push`, `pop`, `replace_top` as public functions.
- `resolution.py` defines the three function-pointer dispatch tables
  (`ATOMIC_HANDLERS`, `NONATOMIC_HANDLERS`, `CHOOSE_SUBACTION_HANDLERS`).
- Every `Pending*` dataclass has a mandatory `initiated_by_id: str` field
  (no default).
- Every `Pending*` dataclass has a `PENDING_ID: ClassVar[str]` —
  parents (`PendingGrainUtilization`) and generic sub-action pendings
  (`PendingSow`, `PendingBakeBread`) alike.
