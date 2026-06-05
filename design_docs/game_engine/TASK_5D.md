# Task 5D — Farm Expansion + Multi-Shot Sub-Action Pendings

A continuation of Tasks 5, 5B, and 5C. The document is split into:

- **Part 1 — Preliminary refactors.** Five behavior-preserving cleanups that touch existing code: (1) introduce the `auto_pop` flag on the commit dispatcher table, (2) absorb `CommitBuildMajor` into the generic dispatch path, (3) extract `ROOM_COSTS` to `constants.py`, add `_can_afford(p, cost)`, simplify `_can_afford_room`, (4) deduplicate predicate-shadows-enumerator helpers and introduce `_can_build_stable(p, cost)`, (5) extract `_new_grid_with_cell` helper and migrate `_execute_plow` to use it. The `CommitBuildMajor` special-case branch in `_apply_action` is deleted; `_has_stable_placement` is deleted; `_can_plow` and `_has_room_placement` collapse to one-liners over their cell enumerators.
- **Part 2 — Multi-shot sub-action pending machinery.** Two new pending types — `PendingBuildStables` and `PendingBuildRooms` — that host multi-commit-then-Stop sub-actions. Each has `cost`, `max_builds`, and `num_built` fields.
- **Part 3 — Farm Expansion.** The parent pending, choose handler, enumerators, and legality predicate.
- **Part 4 — Side Job migration + `PendingBuildStable` retirement.** Side Job moves from `PendingBuildStable` (singular, auto-pop) to `PendingBuildStables` (plural, cap=1). The singular class and its handlers are deleted.
- **Part 5 — Tests.** New test file plus updates to `test_side_job.py` and `test_major_improvement.py`.
- **Part 6 — Documentation updates.** CLAUDE.md edits, CHANGES.md entry.
- **Part 7 — Order of work.**
- **Part 8 — Acceptance criteria.**

After this task, `step()` raises `NotImplementedError` only for `PlaceWorker(space="farm_redevelopment")` and `PlaceWorker(space="fencing")`.

---

## Scope

| Space | Sub-actions | Status |
|---|---|---|
| Farm Expansion | build_rooms and/or build_stables | new |
| Side Job | build_stable and/or bake_bread | migrated to plural-stable pending |

Cross-cutting machinery introduced or modified:

- `auto_pop: bool` field on `COMMIT_SUBACTION_HANDLERS` table entries.
- `_execute_build_major` absorbed into the generic dispatch path (`auto_pop=False`; effect function owns stack management for the non-oven pop and the oven-wrapper push).
- New `PendingBuildStables` (plural, multi-shot), with `cost`, `max_builds`, `num_built`.
- New `PendingBuildRooms` (plural, multi-shot), same shape.
- New `CommitBuildRoom(row, col)` action class.
- Retirement of `PendingBuildStable` (singular).

---

## Motivation

Farm Expansion is one of three remaining non-atomic spaces (with Farm Redevelopment and Fencing) that still raise `NotImplementedError`. It is also the first space whose sub-actions are inherently **multi-shot within a single category** — a player chooses "build_stables" once and then commits multiple stables before transitioning out of that category, similar for rooms.

Two ways to express multi-shot were considered (see conversation log):

1. **Atomic fat commit**: a single `CommitBuildStables(cells: frozenset[(int,int)])` carrying the full set of cells. Legality enumerates all subsets — up to ~C(13,4) ≈ 715 for stables, and a more complex tree for rooms (where within-action adjacency chains).
2. **One-at-a-time with nested plural pending** (chosen): `PendingBuildStables` lives on the stack throughout the multi-build session; each `CommitBuildStable(r, c)` applies one stable and leaves the pending on top; `Stop` is the explicit exit.

The chosen approach keeps per-step legality bounded by farm cells (~13) + Stop and is far better-shaped for the future NN policy head than a one-shot decision with 715 options.

A second design decision was where the **pop** of the multi-shot pending happens. Two options:

- **Approach 1**: effect function auto-pops when `num_built == max_builds`.
- **Approach 2** (chosen): effect function never pops; `Stop` is always the explicit exit. The `max_builds`-reached state surfaces as "only `Stop` is legal."

Approach 2 wins on consistency — the affordability/empty-cell case already requires a singleton-`Stop` state somewhere (player runs out of wood mid-action, no cap involved), so special-casing the cap-reached state to auto-pop introduces a divergence with no upside. It also aligns with the engine's "`step` does not auto-resolve singleton player decisions" principle and keeps effect functions pure-effect.

A side effect of Approach 2 is that Side Job's trace grows by one step: `CommitBuildStable(...)` then `Stop()`, instead of one self-popping commit. The unification gain (one pending type, one set of handlers, one enumerator) is worth the small trace-shape change.

---

# Part 1 — Preliminary refactors

## Change 1 — `auto_pop` flag on `COMMIT_SUBACTION_HANDLERS`

### Convention shift

Today, every entry in `COMMIT_SUBACTION_HANDLERS` is a 2-tuple `(expected_pending_type, effect_fn)`, and the generic dispatcher (`_apply_commit_subaction` in `engine.py`) unconditionally pops the sub-action pending after applying the effect. This blocks the multi-shot pattern, where the pending must remain on top across multiple commits.

Under the new convention each entry is a 3-tuple `(expected_pending_type, effect_fn, auto_pop)`:

| `auto_pop` | Dispatcher behavior |
|---|---|
| `True` (default-shape) | Assert pending type, call effect_fn, pop the pending. |
| `False` | Assert pending type, call effect_fn, **leave the stack alone**. The effect function is responsible for any stack manipulation (pop, push wrapper, replace_top, etc.). |

The variable describes **the dispatcher's behavior**, not the effect function's. It does not encode a single rule for what `auto_pop=False` effect functions do — that varies (multi-shot stables/rooms leave the pending on top; build_major pops for non-ovens and pushes a wrapper for ovens). Effect-function behavior has always been the effect function's prerogative.

### Code edits

**`agricola/engine.py`** — `_apply_commit_subaction`:

```python
def _apply_commit_subaction(state: GameState, action: CommitSubAction) -> GameState:
    expected_pending_type, effect_fn, auto_pop = COMMIT_SUBACTION_HANDLERS[type(action)]
    top = state.pending_stack[-1]
    assert isinstance(top, expected_pending_type), (
        f"{type(action).__name__} expects {expected_pending_type} on top, got {type(top)}"
    )
    state = effect_fn(state, top.player_idx, action)
    if auto_pop:
        state = pop(state)
    return state
```

The `COMMIT_SUBACTION_HANDLERS` table at the end of Change 1 keeps all existing entries (each now a 3-tuple with `auto_pop=True`), with no new entries. The post-Change-1 table reads:

```python
COMMIT_SUBACTION_HANDLERS: dict[type, tuple] = {
    CommitSow:          (PendingSow,                                                 _execute_sow,          True),
    CommitBake:         (PendingBakeBread,                                           _execute_bake,         True),
    CommitPlow:         (PendingPlow,                                                _execute_plow,         True),
    CommitBuildStable:  (PendingBuildStable,                                         _execute_build_stable, True),
    CommitRenovate:     (PendingRenovate,                                            _execute_renovate,     True),
    CommitAccommodate:  ((PendingSheepMarket, PendingPigMarket, PendingCattleMarket), _execute_accommodate,  True),
}
```

(`CommitBuildMajor` is NOT in the table yet — it's still special-cased in `_apply_action` until Change 2. `CommitBuildStable` still points at the singular `PendingBuildStable` / `_execute_build_stable` pair — it won't be re-pointed until step 7 of Part 7's order of work.)

For reference, the final post-task table after all of Part 1 + Part 2 + Part 4 lands looks like:

```python
COMMIT_SUBACTION_HANDLERS: dict[type, tuple] = {
    CommitSow:          (PendingSow,                                                 _execute_sow,          True),
    CommitBake:         (PendingBakeBread,                                           _execute_bake,         True),
    CommitPlow:         (PendingPlow,                                                _execute_plow,         True),
    CommitRenovate:     (PendingRenovate,                                            _execute_renovate,     True),
    CommitAccommodate:  ((PendingSheepMarket, PendingPigMarket, PendingCattleMarket), _execute_accommodate,  True),
    # added in Change 2:
    CommitBuildMajor:   (PendingBuildMajor,                                          _execute_build_major,  False),
    # added in Part 2 (step 6):
    CommitBuildRoom:    (PendingBuildRooms,                                          _execute_build_room,   False),
    # MODIFIED in Part 4 (step 7) — the pre-task (PendingBuildStable, _execute_build_stable, True) entry is replaced atomically with the entry below as the old singular pending+function are retired and the new function is renamed to take the singular name:
    CommitBuildStable:  (PendingBuildStables,                                        _execute_build_stable, False),
}
```

## Change 2 — Absorb `CommitBuildMajor` into the generic dispatch path

`CommitBuildMajor` is currently special-cased in `_apply_action` because it pops `PendingBuildMajor` for non-oven majors but leaves it on top (and pushes a `PendingClayOven` / `PendingStoneOven` wrapper) for ovens. With `auto_pop=False` now available, the special-case branch is unnecessary: `_execute_build_major` already owns the conditional push; we move the conditional pop into it as well.

### Code edits

**`agricola/resolution.py`** — `_execute_build_major`:

**No body changes needed.** The function already owns all its stack manipulation: for oven majors it pushes the wrapper pending ([resolution.py:749-757](agricola/resolution.py:749)); for non-ovens it pops `PendingBuildMajor` itself ([resolution.py:760](agricola/resolution.py:760)). The only edit is to the docstring — remove the "Called directly from `_apply_action`'s special-case branch — NOT through the generic `_apply_commit_subaction` dispatcher" framing, since after Change 2 it IS dispatched through the generic path (with `auto_pop=False` so the dispatcher doesn't add a second pop).

**`agricola/engine.py`** — `_apply_action`:

Delete the `isinstance(action, CommitBuildMajor)` branch entirely (the four lines at [engine.py:125-129](agricola/engine.py:125)). `CommitBuildMajor` now reaches the generic `_apply_commit_subaction` path via its `CommitSubAction` ancestor (it already is one).

**`agricola/engine.py`** — `COMMIT_SUBACTION_HANDLERS`:

Add the entry:
```python
CommitBuildMajor: (PendingBuildMajor, _execute_build_major, False),
```

Also delete the comment on line 157 ("`# CommitBuildMajor is NOT in this table — special-cased in _apply_action.`") since it's now in the table.

### Existing tests

`tests/test_major_improvement.py` should pass without changes — the externally-visible action sequence and resulting states are identical. The internal dispatch path is the only thing that changed.

## Change 3 — `ROOM_COSTS` constant, `_can_afford` helper, `_can_afford_room` simplification

### Convention shift

Today, room costs are encoded as inline material-switch + per-component checks inside `_can_afford_room` ([legality.py:253](agricola/legality.py:253)). When `_choose_subaction_farm_expansion` lands in Part 3, it needs the same cost data — so we extract a constant and route both call sites through it. Mirrors the existing `MAJOR_IMPROVEMENT_COSTS` precedent in `constants.py`.

Multi-shot enumerators and `_can_build_stable` also need a generic "can the player pay this cost?" check. `Resources` doesn't have `__ge__` ([resources.py:16-46](agricola/resources.py:16)) and we're not adding partial-ordering operators just for this — instead, add a small `_can_afford(p, cost)` helper in `legality.py`.

### Code edits

**`agricola/constants.py`** — add:

```python
ROOM_COSTS: dict[HouseMaterial, Resources] = {
    HouseMaterial.WOOD:  Resources(wood=5,  reed=2),
    HouseMaterial.CLAY:  Resources(clay=5,  reed=2),
    HouseMaterial.STONE: Resources(stone=5, reed=2),
}
```

(Import `HouseMaterial` if not already imported in `constants.py`. `Resources` already is, since `MAJOR_IMPROVEMENT_COSTS` uses it.)

**`agricola/legality.py`** — add `_can_afford`:

```python
_RESOURCE_FIELDS = ("wood", "clay", "reed", "stone", "food", "grain", "veg")

def _can_afford(p: PlayerState, cost: Resources) -> bool:
    """True iff every component of the player's resources >= the corresponding cost component."""
    r = p.resources
    return all(getattr(r, f) >= getattr(cost, f) for f in _RESOURCE_FIELDS)
```

(`_RESOURCE_FIELDS` is local to `legality.py` for now — if a second module wants it, lift to `resources.py` at that point.)

**`agricola/legality.py`** — simplify `_can_afford_room`:

```python
def _can_afford_room(p: PlayerState) -> bool:
    return _can_afford(p, ROOM_COSTS[p.house_material])
```

The inline material-switch + per-component check in the previous body is replaced by the single dict lookup + generic affordability call. Behavior preserved exactly.

Verify by grep at implementation time that no other affordability check in `legality.py` independently encodes the same per-room cost (`_can_renovate` reads a different cost — 1 of the new material per room + 1 reed total — so doesn't migrate to `ROOM_COSTS`, but its inline check could optionally migrate to `_can_afford` for consistency).

## Change 4 — Predicate-enumerator deduplication + `_can_build_stable(p, cost)`

### Convention shift

Several existence-predicates in `legality.py` duplicate the logic of an existing cell-enumerator:

| Predicate | Enumerator | Status today |
|---|---|---|
| `_can_plow(p)` | `_legal_plow_cells(p)` | Both compute the same set; predicate returns `bool` of it. |
| `_has_stable_placement(p)` | `_legal_stable_cells(p)` | Same shape. |
| `_has_room_placement(p)` | (new in this task) | New `_legal_room_cells(p)` to be added; current predicate computes inline. |

Each predicate collapses to `bool(<enumerator>(p))` plus its non-cell checks. Single source of truth for "where can X go"; predicates derive.

The stable predicate also gets a different-shaped fix: `_has_stable_placement` is replaced by a parameterized `_can_build_stable(p, cost: Resources)` that combines all three legality checks (cell + supply + affordability) in one call. Eliminates three inline `p.resources.wood >= N and _has_stable_placement(p)` duplications.

### Code edits

**`agricola/legality.py`** — add `_legal_room_cells(p)`:

```python
def _legal_room_cells(p: PlayerState) -> list[tuple[int, int]]:
    """Enumerate every (row, col) where a room can be placed.

    Empty, non-enclosed, orthogonally adjacent to an existing ROOM cell.
    Naturally handles within-action adjacency chaining: a room just built
    counts as an existing ROOM for the next call.
    """
    grid = p.farmyard.grid
    enclosed = enclosed_cells(p.farmyard)
    room_cells = {
        (r, c)
        for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.ROOM
    }
    empty_unenclosed = [
        (r, c)
        for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.EMPTY
        and (r, c) not in enclosed
    ]
    adjacent_to_room = {
        (r + dr, c + dc)
        for (r, c) in room_cells
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]
    }
    return [cell for cell in empty_unenclosed if cell in adjacent_to_room]
```

**`agricola/legality.py`** — refactor `_can_plow` and `_has_room_placement`:

```python
def _can_plow(p: PlayerState) -> bool:
    return bool(_legal_plow_cells(p))

def _has_room_placement(p: PlayerState) -> bool:
    return bool(_legal_room_cells(p))
```

(Both keep their docstrings; the bodies become one-liners. Behavior preserved exactly.)

**`agricola/legality.py`** — introduce `_can_build_stable(p, cost)` and delete `_has_stable_placement`:

```python
def _can_build_stable(p: PlayerState, cost: Resources) -> bool:
    """Combined legality check for one stable build at the given cost.

    Empty cell exists + ≥1 stable in supply + can afford `cost`.
    """
    return (
        stables_in_supply(p.farmyard) >= 1
        and bool(_legal_stable_cells(p))
        and _can_afford(p, cost)
    )
```

Migrate all call sites of `_has_stable_placement`:

| Site | Before | After |
|---|---|---|
| `_legal_farm_expansion` ([legality.py:460](agricola/legality.py:460)) | `p.resources.wood >= 2 and _has_stable_placement(p)` | `_can_build_stable(p, Resources(wood=2))` |
| `_legal_side_job` ([legality.py:475](agricola/legality.py:475)) | `p.resources.wood >= 1 and _has_stable_placement(p)` | `_can_build_stable(p, Resources(wood=1))` |
| `_enumerate_pending_side_job` ([legality.py:818](agricola/legality.py:818)) | `p.resources.wood >= 1 and _has_stable_placement(p)` | `_can_build_stable(p, Resources(wood=1))` |

Then delete `_has_stable_placement` from `legality.py` — no remaining callers.

The future `_enumerate_pending_build_stables` (Part 2) also uses `_can_build_stable(p, pending.cost)`, but that's a new call site, not a migration. The existing singular `_enumerate_pending_build_stable` ([legality.py:736](agricola/legality.py:736)) does NOT call `_has_stable_placement` (it returns `_legal_stable_cells(p)` directly), so no migration there either; it's deleted wholesale in step 7.

### Existing tests

All 315 existing tests should pass unchanged after Changes 3 and 4 — these are pure refactors with no externally-visible behavior change.

## Change 5 — `_new_grid_with_cell` helper

### Convention shift

Three effect functions after this task place a cell on the farmyard grid: `_execute_plow` (existing), `_execute_build_stable` (rewritten in step 7; introduced in step 6 under the temporary plural name `_execute_build_stables`), and `_execute_build_room` (new). Each does the same nested-tuple-comprehension dance to produce a new grid with one cell replaced. Extract it once.

### Code edits

**`agricola/resolution.py`** — add a small private helper near the top of the module (alongside `_update_player` / `_update_space`):

```python
def _new_grid_with_cell(
    grid: tuple, row: int, col: int, cell: Cell,
) -> tuple:
    """Return a new 3×5 grid identical to `grid` except at (row, col), which is replaced by `cell`."""
    new_row = tuple(
        cell if c == col else existing
        for c, existing in enumerate(grid[row])
    )
    return tuple(
        new_row if r == row else existing_row
        for r, existing_row in enumerate(grid)
    )
```

**`agricola/resolution.py`** — migrate `_execute_plow` ([resolution.py:618-625](agricola/resolution.py:618)) to use the helper. The 8-line inline construction collapses to one call. Behavior preserved.

(The other inline site, `_execute_build_stable` at [resolution.py:643-651](agricola/resolution.py:643), is deleted in step 7 of the order-of-work and doesn't need migrating.)

### Existing tests

All 315 existing tests should pass unchanged.

---

# Part 2 — Multi-shot sub-action pending machinery

## `PendingBuildStables`

Frozen dataclass in `agricola/pending.py`:

```python
@dataclass(frozen=True)
class PendingBuildStables:
    PENDING_ID:    ClassVar[str] = "build_stables"
    player_idx:        int
    initiated_by_id:   str
    cost:              Resources                  # per-commit cost (e.g., Resources(wood=2) for Farm Expansion, Resources(wood=1) for Side Job)
    max_builds:        int | None                 # caller-imposed cap; None = no cap. Side Job sets 1; Farm Expansion sets None.
    num_built:         int = 0
```

Cost is **bucket 2** (CLAUDE.md "Sub-action cost handling"): the choose handler computes the cost at push time and stores it on the pending. `_execute_build_stables` reads `top.cost` and debits via `p.resources - top.cost`.

`max_builds` is a **caller-imposed cap** with no semantic tie to global constraints (supply, affordability, cell availability). Those are enforced separately in `_enumerate_pending_build_stables`. Two values matter today:

- Farm Expansion: `max_builds = None` — no caller-imposed cap. The actual ceiling is dynamic and comes from supply + affordability + empty cells, all enforced in the enumerator.
- Side Job: `max_builds = 1` — hard cap from the space's rules, independent of any other constraint.

`num_built` increments on each commit. Pending pops via `Stop`, never via the dispatcher.

No `triggers_resolved` field and no `TRIGGER_EVENT` classvar. Card-trigger machinery for the build_stables event is deferred to whenever the first such card lands; until then, the field and classvar would be dead weight.

## `PendingBuildRooms`

Same shape as `PendingBuildStables`:

```python
@dataclass(frozen=True)
class PendingBuildRooms:
    PENDING_ID:    ClassVar[str] = "build_rooms"
    player_idx:        int
    initiated_by_id:   str
    cost:              Resources                  # e.g. Resources(wood=5, reed=2) for a wood house
    max_builds:        int | None                 # caller-imposed cap; None = no cap
    num_built:         int = 0
```

`cost` is set at push time from the current house material: `Resources(wood=5, reed=2)`, `Resources(clay=5, reed=2)`, or `Resources(stone=5, reed=2)`.

`max_builds` is unused in the Family game (Farm Expansion always pushes with `None`), but is included for forward-compat with the full game: some occupations and minor improvements grant a fixed number of room builds (or modify the cap), and those cards would push or `replace_top` with a concrete integer.

No `triggers_resolved` field and no `TRIGGER_EVENT` classvar, mirroring `PendingBuildStables`.

## `CommitBuildRoom`

New action class in `agricola/actions.py`:

```python
@dataclass(frozen=True)
class CommitBuildRoom(CommitSubAction):
    row: int
    col: int
```

Added to the `Action` union alias alongside the existing commit types.

## Effect function `_execute_build_stables`

In `agricola/resolution.py`. Introduced under the plural name `_execute_build_stables` because the existing singular `_execute_build_stable` from Task 5C is still alive at step 6 (deleted in step 7). At step 7, the old singular function is deleted and this function is renamed to `_execute_build_stable` to match the function-name prefix taxonomy (singular, derived from `CommitBuildStable`).

Signature follows the post-Task-5C convention `(state, player_idx, commit) -> GameState`. Effect function owns stack manipulation (the dispatcher's `auto_pop=False`):

```python
def _execute_build_stables(
    state: GameState, player_idx: int, commit: CommitBuildStable,
) -> GameState:
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildStables)
    p = state.players[player_idx]

    # Place the stable. Recompute pastures explicitly: a stable placed inside
    # an existing pasture changes that pasture's num_stables (and therefore
    # its capacity). Although no pasture can yet exist in current scope (no
    # resolver builds fences pre-Fencing), this is the documented convention
    # for pasture-changing resolvers (CLAUDE.md "Current exception: Farmyard.pastures")
    # and means Fencing won't have to revisit this function later.
    new_grid = _new_grid_with_cell(p.farmyard.grid, commit.row, commit.col, Cell(cell_type=CellType.STABLE))
    new_farmyard = dataclasses.replace(
        p.farmyard,
        grid=new_grid,
        pastures=compute_pastures_from_arrays(
            new_grid, p.farmyard.horizontal_fences, p.farmyard.vertical_fences,
        ),
    )
    new_player = dataclasses.replace(
        p,
        resources=p.resources - top.cost,
        farmyard=new_farmyard,
    )
    state = _update_player(state, player_idx, new_player)
    return replace_top(state, dataclasses.replace(top, num_built=top.num_built + 1))
```

This fixes a latent bug in Task 5C's `_execute_build_stable`, which omitted the pasture recompute. The bug doesn't manifest in current gameplay because no resolver creates fences (Fencing is unimplemented), so `_legal_stable_cells` never returns a cell that's actually inside any pasture — but the moment Fencing lands, the omission would silently produce stale pastures. By placing the recompute in this function (which after step 7's rename takes the same `_execute_build_stable` name and replaces the buggy version), the bug is fixed before it can manifest.

## Effect function `_execute_build_room`

```python
def _execute_build_room(
    state: GameState, player_idx: int, commit: CommitBuildRoom,
) -> GameState:
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildRooms)
    p = state.players[player_idx]

    new_grid = _new_grid_with_cell(p.farmyard.grid, commit.row, commit.col, Cell(cell_type=CellType.ROOM))
    new_farmyard = dataclasses.replace(p.farmyard, grid=new_grid)
    new_player = dataclasses.replace(
        p,
        resources=p.resources - top.cost,
        farmyard=new_farmyard,
    )
    state = _update_player(state, player_idx, new_player)
    return replace_top(state, dataclasses.replace(top, num_built=top.num_built + 1))
```

A newly built room does not house a person; `people_total` only changes via Wish-for-Children, so it's left alone here. Rooms-just-built are immediately adjacent for the next room placed in the same action — the enumerator picks this up automatically because each commit replaces the farmyard, and the next call to `_enumerate_pending_build_rooms` reads the new farmyard.

Pasture cache is unaffected: rooms cannot legally land in enclosed cells (RULES.md "House and Rooms"), and `_legal_room_cells` enforces this.

## Per-pending enumerators

In `agricola/legality.py`:

```python
def _enumerate_pending_build_stables(
    state: GameState, pending: PendingBuildStables,
) -> list[Action]:
    actions: list[Action] = []
    p = state.players[pending.player_idx]

    cap_ok = pending.max_builds is None or pending.num_built < pending.max_builds
    if cap_ok and _can_build_stable(p, pending.cost):
        for (r, c) in _legal_stable_cells(p):
            actions.append(CommitBuildStable(row=r, col=c))

    if pending.num_built >= 1:
        actions.append(Stop())

    return actions
```

Two constraints filter the commit options:

- **Caller-imposed cap**: `max_builds is None or num_built < max_builds`. Side Job's `max_builds=1` saturates after the single commit; Farm Expansion's `None` never blocks here.
- **Buildability**: `_can_build_stable(p, pending.cost)` — combined supply + cell-availability + affordability check (introduced in Part 1 Change 4).

When `cap_ok and _can_build_stable(...)` is True, the cell list comes from `_legal_stable_cells(p)`, which is already known to be non-empty (`_can_build_stable` checks it).

```python
def _enumerate_pending_build_rooms(
    state: GameState, pending: PendingBuildRooms,
) -> list[Action]:
    actions: list[Action] = []
    p = state.players[pending.player_idx]

    cap_ok = pending.max_builds is None or pending.num_built < pending.max_builds
    if cap_ok and _can_afford(p, pending.cost):
        for (r, c) in _legal_room_cells(p):
            actions.append(CommitBuildRoom(row=r, col=c))

    if pending.num_built >= 1:
        actions.append(Stop())

    return actions
```

`_legal_room_cells(p)` was added in Part 1 Change 4. Computed from the current `p.farmyard.grid` (which reflects all room-builds-so-far in the current multi-shot session) — naturally handles within-action adjacency chaining without any explicit "rooms added this session" tracking. There's no analogous `_can_build_room(p, cost)` because the room cost is uniform per house (no Side-Job-vs-Farm-Expansion split for rooms today); the affordability check inlines as `_can_afford(p, pending.cost)`.

Both enumerators registered in `PENDING_ENUMERATORS`:

```python
PendingBuildStables: _enumerate_pending_build_stables,
PendingBuildRooms:   _enumerate_pending_build_rooms,
```

(The existing `PendingBuildStable` enumerator remains in place until Part 4.)

---

# Part 3 — Farm Expansion

## `PendingFarmExpansion`

Frozen dataclass in `agricola/pending.py`:

```python
@dataclass(frozen=True)
class PendingFarmExpansion:
    PENDING_ID:    ClassVar[str] = "farm_expansion"
    player_idx:        int
    initiated_by_id:   str
    room_chosen:       bool      = False
    stable_chosen:     bool      = False
```

Mirrors the Side Job parent's shape (two boolean `*_chosen` flags). No `triggers_resolved` field and no `TRIGGER_EVENT` classvar — card-trigger machinery for the farm_expansion event is deferred until the first such card lands.

## `_initiate_farm_expansion`

In `agricola/resolution.py`:

```python
def _initiate_farm_expansion(state: GameState) -> GameState:
    ap = state.current_player
    return push(state, PendingFarmExpansion(
        player_idx=ap, initiated_by_id="space:farm_expansion",
    ))
```

Registered in `NONATOMIC_HANDLERS`:

```python
"farm_expansion": _initiate_farm_expansion,
```

Remove the `farm_expansion` entry from the `_apply_place_worker` `NotImplementedError` list (in `agricola/engine.py`).

## `_choose_subaction_farm_expansion`

```python
def _choose_subaction_farm_expansion(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFarmExpansion)
    p = state.players[top.player_idx]

    if action.name == "build_rooms":
        state = replace_top(state, dataclasses.replace(top, room_chosen=True))
        return push(state, PendingBuildRooms(
            player_idx=top.player_idx,
            initiated_by_id=top.PENDING_ID,
            cost=ROOM_COSTS[p.house_material],
            max_builds=None,
        ))

    if action.name == "build_stables":
        state = replace_top(state, dataclasses.replace(top, stable_chosen=True))
        return push(state, PendingBuildStables(
            player_idx=top.player_idx,
            initiated_by_id=top.PENDING_ID,
            cost=Resources(wood=2),
            max_builds=None,
        ))

    raise ValueError(f"Unknown sub-action: {action.name!r}")
```

Registered in `CHOOSE_SUBACTION_HANDLERS`:

```python
PendingFarmExpansion: _choose_subaction_farm_expansion,
```

Both pushes use `max_builds=None` — no caller-imposed cap. Dynamic constraints (supply, affordability, cell availability, adjacency) are enforced in the enumerators. `ROOM_COSTS` is the `dict[HouseMaterial, Resources]` constant introduced in Part 1 Change 3.

## `_enumerate_pending_farm_expansion`

In `agricola/legality.py`:

```python
def _enumerate_pending_farm_expansion(
    state: GameState, pending: PendingFarmExpansion,
) -> list[Action]:
    actions: list[Action] = []
    p = state.players[pending.player_idx]

    if not pending.room_chosen and _can_build_room(p):
        actions.append(ChooseSubAction(name="build_rooms"))

    if not pending.stable_chosen and _can_build_stable(p, Resources(wood=2)):
        actions.append(ChooseSubAction(name="build_stables"))

    if pending.room_chosen or pending.stable_chosen:
        actions.append(Stop())

    return actions
```

`_can_build_stable(p, cost)` is the parameterized helper introduced in Part 1 Change 4. No Farm-Expansion-specific predicate is needed.

Registered in `PENDING_ENUMERATORS`:

```python
PendingFarmExpansion: _enumerate_pending_farm_expansion,
```

## Placement-level legality predicate

`_legal_farm_expansion(state)` already exists in [legality.py:455](agricola/legality.py:455). After Part 1 Change 4 (which migrates the inline `p.resources.wood >= 2 and _has_stable_placement(p)` to `_can_build_stable(p, Resources(wood=2))`), the predicate reads:

```python
def _legal_farm_expansion(state: GameState) -> bool:
    if not _is_available(state, "farm_expansion"):
        return False
    p = state.players[state.current_player]
    return _can_build_room(p) or _can_build_stable(p, Resources(wood=2))
```

No additional Part 3 edits to this function — the migration is part of Change 4.

---

# Part 4 — Side Job migration + `PendingBuildStable` retirement

## `_choose_subaction_side_job` migration

The existing handler pushes `PendingBuildStable(player_idx=..., initiated_by_id=..., cost=Resources(wood=1))`. Change it to push `PendingBuildStables(..., cost=Resources(wood=1), max_builds=1)`:

```python
def _choose_subaction_side_job(state, action):
    top = state.pending_stack[-1]
    if action.name == "build_stable":
        state = replace_top(state, dataclasses.replace(top, stable_chosen=True))
        return push(state, PendingBuildStables(
            player_idx=top.player_idx,
            initiated_by_id=top.PENDING_ID,
            cost=Resources(wood=1),
            max_builds=1,
        ))
    # bake_bread branch unchanged
    ...
```

After this change, Side Job's stable-build trace is two actions instead of one: `CommitBuildStable(r, c)` then `Stop()`. The `Stop` is the only legal action after the single commit (`num_built == max_builds == 1` means no more `CommitBuildStable` is legal, and `num_built >= 1` so `Stop` is legal).

## Retirement steps

In `agricola/pending.py`:

- Delete the `PendingBuildStable` class.
- Remove it from the `PendingDecision` union.

In `agricola/resolution.py`:

- Delete the old singular `_execute_build_stable` (Task 5C's implementation that operated on `PendingBuildStable` and auto-popped).
- Rename the new `_execute_build_stables` (plural) → `_execute_build_stable` (singular). The singular name is now free and matches the function-name prefix taxonomy.

In `agricola/legality.py`:

- Delete `_enumerate_pending_build_stable` (replaced by `_enumerate_pending_build_stables`).
- Remove its entry from `PENDING_ENUMERATORS`.

In `agricola/engine.py`:

- The `COMMIT_SUBACTION_HANDLERS` entry for `CommitBuildStable` now points at `(PendingBuildStables, _execute_build_stable, False)` — pending type is plural, function name is back to singular after the rename. The previous entry (singular pending + auto_pop=True) is gone.

`CommitBuildStable` itself (the action class) is **not** deleted — it remains the commit type for both Farm Expansion stables and Side Job stables.

---

# Part 5 — Tests

## New: `tests/test_farm_expansion.py`

Uses prefabricated states from `tests/factories.py`. Covers:

- **Basic walks**:
  - rooms-only path: `PlaceWorker(space="farm_expansion")` → `ChooseSubAction(name="build_rooms")` → `CommitBuildRoom(row=r, col=c)` → `Stop()` → `Stop()`.
  - stables-only path: `... → ChooseSubAction(name="build_stables") → CommitBuildStable(row=r, col=c) → Stop() → Stop()`.
  - rooms-then-stables and stables-then-rooms paths reach identical end states.
- **Multi-room within one session**: starting with a wood house, 15 wood, 6 reed, and adjacency-available cells, the player builds 3 rooms in one Farm Expansion via three `CommitBuildRoom` actions. Verify each subsequent commit's legal cell list reflects the just-built room (within-action adjacency chaining).
- **Multi-stable within one session**: 4 stables built in one session. Verify supply decrement and that the 5th commit is not legal (`stables_in_supply` reaches 0). Farm Expansion's `PendingBuildStables.max_builds is None`; the supply check in the enumerator is what saturates.
- **Supply-exhausted singleton-Stop (Farm Expansion)**: starting state with 2 stables in supply (e.g., 2 already built via a fixture). After 2 commits, `legal_actions` returns exactly `[Stop()]`.
- **Affordability-exhausted singleton-Stop (Farm Expansion)**: starting state with 4 wood + 1 stable already built (supply = 3). Player can afford 2 more stables. After 2 commits, wood = 0 but supply = 1 — affordability is the binding constraint. `legal_actions` returns exactly `[Stop()]` even though supply > 0 and `max_builds is None`. Proves the affordability check fires independently of supply / cap.
- **Stop legality**:
  - `Stop` not legal in `PendingBuildStables` at `num_built=0`.
  - `Stop` not legal in `PendingBuildRooms` at `num_built=0`.
  - `Stop` not legal in `PendingFarmExpansion` until at least one sub-action is `*_chosen=True`.
- **Cost on pending**: `PendingBuildStables.cost == Resources(wood=2)` after Farm Expansion choose; `PendingBuildRooms.cost == Resources(wood=5, reed=2)` for a wood-house player; `Resources(clay=5, reed=2)` for clay-house; `Resources(stone=5, reed=2)` for stone-house. Parametrize over house material.
- **Adjacency rule for rooms**: a player with rooms only at (1,0) and (2,0) and a wood house with enough resources can build at (0,0) but not at (0,4) (non-adjacent).
- **Within-action adjacency chaining**: with starting rooms at (1,0), (2,0), after building (0,0), the cell (0,1) is now in the legal-cell list for the next commit even though it was not before.
- **Empty/non-enclosed cell rule**: rooms cannot be placed inside an existing pasture.
- **Pasture cache recompute on stable build inside an existing pasture**: factory-prefab a state where the player has a pasture enclosing two empty cells (set fence arrays explicitly, with `Farmyard.pastures` recomputed). Enter Farm Expansion, build a stable on one of the enclosed empty cells. Verify the resulting `farmyard.pastures` shows the affected pasture's `num_stables == 1` (was 0) and `capacity == 2 * num_cells * 2` (doubled from the no-stable baseline). Cross-check by reading the `pastures` field directly rather than recomputing on the fly. This test is unreachable through normal gameplay today (Fencing isn't implemented, so no resolver currently creates pastures) — but it pins down the pasture-recompute behavior in `_execute_build_stable` (post-rename) before Fencing lands.
- **Once-per-category rule (parametrized over rooms/stables)**: after `Stop()` from `PendingBuildRooms`, `ChooseSubAction(name="build_rooms")` is not in `legal_actions` at the parent (`room_chosen=True` already). Same for stables — after `Stop()` from `PendingBuildStables`, `ChooseSubAction(name="build_stables")` is not legal.
- **Placement legality**:
  - `farm_expansion` not legal when player can build neither a room nor a stable.
  - `farm_expansion` legal when player can build only rooms (e.g., `stables_in_supply == 0` but rooms affordable + placeable).
  - `farm_expansion` legal when player can build only stables.
- **Stack invariants**: under the choose-time convention, `ChooseSubAction("build_rooms")` writes `room_chosen=True` on `PendingFarmExpansion` and pushes `PendingBuildRooms`. `CommitBuildRoom` does NOT pop `PendingBuildRooms` (Approach 2); `Stop` pops.

## Updates to `tests/test_side_job.py`

- The post-`CommitBuildStable` state now has `PendingBuildStables(num_built=1, max_builds=1)` on top (not a popped pending).
- The next legal action is `Stop()`.
- `Stop` then pops `PendingBuildStables`, returning to `PendingSideJob`.
- `PendingBuildStables.cost == Resources(wood=1)` invariant test replaces the prior `PendingBuildStable.cost` test.
- The "stable cost is 1 wood, debited via `__sub__`" invariant survives — the resource accounting is unchanged.

## Updates to `tests/test_major_improvement.py`

No action-level changes expected — the externally-visible trace and end states are identical. Sanity-pass after Part 1 Change 2 lands: ensure every existing assertion still holds. If any test inspected `_apply_action`'s branching (unlikely; the project tests externally-visible behavior), update it.

---

# Part 6 — Documentation

## CLAUDE.md updates

- **Status table**: mark Farm Expansion complete. Update "Not yet implemented" to list only Farm Redevelopment and Fencing.
- **`agricola/constants.py` description**: add `ROOM_COSTS: dict[HouseMaterial, Resources]` — mirrors the existing `MAJOR_IMPROVEMENT_COSTS` entry.
- **`agricola/pending.py` per-class descriptions**: add `PendingFarmExpansion`, `PendingBuildStables`, `PendingBuildRooms`. Delete the `PendingBuildStable` entry.
- **`agricola/resolution.py` description**: add `_new_grid_with_cell` helper (with note that `_execute_plow` was migrated to use it). Update the existing `_execute_build_stable` entry to describe its new multi-shot semantics (the body was rewritten and the function renamed back to singular at step 7, after the original singular function was deleted; the new body operates on `PendingBuildStables`, does not pop, and recomputes pastures). Add `_execute_build_room`, `_initiate_farm_expansion`, `_choose_subaction_farm_expansion`. Update `_execute_build_major` description to note that it now owns the conditional pop / oven-wrapper push, having been absorbed into the generic dispatch path. Add `farm_expansion` to `NONATOMIC_HANDLERS` description. Add `PendingFarmExpansion` to `CHOOSE_SUBACTION_HANDLERS` description.
- **`agricola/engine.py` description**: update `_apply_action` to note that the `CommitBuildMajor` special-case branch has been removed. Update `COMMIT_SUBACTION_HANDLERS` description: entries are now 3-tuples carrying `auto_pop`; `_execute_build_major` is now in the table with `auto_pop=False`.
- **`agricola/actions.py` description**: add `CommitBuildRoom` to the action class enumeration and to the `Action` union.
- **`agricola/legality.py` description**: add `_can_afford(p, cost)`, `_can_build_stable(p, cost)`, `_legal_room_cells(p)`, `_enumerate_pending_farm_expansion`, `_enumerate_pending_build_stables`, `_enumerate_pending_build_rooms`. Note that `_can_plow` and `_has_room_placement` are now one-liners over their cell enumerators; `_can_afford_room` is a one-liner over `ROOM_COSTS` + `_can_afford`. Remove `_has_stable_placement` and `_enumerate_pending_build_stable`.
- **"Sub-action cost handling" subsection**: `PendingBuildStables` and `PendingBuildRooms` join `PendingBuildStable`'s slot as bucket-2 examples. `PendingBuildStable` is removed from that listing.
- **"Lifecycle of a non-atomic turn" bullets (under "The pending-decision stack")**: amend the existing `CommitX(...)` bullet to add a multi-shot variant. The existing bullet reads "`CommitX(...)` pops the category pending. The parent flag was set earlier, at choose-time." Add: "For multi-shot pendings (`PendingBuildStables`, `PendingBuildRooms`): `CommitX(...)` increments `num_built` and leaves the pending on top via `replace_top`; `Stop` is the explicit exit and pops the pending. See "Multi-shot sub-action pendings" below."
- **New "Multi-shot sub-action pendings" subsection under "Additional Design Principles"** — see draft below.
- **`tests/` directory list**: add `tests/test_farm_expansion.py` with a one-line summary.

### Draft: new "Multi-shot sub-action pendings" subsection

> Some sub-action categories allow multiple commits within a single category invocation (Farm Expansion's build_rooms and build_stables; Side Job's build_stable as a degenerate cap=1 case). The pattern:
>
> - The pending carries two integer fields: `max_builds: int | None` (caller-imposed cap, set at push time; `None` means no cap) and `num_built: int = 0` (increments on each commit).
> - `max_builds` encodes only the **caller's intent**, not global constraints. Affordability, supply, and cell/placement availability are checked separately in the per-pending enumerator. Side Job pushes with `max_builds=1` (the space's rule). Farm Expansion pushes with `max_builds=None` — the dynamic constraints in the enumerator do all the bounding.
> - The effect function is registered with `auto_pop=False` in `COMMIT_SUBACTION_HANDLERS`. Each commit applies its effect, increments `num_built`, and `replace_top`s — but does **not** pop the pending.
> - `Stop` is the explicit exit. `Stop` is legal at `num_built >= 1` (the "must do at least one when entering a category" rule); not legal at `num_built == 0`.
> - Per-pending legality offers `Commit*` actions only while `(max_builds is None or num_built < max_builds)` AND remaining affordability/placement/supply constraints permit. When no commit is legal but `num_built >= 1`, `Stop` becomes the only legal action and the agent explicitly Stops. This singleton-`Stop` state arises uniformly whether the cap, supply, affordability, or cell-availability constraint is the binding one.
>
> Side Job's stable build is a multi-shot pending with `max_builds=1`: after the single commit, `Stop` is the only legal action. There is no auto-pop optimization for `max_builds=1` cases — surfacing the singleton `Stop` keeps trace consistency uniform across multi-shot pendings and aligns with the engine's "no auto-resolved singleton player decisions" principle.
>
> Card-trigger fields (`triggers_resolved`, `TRIGGER_EVENT`) are intentionally absent from the multi-shot pendings introduced in Task 5D. They will be added per-pending when the first card needs them — there is no benefit to forward-compat dead fields. When added, the question of whether `triggers_resolved` persists across commits or resets per commit will be settled per the rules interpretation ("one action with multiple builds" suggests persistence across commits; per-individual-build cards would attach to a different event like `"after_build_stable"` on each commit).

## CHANGES.md entry

**Change 6 — Multi-shot sub-action pendings, `auto_pop` dispatcher flag, `_execute_build_major` absorption, legality helper consolidations.**

Documents:

- `COMMIT_SUBACTION_HANDLERS` entries grow a 3rd field (`auto_pop: bool`); `_apply_commit_subaction` consults it; `auto_pop=False` means the effect function owns stack management.
- `_execute_build_major` absorbed into the generic dispatch path (auto_pop=False; owns its conditional non-oven pop and oven-wrapper push). The special-case branch in `_apply_action` is deleted.
- New multi-shot pending pattern: `PendingBuildStables` and `PendingBuildRooms` host multi-commit-then-Stop sub-actions. Fields: `cost: Resources`, `max_builds: int | None` (caller-imposed cap, `None` = no cap), `num_built: int = 0`. No card-trigger fields (forward-compat added when needed).
- `PendingBuildStable` (singular) retired; Side Job migrated to `PendingBuildStables` with `max_builds=1`. The action class `CommitBuildStable` is reused unchanged.
- `_execute_build_stable` (the post-Task-5D version — old implementation deleted, new multi-shot implementation renamed in from the temporary plural name) recomputes `Farmyard.pastures` via `compute_pastures_from_arrays`, fixing a latent cache-staleness bug in Task 5C's version. The fix is directly exercised by a dedicated test in `tests/test_farm_expansion.py` that prefabs a state with an existing pasture and confirms the cache is updated after a stable lands inside it.
- `ROOM_COSTS: dict[HouseMaterial, Resources]` added to `constants.py`; `_can_afford(p, cost)` added to `legality.py`; `_can_afford_room` simplified to a one-liner. Mirrors the existing `MAJOR_IMPROVEMENT_COSTS` shape.
- Predicate-enumerator deduplication in `legality.py`: `_can_plow` and `_has_room_placement` (with new `_legal_room_cells`) collapse to one-liners over their enumerators; `_can_build_stable(p, cost)` introduced and `_has_stable_placement` deleted, with three call sites migrated.
- `_new_grid_with_cell` helper added to `resolution.py`; `_execute_plow`, `_execute_build_stable` (post-Task-5D version), and `_execute_build_room` all use it instead of inline tuple comprehensions.

---

# Part 7 — Order of work

Each step should leave the test suite green before proceeding.

1. **Part 1 Change 1** — add `auto_pop` field. All existing `COMMIT_SUBACTION_HANDLERS` entries become 3-tuples with `auto_pop=True`. Update `_apply_commit_subaction` to read the flag. No behavior change; all 315 existing tests pass.
2. **Part 1 Change 2** — absorb `CommitBuildMajor`: register it in `COMMIT_SUBACTION_HANDLERS` with `auto_pop=False`, move the conditional pop/push into `_execute_build_major`, delete the `_apply_action` branch. `tests/test_major_improvement.py` passes unchanged.
3. **Part 1 Change 3** — add `ROOM_COSTS` to `constants.py`; add `_can_afford(p, cost)` helper to `legality.py`; refactor `_can_afford_room` to read from both. No behavior change.
4. **Part 1 Change 4** — predicate-enumerator deduplication: add `_legal_room_cells(p)`, refactor `_can_plow` and `_has_room_placement` to one-liners over their enumerators, introduce `_can_build_stable(p, cost)`, migrate three call sites of `_has_stable_placement` (`_legal_farm_expansion`, `_legal_side_job`, `_enumerate_pending_side_job`), delete `_has_stable_placement`. No behavior change. (`_enumerate_pending_build_stable` does not need migration — it returns `_legal_stable_cells(p)` directly without calling `_has_stable_placement`.)
5. **Part 1 Change 5** — add `_new_grid_with_cell` helper in `resolution.py`; migrate `_execute_plow` to use it. No behavior change.
6. **Part 2 — multi-shot pendings (dead-code coexistence with `PendingBuildStable`)**:
   - Add `PendingBuildStables` and `PendingBuildRooms` dataclasses (and `CommitBuildRoom` action class).
   - Add `_execute_build_stables` (with the pasture recompute) and `_execute_build_room` effect functions.
   - Add `_enumerate_pending_build_stables` and `_enumerate_pending_build_rooms`; register both in `PENDING_ENUMERATORS`.
   - `COMMIT_SUBACTION_HANDLERS[CommitBuildStable]` is NOT yet re-pointed — it still maps to `(PendingBuildStable, _execute_build_stable, True)`. The new code exists but no `_choose_subaction_*` handler pushes the new pendings, so the dead-code coexistence is harmless. All 315 existing tests pass.
7. **Part 4 — Side Job migration + `PendingBuildStable` retirement** (must precede Part 3 to avoid a dispatch table conflict — see rationale below):
   - Update `_choose_subaction_side_job` to push `PendingBuildStables(max_builds=1)` instead of `PendingBuildStable`.
   - Delete old `_execute_build_stable` (singular).
   - Rename the new `_execute_build_stables` → `_execute_build_stable` (now that the singular name is free; mechanical rename within `resolution.py` since the old function is just gone).
   - Update `COMMIT_SUBACTION_HANDLERS[CommitBuildStable]` to point at `(PendingBuildStables, _execute_build_stable, False)` — note the now-singular function name.
   - Delete `PendingBuildStable` and `_enumerate_pending_build_stable`, and their entries in the dispatch dicts.
   - Update `tests/test_side_job.py` to expect the new commit-then-Stop trace.
   - All tests pass (with the test_side_job.py updates). The final state has `_execute_build_stable` (singular, matching the function-name prefix taxonomy convention).
8. **Part 3 — Farm Expansion wiring** (now safe because the dispatch table accepts `PendingBuildStables`):
   - Add `PendingFarmExpansion` dataclass and to the union.
   - Add `_initiate_farm_expansion`, `_choose_subaction_farm_expansion`, `_enumerate_pending_farm_expansion`; register in `NONATOMIC_HANDLERS`, `CHOOSE_SUBACTION_HANDLERS`, `PENDING_ENUMERATORS`.
   - `_legal_farm_expansion` already migrated in step 4 — no additional edit needed.
   - Remove `farm_expansion` from the `NotImplementedError` list in `_apply_place_worker`.
9. **Part 5 (new file) — `tests/test_farm_expansion.py`**. All new tests pass.
10. **Part 6 — documentation**. CLAUDE.md and CHANGES.md updates in one commit.

After step 10, `step()` raises `NotImplementedError` only for `farm_redevelopment` and `fencing`.

**Why Part 4 (step 7) precedes Part 3 (step 8).** Once `_choose_subaction_farm_expansion` lands (Part 3), `PendingBuildStables` can be pushed to the stack. But `_apply_commit_subaction` asserts `isinstance(top, expected_pending_type)` against the type registered in `COMMIT_SUBACTION_HANDLERS[CommitBuildStable]`. If that entry still points at the singular `PendingBuildStable` when `PendingBuildStables` is on top, the assertion fails. So the dispatch table update — which is bundled with retiring `PendingBuildStable` — must happen before Farm Expansion's choose handler is wired.

---

# Part 8 — Acceptance criteria

- All 315 pre-existing tests pass (with `tests/test_side_job.py` updated to the new trace shape).
- New `tests/test_farm_expansion.py` passes.
- `step()` raises `NotImplementedError` only for `PlaceWorker(space="farm_redevelopment")` and `PlaceWorker(space="fencing")`.
- `random_agent_play` over **seeds 0–99** completes without raising. Run **before** any code changes (baseline; Farm Expansion is not in `IMPLEMENTED_NON_ATOMIC_SPACES` yet, so it's not selected) AND **after** all changes land (regression check). Add a coverage assertion that, across the 100 post-change seeds, `"farm_expansion"` is selected by the random agent in at least one trace — guards against silent regressions in `filter_implemented` / `IMPLEMENTED_NON_ATOMIC_SPACES`.
- `PendingBuildStable` (singular) is fully removed from the codebase — no references in `pending.py`, `resolution.py`, `legality.py`, `engine.py`, or any test file.
- `_apply_action` has no `isinstance(action, CommitBuildMajor)` branch.
- CLAUDE.md reflects the architecture after this task: multi-shot pending pattern documented, Farm Expansion in the status table, `_execute_build_major` listed as a `COMMIT_SUBACTION_HANDLERS` entry rather than a special case.
- CHANGES.md has a new Change 6 entry covering all five Part 1 refactors (auto_pop, _execute_build_major absorption, ROOM_COSTS + _can_afford, predicate-enumerator dedup + _can_build_stable, _new_grid_with_cell), the multi-shot pending pattern, the PendingBuildStable retirement, and the pasture-cache fix.

---

# Appendix A — Out of scope

- **Farm Redevelopment** and **Fencing** non-atomic resolution. Farm Redevelopment will reuse `PendingRenovate` and the future `PendingBuildFences`; Fencing introduces `PendingBuildFences` and the deferred fence-configuration legality. Both remain `NotImplementedError`.
- **Harvest phases** (HARVEST_FIELD, HARVEST_FEED, HARVEST_BREED) and rounds 5–14.
- **Once-per-turn card pattern**. Sketched during Task 5D design conversation: a future `triggered_this_turn: frozenset[str]` field on `PlayerState`, cleared in `_apply_place_worker`, populated by once-per-turn cards' `apply_fn`s. The card's `eligibility_fn` would check both the per-frame `triggers_resolved` (a future field on the relevant pending — see the next bullet — that prevents re-firing on the same event instance) and the per-player `triggered_this_turn` (prevents re-firing across event instances within a turn). No Family-game card needs this today; both fields and the lifecycle are deferred until the first such card lands.
- **Atomic-space trigger hosting** (phase tracking, phase-transition mechanism) — open questions documented in CLAUDE.md "Card implementation status".
- **Compound-card interactions** (Pan-Baker × Potter-Ceramics-style cross-card eligibility broadening) — speculative-legality machinery not built.
- **Card-trigger machinery on the new pendings.** `PendingFarmExpansion`, `PendingBuildStables`, and `PendingBuildRooms` are introduced **without** `triggers_resolved` fields or `TRIGGER_EVENT` classvars. When the first card needing to fire on `"before_build_stable"`, `"before_build_room"`, or `"before_farm_expansion"` is implemented, the relevant pending(s) gain the field + classvar at that time, and the question of whether the field persists across commits or resets per commit is settled then (current expectation: persists, per the rules interpretation that the multi-shot is "one action").
- **Card-specific pending classes** beyond Potter Ceramics. No new cards are added in this task.
