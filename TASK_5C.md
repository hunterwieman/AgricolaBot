# Task 5C — Non-Atomic Resolution for Eight Spaces

A continuation of Tasks 5 and 5B. The document is split into:

- **Part 1 — Preliminary refactors.** Four convention shifts that touch existing code. Behavior is preserved (modulo the new constants and the broader Bake Bread support). Existing tests are updated for renamed field names; no test should be removed.
- **Part 2 — Shared sub-action pending machinery.** Sub-action pendings (the four pendings that host a `CommitX` action, used by multiple spaces). Each is defined once here and reused by the per-space code in Part 3. Parent pendings — including both top-level pendings pushed by `PlaceWorker` and the non-top-level oven wrappers in §3.5 — live in Part 3 with their owning space.
- **Part 3 — Per-space implementations.** One section per space, in suggested implementation order. Eight spaces total: Farmland, Cultivation, Side Job, Sheep Market, Pig Market, Cattle Market, Major Improvement, House Redevelopment.
- **Part 4 — Tests.** New test files and what each covers.
- **Part 5 — Documentation updates.** CLAUDE.md edits and the new CHANGES.md entry.
- **Part 6 — Order of work.**
- **Part 7 — Acceptance criteria.**

The non-atomic spaces explicitly **excluded** from this task: Farm Expansion, Farm Redevelopment, Fencing. Those remain `NotImplementedError` after this work.

---

## Scope

Eight spaces gain `_initiate`/`_choose_subaction`/`_execute` plumbing and full per-pending legality enumeration:

| Space | Sub-actions |
|---|---|
| Farmland | plow |
| Cultivation | plow and/or sow |
| Side Job | build_stable and/or bake_bread |
| Sheep Market | accommodate (mandatory) |
| Pig Market | accommodate (mandatory) |
| Cattle Market | accommodate (mandatory) |
| Major Improvement | build_major (+ optional free bake after Clay/Stone Oven) |
| House Redevelopment | renovate, then optional improvement |

Four preliminary refactors land first:

1. **Choose-time flag-setting convention.** Parent flags are set in `_choose_subaction_*` handlers at push time, not in the commit dispatcher. The dispatcher's flag-setting block is removed. Existing `*_done` field names are renamed to `*_chosen`.
2. **Top-level pending provenance prefix.** `initiated_by_id` for top-level pendings becomes `"space:<space_id>"` (was `"worker_placement"`). Card-pushed top-level pendings use `"card:<card_id>"`.
3. **Major Improvement constants and Bake Bread expansion.** `MAJOR_IMPROVEMENT_COSTS` and `BAKING_IMPROVEMENT_SPECS` added to `constants.py`. `_execute_bake` becomes a greedy-by-rate allocator over all owned baking improvements; `_enumerate_pending_bake_bread` enumerates `CommitBake(grain=n)` for `n` up to the player's per-action grain cap.
4. **`Resources.__sub__` operator.** Add subtraction to `Resources` alongside the existing `__add__`, eliminating the 7-field-negated-component pattern at pure-subtraction sites. Migrate `_execute_sow` and use the cleaner form in all new effect functions in Part 2.

---

## Motivation

After Task 5, only Grain Utilization had non-atomic resolution. The eight spaces in this task complete non-atomic resolution for every Family-game space that is not Farm Expansion, Farm Redevelopment, or Fencing. The preliminary refactors are landed first because:

- The choose-time convention removes a structural coupling between the commit dispatcher and parent dataclass fields that becomes fragile as the number of (parent, sub-action) pairs grows. Choose-handlers already exist per parent; consolidating flag-setting there keeps the per-parent logic in one place.
- The `"space:"` / `"card:"` prefix scheme makes provenance breadcrumbs informative without a reserved-namespace carve-out for `"worker_placement"`. It also resolves the PENDING_ID/`initiated_by_id` redundancy that arises when cards own pending classes.
- Major Improvement is one of the eight spaces and cannot land without `_execute_bake` understanding Clay Oven and Stone Oven (a player who buys an oven and exercises the free bake would otherwise hit `NotImplementedError`).

---

# Part 1 — Preliminary refactors

## Change 1 — Choose-time flag-setting + `*_done` → `*_chosen`

### Convention shift

Under the new convention, every `_choose_subaction_*` handler:

1. Replaces the parent pending's `<action>_chosen` field with `True` via `replace_top(state, replace(parent, **{flag: True}))`.
2. Pushes the new sub-action pending.

The commit dispatcher (`_apply_commit_subaction` in `engine.py`) no longer sets any flag on the parent. It only:

1. Asserts the expected pending type is on top.
2. Applies the effect function.
3. Pops the sub-action pending.

### Code edits

**`agricola/engine.py`** — `_apply_commit_subaction`:

- Remove line 197 (`initiator = top.initiated_by_id` capture).
- Remove the entire `if state.pending_stack:` block (lines 218–227), including the `dataclasses.replace` parent-flag set.
- Rewrite the function docstring to describe only the assert/effect/pop responsibilities.
- Remove the "Caveat" block on the `COMMIT_SUBACTION_HANDLERS` dispatch table (lines 124–130).

`COMMIT_SUBACTION_HANDLERS` entries shrink from 3-tuples to 2-tuples:

```python
COMMIT_SUBACTION_HANDLERS: dict[type, tuple] = {
    CommitSow:  (PendingSow,       _execute_sow),
    CommitBake: (PendingBakeBread, _execute_bake),
}
```

And the destructure at line 191 becomes `pending_type, effect_fn = COMMIT_SUBACTION_HANDLERS[type(action)]`.

**`agricola/pending.py`** — rename existing fields:

- `PendingGrainUtilization.sow_done` → `sow_chosen`
- `PendingGrainUtilization.bake_done` → `bake_chosen`

(`PendingBakeBread.triggers_resolved` and `PendingSow` have no `*_done` fields; nothing to rename.)

**`agricola/resolution.py`** — update `_choose_subaction_grain_utilization`:

```python
def _choose_subaction_grain_utilization(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    top = state.pending_stack[-1]
    p_idx = top.player_idx
    if action.name == "sow":
        state = replace_top(state, dataclasses.replace(top, sow_chosen=True))
        return push(state, PendingSow(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID,
        ))
    if action.name == "bake_bread":
        state = replace_top(state, dataclasses.replace(top, bake_chosen=True))
        return push(state, PendingBakeBread(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID,
        ))
    raise ValueError(f"Unknown sub-action: {action.name!r}")
```

**`agricola/legality.py`** — update `_enumerate_pending_grain_utilization`:

- References to `sow_done`/`bake_done` become `sow_chosen`/`bake_chosen`. No structural change.

**Tests** — update references in `tests/test_grain_utilization.py` and `tests/test_potter_ceramics.py` from `sow_done`/`bake_done` to `sow_chosen`/`bake_chosen`. The semantics test ("stack invariants: `CommitSow` pops `PendingSow` and writes `sow_chosen=True` on parent") becomes "`ChooseSubAction('sow')` writes `sow_chosen=True` on parent and pushes `PendingSow`; `CommitSow` pops `PendingSow` without modifying the parent."

### Convention for the new pendings

Every new parent pending added in Parts 2–3 follows this convention. Every new `_choose_subaction_*` handler sets the parent's `<action>_chosen` field before pushing.

## Change 2 — Provenance prefix scheme

### Convention shift

`initiated_by_id` values follow a namespaced prefix scheme:

| Pending pushed by | `initiated_by_id` value | Example |
|---|---|---|
| `ChooseSubAction` at a parent pending | parent's `PENDING_ID` | `PendingSow.initiated_by_id = "grain_utilization"` |
| `PlaceWorker` (top-level pending) | `"space:<space_id>"` | `PendingGrainUtilization.initiated_by_id = "space:grain_utilization"` |
| A card trigger's effect | `"card:<card_id>"` | `PendingPlow.initiated_by_id = "card:swing_plow"` |

The middle row (sub-action pendings pushed by `ChooseSubAction` at a parent) is unchanged. Only the PlaceWorker and card-trigger rows shift.

### Code edits

**`agricola/resolution.py`** — `_initiate_grain_utilization`:

```python
def _initiate_grain_utilization(state: GameState) -> GameState:
    ap = state.current_player
    return push(state, PendingGrainUtilization(
        player_idx=ap, initiated_by_id="space:grain_utilization",
    ))
```

**Tests** — update factory usage and assertions in `tests/test_grain_utilization.py` and `tests/test_potter_ceramics.py`.

For card-pushed pendings: only Potter Ceramics exists today and doesn't push its own pending, so no card-side code edits are needed. The convention applies to future cards.

## Change 3 — Major Improvement constants and `_execute_bake` expansion

### New constants in `agricola/constants.py`

```python
from agricola.resources import Resources

# Major improvement costs, indexed by major_idx (0-9).
# Cooking Hearths (idx 2, 3) have an alternate payment: return a Fireplace.
# That alternate is handled in resolution code, not encoded here.
MAJOR_IMPROVEMENT_COSTS: tuple[Resources, ...] = (
    Resources(clay=2),                # 0: Fireplace (cheap)
    Resources(clay=3),                # 1: Fireplace (expensive)
    Resources(clay=4),                # 2: Cooking Hearth (cheap)
    Resources(clay=5),                # 3: Cooking Hearth (expensive)
    Resources(stone=3, wood=1),       # 4: Well
    Resources(clay=3, stone=1),       # 5: Clay Oven
    Resources(clay=1, stone=3),       # 6: Stone Oven
    Resources(wood=2, stone=2),       # 7: Joinery
    Resources(clay=2, stone=2),       # 8: Pottery
    Resources(reed=2, stone=2),       # 9: Basketmaker's Workshop
)

# Per-action Bake Bread specs by major_idx. (max_grain_per_action, food_per_grain).
# A None cap means "any amount" (Fireplace / Cooking Hearth).
BAKING_IMPROVEMENT_SPECS: dict[int, tuple[int | None, int]] = {
    0: (None, 2), 1: (None, 2),       # Fireplaces
    2: (None, 3), 3: (None, 3),       # Cooking Hearths
    5: (1, 5),                         # Clay Oven (exactly 1 grain)
    6: (2, 4),                         # Stone Oven (up to 2 grain)
}

FIREPLACE_INDICES: tuple[int, ...] = (0, 1)
COOKING_HEARTH_INDICES: tuple[int, ...] = (2, 3)
BAKING_IMPROVEMENTS: frozenset[int] = frozenset(BAKING_IMPROVEMENT_SPECS.keys())
```

The `BAKING_IMPROVEMENTS` frozenset currently lives in `agricola/legality.py`. Move it to `constants.py` (derived from `BAKING_IMPROVEMENT_SPECS.keys()`) and update the import in `legality.py`.

### Baking-spec collection helper

To make future card-driven baking sources — minor-improvement ovens like Iron Oven ("exactly 1 grain → 6 food on any Bake Bread action"), and other cards that grant baking — drop in with a single registration call rather than edits to `_execute_bake` or `_enumerate_pending_bake_bread`, introduce a small collection helper and an extension registry. Pattern mirrors `BAKE_BREAD_ELIGIBILITY_EXTENSIONS` in `legality.py`.

Add to `agricola/legality.py` (near the existing `BAKE_BREAD_ELIGIBILITY_EXTENSIONS` block):

```python
# Card-supplied baking sources. Each registered fn takes (state, player_idx)
# and returns a list of (max_grain_per_action, food_per_grain) tuples for
# baking sources the player owns from non-major-improvement origins
# (minor improvements, occupations, future card types).
BAKING_SPEC_EXTENSIONS: list[Callable[[GameState, int], list[tuple[int | None, int]]]] = []

def register_baking_spec_extension(
    fn: Callable[[GameState, int], list[tuple[int | None, int]]],
) -> None:
    BAKING_SPEC_EXTENSIONS.append(fn)


def baking_specs_for_player(
    state: GameState, player_idx: int,
) -> list[tuple[int | None, int]]:
    """Collect (max_grain_per_action, food_per_grain) specs for every baking
    source the player owns. Major improvements feed in directly from
    BAKING_IMPROVEMENT_SPECS; cards (minor improvements, occupations) feed in
    via BAKING_SPEC_EXTENSIONS. The greedy allocator in _execute_bake and the
    grain-cap computation in _enumerate_pending_bake_bread both consume this
    spec list and remain agnostic to source.

    Note: resolution.py imports this helper, introducing a
    resolution.py → legality.py dependency. The arrow is one-way today
    (legality.py does not import from resolution.py), so no cycle. If a
    future card-eligibility path forces a cycle, move this helper and
    BAKING_SPEC_EXTENSIONS into a new agricola/baking.py module.
    """
    specs: list[tuple[int | None, int]] = []
    owners = state.board.major_improvement_owners
    for idx, spec in BAKING_IMPROVEMENT_SPECS.items():
        if owners[idx] == player_idx:
            specs.append(spec)
    for ext in BAKING_SPEC_EXTENSIONS:
        specs.extend(ext(state, player_idx))
    return specs
```

For example, when a card that adds a baking source lands, its baking-side implementation is one registration call. Iron Oven (one such card among several minor-improvement ovens) would look like:

```python
# agricola/cards/iron_oven.py (illustrative; not implemented in this task)
def _iron_oven_specs(state, player_idx):
    p = state.players[player_idx]
    return [(1, 6)] if "iron_oven" in p.minor_improvements else []

register_baking_spec_extension(_iron_oven_specs)
```

No edit to `_execute_bake` or `_enumerate_pending_bake_bread`. Other minor-improvement ovens follow the same shape with their own `(cap, rate)` tuples.

### `_execute_bake` upgrade

Current `_execute_bake` raises `NotImplementedError` for Clay-Oven-only or Stone-Oven-only owners. Replace with greedy-by-rate allocation across the spec list returned by `baking_specs_for_player`:

```python
def _execute_bake(
    state: GameState, player_idx: int, commit: CommitBake,
) -> GameState:
    specs = baking_specs_for_player(state, player_idx)
    grain_remaining = commit.grain
    food = 0
    # Greedy: process highest food/grain rate first.
    for cap, rate in sorted(specs, key=lambda s: s[1], reverse=True):
        used = grain_remaining if cap is None else min(cap, grain_remaining)
        food += used * rate
        grain_remaining -= used
        if grain_remaining == 0:
            break
    assert grain_remaining == 0, (
        f"CommitBake(grain={commit.grain}) exceeds player's per-action grain cap"
    )
    p = state.players[player_idx]
    new_player = dataclasses.replace(
        p,
        resources=p.resources + Resources(food=food, grain=-commit.grain),
    )
    return _update_player(state, player_idx, new_player)
```

(Mixed subtract-and-add cases stay in the single-`Resources` form; `__sub__` is reserved for pure-subtraction sites where it's strictly cleaner.)

### `_enumerate_pending_bake_bread` upgrade

Compute the player's per-action grain cap from the same spec list:

```python
def _enumerate_pending_bake_bread(
    state: GameState, pending: PendingBakeBread,
) -> list[Action]:
    p = state.players[pending.player_idx]
    specs = baking_specs_for_player(state, pending.player_idx)
    finite_cap = sum(cap for (cap, _rate) in specs if cap is not None)
    uncapped_present = any(cap is None for (cap, _rate) in specs)
    max_grain = p.resources.grain if uncapped_present else min(p.resources.grain, finite_cap)

    actions: list[Action] = []
    from agricola.cards.triggers import TRIGGERS
    for entry in TRIGGERS.get("before_bake_bread", []):
        if (entry.card_id not in pending.triggers_resolved
                and entry.eligibility_fn(state, pending.player_idx, pending.triggers_resolved)):
            actions.append(FireTrigger(card_id=entry.card_id))
    for n in range(1, max_grain + 1):
        actions.append(CommitBake(grain=n))
    return actions
```

(Trigger enumeration logic mirrors the existing implementation; the FireTrigger block stays as-is.)

## Change 4 — `Resources.__sub__`

`Resources` currently has only `__add__` and `__bool__`. Resource deduction is expressed as `p.resources + Resources(wood=-cost.wood, clay=-cost.clay, ...)`, which repeats the 7 negated-field-name pattern at every cost-debit site. A typo in any of those field names silently miscounts the deduction. Two existing effect functions (`_execute_sow`, `_execute_bake`) already use this pattern, and Part 2's four new effect functions would each add another instance.

Add `__sub__` to `Resources` in `agricola/resources.py`, parallel to the existing `__add__`:

```python
def __sub__(self, other: Resources) -> Resources:
    """Return a new Resources with all fields differenced. Does not mutate either operand."""
    return Resources(
        wood  = self.wood  - other.wood,
        clay  = self.clay  - other.clay,
        reed  = self.reed  - other.reed,
        stone = self.stone - other.stone,
        food  = self.food  - other.food,
        grain = self.grain - other.grain,
        veg   = self.veg   - other.veg,
    )
```

Same return-new-not-mutate semantics as `__add__`. Negative result components are allowed (mirrors `__add__`, which can also produce negative components from negative inputs).

### Migration

Every new effect function in Parts 2–3 uses the cleaner `p.resources - cost` form. The code stubs throughout this document reflect that.

The existing codebase has one pure-subtraction call site worth migrating in the same change:

- **`_execute_sow` (`agricola/resolution.py:284`)**: `p.resources + Resources(grain=-grain, veg=-veg)` → `p.resources - Resources(grain=grain, veg=veg)`.

Two existing mixed-subtract-and-add sites (`_execute_bake` at `resolution.py:354` and `potter_ceramics._apply` at `potter_ceramics.py:57`) are left alone — `__sub__` would split them into two operands without meaningful clarity gain. The convention going forward: use `__sub__` for pure subtraction; keep mixed cases in the single-`Resources` form with negative components.

### Tests

Add `__sub__` tests to `tests/test_state.py` parallel to the existing `__add__` tests: a basic field-by-field check, subtraction with empty operand (left and right), subtraction yielding negative components, and a check that `a - b + b == a` for arbitrary `a` and `b`.


---

# Part 2 — Shared sub-action pending machinery

Pendings introduced by this task fall into two categories:

- **Sub-action pendings** host a single `CommitX` action — they are pushed by a `ChooseSubAction` at a parent pending, and popped when that commit fires. `PendingPlow`, `PendingBuildStable`, `PendingBuildMajor`, `PendingRenovate` (this part), plus pre-existing `PendingSow` and `PendingBakeBread`.
- **Parent pendings** host `ChooseSubAction` and (after a flag flips) `Stop` legality. They include top-level pendings pushed by `PlaceWorker` (`PendingFarmland`, `PendingCultivation`, `PendingSideJob`, `PendingSheepMarket` / `PendingPigMarket` / `PendingCattleMarket`, `PendingMajorMinorImprovement`, `PendingHouseRedevelopment` — all in Part 3) and the two non-top-level oven wrappers pushed by the special-case `CommitBuildMajor` handler (`PendingClayOven`, `PendingStoneOven` — defined alongside Major Improvement in §3.5).

This part covers only the sub-action pendings used by multiple spaces. Each sub-action pending below comes with its dataclass, commit action class, effect function, enumerator, and dispatch table entries, bundled in one place. Spaces in Part 3 that consume them reference back here rather than duplicating the implementation.

### Union expansions

All new pending dataclasses (sub-action and parent alike) are added to `agricola/pending.py`. The **`PendingDecision`** union alias in that file expands to include every new type: `PendingPlow`, `PendingBuildStable`, `PendingBuildMajor`, `PendingRenovate` (sub-action pendings, defined in §§2.1–2.4); `PendingFarmland`, `PendingCultivation`, `PendingSideJob`, `PendingSheepMarket`, `PendingPigMarket`, `PendingCattleMarket`, `PendingMajorMinorImprovement`, `PendingClayOven`, `PendingStoneOven`, `PendingHouseRedevelopment` (parent pendings, defined in §§3.1–3.6).

The **`Action`** union in `agricola/actions.py` likewise expands to include every new commit subclass introduced by this task:

```python
Action = Union[
    PlaceWorker,
    ChooseSubAction,
    CommitSow,
    CommitBake,
    CommitPlow,             # NEW (§2.1)
    CommitBuildStable,      # NEW (§2.2)
    CommitBuildMajor,       # NEW (§2.3)
    CommitRenovate,         # NEW (§2.4)
    CommitAccommodate,      # NEW (§3.4)
    FireTrigger,
    Stop,
]
```

The `CommitSubAction` base class itself is intentionally not in the union — only concrete commit subclasses are listed so legality enumerators and type checkers see the actual options.

## 2.1 — Plow

### Pending dataclass

```python
@dataclass(frozen=True)
class PendingPlow:
    PENDING_ID: ClassVar[str] = "plow"
    TRIGGER_EVENT: ClassVar[str] = "before_plow"
    player_idx: int
    initiated_by_id: str
    triggers_resolved: frozenset = frozenset()
```

### Commit action class

```python
@dataclass(frozen=True)
class CommitPlow(CommitSubAction):
    row: int
    col: int
```

### Effect function (`agricola/resolution.py`)

```python
def _execute_plow(
    state: GameState, player_idx: int, commit: CommitPlow,
) -> GameState:
    p = state.players[player_idx]
    grid = p.farmyard.grid
    new_row = tuple(
        Cell(cell_type=CellType.FIELD) if c == commit.col else cell
        for c, cell in enumerate(grid[commit.row])
    )
    new_grid = tuple(
        new_row if r == commit.row else row
        for r, row in enumerate(grid)
    )
    new_farmyard = dataclasses.replace(p.farmyard, grid=new_grid)
    new_player = dataclasses.replace(p, farmyard=new_farmyard)
    return _update_player(state, player_idx, new_player)
```

### Enumerator (`agricola/legality.py`)

```python
def _enumerate_pending_plow(
    state: GameState, pending: PendingPlow,
) -> list[Action]:
    p = state.players[pending.player_idx]
    return [CommitPlow(row=r, col=c) for (r, c) in _legal_plow_cells(p)]
```

`_legal_plow_cells(p)` returns every `(r, c)` that is `EMPTY`, not enclosed by fences, and either the first field on the farm or orthogonally adjacent to an existing field tile. Implementation lives in `legality.py` alongside the other helpers; the same logic powers `_can_plow`.

### Dispatch additions

```python
COMMIT_SUBACTION_HANDLERS[CommitPlow] = (PendingPlow, _execute_plow)
PENDING_ENUMERATORS[PendingPlow] = _enumerate_pending_plow
```

**Consumers**: Farmland (§3.1), Cultivation (§3.2). Future plow-granting cards would push `PendingPlow` directly with `initiated_by_id="card:<card_id>"`.

## 2.2 — BuildStable

### Pending dataclass

```python
@dataclass(frozen=True)
class PendingBuildStable:
    PENDING_ID: ClassVar[str] = "build_stable"
    TRIGGER_EVENT: ClassVar[str] = "before_build_stable"
    player_idx: int
    initiated_by_id: str
    cost: Resources                              # debited when CommitBuildStable commits
    triggers_resolved: frozenset = frozenset()
```

`cost` is a `Resources` object describing what the player pays — `Resources(wood=1)` for Side Job, `Resources(wood=2)` for the eventual Farm Expansion path. Card-pushed builds carry whatever cost the card specifies.

### Commit action class

```python
@dataclass(frozen=True)
class CommitBuildStable(CommitSubAction):
    row: int
    col: int
```

### Effect function

```python
def _execute_build_stable(
    state: GameState, player_idx: int, commit: CommitBuildStable,
) -> GameState:
    pending = state.pending_stack[-1]
    assert isinstance(pending, PendingBuildStable)
    p = state.players[player_idx]
    # Debit the per-context cost (read off the pending frame, set at push time).
    new_resources = p.resources - pending.cost
    # Place stable at (row, col).
    grid = p.farmyard.grid
    new_row = tuple(
        Cell(cell_type=CellType.STABLE) if c == commit.col else cell
        for c, cell in enumerate(grid[commit.row])
    )
    new_grid = tuple(
        new_row if r == commit.row else row
        for r, row in enumerate(grid)
    )
    new_farmyard = dataclasses.replace(p.farmyard, grid=new_grid)
    new_player = dataclasses.replace(p, resources=new_resources, farmyard=new_farmyard)
    return _update_player(state, player_idx, new_player)
```

Reading the pending frame to recover `cost` is a new pattern. Convention: effect functions MAY read `state.pending_stack[-1]` during their run; the dispatcher guarantees the matching pending frame is still on top during effect execution. Documented in CLAUDE.md (resolution.py description).

### Enumerator

```python
def _enumerate_pending_build_stable(
    state: GameState, pending: PendingBuildStable,
) -> list[Action]:
    p = state.players[pending.player_idx]
    return [CommitBuildStable(row=r, col=c) for (r, c) in _legal_stable_cells(p)]
```

`_legal_stable_cells(p)` returns every empty cell on the farmyard (stables have no adjacency requirement). The cost-affordability check happens at the parent level — the choose handler that pushes `PendingBuildStable` is responsible for gating on cost before pushing.

### Dispatch additions

```python
COMMIT_SUBACTION_HANDLERS[CommitBuildStable] = (PendingBuildStable, _execute_build_stable)
PENDING_ENUMERATORS[PendingBuildStable] = _enumerate_pending_build_stable
```

**Consumers**: Side Job (§3.3). Future Farm Expansion and card-pushed stable builds will reuse.

## 2.3 — BuildMajor

### Pending dataclass

```python
@dataclass(frozen=True)
class PendingBuildMajor:
    PENDING_ID: ClassVar[str] = "build_major"
    TRIGGER_EVENT: ClassVar[str] = "before_build_major"
    player_idx: int
    initiated_by_id: str
    build_chosen: bool = False                   # set by the special-case handler for ovens
    triggers_resolved: frozenset = frozenset()
```

The `build_chosen` flag is set by `_execute_build_major` (see effect function below). For non-oven majors the pending is popped immediately after, so the flag is never observed externally. For Clay/Stone Oven the pending lingers below the oven wrapper while the optional free bake resolves; the enumerator uses `build_chosen` to emit only `Stop` on the return trip.

### Commit action class

```python
@dataclass(frozen=True)
class CommitBuildMajor(CommitSubAction):
    major_idx: int
    return_fireplace_idx: int | None = None
```

### Effect function

`_execute_build_major` owns the whole `CommitBuildMajor` flow — payment, ownership assignment, Well's future-resources update, `build_chosen` flag flip, and the conditional oven-wrapper push or `PendingBuildMajor` pop. It does NOT go through the generic commit dispatcher; `_apply_action` calls it directly.

This is a small stretch of the function-name prefix taxonomy: `_execute_*` traditionally means "effect-only, dispatched via `_apply_commit_subaction`." Here it also handles stack manipulation because oven-wrapper push and non-oven pop both depend on `major_idx`, which `_execute_build_major` already inspects for the effect. Splitting effect from dispatch would introduce a function-call boundary on the same dataflow without clarity gain.

```python
def _execute_build_major(
    state: GameState, player_idx: int, commit: CommitBuildMajor,
) -> GameState:
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildMajor)
    p = state.players[player_idx]
    cost = MAJOR_IMPROVEMENT_COSTS[commit.major_idx]

    # 1. Pay: either deduct cost, or return a Fireplace (Cooking Hearth only).
    if commit.return_fireplace_idx is None:
        new_player = dataclasses.replace(p, resources=p.resources - cost)
        state = _update_player(state, player_idx, new_player)
    else:
        assert commit.major_idx in COOKING_HEARTH_INDICES, (
            "return_fireplace_idx only valid for Cooking Hearth purchase"
        )
        assert commit.return_fireplace_idx in FIREPLACE_INDICES
        owners = state.board.major_improvement_owners
        assert owners[commit.return_fireplace_idx] == player_idx, (
            "must own the Fireplace being returned"
        )
        new_owners = tuple(
            None if i == commit.return_fireplace_idx else owners[i]
            for i in range(len(owners))
        )
        state = dataclasses.replace(
            state,
            board=dataclasses.replace(state.board, major_improvement_owners=new_owners),
        )

    # 2. Assign the new major to the player.
    owners = state.board.major_improvement_owners
    new_owners = tuple(
        player_idx if i == commit.major_idx else owners[i]
        for i in range(len(owners))
    )
    state = dataclasses.replace(
        state,
        board=dataclasses.replace(state.board, major_improvement_owners=new_owners),
    )

    # 3. Well's special effect: +1 food on each of the next 5 round spaces.
    if commit.major_idx == 4:  # Well
        p = state.players[player_idx]
        new_future = list(p.future_resources)
        # future_resources[r] holds goods promised for round r+1 (0-indexed).
        for r in range(state.round_number, min(state.round_number + 5, 14)):
            new_future[r] = new_future[r] + Resources(food=1)
        new_player = dataclasses.replace(p, future_resources=tuple(new_future))
        state = _update_player(state, player_idx, new_player)

    # 4. Set build_chosen=True on PendingBuildMajor (matters only if we linger for an oven).
    state = replace_top(state, dataclasses.replace(top, build_chosen=True))

    # 5. Branch on major_idx for the oven wrappers; otherwise pop.
    if commit.major_idx == 5:  # Clay Oven
        return push(state, PendingClayOven(
            player_idx=player_idx, initiated_by_id="build_major",
        ))
    if commit.major_idx == 6:  # Stone Oven
        return push(state, PendingStoneOven(
            player_idx=player_idx, initiated_by_id="build_major",
        ))

    # Non-oven: pop PendingBuildMajor immediately. PendingMajorMinorImprovement
    # already has major_chosen=True (set at ChooseSubAction time).
    return pop(state)
```

### Dispatch entry (`agricola/engine.py`)

`CommitBuildMajor` does NOT go through the generic commit dispatcher. `_apply_action` checks for it before the generic `CommitSubAction` branch and calls `_execute_build_major` directly:

```python
def _apply_action(state: GameState, action: Action) -> GameState:
    if isinstance(action, PlaceWorker):
        return _apply_place_worker(state, action)
    if isinstance(action, ChooseSubAction):
        return _apply_choose_sub_action(state, action)
    if isinstance(action, CommitBuildMajor):
        # Bypass generic dispatcher: oven majors keep PendingBuildMajor on the stack,
        # incompatible with the dispatcher's unconditional pop.
        top = state.pending_stack[-1]
        return _execute_build_major(state, top.player_idx, action)
    if isinstance(action, CommitSubAction):
        return _apply_commit_subaction(state, action)
    if isinstance(action, FireTrigger):
        return _apply_fire_trigger(state, action)
    if isinstance(action, Stop):
        return _apply_stop(state)
    raise TypeError(f"Unknown action type: {type(action).__name__}")
```

Player-idx extraction (`top.player_idx`) happens in `_apply_action` because `_execute_build_major`'s signature is `(state, player_idx, commit)` per the established `_execute_*` convention. `_execute_build_major` re-asserts that the top frame is a `PendingBuildMajor` for safety.

### Enumerator

```python
def _enumerate_pending_build_major(
    state: GameState, pending: PendingBuildMajor,
) -> list[Action]:
    # If build_chosen, we're back here after an oven flow completed; only Stop is legal.
    if pending.build_chosen:
        return [Stop()]
    owners = state.board.major_improvement_owners
    actions: list[Action] = []
    for idx in range(10):
        if owners[idx] is not None:
            continue
        # Standard payment.
        if _can_afford_major_idx(state, pending.player_idx, idx):
            actions.append(CommitBuildMajor(major_idx=idx, return_fireplace_idx=None))
        # Cooking Hearth via Fireplace return: emit one option per Fireplace owned.
        if idx in COOKING_HEARTH_INDICES:
            for fp_idx in FIREPLACE_INDICES:
                if owners[fp_idx] == pending.player_idx:
                    actions.append(CommitBuildMajor(
                        major_idx=idx, return_fireplace_idx=fp_idx,
                    ))
    return actions
```

### Dispatch additions

```python
PENDING_ENUMERATORS[PendingBuildMajor] = _enumerate_pending_build_major
# CommitBuildMajor is NOT registered in COMMIT_SUBACTION_HANDLERS; dispatch
# happens via the dedicated branch in _apply_action above.
```

### Helper added to `legality.py`

`_can_afford_major_idx(state, p_idx, idx)`: for major `idx`, returns True iff the player can afford the standard cost OR (for Cooking Hearth) owns a Fireplace to return. Used by `_enumerate_pending_build_major` and by `_can_afford_any_major_improvement` (which already exists; adapt to call the new per-idx helper).

**Consumers**: Major Improvement (§3.5) pushes `PendingBuildMajor` directly. House Redevelopment (§3.6) reaches the same flow indirectly via `PendingMajorMinorImprovement`.

## 2.4 — Renovate

### Pending dataclass

```python
@dataclass(frozen=True)
class PendingRenovate:
    PENDING_ID: ClassVar[str] = "renovate"
    TRIGGER_EVENT: ClassVar[str] = "before_renovate"
    player_idx: int
    initiated_by_id: str
    cost: Resources                              # debited when CommitRenovate commits
    triggers_resolved: frozenset = frozenset()
```

Like `PendingBuildStable.cost`, this is set by the choose handler at push time. In Family-scope, the cost is derived from the current house material and room count (`num_rooms` clay + 1 reed for WOOD→CLAY, `num_rooms` stone + 1 reed for CLAY→STONE) and computed inside `_choose_subaction_house_redevelopment`. Future cards that modify renovation cost (e.g., reduce reed cost, allow alternative payment formulas) update `cost` at push time or via a trigger between push and commit.

### Commit action class

```python
@dataclass(frozen=True)
class CommitRenovate(CommitSubAction):
    pass
```

### Effect function

```python
def _execute_renovate(
    state: GameState, player_idx: int, commit: CommitRenovate,
) -> GameState:
    pending = state.pending_stack[-1]
    assert isinstance(pending, PendingRenovate)
    p = state.players[player_idx]
    if p.house_material == HouseMaterial.WOOD:
        new_material = HouseMaterial.CLAY
    elif p.house_material == HouseMaterial.CLAY:
        new_material = HouseMaterial.STONE
    else:
        raise AssertionError("CommitRenovate illegal on stone house")
    new_player = dataclasses.replace(
        p, resources=p.resources - pending.cost, house_material=new_material,
    )
    return _update_player(state, player_idx, new_player)
```

### Enumerator

```python
def _enumerate_pending_renovate(
    state: GameState, pending: PendingRenovate,
) -> list[Action]:
    return [CommitRenovate()]
```

### Dispatch additions

```python
COMMIT_SUBACTION_HANDLERS[CommitRenovate] = (PendingRenovate, _execute_renovate)
PENDING_ENUMERATORS[PendingRenovate] = _enumerate_pending_renovate
```

**Consumers**: House Redevelopment (§3.6). Future Farm Redevelopment will reuse.

---

# Part 3 — Per-space implementations

Each section below describes the per-space machinery: the parent pending dataclass(es), the `_initiate_<space>` handler, the `_choose_subaction_<space>` handler (when the space has sub-actions to pick from), the parent enumerator, and the dispatch additions for the parent pending(s). Sub-action machinery (commit class, effect function, sub-action enumerator) lives in Part 2 and is referenced from a "Sub-action pendings used" line at the end of each section.

The one exception is §3.4 (animal markets), which bundles its commit class, effect function, and enumerator inline because the commit lands directly on the parent pending (no separate sub-action pending is pushed).

## 3.1 — Farmland

### Parent pending

```python
@dataclass(frozen=True)
class PendingFarmland:
    PENDING_ID: ClassVar[str] = "farmland"
    TRIGGER_EVENT: ClassVar[str] = "before_farmland"
    player_idx: int
    initiated_by_id: str
    plow_chosen: bool = False
    triggers_resolved: frozenset = frozenset()
```

### Handlers (`agricola/resolution.py`)

```python
def _initiate_farmland(state: GameState) -> GameState:
    ap = state.current_player
    return push(state, PendingFarmland(
        player_idx=ap, initiated_by_id="space:farmland",
    ))

def _choose_subaction_farmland(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    top = state.pending_stack[-1]
    if action.name == "plow":
        state = replace_top(state, dataclasses.replace(top, plow_chosen=True))
        return push(state, PendingPlow(
            player_idx=top.player_idx, initiated_by_id=top.PENDING_ID,
        ))
    raise ValueError(f"Unknown sub-action: {action.name!r}")
```

### Enumerator

```python
def _enumerate_pending_farmland(
    state: GameState, pending: PendingFarmland,
) -> list[Action]:
    p = state.players[pending.player_idx]
    actions: list[Action] = []
    if not pending.plow_chosen and _can_plow(p):
        actions.append(ChooseSubAction(name="plow"))
    if pending.plow_chosen:
        actions.append(Stop())
    return actions
```

### Dispatch additions

```python
NONATOMIC_HANDLERS["farmland"] = _initiate_farmland
CHOOSE_SUBACTION_HANDLERS[PendingFarmland] = _choose_subaction_farmland
PENDING_ENUMERATORS[PendingFarmland] = _enumerate_pending_farmland
```

**Sub-action pendings used**: `PendingPlow` (§2.1) — provides `CommitPlow`, `_execute_plow`, `_enumerate_pending_plow`, and its own dispatch entries.

## 3.2 — Cultivation

### Parent pending

```python
@dataclass(frozen=True)
class PendingCultivation:
    PENDING_ID: ClassVar[str] = "cultivation"
    TRIGGER_EVENT: ClassVar[str] = "before_cultivation"
    player_idx: int
    initiated_by_id: str
    plow_chosen: bool = False
    sow_chosen: bool = False
    triggers_resolved: frozenset = frozenset()
```

### Handlers

```python
def _initiate_cultivation(state: GameState) -> GameState:
    ap = state.current_player
    return push(state, PendingCultivation(
        player_idx=ap, initiated_by_id="space:cultivation",
    ))

def _choose_subaction_cultivation(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    top = state.pending_stack[-1]
    p_idx = top.player_idx
    if action.name == "plow":
        state = replace_top(state, dataclasses.replace(top, plow_chosen=True))
        return push(state, PendingPlow(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID,
        ))
    if action.name == "sow":
        state = replace_top(state, dataclasses.replace(top, sow_chosen=True))
        return push(state, PendingSow(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID,
        ))
    raise ValueError(f"Unknown sub-action: {action.name!r}")
```

### Enumerator

```python
def _enumerate_pending_cultivation(
    state: GameState, pending: PendingCultivation,
) -> list[Action]:
    p = state.players[pending.player_idx]
    actions: list[Action] = []
    if not pending.plow_chosen and _can_plow(p):
        actions.append(ChooseSubAction(name="plow"))
    if not pending.sow_chosen and _can_sow(p):
        actions.append(ChooseSubAction(name="sow"))
    if pending.plow_chosen or pending.sow_chosen:
        actions.append(Stop())
    return actions
```

Plow-first-then-sow on the new field falls out naturally: after `CommitPlow` lands a new `FIELD` cell, `_can_sow(p)` returns True (the new empty field is countable) and `ChooseSubAction("sow")` becomes legal.

### Dispatch additions

```python
NONATOMIC_HANDLERS["cultivation"] = _initiate_cultivation
CHOOSE_SUBACTION_HANDLERS[PendingCultivation] = _choose_subaction_cultivation
PENDING_ENUMERATORS[PendingCultivation] = _enumerate_pending_cultivation
```

**Sub-action pendings used**: `PendingPlow` (§2.1), `PendingSow` (existing). Both bring their own commit class, effect function, enumerator, and dispatch entries.

## 3.3 — Side Job

### Parent pending

```python
@dataclass(frozen=True)
class PendingSideJob:
    PENDING_ID: ClassVar[str] = "side_job"
    TRIGGER_EVENT: ClassVar[str] = "before_side_job"
    player_idx: int
    initiated_by_id: str
    stable_chosen: bool = False
    bake_chosen: bool = False
    triggers_resolved: frozenset = frozenset()
```

### Handlers

```python
def _initiate_side_job(state: GameState) -> GameState:
    ap = state.current_player
    return push(state, PendingSideJob(
        player_idx=ap, initiated_by_id="space:side_job",
    ))

def _choose_subaction_side_job(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    top = state.pending_stack[-1]
    p_idx = top.player_idx
    if action.name == "build_stable":
        state = replace_top(state, dataclasses.replace(top, stable_chosen=True))
        return push(state, PendingBuildStable(
            player_idx=p_idx,
            initiated_by_id=top.PENDING_ID,
            cost=Resources(wood=1),
        ))
    if action.name == "bake_bread":
        state = replace_top(state, dataclasses.replace(top, bake_chosen=True))
        return push(state, PendingBakeBread(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID,
        ))
    raise ValueError(f"Unknown sub-action: {action.name!r}")
```

### Enumerator

```python
def _enumerate_pending_side_job(
    state: GameState, pending: PendingSideJob,
) -> list[Action]:
    p = state.players[pending.player_idx]
    actions: list[Action] = []
    if not pending.stable_chosen:
        if p.resources.wood >= 1 and _has_stable_placement(p):
            actions.append(ChooseSubAction(name="build_stable"))
    if not pending.bake_chosen and _can_bake_bread(state, p):
        actions.append(ChooseSubAction(name="bake_bread"))
    if pending.stable_chosen or pending.bake_chosen:
        actions.append(Stop())
    return actions
```

The parent's enumerator gates on cost-affordability (`p.resources.wood >= 1`) and on whether any placement exists (`_has_stable_placement(p)`). The actual cell-by-cell legal placement options come from `PendingBuildStable`'s enumerator in §2.2.

### Dispatch additions

```python
NONATOMIC_HANDLERS["side_job"] = _initiate_side_job
CHOOSE_SUBACTION_HANDLERS[PendingSideJob] = _choose_subaction_side_job
PENDING_ENUMERATORS[PendingSideJob] = _enumerate_pending_side_job
```

**Sub-action pendings used**: `PendingBuildStable` (§2.2) — pushed with `cost=Resources(wood=1)`; provides `CommitBuildStable`, `_execute_build_stable`, `_enumerate_pending_build_stable`, and its own dispatch entries. `PendingBakeBread` (existing) — provides `CommitBake`, `_execute_bake` (upgraded in Change 3), `_enumerate_pending_bake_bread`.

## 3.4 — Sheep Market, Pig Market, Cattle Market

The three markets share structure. Three distinct parent pending classes (so each has its own `PENDING_ID` and `TRIGGER_EVENT`); one shared `CommitAccommodate` action class; one shared `_execute_accommodate` effect function. The COMMIT_SUBACTION_HANDLERS entry uses a tuple of pending types (`isinstance` handles tuple-of-types natively).

Unlike the other Part 3 sections, this one bundles the commit class, effect function, and enumerator inline rather than referring to Part 2. The reason: there is no separate sub-action pending here — `CommitAccommodate` lands directly on the parent pending. The commit machinery has nowhere else to live.

### Parent pendings

```python
@dataclass(frozen=True)
class PendingSheepMarket:
    PENDING_ID: ClassVar[str] = "sheep_market"
    TRIGGER_EVENT: ClassVar[str] = "before_sheep_market"
    player_idx: int
    initiated_by_id: str
    gained: int                                  # animals taken from the space, not yet on the player
    triggers_resolved: frozenset = frozenset()

@dataclass(frozen=True)
class PendingPigMarket:
    PENDING_ID: ClassVar[str] = "pig_market"
    TRIGGER_EVENT: ClassVar[str] = "before_pig_market"
    player_idx: int
    initiated_by_id: str
    gained: int
    triggers_resolved: frozenset = frozenset()

@dataclass(frozen=True)
class PendingCattleMarket:
    PENDING_ID: ClassVar[str] = "cattle_market"
    TRIGGER_EVENT: ClassVar[str] = "before_cattle_market"
    player_idx: int
    initiated_by_id: str
    gained: int
    triggers_resolved: frozenset = frozenset()
```

Note: `gained` is staged on the pending frame rather than added to the player's supply at `_initiate` time. This keeps the player's `Animals` field in a state that is always physically accommodatable (no transient "overcrowded" state). The animals only land on the player when `CommitAccommodate` commits.

### Handlers

```python
def _initiate_sheep_market(state: GameState) -> GameState:
    ap = state.current_player
    gained = state.board.action_spaces["sheep_market"].accumulated_amount
    state = _update_space(state, "sheep_market", accumulated_amount=0)
    return push(state, PendingSheepMarket(
        player_idx=ap, initiated_by_id="space:sheep_market", gained=gained,
    ))

# _initiate_pig_market and _initiate_cattle_market identical except for the
# space_id and pending type.
```

No `_choose_subaction_*` for the markets — they have no sub-action choice; `CommitAccommodate` lands directly on the parent.

### Effect function

```python
def _execute_accommodate(
    state: GameState, player_idx: int, commit: CommitAccommodate,
) -> GameState:
    pending = state.pending_stack[-1]
    assert isinstance(pending, (PendingSheepMarket, PendingPigMarket, PendingCattleMarket))
    p = state.players[player_idx]
    rates = cooking_rates(state, player_idx)

    # Compute "available" per type (player's existing + gained for this market only).
    s_avail = p.animals.sheep   + (pending.gained if isinstance(pending, PendingSheepMarket) else 0)
    b_avail = p.animals.boar    + (pending.gained if isinstance(pending, PendingPigMarket)   else 0)
    c_avail = p.animals.cattle  + (pending.gained if isinstance(pending, PendingCattleMarket) else 0)

    # Food = excess released at cooking rates.
    food = (
        (s_avail - commit.sheep)  * rates[0]
        + (b_avail - commit.boar)   * rates[1]
        + (c_avail - commit.cattle) * rates[2]
    )

    new_animals = Animals(sheep=commit.sheep, boar=commit.boar, cattle=commit.cattle)
    new_resources = p.resources + Resources(food=food)
    new_player = dataclasses.replace(p, animals=new_animals, resources=new_resources)
    return _update_player(state, player_idx, new_player)
```

### Enumerators

```python
def _enumerate_pending_sheep_market(
    state: GameState, pending: PendingSheepMarket,
) -> list[Action]:
    p = state.players[pending.player_idx]
    rates = cooking_rates(state, pending.player_idx)
    gained = Animals(sheep=pending.gained)
    frontier = pareto_frontier(p, gained, rates)
    return [CommitAccommodate(sheep=a.sheep, boar=a.boar, cattle=a.cattle)
            for (a, _food) in frontier]

# _enumerate_pending_pig_market and _enumerate_pending_cattle_market identical
# except for the pending type annotation and which Animals field gets `pending.gained`.
```

### Dispatch table additions

```python
NONATOMIC_HANDLERS["sheep_market"]  = _initiate_sheep_market
NONATOMIC_HANDLERS["pig_market"]    = _initiate_pig_market
NONATOMIC_HANDLERS["cattle_market"] = _initiate_cattle_market
COMMIT_SUBACTION_HANDLERS[CommitAccommodate] = (
    (PendingSheepMarket, PendingPigMarket, PendingCattleMarket),
    _execute_accommodate,
)
PENDING_ENUMERATORS[PendingSheepMarket]  = _enumerate_pending_sheep_market
PENDING_ENUMERATORS[PendingPigMarket]    = _enumerate_pending_pig_market
PENDING_ENUMERATORS[PendingCattleMarket] = _enumerate_pending_cattle_market
```

### New action class

```python
@dataclass(frozen=True)
class CommitAccommodate(CommitSubAction):
    sheep: int
    boar: int
    cattle: int
```

## 3.5 — Major Improvement

This is the most involved space. The optional free Bake Bread after Clay Oven / Stone Oven purchase requires a special-case handler in `engine.py` that bypasses the generic commit dispatcher and manipulates the stack manually.

The space introduces three parent pendings: one top-level pending (`PendingMajorMinorImprovement`, pushed by `PlaceWorker`) plus two non-top-level wrapper pendings (`PendingClayOven` / `PendingStoneOven`, pushed by the special-case `CommitBuildMajor` handler when an oven is built). All three offer `ChooseSubAction` and `Stop` legality in the same shape as any other parent pending.

### Top-level parent pending

```python
@dataclass(frozen=True)
class PendingMajorMinorImprovement:
    PENDING_ID: ClassVar[str] = "major_minor_improvement"
    TRIGGER_EVENT: ClassVar[str] = "before_major_minor_improvement"
    player_idx: int
    initiated_by_id: str
    major_chosen: bool = False
    minor_chosen: bool = False
    triggers_resolved: frozenset = frozenset()
```

`minor_chosen` is forward-compat — in Family scope, no minor-improvement playing path exists.

Field names `major_chosen` / `minor_chosen` are the shorter forms (vs. strict-convention `build_major_chosen` / `play_minor_chosen`); shorter forms confirmed in design discussion.

### Non-top-level parent pendings (oven wrappers)

Two parent pendings pushed by `_execute_build_major` (§2.3) when `major_idx` is 5 or 6. They host the optional free Bake Bread that comes with the oven purchase. Two distinct classes (rather than one parameterized class) so `PENDING_ID` is a static `ClassVar` and the provenance breadcrumb on a child `PendingBakeBread` carries the specific oven name.

```python
@dataclass(frozen=True)
class PendingClayOven:
    PENDING_ID: ClassVar[str] = "clay_oven"
    player_idx: int
    initiated_by_id: str
    bake_chosen: bool = False

@dataclass(frozen=True)
class PendingStoneOven:
    PENDING_ID: ClassVar[str] = "stone_oven"
    player_idx: int
    initiated_by_id: str
    bake_chosen: bool = False
```

No `TRIGGER_EVENT` on these wrappers; cards wanting to trigger on oven-purchase-bake attach to the inner `PendingBakeBread`'s existing `"before_bake_bread"` event.

### Handlers

```python
def _initiate_major_improvement(state: GameState) -> GameState:
    ap = state.current_player
    return push(state, PendingMajorMinorImprovement(
        player_idx=ap, initiated_by_id="space:major_improvement",
    ))

def _choose_subaction_major_minor_improvement(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    top = state.pending_stack[-1]
    p_idx = top.player_idx
    if action.name == "build_major":
        state = replace_top(state, dataclasses.replace(top, major_chosen=True))
        return push(state, PendingBuildMajor(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID,
        ))
    if action.name == "play_minor":
        # No path to here in Family scope; raise to flag the gap clearly.
        raise NotImplementedError("Minor improvement plays not in Family scope")
    raise ValueError(f"Unknown sub-action: {action.name!r}")

def _choose_subaction_clay_oven(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    top = state.pending_stack[-1]
    if action.name == "bake_bread":
        state = replace_top(state, dataclasses.replace(top, bake_chosen=True))
        return push(state, PendingBakeBread(
            player_idx=top.player_idx, initiated_by_id=top.PENDING_ID,
        ))
    raise ValueError(f"Unknown sub-action: {action.name!r}")

# _choose_subaction_stone_oven identical, just for PendingStoneOven.
```

### Enumerators

```python
def _enumerate_pending_major_minor_improvement(
    state: GameState, pending: PendingMajorMinorImprovement,
) -> list[Action]:
    p = state.players[pending.player_idx]
    actions: list[Action] = []
    if not pending.major_chosen and _can_afford_any_major_improvement(state, p):
        actions.append(ChooseSubAction(name="build_major"))
    # Family scope: no play_minor path.
    if pending.major_chosen or pending.minor_chosen:
        actions.append(Stop())
    return actions

def _enumerate_pending_clay_oven(
    state: GameState, pending: PendingClayOven,
) -> list[Action]:
    p = state.players[pending.player_idx]
    actions: list[Action] = [Stop()]
    if not pending.bake_chosen and _can_bake_bread(state, p):
        actions.append(ChooseSubAction(name="bake_bread"))
    return actions

# _enumerate_pending_stone_oven identical, just for PendingStoneOven.
```

### Dispatch additions

```python
NONATOMIC_HANDLERS["major_improvement"] = _initiate_major_improvement
CHOOSE_SUBACTION_HANDLERS[PendingMajorMinorImprovement] = _choose_subaction_major_minor_improvement
CHOOSE_SUBACTION_HANDLERS[PendingClayOven] = _choose_subaction_clay_oven
CHOOSE_SUBACTION_HANDLERS[PendingStoneOven] = _choose_subaction_stone_oven
PENDING_ENUMERATORS[PendingMajorMinorImprovement] = _enumerate_pending_major_minor_improvement
PENDING_ENUMERATORS[PendingClayOven] = _enumerate_pending_clay_oven
PENDING_ENUMERATORS[PendingStoneOven] = _enumerate_pending_stone_oven
```

**Sub-action pendings used**: `PendingBuildMajor` (§2.3) — provides `CommitBuildMajor`, `_execute_build_major` (which handles its own dispatch via a special-case branch in `_apply_action`), `_enumerate_pending_build_major`, the `_can_afford_major_idx` helper, and dispatch wiring. The oven wrappers above push child `PendingBakeBread` (existing) on `ChooseSubAction("bake_bread")`.

## 3.6 — House Redevelopment

Reuses `PendingMajorMinorImprovement` and `PendingBuildMajor` from §3.5 for the optional second step.

### Parent pending

```python
@dataclass(frozen=True)
class PendingHouseRedevelopment:
    PENDING_ID: ClassVar[str] = "house_redevelopment"
    TRIGGER_EVENT: ClassVar[str] = "before_house_redevelopment"
    player_idx: int
    initiated_by_id: str
    renovate_chosen: bool = False
    improvement_chosen: bool = False
    triggers_resolved: frozenset = frozenset()
```

`improvement_chosen` follows the choose-time convention: set when `ChooseSubAction("improvement")` fires. Stop-time flag-setting (would have been needed for commit-time convention) is sidestepped entirely.

Sub-action name `"improvement"` and flag `improvement_chosen` are the shorter forms (vs. strict-convention `"major_minor_improvement"` / `major_minor_improvement_chosen`); shorter forms confirmed in design discussion.

### Handlers

```python
def _initiate_house_redevelopment(state: GameState) -> GameState:
    ap = state.current_player
    return push(state, PendingHouseRedevelopment(
        player_idx=ap, initiated_by_id="space:house_redevelopment",
    ))

def _choose_subaction_house_redevelopment(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    top = state.pending_stack[-1]
    p_idx = top.player_idx
    p = state.players[p_idx]
    if action.name == "renovate":
        # Compute renovation cost at push time. The pending carries the cost
        # so future card triggers / alternate-formula choose handlers can
        # vary it without changing _execute_renovate.
        num_rooms = sum(
            1 for r in range(3) for c in range(5)
            if p.farmyard.grid[r][c].cell_type == CellType.ROOM
        )
        if p.house_material == HouseMaterial.WOOD:
            cost = Resources(clay=num_rooms, reed=1)  # 1 clay per room, 1 reed total
        else:  # CLAY (STONE is filtered out by _can_renovate at the parent enumerator)
            cost = Resources(stone=num_rooms, reed=1)
        state = replace_top(state, dataclasses.replace(top, renovate_chosen=True))
        return push(state, PendingRenovate(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID, cost=cost,
        ))
    if action.name == "improvement":
        state = replace_top(state, dataclasses.replace(top, improvement_chosen=True))
        return push(state, PendingMajorMinorImprovement(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID,
        ))
    raise ValueError(f"Unknown sub-action: {action.name!r}")
```

### Enumerator

```python
def _enumerate_pending_house_redevelopment(
    state: GameState, pending: PendingHouseRedevelopment,
) -> list[Action]:
    p = state.players[pending.player_idx]
    actions: list[Action] = []
    if not pending.renovate_chosen and _can_renovate(p):
        actions.append(ChooseSubAction(name="renovate"))
    if pending.renovate_chosen and not pending.improvement_chosen and _can_afford_any_major_improvement(state, p):
        actions.append(ChooseSubAction(name="improvement"))
    if pending.renovate_chosen:
        actions.append(Stop())
    return actions
```

`Stop` appears in two situations: after the player completes the renovate step and chooses to skip the optional improvement (renovate_chosen=True, improvement_chosen=False), and after the player completes both steps (both flags True). It is illegal before renovating — renovate is mandatory first.

### Dispatch additions

```python
NONATOMIC_HANDLERS["house_redevelopment"] = _initiate_house_redevelopment
CHOOSE_SUBACTION_HANDLERS[PendingHouseRedevelopment] = _choose_subaction_house_redevelopment
PENDING_ENUMERATORS[PendingHouseRedevelopment] = _enumerate_pending_house_redevelopment
```

**Sub-action pendings used**: `PendingRenovate` (§2.4) — provides `CommitRenovate`, `_execute_renovate`, `_enumerate_pending_renovate`, and its own dispatch entries.

**Other parent pendings pushed**: `PendingMajorMinorImprovement` (§3.5) — pushed for the optional second step with `initiated_by_id="house_redevelopment"`. It transitively uses `PendingBuildMajor` (§2.3) for the actual major build.

---

# Part 4 — Tests

Prefabricated factories continue to be the project-wide convention; tests construct states directly rather than reaching them through gameplay.

### Updated existing tests

- **`tests/test_grain_utilization.py`** and **`tests/test_potter_ceramics.py`**: rename `sow_done` / `bake_done` references to `sow_chosen` / `bake_chosen`. Adjust the "writes flag on parent" tests to verify the flag is set after `ChooseSubAction`, not after `CommitX`. Provenance prefix references (`"worker_placement"`) become `"space:grain_utilization"`.

### New test files

#### `tests/test_bake_bread.py`

Lands with Change 3 (Part 1). One parametrized test function covers both `_execute_bake` (food allocation) and `_enumerate_pending_bake_bread` (per-action grain cap) across a matrix of `(owned_majors, grain_in_supply)` cases. Single test, many cases — keeps setup centralized and failure diagnostics legible via parametrize IDs.

The case table is a list of `(owned: tuple[int, ...], grain: int, expected_food_by_amount: dict[int, int])`. Each entry's `expected_food_by_amount` maps `n` (grain to bake) to the food that should be produced. Cases that are illegal to bake (grain not in the dict) are implicitly absent from `_enumerate_pending_bake_bread`'s output.

Cases to include (this list is intentionally exhaustive across the relevant interaction surface — the parametrize table is the test spec):

| Owned majors (indices) | Grain | Legal `n` → expected food |
|---|---|---|
| `(0,)` Fireplace | 3 | 1→2, 2→4, 3→6 |
| `(2,)` Hearth | 3 | 1→3, 2→6, 3→9 |
| `(5,)` Clay Oven | 3 | 1→5 (cap=1) |
| `(6,)` Stone Oven | 3 | 1→4, 2→8 (cap=2) |
| `(0, 5)` Fireplace + Clay Oven | 3 | 1→5, 2→7, 3→9 |
| `(0, 6)` Fireplace + Stone Oven | 3 | 1→4, 2→8, 3→10 |
| `(2, 6)` Hearth + Stone Oven | 5 | 1→4, 2→8, 3→11, 4→14, 5→17 |
| `(5, 6)` Clay + Stone Oven | 5 | 1→5, 2→9, 3→13 (cap-sum=3; grain in supply exceeds cap) |
| `(0, 2, 5, 6)` all four | 4 | 1→5, 2→9, 3→13, 4→16 |
| `(2, 5)` Hearth + Clay Oven | 3 | 1→5, 2→8, 3→11 |
| `(5, 6)` Clay + Stone Oven | 2 | 1→5, 2→9 (grain less than cap-sum) |
| `(6,)` Stone Oven | 0 | (no legal options) |
| `(0,)` Fireplace | 0 | (no legal options) |

The test body, schematically:

```python
@pytest.mark.parametrize("owned, grain, expected", BAKE_BREAD_CASES)
def test_bake_bread_algorithm(owned, grain, expected):
    # Construct a state where player 0 owns the given majors and has `grain`
    # grain in supply. Push a PendingBakeBread frame so the enumerator runs.
    state = base_state_for_bake_test(owned_majors=owned, grain=grain)
    state = push(state, PendingBakeBread(
        player_idx=0, initiated_by_id="space:grain_utilization",
    ))

    # 1. Enumerator returns the expected set of CommitBake amounts.
    p = state.players[0]
    legal = _enumerate_pending_bake_bread(state, p)
    legal_amounts = sorted(a.grain for a in legal if isinstance(a, CommitBake))
    assert legal_amounts == sorted(expected.keys()), (
        f"owned={owned}, grain={grain}: legal amounts mismatch"
    )

    # 2. For each legal amount, _execute_bake produces the expected food and
    #    debits the expected grain.
    for n, expected_food in expected.items():
        new_state = _execute_bake(state, 0, CommitBake(grain=n))
        delta_food  = new_state.players[0].resources.food  - p.resources.food
        delta_grain = new_state.players[0].resources.grain - p.resources.grain
        assert delta_food  == expected_food, (
            f"owned={owned}, grain={grain}, bake={n}: food mismatch"
        )
        assert delta_grain == -n, (
            f"owned={owned}, grain={grain}, bake={n}: grain debit mismatch"
        )
```

A small `base_state_for_bake_test(owned_majors, grain)` factory helper (in `tests/factories.py` or local to this test file) composes existing `with_majors` / `with_resources` factories.

The `BAKING_SPEC_EXTENSIONS` registry is exercised separately by a one-off test that registers a synthetic extension (e.g., `(1, 6)` to mimic Iron Oven), confirms `baking_specs_for_player` includes it, confirms `_enumerate_pending_bake_bread`'s cap reflects it, and confirms `_execute_bake`'s greedy allocation places the synthetic source correctly (rate 6 → fires before Clay Oven if both owned). The extension is removed in a fixture teardown so the registry stays clean across the suite.

#### `tests/test_farmland.py`

- Basic walk: `PlaceWorker(farmland)` → `ChooseSubAction("plow")` → `CommitPlow(r, c)` → `Stop`.
- Stop legality: illegal before plow_chosen; legal after.
- Cell-choice enumeration: `CommitPlow` options exclude non-empty cells, enclosed cells, and (after the first field exists) non-adjacent cells.
- Placement illegality: `PlaceWorker(farmland)` illegal when the player has no legal plow cells.
- Choose-time flag invariant: `ChooseSubAction("plow")` sets `plow_chosen=True` on the parent; `CommitPlow` does not modify the parent.

#### `tests/test_cultivation.py`

- Basic walks: plow-only, sow-only, plow-then-sow on newly plowed field, sow-then-plow.
- Plow-enables-sow: after `CommitPlow` at an empty field, `ChooseSubAction("sow")` becomes legal even if no fields existed before.
- Stop legality: requires at least one of plow_chosen or sow_chosen.
- Same flag-invariant checks as Farmland.

#### `tests/test_side_job.py`

- Basic walks: stable-only, bake-only, both.
- 1-wood debit: building a stable costs exactly 1 wood (from the `cost` field on the pending).
- `PendingBuildStable.cost` value: `Resources(wood=1)` after pushing from Side Job's choose handler.
- Bake on Side Job: integrates with Potter Ceramics' trigger machinery.
- Stop legality requires at least one of stable_chosen or bake_chosen.

#### `tests/test_animal_markets.py`

Bundles sheep, pig, cattle markets in one file (structurally identical).

- Basic walks per market: `PlaceWorker(<market>)` → `CommitAccommodate(s, b, c)` (no Stop; commit pops the parent directly).
- Frontier enumeration: legal `CommitAccommodate` actions match `pareto_frontier` output exactly.
- Animals staged on the pending: `pending.gained == accumulated_amount` at the time of placement; the space's `accumulated_amount` is zeroed; the player's `animals` field is not changed until commit.
- Food conversion: post-commit `resources.food` increases by the excess-times-rates formula at the player's `cooking_rates`.
- No cooking improvement → food gained is 0 regardless of excess.
- Pareto-optimal-only: dominated configurations (e.g., `(0, 0, 0)` when `(1, 0, 0)` is feasible) are NOT in the enumeration. Document the optionality-preservation rationale in `pareto_frontier`'s docstring.

#### `tests/test_major_improvement.py`

- Build each of the 10 majors individually: cost paid correctly, ownership updated, parent flag set, stack cleared.
- Cooking Hearth via clay payment: cost is 4 (idx 2) or 5 (idx 3) clay.
- Cooking Hearth via Fireplace return (idx 0 or idx 1): no clay spent; returned Fireplace's owner reverts to `None`.
- Cooking Hearth: when player owns both Fireplaces, both `return_fireplace_idx=0` and `return_fireplace_idx=1` appear in the legal actions.
- Well: future_resources gets `+1 food` written into rounds `r+1 .. r+5` (clipped at the 14-round bound).
- Clay Oven purchase + free bake (with grain): full chain `PlaceWorker` → `ChooseSubAction("build_major")` → `CommitBuildMajor(major_idx=5)` → `ChooseSubAction("bake_bread")` → `CommitBake(grain=1)` → `Stop` (PendingClayOven) → `Stop` (PendingBuildMajor) → `Stop` (PendingMajorMinorImprovement). Final state: 1 grain converted to 5 food.
- Clay Oven purchase + skip bake: chain ends after `Stop` on `PendingClayOven`. No food added.
- Clay Oven purchase + bake with 0 grain + Potter Ceramics + 1 clay: `_can_bake_bread` returns True via extension; `FireTrigger` swaps clay for grain; `CommitBake(grain=1)` then runs.
- Stone Oven purchase + bake with 2 grain: full-chain integration test landing through `_execute_bake` and producing 8 food.

Unit-level coverage of `_execute_bake` and `_enumerate_pending_bake_bread` across the matrix of owned majors × grain counts lives in `tests/test_bake_bread.py` (below). The Major Improvement test file only contains integration tests that exercise the full purchase-then-bake chain.

#### `tests/test_house_redevelopment.py`

- Basic walks: renovate-only, renovate-then-improvement (build a major), renovate-then-improvement (free bake after oven).
- Improvement step requires renovate_chosen first.
- Stop legality: illegal before renovate_chosen; legal after (regardless of whether improvement is taken).
- Material progression: WOOD→CLAY→STONE. STONE house cannot renovate (`_can_renovate` returns False).
- Renovation cost on pending: `PendingRenovate.cost == Resources(clay=num_rooms, reed=1)` for WOOD→CLAY; `Resources(stone=num_rooms, reed=1)` for CLAY→STONE (reed cost is 1 total, not per-room). Computed by `_choose_subaction_house_redevelopment` and stored on the pending; `_execute_renovate` debits via `p.resources - pending.cost`.
- Inner `PendingMajorMinorImprovement.initiated_by_id` is `"house_redevelopment"` (not `"space:major_improvement"`) — verifies provenance.

### `tests/test_utils.py`

`IMPLEMENTED_NON_ATOMIC_SPACES` (currently just `{"grain_utilization"}`) expands to include all eight new spaces. `filter_implemented(actions)` then permits agents to use them.

### `tests/factories.py`

No new helpers needed. Audit of the existing file confirms all required factories are present:

- `with_majors(state, *, owner_by_idx: dict)` — sets `major_improvement_owners`. Call as `with_majors(s, owner_by_idx={0: 0})` to give player 0 the Fireplace at idx 0.
- `with_animals(state, player_idx, **animal_kwargs)` — replaces animals.
- `with_house(state, player_idx, material: HouseMaterial)` — sets house material. (Note the name is `with_house`, not `with_house_material`; same semantics.)
- `with_resources`, `add_resources`, `with_minors`, `with_grid`, `with_fields`, `with_sown_fields`, `with_space`, `with_pending_stack`, `with_phase`, `with_round`, `with_current_player`, `with_people` — all exist and cover the per-space test needs.

If a per-space test file finds itself wanting a one-off helper not yet in factories, add it locally to the test file rather than extending `factories.py` for a single consumer.

---

# Part 5 — Documentation updates

## CLAUDE.md edits

Organized by section. All edits describe the architecture as it is *after* this task lands. Outdated conventions are not mentioned in CLAUDE.md — those live in CHANGES.md.

### `Engine and Turn Resolution Architecture` → `The pending-decision stack`

- **`Pending provenance metadata`**: rewrite the three-row `initiated_by_id` table to use the `"space:<space_id>"` and `"card:<card_id>"` forms. Drop the `"worker_placement"` reserved-string sentence. Add a sentence noting that the prefix scheme makes the two namespaces disjoint without a separate reserved-string carve-out.
- **The `commit dispatcher` paragraph** ("After popping the sub-action's frame, it compares the popped frame's `initiated_by_id` to the new top frame's `PENDING_ID`..."): remove entirely. Replace with: "The commit dispatcher asserts, applies the effect, and pops. The parent's `<action>_chosen` flag is set earlier, by the `_choose_subaction_*` handler that pushed the sub-action pending."
- **`Lifecycle of a non-atomic turn`** bullet: change `CommitX(...) pops the category pending and writes <x>_done=True on the parent` to `ChooseSubAction("X") pushes the category pending and writes <X>_chosen=True on the parent; CommitX(...) pops the category pending`. Rename other `_done` references in this section to `_chosen`.

### `Eight design philosophies`

- The `Commit sub-actions inherit from CommitSubAction` bullet stays valid as-is; the metadata table content changes from 3-tuples to 2-tuples but the bullet's wording doesn't need editing.
- Add a new bullet describing the invariant: **`PlaceWorker` and each `ChooseSubAction` push exactly one pending frame. This ensures card triggers fire cleanly between frames.**
- Add a new bullet documenting choose-time flag-setting as the convention.

### `The architecture is built with cards in mind`

- The `Pending provenance via initiated_by_id + PENDING_ID, used by the generic commit dispatcher...` bullet: rewrite. Provenance is used for debugging and for cards to choose, at push time, which parent (if any) to flag. The commit dispatcher does not touch parent state.

### `Card implementation status`

- **Remove the `Card-specific pending classes: PENDING_ID vs initiated_by_id redundancy`** deferred-question paragraph. The redundancy is resolved by the `"card:<card_id>"` prefix.
- The other two deferred questions (compound card interactions; atomic-space trigger hosting) remain.

### `Documentation Files` table

The table currently has an erroneous individual row for `TASK_5B_DISPATCH_CLEANUP.md` that violates the project's convention of one catch-all `TASK_*.md` row covering every individual task file. **Remove the `TASK_5B_DISPATCH_CLEANUP.md` row**; the `TASK_*.md` row already covers it (and covers TASK_5C.md, with no individual row needed).

### `Current Status` table

The table currently does not list TASK_5B_DISPATCH_CLEANUP's contributions and (obviously) does not list TASK_5C's. Update with rows for both.

**New rows reflecting TASK_5B_DISPATCH_CLEANUP** (already implemented; previously not in the table):

| Component | Status | Task file(s) |
|---|---|---|
| `CommitSubAction` hierarchy + generic commit dispatch | Complete | `TASK_5B_DISPATCH_CLEANUP.md`, `CHANGES.md` |
| Pending provenance metadata (`initiated_by_id`, `PENDING_ID`) | Complete | `TASK_5B_DISPATCH_CLEANUP.md`, `CHANGES.md` |
| Dispatch table relocation (`NONATOMIC_HANDLERS` / `CHOOSE_SUBACTION_HANDLERS` in `resolution.py`; stack helpers in `pending.py`) | Complete | `TASK_5B_DISPATCH_CLEANUP.md` |

**New rows reflecting TASK_5C**:

| Component | Status | Task file(s) |
|---|---|---|
| Farmland non-atomic resolution | Complete | `TASK_5C.md` |
| Cultivation non-atomic resolution | Complete | `TASK_5C.md` |
| Side Job non-atomic resolution | Complete | `TASK_5C.md` |
| Sheep / Pig / Cattle Market non-atomic resolution | Complete | `TASK_5C.md` |
| Major Improvement non-atomic resolution (incl. Cooking Hearth payment options, Clay/Stone Oven free Bake) | Complete | `TASK_5C.md` |
| House Redevelopment non-atomic resolution | Complete | `TASK_5C.md` |
| Choose-time flag-setting convention (`*_chosen` fields) | Complete | `TASK_5C.md`, `CHANGES.md` |
| Provenance prefix scheme (`"space:<id>"` / `"card:<id>"`) | Complete | `TASK_5C.md`, `CHANGES.md` |
| Major improvement costs and baking specs in `constants.py` | Complete | `TASK_5C.md` |
| Bake Bread support for Clay Oven and Stone Oven (greedy-by-rate over all owned baking improvements) | Complete | `TASK_5C.md` |

**`Not yet implemented` paragraph rewrite**:

After this task, remove the eight implemented spaces from the "Not yet implemented" paragraph. The remaining items become:

- Non-atomic resolution for the three remaining spaces: **Farm Expansion**, **Farm Redevelopment**, and **Fencing** (selecting them via `PlaceWorker(...)` still raises `NotImplementedError`).
- `fencing` legality (still missing entirely).
- Harvest phases (HARVEST_FIELD / HARVEST_FEED / HARVEST_BREED).
- Rounds 5–14 (engine halts in `Phase.BEFORE_SCORING` after round 4's RETURN_HOME).
- Cards other than Potter Ceramics, and the action-space paths that would let players play minor improvements or occupations (`lessons` remains permanently illegal in the Family game; the optional minor / improvement paths at Basic Wish for Children, House Redevelopment, Major Improvement, and Farm Redevelopment depend on minor-card support arriving).

### Per-file descriptions

- **`agricola/resources.py`**: note that `Resources` gains `__sub__` alongside the existing `__add__` and `__bool__`. Same return-new-not-mutate semantics.
- **`agricola/constants.py`**: add lines for `MAJOR_IMPROVEMENT_COSTS`, `BAKING_IMPROVEMENT_SPECS`, `FIREPLACE_INDICES`, `COOKING_HEARTH_INDICES`. Note `BAKING_IMPROVEMENTS` migrated here from `legality.py`.
- **`agricola/pending.py`**: full table of pending classes (existing + new). Document the `cost: Resources` field on both `PendingBuildStable` and `PendingRenovate` (set at push time by the choose handler; debited at commit time by the effect function), and the staging-via-`gained` pattern on the three animal-market pendings.
- **`agricola/actions.py`**: enumerate the new `CommitSubAction` subclasses (`CommitPlow`, `CommitBuildStable`, `CommitAccommodate`, `CommitBuildMajor`, `CommitRenovate`).
- **`agricola/legality.py`**: list the new per-pending enumerators and the new shared helpers (`_legal_plow_cells`, `_legal_stable_cells`, `_can_afford_major_idx`, `baking_specs_for_player`). Add the `BAKING_SPEC_EXTENSIONS` registry and `register_baking_spec_extension` helper alongside the existing `BAKE_BREAD_ELIGIBILITY_EXTENSIONS` block. `BAKING_IMPROVEMENTS` reference moved to `constants.py`.
- **`agricola/resolution.py`**: list the new `_initiate_*`, `_choose_subaction_*`, and `_execute_*` functions. Updated description for `_execute_bake` (greedy-by-rate over all owned baking improvements). New convention note: effect functions MAY read `state.pending_stack[-1]`; the dispatcher guarantees the pending frame is still on top during effect execution. Updated dispatch tables.
- **`agricola/engine.py`**: rewrite `_apply_commit_subaction` description (asserts + effect + pop, no parent flag). Note the special-case `CommitBuildMajor` branch in `_apply_action` that bypasses the generic dispatcher and calls `_execute_build_major` directly. Updated `COMMIT_SUBACTION_HANDLERS` description (2-tuples; no `parent_flag`). Remove the obsolete `Caveat` block.

### tests/ section

Add per-file descriptions for the six new test files (`tests/test_farmland.py`, `tests/test_cultivation.py`, `tests/test_side_job.py`, `tests/test_animal_markets.py`, `tests/test_major_improvement.py`, `tests/test_house_redevelopment.py`). Update descriptions for `tests/test_grain_utilization.py` and `tests/test_potter_ceramics.py` to reflect the `*_chosen` field renames and the new "writes flag on parent at ChooseSubAction time" assertions.

### New "Code Conventions" section (after "Additional Design Principles")

Add a new top-level section to CLAUDE.md, between "Additional Design Principles" and "Engine and Turn Resolution Architecture." Content as follows:

---

## Code Conventions

Syntactic and style patterns followed across the codebase. Architectural conventions — frozen-dataclass rules, the player-parameter convention, function-name prefix taxonomy, pending provenance metadata — live in "Key Design Principles" and "Additional Design Principles" above. This section covers smaller-grained patterns about how code is *written*.

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

`ClassVar` declarations are class-level identifiers/tags, not `__init__` parameters; they belong with class metadata, not with per-instance state.

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

The commit dispatcher (`_apply_commit_subaction`) does NOT set the flag; its sole job is assert, effect, pop. The choose-time setting keeps flag management adjacent to the push that creates the sub-action, making each parent's chosen-tracking visible in one function.

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

(end of new Code Conventions section content)

### New "Sub-action cost handling" subsection (added to existing "Additional Design Principles")

Add this as a third subsection to CLAUDE.md's existing "Additional Design Principles" section, alongside the existing "Player parameter convention" and "Function-name prefix taxonomy". Content as follows:

---

### Sub-action cost handling

Sub-actions that debit resources fall into three buckets based on where the cost lives. When adding a new sub-action pending that debits resources, choose the bucket that fits — pick bucket 2 by default; reach for bucket 3 only when the cost is genuinely a function of a commit-time parameter.

1. **No cost.** The sub-action doesn't debit resources (e.g., `PendingPlow`). No `cost` field. Effect function applies its non-resource effect and returns.

2. **Caller-parameterizable cost — field on the pending.** The cost varies by who pushed the sub-action: different spaces specify different costs, and cards may inject alternate costs or formula choices. The choose handler (or trigger / `_initiate_*` / card effect that pushes the pending) computes the cost at push time and stores it on the pending as `cost: Resources`. The effect function reads `pending.cost` and debits via `p.resources - pending.cost`. Cards that modify cost can update `pending.cost` either at push time (by computing differently) or via a trigger between push and commit (by `replace_top`-ing the pending). `PendingBuildStable` and `PendingRenovate` are the current examples; `PendingBuildRoom` and `PendingBuildFences` will follow the same pattern when introduced.

3. **Commit-time-parameterizable cost — keyed lookup at execute time.** The cost varies by a parameter on the commit action itself, chosen at commit time rather than push time. No `cost` field on the pending — the effect function looks up the cost from the commit's parameters against a const table. `PendingBuildMajor` is the canonical example: cost depends on `commit.major_idx`, looked up in `MAJOR_IMPROVEMENT_COSTS`. This pattern fits when the commit-time parameter space is small and pre-defined.

Bucket 2 is the most flexible for card extensions because the cost can be set or modified anywhere along the push → commit path. Bucket 3 trades flexibility for a single source of truth (the const table) and is appropriate when the cost variations *are* the action's identity (each major improvement is fundamentally a distinct item with a distinct cost).

---

## CHANGES.md new entry

A new Change entry, **Change 4 — Choose-time flag-setting, provenance prefix scheme, and Bake Bread expansion**. Documents:

- The shift from commit-time to choose-time parent-flag setting in non-atomic resolution.
- The `*_done` → `*_chosen` field rename on existing pendings (`PendingGrainUtilization.sow_done` / `bake_done`).
- The `initiated_by_id` prefix scheme: top-level pendings `"space:<space_id>"`, card-pushed `"card:<card_id>"`.
- `BAKING_IMPROVEMENTS` migrating from `legality.py` to `constants.py`.
- `_execute_bake` expansion to handle all baking improvements via greedy-by-rate.
- New `BAKING_SPEC_EXTENSIONS` registry and `baking_specs_for_player` helper (in `legality.py`) so future card-driven baking sources (e.g., Iron Oven minor improvement) drop in via a single `register_baking_spec_extension(fn)` call without edits to `_execute_bake` or `_enumerate_pending_bake_bread`.
- `Resources.__sub__` added (parallel to existing `__add__`), eliminating the 7-field-negated-component pattern at pure-subtraction sites. Migration: `_execute_sow` in the existing codebase, plus the new pure-subtraction effect functions in Part 2 (`_execute_build_stable`, `_execute_build_major`'s standard payment path, `_execute_renovate`). Mixed subtract-and-add sites (`_execute_bake`, `potter_ceramics._apply`) stay in the single-`Resources` form.

---

# Part 6 — Order of work

Suggested implementation order, each step accompanied by tests:

1. **Part 1 changes**:
   1. Convention shift (choose-time flag-setting + `*_done` → `*_chosen`). All 236 existing tests should pass after this with field-name updates only. CHANGES.md entry started.
   2. Provenance prefix refactor. Tests updated to reference new strings.
   3. Constants additions + `_execute_bake` upgrade + `baking_specs_for_player` / `BAKING_SPEC_EXTENSIONS` registry. Tests: `tests/test_bake_bread.py` (parametrized over the matrix in Part 4) plus a separate test exercising the extension registry with a synthetic spec.
   4. `Resources.__sub__` addition + swap the negative-component pattern for `__sub__` at `_execute_sow` (the one pure-subtraction site in existing code — a one-line change inside the function; the function stays in `resolution.py`). `_execute_bake` and `potter_ceramics._apply` are left untouched (mixed subtract-and-add sites stay in single-`Resources` form per the convention). Tests: `__sub__` cases added to `tests/test_state.py`.
2. **Part 2 — shared sub-action pending machinery**. Dataclasses, commit classes, effect functions, enumerators, and dispatch entries — all four sub-action pendings (Plow, BuildStable, BuildMajor, Renovate). Compiles after Part 1 lands; tested via the per-space tests in Part 3.
3. **Part 3 spaces** in order:
   1. **Farmland**. Smallest space; validates `PendingPlow` machinery. Tests: `tests/test_farmland.py`.
   2. **Cultivation**. Reuses `PendingPlow` + `PendingSow`. Tests: `tests/test_cultivation.py`.
   3. **Side Job**. Reuses `PendingBuildStable` + `PendingBakeBread`. Tests: `tests/test_side_job.py`.
   4. **Animal markets** (sheep, pig, cattle in one go). Validates the "commit pops parent directly" pattern and the COMMIT_SUBACTION_HANDLERS tuple-of-types entry. Tests: `tests/test_animal_markets.py`.
   5. **Major Improvement**. Most involved; introduces the special-case `CommitBuildMajor` branch in `_apply_action` and the oven wrappers. Tests: `tests/test_major_improvement.py`.
   6. **House Redevelopment**. Reuses `PendingMajorMinorImprovement` + `PendingBuildMajor`. Tests: `tests/test_house_redevelopment.py`.
4. **Part 5 — documentation pass**. CLAUDE.md + CHANGES.md updates land in one commit at the end. (Per the project's documentation convention, the per-space test files added in Part 4 also get one-line entries in CLAUDE.md's `tests/` per-file descriptions during this pass.)

After step 3.6, all 236 existing tests plus the new test suites should pass. The 8 spaces should be usable end-to-end through `step()` without `NotImplementedError`.

---

# Part 7 — Acceptance criteria

- All 236 pre-existing tests pass.
- New per-space test suites pass.
- `random_agent_play` (`tests/test_utils.py`) plays a full 4-round game without raising when the agent picks any of the 8 new spaces. Tested over multiple seeds to ensure each new space is exercised at least once across the seed sweep.
- `step()` raises `NotImplementedError` only for `PlaceWorker` on `"farm_expansion"`, `"farm_redevelopment"`, or `"fencing"`.
- CLAUDE.md reflects the architecture as it is after this task.
- CHANGES.md has a new entry documenting the convention shifts and the `_execute_bake` expansion.

---

# Appendix A — Out of scope (deferred)

- **Farm Expansion**, **Farm Redevelopment**, **Fencing**. Of the four sub-action pendings defined in Part 2, only two see future reuse by these spaces: Farm Expansion would reuse `PendingBuildStable` (for the 2-wood stable build) and would also need new infrastructure for room builds; Farm Redevelopment would reuse `PendingRenovate` and would also need new infrastructure for fence builds. Fencing needs its own fence-build sub-action pending. `PendingBuildMajor` and `PendingPlow` see no reuse from the deferred spaces (they're consumed only by Major Improvement / House Redevelopment and Farmland / Cultivation respectively, all implemented in this task).

  Note: the new `PendingBuildRoom` (whenever Farm Expansion / House Redevelopment / Farm Redevelopment introduce it) and the new `PendingBuildFences` (Fencing / Farm Redevelopment) should both carry a `cost: Resources` field, matching the cost-on-pending convention established by `PendingBuildStable` and `PendingRenovate`. Cards that modify room or fence costs would then update the pending's `cost` at push time or via a trigger between push and commit.
- **Harvest phases** (HARVEST_FIELD, HARVEST_FEED, HARVEST_BREED) and rounds 5–14.
- **Occupation and minor improvement cards** beyond Potter Ceramics.
- **`"after_<event>"` trigger events** on the new pendings. The plan only adds `"before_<event>"` events; `"after"` events arrive when a card needs one.
- **`can_accommodate` optimization** (`range(3)` instead of `range(4)`) and the user's further optimization thoughts — end-of-session cleanup list.
- **`pareto_frontier` docstring expansion** documenting the optionality-preservation argument — bundled into the Part 3.4 (animal markets) implementation step.
