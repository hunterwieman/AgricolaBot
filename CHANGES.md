# AgricolaBot — Planned and Completed Changes

This is a living document recording significant refactors and design changes — things that cut across multiple files or require coordinated edits. Each entry describes the motivation, the full list of code changes required, and (once done) the outcome and any tests added or updated.

For the record of completed task implementations see `SESSION_HISTORY.md`.
For implementation decisions that may need revisiting when cards are introduced see `IMPLEMENTATION_CHOICES.md`.

---

## Table of Contents

- [Change 1 — Replace `accumulated_goods: int` with `accumulated: Resources` on accumulation spaces](#change-1)
- [Change 2 — Cache the pasture decomposition on `Farmyard`; remove the public `compute_pastures(farmyard)` function](#change-2)
- [Change 3 — Disable auto-fill `__post_init__` on `Farmyard`; pasture-changing resolvers recompute `pastures` explicitly](#change-3)
- [Change 4 — Dispatch refactor and pending provenance](#change-4)
- [Change 5 — Choose-time flag-setting, provenance prefix scheme, and Bake Bread expansion](#change-5)

---

<a name="change-1"></a>
## Change 1 — Replace `accumulated_goods: int` with `accumulated: Resources` on building-resource accumulation spaces

**Status:** Completed (session 3)

**Motivation:**
Some cards (e.g. the Geologist occupation) allow a building resource to be placed a space that normally accumulates building resources of a different type. The current `accumulated_goods: int` field can only represent one resource type, inferred implicitly from the space ID. Replacing it with `accumulated: Resources` makes the accumulation explicit and generic — the Geologist just changes the `Resources` object that gets added each round, with no special-casing in resolution.

As a side effect, this eliminates the `getattr`/`**kwargs` dynamic lookup pattern in `_resolve_accumulation` (see `IMPLEMENTATION_CHOICES.md #7`), replacing it with a direct `Resources.__add__` call.

**Scope:** Building-resource accumulation spaces only (`forest`, `clay_pit`, `reed_bank`, `western_quarry`, `eastern_quarry`). Animal and food accumulation spaces (`sheep_market`, `pig_market`, `cattle_market`, `fishing`, `meeting_place`) keep their existing `accumulated_goods: int` field — these spaces are never modified by cards in the same way.

---

### Outcome

All 9 files updated as planned. 110 tests pass (6 new `Resources.__add__` / `__bool__` tests added to `test_state.py`; all pre-existing 104 tests continue to pass).

Per-file changes:

- **`agricola/resources.py`** (new file): `Resources` and `Animals` extracted from `state.py`. `Resources.__add__` returns a fresh frozen instance (safe with frozen dataclasses, does not mutate either operand); `Resources.__bool__` enables `if space.accumulated:` legality checks, replacing `accumulated_goods > 0`.
- **`agricola/state.py`**: `Resources` and `Animals` class definitions removed; `from agricola.resources import Resources, Animals` added. In `ActionSpaceState`: `accumulated: Resources = Resources()` field added alongside the existing scalar field (which stays for animal/food spaces); the scalar field renamed `accumulated_goods` → `accumulated_amount`.
- **`agricola/constants.py`**: `from agricola.resources import Resources` added (no circular import: `resources.py` imports nothing from `agricola`). `ACCUMULATION_RATES` replaced by `BUILDING_ACCUMULATION_RATES: dict[str, Resources]` (5 building-resource spaces: `forest`/`clay_pit`/`reed_bank`/`western_quarry`/`eastern_quarry`, with values like `Resources(wood=3)`) and `FOOD_ANIMAL_ACCUMULATION_RATES: dict[str, tuple]` (5 food/animal spaces: `fishing`/`meeting_place`/`sheep_market`/`pig_market`/`cattle_market`, scalar). `ACCUMULATION_SPACES` derived as the frozenset union of the two dicts' keys.
- **`agricola/setup.py`**: `_make_action_spaces` dispatches on the two new dicts. Building-resource spaces are pre-loaded with their `Resources` increment for round 1 (`accumulated=BUILDING_ACCUMULATION_RATES[space_id]`); all other spaces get `accumulated=Resources()` (default). The scalar field for food/animal spaces is initialised as before.
- **`agricola/legality.py`**: five building-resource predicates changed from `accumulated_goods > 0` to `bool(space.accumulated)` (uses `Resources.__bool__`). Food/animal space predicates (`_legal_fishing` etc.) continue to check the scalar field unchanged.
- **`agricola/resolution.py`**: `_resolve_accumulation` + `getattr`/`**kwargs` dynamic lookup pattern removed (see `IMPLEMENTATION_CHOICES.md #7`). Replaced by `_resolve_building_accumulation` (uses `p.resources + space_state.accumulated`, then resets `accumulated=Resources()`) and `_resolve_food_accumulation` (uses `p.resources + Resources(food=amount)`). `ACCUMULATION_RATES` import removed; `from agricola.resources import Resources` added.
- **`tests/test_legality_atomic.py`, `tests/test_resolution_atomic.py`**: `_reveal_space` helper updated to dispatch on `isinstance(accumulated, Resources)` vs `int` (now accepts a `Resources` object for building-resource spaces; defaults derive from `BUILDING_ACCUMULATION_RATES[space_id]` or are passed explicitly at call sites). `_reveal_space_no_goods` renamed to `_reveal_space_empty` (passes `accumulated=Resources()`). All accumulation assertions updated: `accumulated_goods == 1` → `accumulated == Resources(...)`, `accumulated_goods == 0` after resolution → `accumulated == Resources()`.
- **`tests/test_helpers.py`, `tests/test_scoring.py`, `agricola/helpers.py`**: import of `Resources`/`Animals` updated to use `resources.py`.


---

<a name="change-2"></a>
## Change 2 — Cache the pasture decomposition on `Farmyard`; remove the public `compute_pastures(farmyard)` function

**Status:** Completed (session adding pasture cache).

**Motivation:**
The `compute_pastures` BFS flood-fill was previously called on demand by `extract_slots` (and through it by `can_accommodate`, `pareto_frontier`, `breeding_frontier`) and by `scoring.score`. Once non-atomic legality lands (Task 4b), it will additionally be called on every legality enumeration in MCTS — likely millions of times per self-play game. Caching the pasture decomposition on `Farmyard` removes the repeated BFS at zero risk to correctness, because (a) `Farmyard` is a frozen dataclass shared by reference across MCTS subtrees, so the cached tuple is shared too, and (b) auto-fill `__post_init__` makes the cache invariant physically impossible to violate.

This is the project's first deliberate exception to the "Derived data, not cached data" principle in CLAUDE.md. The exception is specifically scoped to the most fundamental form of pasture data; everything else (`enclosed_cells`, capacities, count, fenced-stable count) remains derived from the cache on demand.

**Scope:**
- `Pasture` dataclass and the BFS moved out of `helpers.py` into a new `agricola/pasture.py` (avoids circular import once `Farmyard` references the BFS).
- New `Farmyard.pastures: tuple[Pasture, ...]` field, auto-filled by `Farmyard.__post_init__` via `object.__setattr__` (the documented Python escape hatch for derived fields on frozen dataclasses).
- Public `compute_pastures(farmyard)` removed. Call sites read `farmyard.pastures` directly.
- New helper `enclosed_cells(farmyard) -> frozenset[(row, col)]` in `helpers.py` for legality code.
- Canonical pasture ordering by `min(p.cells)` so equivalent farmyards always produce equal `pastures` tuples (required for `Farmyard.__eq__` / hashing).

**Design choice — auto-fill vs. validate-only:**
Two designs for `__post_init__` were considered:
1. **Validate-only:** caller passes `pastures` explicitly; `__post_init__` recomputes and asserts the passed value matches.
2. **Auto-fill:** caller never passes `pastures`; `__post_init__` always recomputes and writes the cache via `object.__setattr__`.

Auto-fill won because validate-only would fire false-alarm assertions on the very common pattern `dataclasses.replace(farmyard, grid=new_grid)` whenever the new grid changed stable counts inside an existing pasture (e.g. when the future stable-build resolver runs). Auto-fill makes that pattern correct by construction. The only downside is hypothetical: a caller who explicitly passes `pastures=...` to `Farmyard(...)` will have their value silently overwritten — but no legitimate code path does this.

---

### Outcome

116 tests pass (110 pre-existing tests continue to pass; 6 new tests added — 5 in `test_helpers.py`, 1 in `test_state.py`). Reads of the cached decomposition are O(1); construction (including `dataclasses.replace`) recomputes the cache automatically. Canonical pasture ordering by `min(p.cells)` ensures `Farmyard.__eq__` and hashing work correctly across MCTS.

Per-file changes:

- **`agricola/pasture.py`** (new file): owns the `Pasture` frozen dataclass (`cells: frozenset`, `num_stables: int`, `capacity: int`) and `compute_pastures_from_arrays(grid, horizontal_fences, vertical_fences) -> tuple[Pasture, ...]`. The BFS algorithm is unchanged from the previous `compute_pastures(farmyard)` body; it now takes raw arrays so it can be called from inside `Farmyard.__post_init__` without needing a `Farmyard` first. Also exports a private `_are_connected(horizontal_fences, vertical_fences, r1, c1, r2, c2)`. Imports only from `agricola.constants` (for `CellType`); reads `grid[r][c].cell_type` via duck typing and never imports `Cell`, keeping it free of any circular dependency on `state.py`. The returned tuple is sorted by `min(p.cells)` lexicographically so equivalent farmyards always produce equal `pastures` tuples.
- **`agricola/state.py`**: `from agricola.pasture import compute_pastures_from_arrays` added. Field `pastures: tuple = ()` added to `Farmyard` (placeholder default; always overwritten in `__post_init__`). `Farmyard.__post_init__` added — calls `compute_pastures_from_arrays` and writes the result via `object.__setattr__(self, "pastures", computed)` (the documented Python escape hatch for derived fields on frozen dataclasses). Inline comment on the `pastures` field documents the auto-fill convention and points at this CHANGES.md entry.
- **`agricola/helpers.py`**: local `Pasture` class removed; `_are_connected` removed (moved into `pasture.py`); `compute_pastures(farmyard)` removed entirely. Now-unused imports dropped (`from collections import deque`, `from dataclasses import dataclass`). `enclosed_cells(farmyard) -> frozenset[(row, col)]` added — returns the union of all `p.cells` for `p in farmyard.pastures` (used by legality code). `extract_slots` now reads `pastures = player_state.farmyard.pastures` directly.
- **`agricola/scoring.py`**: `from agricola.helpers import compute_pastures` dropped. `score(...)` now reads `pastures = farmyard.pastures` directly.
- **`tests/test_helpers.py`, `tests/test_state.py`**: updated; 5 new tests added in `test_helpers.py` (auto-fill behaviour, canonical ordering, `enclosed_cells` round-trip) and 1 in `test_state.py` (`test_fresh_farmyard_has_empty_pastures`).

---

<a name="change-3"></a>
## Change 3 — Disable auto-fill `__post_init__` on `Farmyard`; pasture-changing resolvers recompute `pastures` explicitly

**Status:** Completed (current session).

**Motivation:**
Change 2 made `Farmyard.pastures` a cached field auto-filled in `__post_init__`, so the BFS runs on every `Farmyard` construction. Most farmyard mutations cannot change pastures — room-builds, plows, sows, renovations, and any other grid mutation that doesn't add a stable inside a pasture all currently pay the BFS cost unnecessarily. The number of mutations of this form will grow significantly once Task 4b-ii (non-atomic resolution) lands.

After this change, the BFS runs only when an action that *can* change pastures runs. Four resolvers (Fencing, Farm Expansion's stable build, Side Job's stable build, Farm Redevelopment's fence build) gain a one-line `pastures=compute_pastures_from_arrays(...)` in their `Farmyard` construction; every other resolver is unchanged. The structural invariant from Change 2 is dropped in favour of a per-resolver convention.

**Trade-off being made:**
*Gained:* measurable BFS savings on most farmyard mutations. The exact magnitude is small in absolute terms — the BFS is sub-microsecond on a 3×5 grid — but the proportion of mutations that pay it drops from "all" to "the small subset that can actually change pastures."

*Given up:* the structural guarantee from Change 2 that `Farmyard.pastures` is correct by construction. After this change, the cache invariant is enforced by caller discipline. Forgetting to update `pastures` in a pasture-changing resolver produces a silently-wrong cache that does not crash and does not fail any local test — the same failure mode CLAUDE.md's "Derived data, not cached data" principle was originally written to prevent.

The user judges this trade acceptable given the small, fixed list of pasture-changing resolvers in the Family game. This change does **not** retract Change 2 — the `Farmyard.pastures` field stays, and the "first accepted exception to derived-not-cached" framing in CLAUDE.md stays. What changes is the *mechanism* by which the cache is kept consistent: auto-fill → caller discipline.

**Scope — list of pasture-changing resolvers:**
The set of resolvers that must explicitly recompute `pastures` when constructing a new `Farmyard`:

1. **Fencing** (Task 4b-ii, not yet implemented). Adds one or more fences. Can create, subdivide, or extend pastures.
2. **Farm Expansion (Build Stable)** (Task 4b-ii, not yet implemented). Adds a STABLE cell. Changes pastures iff the cell is currently inside a pasture (changes `num_stables` and `capacity` on that pasture).
3. **Side Job (Build Stable)** (Task 4b-ii, not yet implemented). Same shape as above.
4. **Farm Redevelopment** (Task 4b-ii, not yet implemented). Optionally adds fences after renovation. Same shape as Fencing.

The renovate-only part of House Redevelopment and Farm Redevelopment does **not** touch the farmyard — `house_material` lives on `PlayerState`. No `Farmyard` construction happens at all in that path. Atomic resolvers (`agricola/resolution.py`) do not construct new `Farmyard` objects, so they are unaffected.

---

### Outcome

170 tests pass (177 → 170; 7 auto-fill-specific tests deleted, no new tests added).

Per-file changes:

- **`agricola/state.py`**: `Farmyard.__post_init__` is commented out (per the user's request that it not be deleted, so the original implementation remains visible in source as a reference). The inline comment on the `pastures: tuple = ()` field is updated to describe the new convention and points back at this CHANGES.md entry. The full commented-out body is preserved in `state.py`. The `from agricola.pasture import compute_pastures_from_arrays` import at the top of the file is left in place — harmless and convenient for any future state-level code that needs to recompute.
- **`tests/test_helpers.py`**: import updated to `from agricola.pasture import Pasture, compute_pastures_from_arrays` (added `compute_pastures_from_arrays`; the unused `Pasture` import was then removed). `_make_farmyard` helper updated to compute `pastures` explicitly via `compute_pastures_from_arrays(grid, hf, vf)` and pass it through — this restores correct cache behaviour for every test that uses the helper without requiring per-test edits. **Deleted 7 auto-fill-specific tests** whose assertions can no longer hold without auto-fill: `test_pastures_auto_filled_on_construction`, `test_pastures_auto_filled_on_dataclasses_replace_fences`, `test_pastures_auto_filled_on_grid_change_adds_stable`, `test_replace_adds_fence_creates_pasture`, `test_replace_adds_internal_fence_subdivides_pasture`, `test_replace_adds_stable_outside_pasture_no_change`, `test_replace_adds_second_stable_inside_existing_pasture`. The first three were Change 2's original auto-fill tests; the last four were the additional auto-fill tests added later in the same session as TASK_4b insurance. Their reason for existence (proving auto-fill works) is gone. **Kept** `test_pastures_canonical_order` and `test_equivalent_farmyards_compare_equal_and_hash_equal`: both rely on the `_make_farmyard` helper to produce correct pastures and exercise the canonical-ordering / structural-equality guarantee that MCTS subtree sharing depends on. The section header above them was updated to reflect that pastures are now populated by the helper rather than by `__post_init__`.
- **`tests/test_legality_non_atomic.py`**: three test helpers (`_set_grid`, `_enclose_cell`, `_enclose_rect`) were calling `dataclasses.replace(farmyard, ...)` and relying on auto-fill to recompute `pastures`. Each was updated to compute `pastures` explicitly via `compute_pastures_from_arrays(...)` and pass it through. Import of `compute_pastures_from_arrays` added.
- **`tests/test_scoring.py`**: has its own local `_make_farmyard` helper duplicated from `test_helpers.py`. Updated identically — import `compute_pastures_from_arrays` and pass the BFS result through to the `Farmyard` constructor.

**Things deliberately not done:**
- Loud failure when `pastures=...` is passed inconsistently with `(grid, fences)`. The current behavior is silent acceptance; this change preserves it. Adding validation would be a separate, future change.

**Convention for pasture-changing resolvers (Task 4b-ii reference):**

```python
from agricola.pasture import compute_pastures_from_arrays

new_farmyard = dataclasses.replace(
    old_farmyard,
    horizontal_fences=new_hf,        # or grid=new_grid for stable-builds
    vertical_fences=new_vf,
    pastures=compute_pastures_from_arrays(new_grid_or_old_grid, new_hf, new_vf),
)
```

---

<a name="change-4"></a>
## Change 4 — Dispatch refactor and pending provenance

**Status:** Completed (Task 5B).

Reorganized resolution-layer code, replaced the per-`Commit*` apply handlers with a single generic dispatcher, and added provenance metadata to pending dataclasses. Touched five modules; behavior is unchanged (all 236 existing tests pass after the work, modulo `initiated_by_id=` kwargs added to a handful of `Pending*` construction calls in test bodies).

**Code relocations.** Per-space resolution code now lives uniformly in `agricola/resolution.py` — atomic handlers (already there), non-atomic initiators (`_initiate_<space>`), choose-sub-action handlers (`_choose_subaction_<space>`), and sub-action effect functions (`_execute_<sub_action>`). The function-pointer dispatch tables `NONATOMIC_HANDLERS` and `CHOOSE_SUBACTION_HANDLERS` moved from `engine.py` to `resolution.py` to sit with their handler functions (joining the existing `ATOMIC_HANDLERS`). Stack helpers (`push`, `pop`, `replace_top`) moved from `engine.py` to `pending.py`, where they sit with the dataclasses they manipulate; underscores were dropped since they now cross module boundaries. `_resolve_grain_utilization` was renamed `_initiate_grain_utilization` to honestly describe what it does (push a pending and exit; the actual resolution happens later via committed sub-actions).

**`CommitSubAction` hierarchy.** Added a frozen-dataclass marker base `CommitSubAction` in `agricola/actions.py`. `CommitSow` and `CommitBake` inherit from it. The engine dispatches them uniformly through a single `_apply_commit_subaction` handler driven by a new `COMMIT_SUBACTION_HANDLERS` metadata table in `engine.py` (co-located with the dispatcher; the table's values are `(expected_pending_type, parent_flag, effect_fn)` tuples, not raw function pointers). `_apply_action` now has exactly five branches. Adding a new `Commit*` sub-action requires no changes to `_apply_action` — only a new dataclass, a new effect function, and a new row in the table.

**Pending provenance fields.** Every pending class now carries an `initiated_by_id: str` mandatory instance field (identifies what pushed this frame) and a `PENDING_ID: ClassVar[str]` class attribute (identifies the kind of pending). The generic commit dispatcher uses these for an identity check when writing to the parent: it sets `parent_flag=True` on the new top frame only if the popped frame's `initiated_by_id` matches the new top's `PENDING_ID` and the named field exists on the new top (checked via `parent_flag in type(parent).__dataclass_fields__`). The check lets card-driven cross-cutting sub-actions land harmlessly on unrelated parents in the future card system.

**Conventions established.** Function-name prefixes (`_resolve_<atomic>` / `_initiate_<nonatomic>` / `_choose_subaction_<space>` / `_execute_<sub_action>`); non-atomic spaces always push a parent pending (for sub-action progress tracking and for hosting the space's card trigger event); space-ids and card-ids share a single namespace with collision validated at card-registration time; trigger event names follow `"before_<PENDING_ID>"` / `"after_<PENDING_ID>"`. See `TASK_5B_DISPATCH_CLEANUP.md` Part 2 for the full conventions and forward-compat notes for the card system.

---

<a name="change-5"></a>
## Change 5 — Choose-time flag-setting, provenance prefix scheme, and Bake Bread expansion

**Status:** Completed (Task 5C).

Five convention shifts plus the implementation of eight new non-atomic action spaces (Farmland, Cultivation, Side Job, Sheep/Pig/Cattle Markets, Major Improvement, House Redevelopment). The convention shifts are described here; per-space implementation details live in `TASK_5C.md`.

**Choose-time flag-setting.** The convention for setting parent `*_chosen` flags shifted from the commit dispatcher (`_apply_commit_subaction` in `engine.py`) to the `_choose_subaction_*` handlers in `resolution.py`. Each handler now does `replace_top(state, dataclasses.replace(parent, <action>_chosen=True))` before pushing the sub-action pending. The commit dispatcher's old "after pop, check identity + field-existence, set flag" block was removed. `COMMIT_SUBACTION_HANDLERS` entries shrank from 3-tuples `(expected_pending_type, parent_flag, effect_fn)` to 2-tuples `(expected_pending_type, effect_fn)`. Field names renamed: `sow_done`→`sow_chosen`, `bake_done`→`bake_chosen` on `PendingGrainUtilization`. The motivation is reader locality (flag management adjacent to the push that creates the sub-action) and removing structural coupling between the dispatcher and parent dataclass fields.

**Provenance prefix scheme.** `initiated_by_id` values now use a namespaced prefix:
- Top-level pendings pushed by `PlaceWorker`: `"space:<space_id>"` (was `"worker_placement"`).
- Card-pushed top-level pendings: `"card:<card_id>"` (new convention; not exercised by current code).
- Sub-action pendings pushed by `ChooseSubAction`: unchanged (still the parent's `PENDING_ID`).

The `"worker_placement"` reserved-string carve-out is eliminated; the `"space:"` and `"card:"` prefixes are disjoint by construction.

**`Resources.__sub__` operator.** Added alongside the existing `__add__` and `__bool__`. Same return-new-not-mutate semantics. Allows the pure-subtraction sites to use `p.resources - cost` instead of the 7-field-negated-component pattern. Migration: `_execute_sow` was updated from `p.resources + Resources(grain=-grain, veg=-veg)` to `p.resources - Resources(grain=grain, veg=veg)`. New effect functions in this task use the cleaner form for pure subtraction; mixed subtract-and-add sites (`_execute_bake`, `potter_ceramics._apply`) stay in the single-`Resources` form with negative components — splitting them would add operands without clarity gain.

**Bake Bread support for Clay Oven and Stone Oven.** `_execute_bake` previously raised `NotImplementedError` for Clay-Oven-only or Stone-Oven-only owners and used a hardcoded best-of-Hearth-or-Fireplace rate. It now does greedy-by-rate allocation across all owned baking improvements. The per-improvement specs live in a new `BAKING_IMPROVEMENT_SPECS` dict in `agricola/constants.py` keyed by major_idx, with `(max_grain_per_action, food_per_grain)` tuples. `BAKING_IMPROVEMENTS` migrated from `legality.py` to `constants.py`. `MAJOR_IMPROVEMENT_COSTS` (a tuple indexed by major_idx) was also added to `constants.py`. The greedy allocator consults `baking_specs_for_player`, a new helper in `legality.py` that combines the major-keyed specs with a card-extension registry (`BAKING_SPEC_EXTENSIONS`); cards that add baking sources (e.g., the Iron Oven minor improvement) register via `register_baking_spec_extension(fn)` without touching `_execute_bake` or `_enumerate_pending_bake_bread`. `_enumerate_pending_bake_bread` consults the same helper to compute the per-action grain cap.

**Bug fix in `_execute_renovate`.** The renovation cost was changed from `Resources(<material>=num_rooms, reed=num_rooms)` (the original draft) to `Resources(<material>=num_rooms, reed=1)`. Per RULES.md (clarified during the design pass) and the existing `_can_renovate` legality check, the reed cost is 1 total, not per-room. RULES.md was reworded to "1 clay per room + 1 reed" / "1 stone per room + 1 reed" with an explicit parenthetical to remove the ambiguity.

**Sub-action cost handling pattern.** Two new sub-action pendings carry a `cost: Resources` field set at push time by the choose handler: `PendingBuildStable` (cost specified by the calling space — 1 wood for Side Job) and `PendingRenovate` (cost computed from the player's house material and room count). The effect function reads `pending.cost` and debits via `p.resources - pending.cost`. This pattern lets future cards modify the cost (either at push time by an alternative choose handler, or via a trigger between push and commit by `replace_top`-ing the pending) without changing the effect function. `PendingBuildMajor` uses a different pattern (cost looked up in `MAJOR_IMPROVEMENT_COSTS` keyed by `commit.major_idx`); the choice of pattern is documented in CLAUDE.md "Additional Design Principles" → "Sub-action cost handling".

**Outcome.** 315 tests pass (up from 236 baseline). New tests: `tests/test_bake_bread.py` (16 parametrized cases covering the greedy allocator and extension registry), `tests/test_farmland.py` (8), `tests/test_cultivation.py` (7), `tests/test_side_job.py` (8), `tests/test_animal_markets.py` (13 parametrized across the three markets), `tests/test_major_improvement.py` (9 integration tests), `tests/test_house_redevelopment.py` (10), plus `__sub__` tests in `tests/test_state.py` (6) and updated assertions in `tests/test_grain_utilization.py` and `tests/test_potter_ceramics.py` for the renamed flags. `step()` no longer raises `NotImplementedError` for any of the eight new spaces; only Farm Expansion, Farm Redevelopment, and Fencing remain deferred.
