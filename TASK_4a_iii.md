# Task 4a-iii — Cache `pastures` on `Farmyard`

> **Note (out of date):** This task document specifies the `__post_init__`
> auto-fill mechanism for the `Farmyard.pastures` cache. That mechanism was
> subsequently disabled in `CHANGES.md` Change 3. The cache itself remains
> (the `pastures` field is still on `Farmyard`, accessed via
> `farmyard.pastures`), but it is no longer auto-filled — pasture-changing
> resolvers now recompute and pass `pastures=compute_pastures_from_arrays(...)`
> explicitly when constructing a new `Farmyard`, and all other `Farmyard`
> mutations leave `pastures` alone (it rides along correctly via
> `dataclasses.replace`). See `CHANGES.md` Change 3 for the full rationale.
> The body of this task document is preserved as the original specification.

This task changes the `Farmyard` dataclass to store its pasture decomposition as a derived-but-cached field. The cache is automatically (re)computed by `__post_init__` every time a `Farmyard` is constructed, including via `dataclasses.replace(...)`. Production code does not pass `pastures` to the constructor — the field fills itself from the grid + fence arrays.

## Motivation

`compute_pastures` runs a BFS flood-fill over the 3×5 farmyard each call. It is invoked by `extract_slots` (and through it by `can_accommodate`, `pareto_frontier`, and `breeding_frontier`) and by `scoring.score`. Once non-atomic legality lands (Task 4b), it will also be hit on every legality enumeration in MCTS — likely millions of times per self-play game.

The BFS itself is microseconds, but the data (`tuple[Pasture, ...]`) is small, immutable, and changes only when the player builds fences or places a stable. That is a textbook "derive once, cache, share by reference" situation, especially because:

- `Farmyard` is a frozen dataclass shared by reference across MCTS subtrees.
- All other action resolutions (resource gain, taking workers, etc.) leave `Farmyard` unchanged, so the cached `pastures` tuple is shared by reference too.
- With auto-fill `__post_init__`, sync invariants are physically impossible to violate: every construction recomputes the cache, and there is no way to end up with a stale cache.

This deviates from the "derived data, not cached data" principle in CLAUDE.md, which is intentional — see the discussion in the design session that produced this task. The cache is the lowest-level "fundamental" form of the pasture data; everything else (`enclosed_cells`, `pasture_capacities`, `num_pastures`, `fenced_stables`) is a one-line derivation from `farmyard.pastures` and is **not** cached separately.

## Scope

**In scope**
- Move `Pasture` and the pasture BFS into a new `agricola/pasture.py` module (avoids circular import once `Farmyard` references `Pasture`).
- Add `pastures: tuple = ()` to `Farmyard` with auto-fill `__post_init__`.
- Drop the `compute_pastures(farmyard)` wrapper from `helpers.py`. Replace its call sites with direct `farmyard.pastures` access.
- Add `enclosed_cells(farmyard) -> frozenset[tuple[int, int]]` in `helpers.py` for legality code.
- Update tests that import `Pasture` to import from `agricola.pasture` directly.
- Add new tests covering the auto-fill behavior.

**Out of scope** (deferred)
- Any non-atomic action implementation (Fencing, Farm Expansion stable build, Farmland field placement). The cache makes those easier, but they are TASK_4b and beyond.
- Caching anything else (`enclosed_cells`, `pasture_capacities`, etc.) on `Farmyard`.
- Changing `Pasture` itself (its `cells`, `num_stables`, `capacity` fields stay as they are).

## Decisions

### D1. Module layout

Move `Pasture` and the BFS into `agricola/pasture.py`.

```python
# agricola/pasture.py
from __future__ import annotations
from dataclasses import dataclass
from collections import deque

from agricola.constants import CellType


@dataclass(frozen=True)
class Pasture:
    cells: frozenset
    num_stables: int
    capacity: int


def compute_pastures_from_arrays(
    grid: tuple,
    horizontal_fences: tuple,
    vertical_fences: tuple,
) -> tuple[Pasture, ...]:
    """BFS flood-fill from outside the farmyard; returns canonically ordered tuple."""
    ...
```

`compute_pastures_from_arrays` takes raw arrays so it can be called from inside `Farmyard.__post_init__` without needing a `Farmyard` first. It must not import from `agricola.state` (circularity). It reads `grid[r][c].cell_type` via duck typing (no `Cell` import needed) and imports only `CellType` from `agricola.constants`.

### D2. Auto-fill `__post_init__` on `Farmyard`

`pastures` is declared with a placeholder default. `__post_init__` always recomputes it from the inputs and writes it via `object.__setattr__` (the documented Python escape hatch for filling derived fields on frozen dataclasses).

```python
# agricola/state.py
from agricola.pasture import Pasture, compute_pastures_from_arrays

@dataclass(frozen=True)
class Farmyard:
    grid: tuple
    horizontal_fences: tuple
    vertical_fences: tuple
    pastures: tuple = ()  # auto-filled by __post_init__; do not pass directly

    def __post_init__(self):
        computed = compute_pastures_from_arrays(
            self.grid, self.horizontal_fences, self.vertical_fences,
        )
        object.__setattr__(self, "pastures", computed)
```

Consequences:
- All call sites construct farmyards normally: `Farmyard(grid=g, horizontal_fences=h, vertical_fences=v)`. They never pass `pastures`.
- `dataclasses.replace(farmyard, grid=new_grid)` works correctly. `replace` invokes the constructor on the new instance, which invokes `__post_init__`, which recomputes `pastures` from the new grid. No stale-cache bug is possible.
- A caller who explicitly passes `pastures=...` will have their value silently overwritten. This is a hypothetical risk; no legitimate code path does this.
- No `make_farmyard` helper is needed.

### D3. Canonical ordering of `pastures`

`compute_pastures_from_arrays` returns the pastures sorted by `min(p.cells)` (lexicographic on `(row, col)`). This guarantees two equivalent farmyards produce equal `pastures` tuples, which is required for `Farmyard.__eq__` and hashing to work correctly across MCTS.

### D4. (removed)

This decision concerned not having a default for `pastures`. Auto-fill makes it moot — the placeholder default is fine because the value is always overwritten in `__post_init__`.

### D5. (removed)

This decision concerned banning `dataclasses.replace(farmyard, …)`. Auto-fill makes it moot — `replace` always produces a consistent farmyard because `__post_init__` recomputes the cache.

### D6. Drop the `compute_pastures(farmyard)` wrapper

The existing `compute_pastures(farmyard)` function in `helpers.py` is removed. Call sites read `farmyard.pastures` directly. This is clearer at the read site (it's obviously a stored field) and avoids the misleading appearance of an expensive call.

There are exactly two production call sites and six test call sites (see "Code changes" §3 and §6). All are updated to direct attribute access.

### D7. Drop the `Pasture` re-export

`Pasture` is imported only from its real home (`agricola.pasture`). The single existing import site (`tests/test_helpers.py:9`) is updated to `from agricola.pasture import Pasture`. No re-export is added in `helpers.py`.

## Code changes

### 1. Create `agricola/pasture.py`

New file. Contents:

- `Pasture` dataclass (moved from `helpers.py`, identical fields).
- `compute_pastures_from_arrays(grid, horizontal_fences, vertical_fences) -> tuple[Pasture, ...]`:
  1. Flood-fill from outside the grid (same algorithm as today's `compute_pastures`).
  2. Identify connected components among enclosed cells.
  3. For each component, count stables in `grid[r][c].cell_type == CellType.STABLE` and compute `capacity = 2 * len(component) * (2 ** num_stables)`.
  4. Build `Pasture` objects.
  5. Return them as a tuple sorted by `min(cells)` (lexicographic). Empty tuple if no enclosures.

Imports: only `dataclasses.dataclass`, `collections.deque`, and `agricola.constants.CellType`. No `agricola.state` import (would be circular).

### 2. Update `agricola/state.py`

- Add `from agricola.pasture import compute_pastures_from_arrays` at the top.
- Add `pastures: tuple = ()` field to `Farmyard`.
- Add `Farmyard.__post_init__` (auto-fill, see D2 snippet).
- Update the docstring/comment block above `Farmyard` to mention the auto-filled cache.

### 3. Update `agricola/helpers.py`

- Remove the local `Pasture` class and the BFS body (now in `pasture.py`).
- Remove `compute_pastures(farmyard)` entirely.
- Remove the now-orphaned `_are_connected` helper if it was only used by the BFS. (Audit: `_are_connected` should move to `pasture.py` alongside the BFS, since the BFS is its only caller.)
- Update `extract_slots`: replace `pastures = compute_pastures(player_state.farmyard)` with `pastures = player_state.farmyard.pastures`.
- Add a new helper:
  ```python
  def enclosed_cells(farmyard) -> frozenset:
      """Return the set of (row, col) coordinates that are inside any pasture."""
      result: set = set()
      for p in farmyard.pastures:
          result.update(p.cells)
      return frozenset(result)
  ```
- Update the module's imports: drop `from collections import deque` if it was only used by the BFS, drop the `Pasture` class definition.

### 4. Update `agricola/setup.py`

No changes needed. `_make_farmyard` already calls `Farmyard(grid=..., horizontal_fences=..., vertical_fences=...)` without passing `pastures`, which is exactly the new convention. The auto-fill `__post_init__` will populate `pastures=()` for the fresh farmyard correctly.

### 5. Update `agricola/scoring.py`

- Replace `pastures = compute_pastures(farmyard)` (line ~140) with `pastures = farmyard.pastures`.
- Drop the `from agricola.helpers import compute_pastures` import.

### 6. Update tests

#### `tests/test_helpers.py`

- Change the `Pasture` import from `from agricola.helpers import (..., Pasture, ...)` to `from agricola.pasture import Pasture` (separate line). Drop `Pasture` from the helpers import.
- Drop `compute_pastures` from the helpers import.
- Replace every `compute_pastures(farmyard)` call (6 sites) with `farmyard.pastures`.
- Specifically: `compute_pastures(farmyard) == []` becomes `farmyard.pastures == ()`. Other tuple-iteration uses (`pastures = farmyard.pastures`) work unchanged.

#### `tests/test_scoring.py`

- No `compute_pastures` calls. No `Pasture` import. No changes needed.

#### `tests/test_state.py`

- Add a new test `test_fresh_farmyard_has_empty_pastures`: assert `setup(seed).players[0].farmyard.pastures == ()`.

#### `tests/test_resolution_atomic.py` and `tests/test_legality_atomic.py`

- Both contain `dataclasses.replace(player.farmyard, grid=new_grid)` for the room-adding helper. With auto-fill, this is now correct as-is — the new farmyard's `pastures` is recomputed from the new grid. No edits required.

#### New tests in `tests/test_helpers.py` (or new `tests/test_pasture.py`)

- `test_pastures_auto_filled_on_construction`: build a farmyard with a 1×1 enclosure via the normal constructor, assert `farmyard.pastures` has the expected single `Pasture`.
- `test_pastures_auto_filled_on_dataclasses_replace`: start with a no-fence farmyard, do `dataclasses.replace(farmyard, horizontal_fences=h_with_enclosure, vertical_fences=v_with_enclosure)`, assert the result's `pastures` reflects the new fences.
- `test_pastures_auto_filled_on_grid_change_adds_stable`: start with a farmyard that has a 1×1 pasture at `(0,0)`, no stable; do `dataclasses.replace(farmyard, grid=grid_with_stable_at_(0,0))`; assert the new pasture has `num_stables=1, capacity=4`. **This is the key test motivating auto-fill.**
- `test_pastures_canonical_order`: build a farmyard with two enclosed regions; assert `farmyard.pastures` is sorted by `min(p.cells)`.

### 7. Documentation

- `CLAUDE.md`:
  - Update the `Farmyard` description (line 161) to mention `pastures` as an auto-filled cached field.
  - Update the `helpers.py` description (lines ~187–204): drop the `compute_pastures` line, drop `Pasture` (now lives elsewhere), add `enclosed_cells`. Explain that `extract_slots` now reads from `farmyard.pastures` directly.
  - Update the `scoring.py` description if it mentions `compute_pastures`.
  - Add `agricola/pasture.py` to the Directory Structure listing and add a per-file description.
  - Add a brief note in the "Key Design Principles" section acknowledging this as the one accepted exception to "derived data, not cached data," with a one-line rationale and pointer to CHANGES.md.
- `IMPLEMENTATION_CHOICES.md`: add an entry explaining (a) why we cache `pastures` on `Farmyard` rather than `PlayerState` or `Cell`, (b) why we cache only `pastures` and derive everything else, (c) the canonical-ordering decision, and (d) the auto-fill `__post_init__` choice over validate-only.
- `CHANGES.md`: add a Change 2 entry summarizing this refactor (motivation, scope, file-by-file changes, outcome — to be filled in after implementation). Note the rename from `compute_pastures(farmyard)` → `farmyard.pastures`.
- Historical docs (`TASK_2.md`, `ARCHITECTURE.md`, `SESSION_HISTORY.md`, `TESTS.md`): leave wording alone. CHANGES.md is the canonical record of the rename.

## Suggested implementation order

1. Create `agricola/pasture.py` with `Pasture`, `_are_connected` (if moved), and `compute_pastures_from_arrays`. No tests yet.
2. Update `agricola/state.py`: import from `pasture.py`, add `pastures` field with default, add `__post_init__`. Tests will fail to import `Pasture`/`compute_pastures` from helpers in this intermediate state.
3. Update `agricola/helpers.py`: remove local `Pasture`, remove `compute_pastures`, add `enclosed_cells`, update `extract_slots`.
4. Update `agricola/scoring.py`: replace `compute_pastures(farmyard)` with `farmyard.pastures`, drop the import.
5. Update `tests/test_helpers.py`: fix imports, replace 6 `compute_pastures` calls.
6. Run all tests. Expect everything to pass.
7. Add the 4 new tests covering auto-fill and ordering.
8. Add `test_fresh_farmyard_has_empty_pastures` to `tests/test_state.py`.
9. Run all tests again.
10. Update CLAUDE.md, IMPLEMENTATION_CHOICES.md, CHANGES.md.

## Acceptance criteria

- All previously-passing tests still pass without semantic changes (only import/access updates allowed).
- New tests above all pass, including the stable-added-via-`dataclasses.replace` test.
- No `compute_pastures(farmyard)` reference remains in production code or tests. Audit by `grep -nE "\bcompute_pastures\b"` — should match only `compute_pastures_from_arrays` plus historical doc files.
- `farmyard.pastures` is the canonical access pattern at every read site.
- The `Farmyard` constructor and `dataclasses.replace(farmyard, …)` both produce farmyards with a correctly-computed `pastures` cache, with no caller discipline required.
- `Pasture` is defined in exactly one place (`agricola/pasture.py`) and imported from there everywhere.
