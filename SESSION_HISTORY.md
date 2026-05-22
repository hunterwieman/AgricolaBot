# AgricolaBot — Session History

This file records the full history of what was built, why, and how. Future sessions should read this alongside ARCHITECTURE.md and the TASK_*.md files to understand the current state of the codebase.

---

## Table of Contents

- [Task 1 — State Dataclasses + Setup](#task-1)
- [Task 2 — Pastures, Slots, Accommodation, Pareto Frontier](#task-2)
- [Task 3 — Cooking Rates, Modified pareto_frontier, breeding_frontier](#task-3)
- [Bugs Caught and Fixed (session 2)](#bugs-session-2)
- [Testing Principles Established (session 2)](#testing-principles)
- [Features Implemented Beyond Spec](#beyond-spec)
- [Test Count by File](#test-count)
- [Task 4a-i — State Additions + Atomic-Space Legality](#task-4a-i)
- [Task 4a-ii — Atomic-Space Resolution](#task-4a-ii)
- [Change 1 — Resources Refactor](#change-1)
- [Cleanups 1–3 — State Field Cleanups](#cleanups-1-3)
- [Change 2 — Pasture Cache on `Farmyard`](#change-2)
- [Documentation and tone refinements](#doc-tone-refinements)
- [Additional Auto-Fill Cache Tests](#auto-fill-extra-tests)
- [Task 4b-i — Non-Atomic Legality](#task-4b-i)
- [Change 3 — Disable Auto-Fill `__post_init__` on `Farmyard`](#change-3)
- [Documentation cascade for Change 3](#change-3-doc-cascade)
- [Task 5 — The `step` Function, Pending Stack, Grain Utilization, Potter Ceramics](#task-5)
- [Task 5B — Dispatch Cleanup](#task-5b)
- [Task 5C — Eight Non-Atomic Spaces + Convention Shifts](#task-5c)
- [Task 5D — Farm Expansion + Multi-Shot Sub-Action Pendings](#task-5d)
- [Task 6_pre — Fencing Universe Enumeration](#task-6-pre)
- [Task 6 — Fencing, Build Fences, and Farm Redevelopment](#task-6)
- [Task 7 design — Harvest spec + breeding_frontier Pareto-dim fix](#task-7-design)
- [Task 7 design follow-up — breeding_frontier revert + "Preserving optionality" principle](#task-7-design-followup)
- [Task 7 implementation — Harvest phases + rounds 5–14 + Cooking-Hearth fix + non-negative invariant](#task-7-impl)
- [Hashability refactor — `BoardState.action_spaces` dict → canonical tuple](#hashability-refactor)
- [Engine performance pass — profiling, `fast_replace`, `legal_actions_cache`, assertion gate](#perf-pass)
- [Current State](#current-state)

---

<a name="task-1"></a>
## Task 1 — State Dataclasses + Setup (completed in session 1)

### What was built

- `agricola/__init__.py` — empty package marker
- `agricola/constants.py` — all enums and constants
- `agricola/state.py` — all frozen dataclasses
- `agricola/setup.py` — `setup(seed) -> GameState`
- `tests/__init__.py` — empty
- `tests/test_state.py` — 11 tests covering setup correctness

### Key design decisions

All state objects use `@dataclass(frozen=True)`. State is never mutated; transitions produce new objects using `dataclasses.replace()`. This is required for safe structural sharing in MCTS.

The seeded RNG is `numpy.random.default_rng(seed)`. It is passed explicitly to any sub-function that needs it; no global state.

### Features implemented beyond ARCHITECTURE.md / task files

**`STAGE_ROUNDS` constant in `constants.py`**: A convenience dict mapping stage number (1–6) to the round range that stage occupies:

```python
STAGE_ROUNDS = {
    1: range(1, 5),   # rounds 1–4
    2: range(5, 8),   # rounds 5–7
    3: range(8, 10),  # rounds 8–9
    4: range(10, 12), # rounds 10–11
    5: range(12, 14), # rounds 12–13
    6: range(14, 15), # round 14
}
```

This is used in `test_setup_stage_ordering` to avoid hardcoding round numbers in the test body. It was not specified in any task file but was added as a natural convenience.

**Two TODOs noted in `state.py`**:
- `pending_decision` field in `GameState` — will be needed for multi-step actions (e.g. fencing, which requires multiple fence placement decisions)
- Animal location tracking in `PlayerState` — currently animals are tracked as totals only; a small number of full-game cards reference specific animal locations

---

<a name="task-2"></a>
## Task 2 — Pastures, Slots, Accommodation, Pareto Frontier (completed in session 1)

### What was built

All additions are in `agricola/helpers.py` and `tests/test_helpers.py`.

- `Pasture` dataclass: `cells: frozenset`, `num_stables: int`, `capacity: int`
- `compute_pastures(farmyard) -> list[Pasture]`
- `extract_slots(player_state) -> (list[int], int)`
- `can_accommodate(pasture_capacities, num_flexible, sheep, boar, cattle) -> bool`
- `pareto_frontier(player_state, gained) -> list[Animals]` (later extended in Task 3)

### compute_pastures algorithm

BFS flood-fill from outside the farmyard. Seed from border cells that are open (no fence on the outer edge). BFS propagates cell-to-cell only when there is no fence between them. Any cell not reached from outside is enclosed. Connected components among enclosed cells = pastures. Capacity formula: `2 × num_cells × (2 ^ num_stables)`.

The outer fence check is: `horizontal_fences[0][c]` for the top boundary, `horizontal_fences[3][c]` for the bottom, `vertical_fences[r][0]` for the left, `vertical_fences[r][5]` for the right.

The cell-to-cell fence check (`_are_connected`) uses the shared edge:
- Cell above to cell below: `horizontal_fences[r2][c]` (the row index of the lower cell)
- Cell left to cell right: `vertical_fences[r][c2]` (the column index of the right cell)

### extract_slots logic

```python
total_stables_built = 4 - stables_in_supply(farmyard)
stables_in_pastures = sum(p.num_stables for p in pastures)
standalone_stables = total_stables_built - stables_in_pastures
num_flexible = standalone_stables + 1  # +1 always for house pet
```

The house pet slot is always present regardless of farm configuration. Standalone stables (unfenced) each add 1 flexible slot.

### can_accommodate logic

Brute-force `itertools.product(range(4), repeat=n)` over all assignments of animal types to pastures (0=empty, 1=sheep, 2=boar, 3=cattle). For each assignment, compute dedicated capacity per type and total overflow. If any assignment has `overflow <= num_flexible`, return True.

This is O(4^n) in number of pastures. In practice a player has at most 6 pastures (15 fences / 4 sides minimum = ~3, but subdivision is possible), so this is always fast.

### Why the Pareto frontier?

When a player gains animals (or enters the breeding phase), they must decide how many of each type to keep. Excess animals can be cooked for food using a Fireplace or Cooking Hearth — but since cooking is available at any time, there is never a reason to cook more than necessary at the moment of gaining animals. The optimal time to cook is exactly when food is needed: the feeding phase of harvest. This means the animal-gain decision and the cooking decision can be separated: first choose how many animals to keep, then cook later as needed.

This separation justifies restricting attention to the Pareto frontier over `(sheep, boar, cattle)`. A configuration is on the frontier if no other achievable configuration has at least as many of every animal type and strictly more of at least one. Any configuration off the frontier is dominated — there exists a strictly better one — so a rational agent would never choose it.

Food is not a third axis of the frontier. Given a fixed `(sheep, boar, cattle)` endpoint and known cooking rates, the food generated from the discarded animals is fully determined — there is no further choice. Food is therefore computed as a deterministic output for each frontier point rather than being optimised over. The agent picks whichever `(Animals, food)` pair it prefers, with the understanding that more kept animals is always at least as good as fewer (dominance), and the food values only matter for comparing points that keep equal animals in some types.

### pareto_frontier (Task 2 version)

Enumerates all `(s, b, c)` where `0 ≤ s ≤ s_available`, etc., that pass `can_accommodate`. Keeps non-dominated points. Original return type was `list[Animals]` — changed to `list[tuple[Animals, int]]` in Task 3.

---

<a name="task-3"></a>
## Task 3 — Cooking Rates, Modified pareto_frontier, breeding_frontier (completed in session 2)

### What was built

All additions are in `agricola/helpers.py` and `tests/test_helpers.py`.

- `cooking_rates(state, player_idx) -> tuple[int, int, int]`
- Extended `pareto_frontier` with `rates` parameter and food return value
- `breeding_frontier(player_state, rates=(0,0,0)) -> list[tuple[Animals, int]]`
- `agricola/scoring.py` with `ScoreBreakdown`, `score`, `tiebreaker`
- `tests/test_scoring.py` — 8 tests

### cooking_rates

```python
owners = state.board.major_improvement_owners
has_hearth    = any(owners[i] == player_idx for i in (2, 3))
has_fireplace = any(owners[i] == player_idx for i in (0, 1))

if has_hearth:
    return (2, 3, 4)
elif has_fireplace:
    return (2, 2, 3)
else:
    return (0, 0, 0)
```

Hearth always wins over Fireplace (strictly better rates for every animal type).

### pareto_frontier extension

Return type changed from `list[Animals]` to `list[tuple[Animals, int]]`. Food is computed after identifying Pareto-optimal points:

```python
food = (s_available - sF) * sR + (b_available - bF) * bR + (c_available - cF) * cR
```

The Pareto frontier itself (which configurations are non-dominated) is unchanged — it is still computed over animal counts only. Food is purely deterministic from the frontier point and the rates.

**Breaking change**: all callers and tests had to be updated to unpack `(Animals, int)` tuples.

### breeding_frontier

Called at the start of the breeding phase. The key difference from `pareto_frontier` is that the "upper bound" comes from the breeding rule, not from an external gain:

```python
s_desired = s + 1 if s >= 2 else s
b_desired = b + 1 if b >= 2 else b
c_desired = c + 1 if c >= 2 else c
```

Food formula uses two branches per animal type:

```python
food_s = (s + 1 - sF) * sR if (s >= 2 and sF >= 3) else (s - sF) * sR
```

The condition `s >= 2 and sF >= 3` is the exact indicator that breeding fired for sheep. If the player ended with ≥ 3 sheep and started with ≥ 2, the newborn was kept. The player ate `(s + 1 - sF)` sheep pre-breeding. If the condition is false (either breeding didn't fire, or the player ate enough sheep to prevent it), the player ate `(s - sF)` sheep.

### scoring.py features

**`_craft_bonus_spending(state, player_idx) -> (int, dict)`**: Private helper that computes craft building bonus points (Joinery idx 7, Pottery idx 8, Basketmaker's idx 9) and tracks resources consumed for the tiebreaker. Not explicitly specified in any task file — extracted to avoid code duplication between `score` and `tiebreaker`.

Craft building tiers for Joinery/Pottery/Basketmaker's:
- 0–1 of the resource: 0 bonus pts, 0 spent
- 2–3: 1 bonus pt, resource cost consumed (e.g. 2 wood for Joinery tier 1)
- 4–5: 2 bonus pts
- 6+: 3 bonus pts

**`tiebreaker`**: Returns `wood + clay + reed + stone` after subtracting resources spent on craft bonuses. Food is excluded from the tiebreaker.

```python
def tiebreaker(state, player_idx) -> int:
    res = state.players[player_idx].resources
    _, spent = _craft_bonus_spending(state, player_idx)
    return (res.wood - spent.get("wood", 0)) + (res.clay - spent.get("clay", 0)) \
         + (res.reed - spent.get("reed", 0)) + res.stone
```

---

<a name="bugs-session-2"></a>
## Bugs Caught and Fixed (session 2)

### 1. test_breeding_food_from_excess — invalid starting state

**Original code**: `animals=Animals(sheep=4)` with a 1×1 pasture (capacity 2) + house (1 flex). Maximum capacity is 3. Starting with 4 sheep is physically impossible.

**User's observation**: "test_breeding_food_from_excess seems confusing to me. How do we start with 4 sheep if capacity is 3?"

**User's suggestion**: "why not have one unfenced stable since unfenced stables each hold 1 animal of any type? You could also have a 2x1 pasture and also have a cow, so you have 4 sheep in the pasture and 1 cow in the house. Then we will have two pareto points and one of them is what we want."

**First attempted fix**: standalone stable at (1,3) + 1×1 pasture at (0,0) + house (1 flex). This gave max capacity 4 (pasture) + 2 flex = 6, so both sheep=4 + cattle=1 + newborn sheep fit, giving a single frontier point (5,0,1). Not the desired two-point frontier.

**Final fix**: 2×1 pasture (cells (0,0) and (0,1), capacity 4) + house only (1 flex). Starting state: sheep=4, cattle=1. Capacity: 4 in pasture + 1 in house = 5 total, but mixed types are constrained. sheep=4 fills the pasture; cattle=1 goes in the house. s_desired=5, c_desired=2. The two Pareto-optimal configurations are:
- (5, 0, 0): sheep breeds (4→5), cattle eaten. sF=5≥3 and s=4≥2, so food_s=(4+1-5)×2=0. But c=1<2 so no cattle breeding; cF=0, food_c=(1-0)×3=3. Total food=3. Wait — rates used in test are (2,0,0) for sheep only. food_c=0. food_s=0. Total=0. ✓
- (4, 0, 1): keep cattle in house, sheep fills pasture. sF=4≥3 and s=4≥2, so food_s=(4+1-4)×2=2. cF=1, food_c=0. Total=2. ✓

Final assertion:
```python
assert frontier_dict == {(5, 0, 0): 0, (4, 0, 1): 2}
```

### 2. Membership-only assertions in breeding tests

Several breeding frontier tests only checked `assert (x,y,z) in frontier_dict` rather than `assert frontier_dict == {(x,y,z): food}`. This meant a function returning extra, incorrect points would still pass.

**User's observation**: "test_breeding_food_from_excess seems to check only if (4,0,1) is included in the set of pareto points, not if the entire set of pareto points is correct. Is my reading of this correct? If so can you fix it so that you verify the entire answer?"

**Fix**: All breeding frontier tests now use exact dict equality:
- `test_breeding_sheep_only_breeds`: `assert frontier_dict == {(1, 0, 0): 0}`
- `test_breeding_sheep_breeds_with_room`: `assert frontier_dict == {(3, 0, 0): 0}`
- `test_breeding_food_from_excess`: `assert frontier_dict == {(5, 0, 0): 0, (4, 0, 1): 2}`
- `test_breeding_worked_example`: `assert frontier_dict == {(0, 5, 0): 0}`
- `test_breeding_formula_sF_ge_3`: `assert frontier_dict == {(3, 0, 0): 2}`
- `test_breeding_formula_sF_lt_3`: `assert frontier_dict == {(1, 0, 0): 4}`

### 3. Circular test validation

For `test_breeding_worked_example`, the expected frontier value was initially derived by running `breeding_frontier` in a shell command. This is circular — it uses the function under test to produce the gold standard.

**User's policy**: "I am happy with you calculating them as long as you are confident in the method you are using. You shouldn't use the method to generate the answers for the tests of that method."

**Resolution**: All expected values are now derived by hand from game rules. For `test_breeding_worked_example`: b=4, farm has cap-4 pasture + cap-2 pasture + house (1 flex). b_desired=5. Assigning pasture-0 (cap 4) to boar: dedicated boar = 4, overflow = 1 ≤ 1 flex → bF=5 fits. No other configuration keeps 5 boar. (0,5,0) dominates all lower points. food=(4+1-5)×2=0. Therefore `{(0,5,0): 0}`.

---

<a name="testing-principles"></a>
## Testing Principles Established (session 2)

These were not specified in any task file. They were established during this session and should be followed in all future test work.

### 1. Exact frontier assertions

All tests for `pareto_frontier` and `breeding_frontier` must assert the **complete** frontier dict, not just membership of specific points. Pattern:

```python
frontier_dict = {(a.sheep, a.boar, a.cattle): food for a, food in frontier}
assert frontier_dict == {(s, b, c): expected_food}
```

### 2. Hand-derived expected values

Expected values in tests must be derived from game rules by hand, not by running the function under test. Shell commands (`python -c`) are acceptable for exploratory discovery, but the final expected value must be verifiable by reading the rules and computing manually.

### 3. Physically valid starting states

Starting states in tests must be physically achievable. Animals must fit in the farm's current capacity. A test that begins with `animals=Animals(sheep=4)` on a farm that holds at most 3 sheep is invalid — it would never arise in a real game and may produce misleading test results.

---

<a name="beyond-spec"></a>
## Features Implemented Beyond ARCHITECTURE.md / Task Files

Summary of everything that was built that is not explicitly specified in ARCHITECTURE.md, TASK_2.md, or TASK_3.md:

| Feature | File | Notes |
|---|---|---|
| `STAGE_ROUNDS` constant | `constants.py` | Convenience dict, stage → round range. Used in `test_setup_stage_ordering`. |
| `TODO: pending_decision` | `state.py` | Noted for multi-step actions in future game loop. |
| `TODO: animal location tracking` | `state.py` | Noted for full-game card support. |
| `_craft_bonus_spending` helper | `scoring.py` | Private helper extracted from `score` and reused by `tiebreaker`. Not specified. |
| `test_extract_slots_standalone_stable` | `test_helpers.py` | Tests the standalone stable path of `extract_slots`. Not in any test spec. |
| Exact-frontier-dict assertion pattern | `test_helpers.py` | Stronger than TASK_3.md required (which only said "checks that X is in the frontier"). |
| Hand-derived expected values policy | all test files | Testing discipline established in session, not in any spec. |
| Physically valid starting states policy | all test files | Testing discipline established in session, not in any spec. |

---

## Test Count by File (after Task 3)

| File | Tests |
|---|---|
| `tests/test_state.py` | 11 |
| `tests/test_helpers.py` | 34 |
| `tests/test_scoring.py` | 8 |
| `tests/test_legality_atomic.py` | 27 |
| **Total** | **80** |

See `TESTS.md` for the full description of every test.

---

<a name="task-4a-i"></a>
## Task 4a-i — State Additions + Atomic-Space Legality (completed in session 3)

### What was built

- `agricola/actions.py` — `PlaceWorker` frozen dataclass and `Action` type alias
- `agricola/legality.py` — `legal_atomic_placements(state)` with per-space predicates and shared cross-cutting helper
- `tests/test_legality_atomic.py` — 27 tests covering all 12 atomic spaces

### State changes

**`ActionSpaceState`**: replaced `occupied_by: Optional[int]` with `workers: tuple[int, int]` — a length-2 count tuple `(player_0_count, player_1_count)`. See `IMPLEMENTATION_CHOICES.md #1` for rationale and caveats.

**`PlayerState`**: added `newborns: int = 0` — workers born this round, used only for harvest feeding cost (1 food instead of 2). Included in `people_total` immediately when a Wish for Children action resolves.

**`GameState`**: added `next_starting_player: int` — stages the next round's starting player token. Updated when Meeting Place is taken; applied at the start of each new round. Distinct from `starting_player` because Meeting Place can be taken mid-round before the current round's turn order is complete.

**`constants.py`**: added `ACCUMULATION_SPACES` (frozenset derived from `ACCUMULATION_RATES`) and `PERMANENT_ACTION_SPACES_SET` (frozenset of permanent space IDs).

### Legality design

Cross-cutting check (`_is_available`): unoccupied (`workers == (0, 0)`) and revealed (`round_revealed <= round_number`). Per-space predicates add accumulation-goods checks or family-size checks on top. Dispatch table `ATOMIC_LEGALITY` maps each atomic space string to its predicate.

Atomic spaces in scope: `day_laborer`, `fishing`, `forest`, `clay_pit`, `reed_bank`, `grain_seeds`, `meeting_place`, `western_quarry`, `vegetable_seeds`, `eastern_quarry`, `basic_wish_for_children`, `urgent_wish_for_children`. Non-atomic spaces deferred to later tasks.

### Bugs fixed during implementation

**Manual `GameState(...)` construction in old tests**: `test_helpers.py` and `test_scoring.py` both had helper functions that constructed `GameState` by listing every field explicitly. Adding `next_starting_player` broke these. All such helpers were migrated to `dataclasses.replace(state, ...)`, which is robust to future field additions.

### New documents created

- `IMPLEMENTATION_CHOICES.md` — records implementation decisions that may need revision when cards are introduced. Initial entries: worker encoding, animal location tracking, string vs enum IDs, `future_food` generalisation, newborn counting.

### Task 4a-i was originally written by another author and reviewed for conflicts before implementation. Conflicts resolved:
- `ActionSpaceId` enum replaced with plain strings (consistent with existing code)
- `Board` renamed to `BoardState`
- `occupants`/`accumulation`/`revealed_spaces` replaced with `workers` on `ActionSpaceState` and `round_revealed` already in `ActionSpaceState`
- `unplaced_workers` replaced with existing `people_home`
- `family_size` replaced with existing `people_total`
- `active_player` replaced with existing `current_player`
- `ACCUMULATION_RATES` redefinition removed
- `next_starting_player` and `newborns` retained (genuinely new)
- Worker encoding changed from flat index tuple to count tuple per discussion

---

<a name="task-4a-ii"></a>
## Task 4a-ii — Atomic-Space Resolution (completed in session 3)

### What was built

- `agricola/resolution.py` — `resolve_atomic(state, action)` with per-space resolution handlers and cross-cutting placement bookkeeping
- `tests/test_resolution_atomic.py` — 24 tests covering all 12 atomic spaces, cross-cutting invariants, edge cases, and Wish-specific assertions

### Design

**`_apply_worker_placement(state, space_id)`**: cross-cutting helper. Increments `workers[ap]` on the action space and decrements `people_home` on the active player. Called by `resolve_atomic` before dispatching to per-space handlers. Currently private to `resolution.py` — see `IMPLEMENTATION_CHOICES.md #6`.

**`_resolve_accumulation(state, space_id)`**: shared handler for the 8 accumulation spaces. Looks up the resource field name via `ACCUMULATION_RATES[space_id][0]`, applies `getattr`/`**kwargs` dynamic update, and resets `accumulated_goods` to 0. See `IMPLEMENTATION_CHOICES.md #7`.

**Wish handlers (`_resolve_wish_for_children`)**: after `_apply_worker_placement` has placed the parent (workers[ap] == 1), this handler adds the newborn: workers[ap] becomes 2, `people_total += 1`, `newborns += 1`. `people_home` is NOT incremented for the newborn (it is on the space, not at home).

**Meeting Place**: calls `_resolve_accumulation` then sets `next_starting_player = ap`. `starting_player` is not changed.

**Dispatch table `ATOMIC_HANDLERS`**: exactly 12 entries, one per atomic space.

### Internal utilities

`_update_player(state, ap, new_player)` and `_update_space(state, space_id, **kwargs)` — thin wrappers around `dataclasses.replace` that handle the chain of nested object replacements (ActionSpaceState → action_spaces dict → BoardState → GameState, or PlayerState → players tuple → GameState).

### New IMPLEMENTATION_CHOICES.md entries added

- **#6**: `_apply_worker_placement` visibility decision (keep private until Task 4b)
- **#7**: accumulation handler `getattr`/`**kwargs` dynamic resource lookup

---

<a name="test-count"></a>
## Test Count by File

| File | Tests |
|---|---|
| `tests/test_state.py` | 11 |
| `tests/test_helpers.py` | 34 |
| `tests/test_scoring.py` | 8 |
| `tests/test_legality_atomic.py` | 27 |
| `tests/test_resolution_atomic.py` | 24 |
| **Total** | **104** |

---

<a name="change-1"></a>
## Change 1 — Resources Refactor (completed in session 3)

### What changed

See `CHANGES.md` for the full cross-cutting change plan and outcome notes. Summary:

- **New file `agricola/resources.py`**: `Resources` and `Animals` extracted from `state.py`. `Resources.__add__` (returns new frozen instance) and `Resources.__bool__` (enables `if space.accumulated:`) added.
- **`constants.py`**: `ACCUMULATION_RATES` split into `BUILDING_ACCUMULATION_RATES: dict[str, Resources]` (building-resource spaces) and `FOOD_ANIMAL_ACCUMULATION_RATES: dict[str, tuple]` (food/animal spaces).
- **`state.py`**: `ActionSpaceState` gains `accumulated: Resources = Resources()` alongside the kept `accumulated_goods: int = 0`. `Resources`/`Animals` imports redirected to `resources.py`.
- **`setup.py`**: `_make_action_spaces` dispatches on the two new constants dicts.
- **`legality.py`**: building-resource predicates use `bool(space.accumulated)`.
- **`resolution.py`**: `getattr`/`**kwargs` pattern removed; replaced by `_resolve_building_accumulation` and `_resolve_food_accumulation`.
- **Test files**: helpers and assertions updated throughout.

### Motivation

Some cards (e.g. Geologist occupation) allow stone to accumulate on a space that normally accumulates clay. The `accumulated: Resources` field makes this trivial — the Geologist just sets a different `Resources` increment object. No special-casing needed in resolution.

### Tests added

6 new `Resources.__add__` / `__bool__` tests in `test_state.py`. All 104 pre-existing tests continue to pass.

---

<a name="test-count-after-change-1"></a>
## Test Count by File (after Change 1)

| File | Tests |
|---|---|
| `tests/test_state.py` | 17 |
| `tests/test_helpers.py` | 34 |
| `tests/test_scoring.py` | 8 |
| `tests/test_legality_atomic.py` | 27 |
| `tests/test_resolution_atomic.py` | 24 |
| **Total** | **110** |

---

<a name="cleanups-1-3"></a>
## Cleanups 1–3 — State Field Cleanups (completed in session 4)

These cleanups were specified in `CLEANUP.md` and implemented in code during session 3 but tests were not run until session 4. All three are cross-cutting changes to `state.py` and the files that depend on it.

### Cleanup 1 — Move `house_material` from `Cell` to `PlayerState`

**Motivation**: `house_material` is a property of the entire house, not of individual cells. Storing it on `Cell` created redundancy (the same value on every room cell) and required keeping all room cells in sync whenever the house was renovated.

**Changes**:
- `Cell`: `house_material: HouseMaterial` field removed. `Cell` now has only `cell_type`, `grain`, `veg`.
- `PlayerState`: `house_material: HouseMaterial` field added (between `farmyard` and `people_total`).
- `setup.py` `_make_farmyard()`: `Cell(cell_type=CellType.ROOM)` — no `house_material` kwarg.
- `setup.py` `_make_player(food)`: `house_material=HouseMaterial.WOOD` added.

**Test fixes required** (25 failures revealed when tests were run):
- `tests/test_scoring.py`: 6 `PlayerState(...)` constructions that listed all fields explicitly were missing `house_material`. Added `house_material=ps.house_material` to each (using `dataclasses.replace` was impractical here since these tests deliberately modify most fields). Also 2 `Cell(cell_type=CellType.ROOM, house_material=HouseMaterial.WOOD)` calls — `house_material` kwarg removed.
- `tests/test_helpers.py`: `_make_player` local helper missing `house_material=HouseMaterial.WOOD`. One inline `PlayerState(...)` at line 479 also fixed. `HouseMaterial` was already imported so no import change was needed.

### Cleanup 2 — Rename `accumulated_goods` to `accumulated_amount` on `ActionSpaceState`

**Motivation**: `accumulated_goods` was ambiguous and inconsistent. `accumulated_amount` better reflects that this is a scalar integer count (for food/animal accumulation spaces), distinct from `accumulated` which is a `Resources` object (for building-resource spaces).

**Changes**: Field rename on `ActionSpaceState` in `state.py`. All references in `setup.py`, `legality.py`, `resolution.py`, and test files updated.

### Cleanup 3 — Remove `next_starting_player` from `GameState`

**Motivation**: `next_starting_player` was introduced to stage the starting player token update for the following round. On review, this was redundant: Meeting Place can update `starting_player` immediately (mid-round) without affecting current-round turn order, because `current_player` drives whose turn it is. Removing `next_starting_player` simplifies the state and eliminates a synchronization obligation in the round-transition logic.

**Changes**:
- `GameState`: `next_starting_player` field removed.
- `resolution.py` Meeting Place handler: now sets `starting_player = ap` directly instead of `next_starting_player = ap`.
- `test_resolution_atomic.py` Meeting Place test: assertion updated to check `starting_player` directly.

### All 110 tests pass after these fixes.

---

<a name="change-2"></a>
## Change 2 — Pasture Cache on `Farmyard` (completed in undated prior session)

### What changed

See `CHANGES.md` Change 2 for the full plan and outcome notes. Summary:

- **New file `agricola/pasture.py`**: `Pasture` frozen dataclass and `compute_pastures_from_arrays(grid, h_fences, v_fences)` extracted from `helpers.py`. The BFS algorithm is unchanged; it now takes raw arrays so `Farmyard.__post_init__` can call it without circular imports. Returns the pasture tuple sorted canonically by `min(p.cells)`.
- **`state.py`**: `Farmyard` gains a fourth field `pastures: tuple = ()`. A new `__post_init__` recomputes `pastures` from the inputs and writes it via `object.__setattr__` (the documented Python escape hatch for derived fields on frozen dataclasses). Production callers never pass `pastures`; the cache is auto-filled on every construction including `dataclasses.replace(...)`.
- **`helpers.py`**: dropped local `Pasture`, `_are_connected`, and `compute_pastures(farmyard)`. Added `enclosed_cells(farmyard) -> frozenset[(row, col)]` for legality code. `extract_slots` now reads `player_state.farmyard.pastures` directly.
- **`scoring.py`**: dropped the `compute_pastures` import; `score(...)` reads `farmyard.pastures` directly.
- **`setup.py`**: no changes — `_make_farmyard()` already constructed `Farmyard` without passing `pastures`, matching the new convention.
- **Tests**: `test_helpers.py` redirects `Pasture` import to `agricola.pasture`; replaces 6 `compute_pastures(farmyard)` call sites with `farmyard.pastures`; renames a local variable to avoid shadowing the new `enclosed_cells` import. 5 new tests cover auto-fill behavior (including the key scenario of adding a stable inside an existing pasture via `dataclasses.replace`) plus canonical ordering and the `enclosed_cells` helper. `test_state.py` adds 1 test for fresh-farmyard empty cache.

### Motivation

`compute_pastures` is hit on every legality enumeration in MCTS (likely millions of times per self-play game). The cache turns repeated O(n) BFS work into O(1) reads. With auto-fill `__post_init__`, the cache invariant is physically impossible to violate: every construction recomputes from ground-truth, every `dataclasses.replace(...)` recomputes correctly, and there is no caller-discipline rule that can be forgotten.

### Design choices made along the way

1. **Cache `pastures` rather than per-cell `is_in_pasture`.** Per-cell would force every fence-build to reconstruct `Farmyard.grid` (new `Cell` objects, new row tuples), breaking structural sharing across MCTS subtrees for the most-frequently-mutated piece of state.
2. **Cache on `Farmyard` rather than `PlayerState`.** The cache is a pure function of fence and grid arrays, both of which live on `Farmyard`. Co-locating cache and inputs minimizes the sync-rule blast radius.
3. **Cache only `pastures`; derive `enclosed_cells`, capacities, count, and fenced-stable count on demand.** `pastures` is the most fundamental form; everything else is a one-line derivation.
4. **Auto-fill `__post_init__` over validate-only.** Validate-only would fire false-alarm assertions on `dataclasses.replace(farmyard, grid=new_grid)` whenever the new grid changes stable counts inside an existing pasture. Auto-fill makes that pattern correct by construction. The hypothetical downside (a caller explicitly passing a wrong `pastures` and having it silently overwritten) has no legitimate use case.
5. **Canonical pasture ordering by `min(p.cells)`.** Required so equivalent farmyards compare equal — critical for `Farmyard.__eq__` and hashing across MCTS transposition tables.
6. **Renamed and relocated the BFS function.** `compute_pastures(farmyard) -> list[Pasture]` is gone from the public API. The actual algorithm now lives at `agricola.pasture.compute_pastures_from_arrays(...) -> tuple[Pasture, ...]` and is treated as an implementation detail of `Farmyard.__post_init__`. Read sites use `farmyard.pastures` directly.

### Bugs caught

None — the implementation worked on first run. All 110 pre-existing tests passed unchanged after the refactor; the 6 new tests passed on first run.

### Tests added

- `test_pastures_auto_filled_on_construction` (helpers): direct constructor populates the cache.
- `test_pastures_auto_filled_on_dataclasses_replace_fences` (helpers): adding fences via replace recomputes the cache.
- `test_pastures_auto_filled_on_grid_change_adds_stable` (helpers): adding a stable inside an existing pasture via `dataclasses.replace(farmyard, grid=...)` correctly updates `num_stables` and `capacity`. **The key motivating test for auto-fill.**
- `test_pastures_canonical_order` (helpers): two equivalent farmyards built in different orders produce equal `pastures` tuples.
- `test_enclosed_cells_helper` (helpers): round-trip the new `enclosed_cells` helper on fresh and multi-pasture farmyards.
- `test_fresh_farmyard_has_empty_pastures` (state): `setup(seed).players[i].farmyard.pastures == ()`.

### Test count after Change 2

| File | Tests |
|---|---|
| `tests/test_state.py` | 18 |
| `tests/test_helpers.py` | 39 |
| `tests/test_scoring.py` | 8 |
| `tests/test_legality_atomic.py` | 27 |
| `tests/test_resolution_atomic.py` | 24 |
| **Total** | **116** |

---

<a name="doc-tone-refinements"></a>
## Documentation and tone refinements (undated prior session)

A series of smaller documentation, wording, and design-doc framing changes were made alongside Change 2. Grouped here so the session record is complete.

### Wording fixes early in the session

- **`accumulated_goods` → `accumulated` / `accumulated_amount` in `CLAUDE.md`.** The file's description of `ActionSpaceState` still referenced the pre-refactor single-track field. Updated to the current two-track model: `accumulated` (a `Resources` object on the 5 building-resource spaces) and `accumulated_amount` (a plain int on the 5 food/animal spaces). This brings CLAUDE.md back in sync with `CHANGES.md` Change 1 and the actual code.
- **Newborn feeding-cost wording in `state.py`.** The `PlayerState.newborns` docstring previously implied "born since the last harvest", which is wrong: a child born in round 6 still costs 2 food at round 7's harvest, because `newborns` is cleared between rounds. Rewrote to specify the per-round semantics: born during the current round; cleared when the next round begins; the 1-food discount applies only when a harvest occurs at the end of the birth round.
- **Newborn feeding-cost wording in `RULES.md`.** Same correction applied in two places: the People bullet (~line 145), and the Feeding Phase bullets (~lines 380–383). Both now precisely state which newborns get the 1-food discount.

### New placement rules in `RULES.md`

Three rules were added so future legality code has a clear, citable spec:

- **Rooms must be on an empty, non-enclosed cell** (~lines 129–130). Prevents building a room inside a pasture.
- **Fields must be on an empty, non-enclosed cell** (~lines 152–155). Prevents placing a field inside a pasture; also notes the first field is unrestricted within those bounds.
- **Enclosable cells: fences may only enclose cells that are empty or contain a stable** (~lines 242–246). Stables can be inside pastures (becoming "fenced stables") or standalone (becoming flexible single-animal slots); rooms and fields cannot be inside pastures.

### Two-pass rewrite of "Derived data, not cached data" in `CLAUDE.md`

The principle was edited twice during the session:

1. **First pass**: added explicit analytical guidance for when caching is justified — three factors (expensive in hot paths; structurally enforceable invariant; cache lives on the object that owns its inputs) — and tied the live exception (the `Farmyard.pastures` cache from Change 2) to those factors.
2. **Second pass**: softened the framing from a gate ("Caching is justified only when *all three* hold") to a default with guidance ("Three factors make a cache safer to adopt; the more of them apply, the stronger the case"). Added an explicit **"Note for future sessions"** paragraph telling future Claude instances not to reflexively reject a caching proposal because the doc says no — they should weigh the factors and discuss with the user.

The motivation for the second pass was the observation that I (and prior Claude instances) had been instinctively resistant to even considering the pasture cache, because the design-principles section read as prescriptive rather than analytical.

### Softening of the "Key Design Principles" preamble in `CLAUDE.md`

Changed from "These are firm architectural decisions that all code must follow. Deviating from them will cause problems for MCTS and self-play later." to a more nuanced framing that:

- Describes the first three principles (immutable frozen dataclasses, functional core, determinism after setup) as near-absolute.
- Describes the fourth (derived data, not cached data) as a default with explicit guidance for when to deviate, currently with one accepted exception.
- Tells the reader to read each principle for its own framing rather than treating the bundle as a single rule.

### "the *one* accepted exception" → "the *first* accepted exception"

Updated in two places to reflect the expectation that additional caching exceptions may be added later when the same three factors apply:

- `CLAUDE.md` line ~185, in the description of `Farmyard`.
- `agricola/state.py`, the inline comment on the `pastures` field of `Farmyard`.

### Current Status table updated in `CLAUDE.md`

- New row added: "Pasture cache on `Farmyard` (auto-fill, `agricola/pasture.py`)", referencing `CHANGES.md` Change 2 and `TASK_4a_iii.md`.
- Test count bumped from 110 to 116 in the table preamble and surrounding prose.

---

<a name="auto-fill-extra-tests"></a>
## Additional Auto-Fill Cache Tests (undated prior session)

### Motivation

Change 2 introduced auto-fill of `Farmyard.pastures` in `__post_init__` and added 4 tests covering the cache (`test_pastures_auto_filled_on_construction`, `test_pastures_auto_filled_on_dataclasses_replace_fences`, `test_pastures_auto_filled_on_grid_change_adds_stable`, `test_pastures_canonical_order`). Reviewing the upcoming TASK_4b work — Fencing, Farm Expansion's stable build, and other actions that mutate fences and stables one piece at a time via `dataclasses.replace` — surfaced specific incremental-mutation flows that the existing tests did not directly exercise. Adding focused tests here is cheap insurance: any cache-invariant bug that escapes into TASK_4b will manifest as silently-wrong pasture decompositions deep inside MCTS, which is hard to debug.

The user asked for tests that target how `Farmyard` changes when fences and stables are modified. Five new tests were proposed and added.

### Decision: which tests to add (and which to skip)

Five tests added (all in `tests/test_helpers.py`, after `test_pastures_canonical_order`, before `test_enclosed_cells_helper`):

1. **`test_replace_adds_fence_creates_pasture`** — start with 3 of the 4 fences around (0, 0); add the 4th fence via `dataclasses.replace`; assert a 1×1 cap-2 pasture appears. Mirrors the dominant flow of an incremental Fencing action.
2. **`test_replace_adds_internal_fence_subdivides_pasture`** — start with a 2×1 cap-4 pasture; add the internal vertical fence between (0, 0) and (0, 1); assert two 1×1 cap-2 pastures. The only fence-add flow where pasture count increases.
3. **`test_replace_adds_stable_outside_pasture_no_change`** — existing 1×1 pasture at (0, 0); add a STABLE at (1, 3) via grid `replace`; assert the existing pasture is unchanged and the standalone stable does not appear in `farmyard.pastures`.
4. **`test_replace_adds_second_stable_inside_existing_pasture`** — 2×1 pasture with one STABLE already at (0, 0) (cap = 2·2·2¹ = 8); add a second STABLE at (0, 1) via `replace`; assert num_stables=2, capacity=16. Exercises the `2 ** num_stables` exponent path on a non-trivial input (the existing test only checked 0→1).
5. **`test_equivalent_farmyards_compare_equal_and_hash_equal`** — same enclosures built in different orders; assert `farmyard1 == farmyard2` and `hash(farmyard1) == hash(farmyard2)`. The previous canonical-ordering test only asserted `farmyard.pastures == farmyard2.pastures`. This new test pins down the structural guarantee that MCTS subtree sharing depends on (frozen-dataclass equality + hashing across all fields, including the cached `pastures`).

Three further tests were considered and rejected:
- **Fence removal dissolves a pasture.** The engine never demolishes fences in production; the cache happens to compute correctly from any inputs, but testing this would assert behavior the codebase doesn't need.
- **Two-step `replace` chain.** Redundant given that each individual `replace` already exercises auto-fill; chaining adds no new code path.
- **Silent-overwrite of an explicitly passed `pastures=...` kwarg.** `TASK_4a_iii.md` §D2 frames silent overwrite as an *accepted side effect*, not an intended feature. Writing a test for it would promote the behavior from "hypothetical risk we tolerate" to "supported contract" — constraining future refactors (e.g. switching to a loud `ValueError` if a non-default `pastures` is passed) for no current benefit.

### Bugs caught

None — all 5 new tests passed on first run. Total test count: 116 → 121.

### Test count after Additional Auto-Fill Cache Tests

| File | Tests |
|---|---|
| `tests/test_state.py` | 18 |
| `tests/test_helpers.py` | 44 |
| `tests/test_scoring.py` | 8 |
| `tests/test_legality_atomic.py` | 27 |
| `tests/test_resolution_atomic.py` | 24 |
| **Total** | **121** |

---

<a name="task-4b-i"></a>
## Task 4b-i — Non-Atomic Legality (undated prior session)

### What was built

- `agricola/legality.py` — extended from atomic-only to full non-atomic-space coverage.
  - 11 new per-space predicates: `farm_expansion`, `farmland`, `side_job`,
    `grain_utilization`, `sheep_market`, `pig_market`, `cattle_market`,
    `major_improvement`, `house_redevelopment`, `cultivation`,
    `farm_redevelopment`. (`fencing` deferred — requires fence enumeration;
    `lessons` omitted entirely — permanently illegal in Family game.)
  - 9 shared helpers: `_can_bake_bread`, `_can_sow`, `_can_plow` (filters
    enclosed cells), `_has_stable_placement`, `_can_afford_room`,
    `_has_room_placement` (filters enclosed cells), `_can_build_room`
    (composition `_can_afford_room and _has_room_placement`),
    `_can_renovate`, `_can_afford_any_major_improvement` plus per-index
    helper `_can_afford_major`.
  - `BAKING_IMPROVEMENTS` constant (frozenset of major-improvement indices
    that grant Bake Bread: 0, 1, 2, 3, 5, 6).
  - Two dispatch dicts (`ATOMIC_LEGALITY`, `NON_ATOMIC_LEGALITY`) merged
    into `ALL_LEGALITY`.
  - **`legal_atomic_placements` renamed to `legal_placements`** and extended
    to cover both atomic and non-atomic spaces. The old name no longer exists.
- `tests/test_legality_non_atomic.py` — new file, 56 tests covering each
  shared helper directly (legal/illegal cases including the enclosed-cell
  exclusion in plow and room-placement contexts), each new per-space
  legality (legal/illegal), and cross-cutting absence of `fencing`/`lessons`.
  Includes new test fixtures `_enclose_cell` (1×1 pasture) and
  `_enclose_rect` (rectangular pasture) for constructing test states with
  fenced regions.

### Design decisions

1. **Single `ALL_LEGALITY` dispatch.** The public `legal_placements`
   iterates one dict, not two, so callers don't need to know whether a
   space is atomic.
2. **Renamed rather than added.** `legal_atomic_placements` is gone; only
   `legal_placements` exists. All 28 call sites in
   `tests/test_legality_atomic.py` were updated. One docstring reference
   in `agricola/resolution.py` was updated for accuracy (no behavior change).
3. **`_can_build_room` split into `_can_afford_room` + `_has_room_placement`.**
   Prepares the seam for future card support that varies room-building
   costs without touching placement geometry.
4. **`_can_plow` and `_has_room_placement` filter enclosed cells.** Per
   RULES.md §Fields and Crops and §House and Rooms, fields and rooms cannot
   be placed inside a pasture. Implemented by intersecting candidate empty
   cells with the complement of `enclosed_cells(p.farmyard)`.

### Bugs caught and fixed during the task

1. **`_can_plow` was treating enclosed empty cells as valid plow targets.**
   Without the `enclosed_cells` filter, an empty cell inside a pasture
   would be reported as plowable, contradicting RULES.md. Fixed by adding
   the filter to both branches (first-field and subsequent-plow). Same
   bug class existed in `_has_room_placement`; fixed identically.
2. **Player-index lookup in helpers using `state.current_player`.** The
   first implementation of `_can_bake_bread`, `_can_afford_major`, and
   `_can_afford_any_major_improvement` took `p` as a parameter but read
   the index from `state.current_player`, silently coupling them to
   "p must be the active player." Fixed via identity-based derivation
   (`0 if p is state.players[0] else 1`). Audited the rest of the
   codebase for the same pattern; no other instances found.
3. **Incorrect "Maximum 5 rooms" claim in RULES.md §House and Rooms.**
   Agricola has no fixed room cap — the only constraints are physical
   (farmyard space, adjacency, empty/non-enclosed requirement). The 5-cap
   was a misreading of the people cap. Fixed in RULES.md.

### Documentation changes outside the task scope

- **`CLAUDE.md`**: new "Additional Design Principles" section between
  "Key Design Principles" and "Current Status." First entry is the
  **Player parameter convention** — a two-step rule for any function
  that needs information about a player:
  1. Decide whether to take `p`. Take it when the function could
     plausibly be called for any player. Skip it when the function is
     intrinsically active-player-only. Use an explicit `player_idx`
     when the player is specific but not active.
  2. If you took `p`, derive any required player index from `p` itself,
     never from `state.current_player`.
  Includes a concrete examples table mapping function shapes to current
  code (`_can_bake_bread`, `_can_sow`, `_resolve_day_laborer`, `score`,
  `legal_placements`) and a card-trigger disclaimer.
- **`RULES.md` §House and Rooms**: room-cap line replaced (see Bug 3).
- **`TASK_4b_i.md`**: kept in sync with the final design throughout
  (helper signatures, code examples, test list, design rationale).
- **`tests/test_legality_atomic.py`**: `test_setup_legal_set` updated to
  expect `farmland` in the fresh-setup legal set, since the unified
  `legal_placements` now reports it as legal at round 1.

### Test count after Task 4b-i

| File | Tests |
|---|---|
| `tests/test_state.py` | 18 |
| `tests/test_helpers.py` | 44 |
| `tests/test_scoring.py` | 8 |
| `tests/test_legality_atomic.py` | 27 |
| `tests/test_legality_non_atomic.py` | 56 |
| `tests/test_resolution_atomic.py` | 24 |
| **Total** | **177** |

---

<a name="change-3"></a>
## Change 3 — Disable Auto-Fill `__post_init__` on `Farmyard` (2026-05-10)

### What changed

See `CHANGES.md` Change 3 for the full plan and outcome notes. Summary of the resulting design:

- The `Farmyard.pastures` cache is still on `Farmyard` and `farmyard.pastures` is still the canonical read site. What changes is *how* the cache is kept consistent: instead of an auto-fill `__post_init__` recomputing on every construction, the cache is now maintained by caller discipline at the four pasture-changing resolvers (Fencing, Farm Expansion's stable build, Side Job's stable build, Farm Redevelopment's fence build). Each of those passes `pastures=compute_pastures_from_arrays(new_grid, new_h, new_v)` explicitly when constructing a new `Farmyard`. All other `Farmyard` mutations use `dataclasses.replace(farmyard, ...)` and leave `pastures` alone — correct because those mutations cannot change pastures.

Concrete file changes:

- **`agricola/state.py`**: `Farmyard.__post_init__` is commented out (not deleted, per user request — kept as on-site reference). The inline comment on the `pastures` field is rewritten to describe the new caller-discipline convention and points at CHANGES.md Change 3.
- **No other production code changed.** Atomic resolvers don't construct new `Farmyard` objects; `_make_farmyard()` in `setup.py` builds a fence-free, stable-free farmyard whose correct `pastures` value is the placeholder default `()`.
- **Test helpers**: three helpers that were implicitly relying on auto-fill now compute pastures explicitly:
  - `tests/test_helpers.py::_make_farmyard`
  - `tests/test_legality_non_atomic.py::_set_grid`, `_enclose_cell`, `_enclose_rect`
  - `tests/test_scoring.py::_make_farmyard`
- **Seven auto-fill-specific tests deleted** from `tests/test_helpers.py` (their assertions no longer apply): `test_pastures_auto_filled_on_construction`, `test_pastures_auto_filled_on_dataclasses_replace_fences`, `test_pastures_auto_filled_on_grid_change_adds_stable`, `test_replace_adds_fence_creates_pasture`, `test_replace_adds_internal_fence_subdivides_pasture`, `test_replace_adds_stable_outside_pasture_no_change`, `test_replace_adds_second_stable_inside_existing_pasture`. `test_pastures_canonical_order` and `test_equivalent_farmyards_compare_equal_and_hash_equal` were kept — they exercise canonical ordering and structural equality/hashing (the property MCTS subtree sharing depends on) via the updated `_make_farmyard` helper, not via the auto-fill machinery.
- `test_fresh_farmyard_has_empty_pastures` in `tests/test_state.py` still passes unchanged.

### Motivation

The auto-fill `__post_init__` makes the BFS run on every `Farmyard` construction. The vast majority of `Farmyard` mutations cannot change pastures (room-builds, plows, sows, renovations, and any other grid mutation that doesn't add a stable inside a pasture), and the share of these will grow significantly once Task 4b-ii lands. The BFS is microseconds in absolute terms but runs inside MCTS rollouts millions of times per self-play game. Cutting it from "every `Farmyard` mutation" to "only the four pasture-changing resolvers" is a real win.

### Trade-off accepted

The cache invariant is no longer structurally enforced. Forgetting to pass `pastures=...` in a future pasture-changing resolver produces a silently-stale cache that does not crash and does not fail any local test — exactly the failure mode that "Derived data, not cached data" was originally written to prevent. CLAUDE.md's framing of factor 2 is updated to acknowledge that this exception now satisfies factors 1 and 3 but is a deliberate weakening of factor 2.

Mitigations: the list of pasture-changing resolvers is small, fixed, and statically known (just four). They will be reviewed against the convention when Task 4b-ii lands. Cache and inputs still co-locate on the same object (factor 3).

### Design choices made along the way

1. **Comment out `__post_init__`, don't delete it.** Kept (commented) in `agricola/state.py` as on-site documentation of the road-not-taken, with a pointer to CHANGES.md Change 3.
2. **Don't introduce a `Farmyard.with_grid(...)` / `Farmyard.with_fences(...)` builder.** That would be a new method API on a frozen dataclass that the rest of the codebase doesn't use, for one call site per resolver. The `dataclasses.replace(...)` + explicit `pastures=...` pattern is already the convention.
3. **Don't add a runtime assertion that the passed-in `pastures` matches a recomputed value.** The four pasture-changing resolvers are the only places that pass a non-default `pastures`, and they always recompute via the same function the assertion would call. Test coverage on those resolvers (Task 4b-ii) is the right place to catch bugs.
4. **Update tests, don't write a regression test for the new convention.** The convention will be enforced by the four resolvers' own tests once they exist; piggybacking a "you must recompute" assertion onto generic `Farmyard` tests would invert the layering.

### Bugs caught

None — once the three test helpers were updated, all 170 remaining tests passed on the first run.

### Test count after Change 3

Seven auto-fill-specific tests deleted; no tests added. 177 → 170.

| File | Tests |
|---|---|
| `tests/test_state.py` | 18 |
| `tests/test_helpers.py` | 37 |
| `tests/test_scoring.py` | 8 |
| `tests/test_legality_atomic.py` | 27 |
| `tests/test_legality_non_atomic.py` | 56 |
| `tests/test_resolution_atomic.py` | 24 |
| **Total** | **170** |

### Convention for Task 4b-ii resolvers

When implementing Fencing, Farm Expansion's stable build, Side Job's stable build, and Farm Redevelopment's fence build, the new `Farmyard` must be constructed with an explicit `pastures=...` kwarg:

```python
new_farmyard = dataclasses.replace(
    player.farmyard,
    grid=new_grid,              # or horizontal_fences=..., vertical_fences=...
    pastures=compute_pastures_from_arrays(new_grid, new_h, new_v),
)
```

All other non-atomic resolvers (Plow, Sow, BuildRoom, Renovate, etc.) leave `pastures` alone — `dataclasses.replace(farmyard, grid=new_grid)` correctly preserves the cached `pastures` because those mutations cannot change them.

---

<a name="change-3-doc-cascade"></a>
## Documentation cascade for Change 3 (2026-05-10)

### What changed

A grep audit (`__post_init__`, `auto-fill`, `compute_pastures`, `farmyard.pastures`, `pasture cache`, `pasture decomposition`) across all `.md` files surfaced six docs that referenced the now-disabled auto-fill mechanism. Each was updated in line with the principle "describe the current code, not the chronology" — the auto-fill `__post_init__` is mentioned at most as a road-not-taken aside with a pointer to CHANGES.md.

- **`CLAUDE.md`** — six in-place edits:
  1. **"Current exception" bullet under "Derived data, not cached data" (line ~47)**: rewritten to lead with the caller-discipline convention and the four pasture-changing resolvers; explicitly notes this is a deliberate weakening of factor 2 (structural enforcement); points at Change 2 *and* Change 3 for rationale.
  2. **Test count line (line ~89)**: `116` → `170`. (Stale by several sessions, not just by Change 3.)
  3. **Current Status table row (line ~100)**: drops the "(auto-fill, …)" tag from the row label and adds Change 3 to the references column.
  4. **`Farmyard` per-file description (line ~220)**: rewritten to lead with the cache convention (caller discipline + the four resolvers) and the placeholder-default behavior for fresh farmyards; auto-fill is mentioned only as a parenthetical aside.
  5. **Pasture-derived-helpers introductory sentence (line ~257)**: drops the chronological "(auto-filled by `__post_init__`)" annotation and points back at the `Farmyard` description for cache mechanics.
  6. **`tests/test_helpers.py` per-file description (line ~336)**: drops the "auto-fill behavior" coverage clause; the surviving description (canonical ordering, structural equality/hashing, decomposition correctness) is what the file actually tests now.
- **`TESTS.md`** — header test count `177` → `170`; `test_helpers.py` file count `44` → `37`; the seven deleted tests removed; the two surviving tests (`test_pastures_canonical_order`, `test_equivalent_farmyards_compare_equal_and_hash_equal`) consolidated under a renamed "Cache structural-property tests" section header with a callout note explaining the auto-fill-test deletions; the section header text itself updated to refer to the `_make_farmyard` helper.
- **`TASK_2.md`** — extended the existing post-task-update note with a second paragraph noting the `__post_init__` auto-fill is no longer in use; points at CHANGES.md Change 3.
- **`TASK_4a_iii.md`** (the original Change 2 spec) — "Note (out of date)" callout added at the top: cache itself remains, `__post_init__` auto-fill mechanism disabled, points at CHANGES.md Change 3. Body of the spec preserved as-is.
- **`ARCHITECTURE.md`** — line 45 (the inline note on principle 6 "Pastures are derived, not stored") extended with a Change 3 sub-note: cache and `farmyard.pastures` access remain; auto-fill disabled; points at CHANGES.md Change 3.

### Files audited but not changed

- **`TASK_4b_i.md`** — only references "the cached `Farmyard.pastures` decomposition (O(1))", which is still accurate. The reading mechanics didn't change in Change 3.
- **`STRATEGY.md`, `RULES.md`, `IMPLEMENTATION_CHOICES.md`, `CLEANUP.md`** — no relevant matches.

### Style note

The user pushed back on a first-draft preview as being "overly interested in chronology" — leading with "originally X was done; later we changed it to Y" rather than "the code does Y today". The resulting style for these doc updates: lead with the current state, mention the original `__post_init__` mechanism as a road-not-taken aside if at all, reference Change 2/Change 3 for readers who want the full story. CLAUDE.md's "Current exception" bullet is the one place where the chronology stays prominent — there it carries weight because the wording explicitly flags the deliberate weakening of factor 2.

### Bugs caught

None. Documentation-only.

### Test count after this entry

Unchanged from Change 3: 170 tests pass.

---

<a name="task-5"></a>
## Task 5 — The `step` Function, Pending Stack, Grain Utilization, Potter Ceramics (2026-05-13)

### What was built

The engine's transition function, the pending-decision stack architecture for multi-step actions, round-transition machinery for rounds 1 → 4, the first non-atomic action-space resolution (Grain Utilization), and the first concrete card (Potter Ceramics). See **`TASK_5.md`** for the complete implementation plan and design rationale, and **`CLAUDE.md`** ("Engine and Turn Resolution Architecture" section) for the conceptual frame every future session should internalize.

Files created:

- **`agricola/engine.py`** (429 lines) — `step(state, action) -> GameState` as the public transition function, plus `_advance_until_decision`, `_advance_current_player`, `_resolve_return_home`, `_resolve_preparation`, the per-action-type dispatch helpers (`_apply_place_worker`, `_apply_choose_sub_action`, `_apply_commit_sow`, `_apply_commit_bake`, `_apply_fire_trigger`, `_apply_stop`), and the stack helpers (`_push`, `_pop`, `_replace_top`).
- **`agricola/pending.py`** (68 lines) — `PendingGrainUtilization`, `PendingSow`, `PendingBakeBread`, and the `PendingDecision` union alias. Lives in its own module to avoid circular imports between `state.py` and resolution code.
- **`agricola/cards/__init__.py`**, **`agricola/cards/triggers.py`**, **`agricola/cards/potter_ceramics.py`** — the card framework and the one card. `TRIGGERS` (event-keyed) + `CARDS` (id-keyed) registries are both populated at import time via `register(event, card_id, eligibility_fn, apply_fn)`.
- **`tests/factories.py`** (172 lines) — prefabricated-state helpers (`with_resources`, `with_majors`, `with_minors`, `with_fields`, `with_pending_stack`, `with_phase`, etc.). Establishes the project-wide convention for test state construction: tests build whatever state they need by direct dataclass construction, not by playing through.
- **`tests/test_utils.py`** — `run_actions` (scripted multi-action helper), `filter_implemented` and `IMPLEMENTED_NON_ATOMIC_SPACES` (filter to actions step can apply), `random_agent_play` (end-to-end random-agent driver).
- **`tests/test_engine.py`** (28 tests), **`tests/test_grain_utilization.py`** (22 tests), **`tests/test_potter_ceramics.py`** (11 tests).

Files modified:

- **`agricola/state.py`** — added `GameState.pending_stack: tuple = ()`; migrated `PlayerState.future_food: tuple[int, ...]` → `PlayerState.future_resources: tuple[Resources, ...]`; added `PlayerState.minor_improvements: frozenset = frozenset()` and `PlayerState.occupations: frozenset = frozenset()`.
- **`agricola/constants.py`** — added `Phase.PREPARATION` and `Phase.BEFORE_SCORING` to the enum.
- **`agricola/setup.py`** — initializes the new fields.
- **`agricola/actions.py`** — full rewrite. The `Action` union now contains `PlaceWorker`, `ChooseSubAction(name: str)`, `CommitSow(grain, veg)`, `CommitBake(grain)`, `FireTrigger(card_id)`, `Stop`. There is no `SkipTrigger` — declining a trigger is implicit.
- **`agricola/legality.py`** — added `_owns_baker`, extended `_can_bake_bread` with the `BAKE_BREAD_ELIGIBILITY_EXTENSIONS` registry hook, added `register_bake_bread_extension(fn)`, added per-pending enumerators (`_enumerate_pending_grain_utilization`, `_enumerate_pending_sow`, `_enumerate_pending_bake_bread`), added `_enumerate_pending` and `PENDING_ENUMERATORS` dispatch, added the top-level `legal_actions(state)` function. `legal_placements` remains as an internal helper.
- **`agricola/resolution.py`** — removed the public `resolve_atomic` function; added `_execute_sow` and `_execute_bake`. `ATOMIC_HANDLERS` is now imported by the engine for dispatch. Clay Oven and Stone Oven baking raise `NotImplementedError` (their parameterized rates are deferred).
- **`tests/test_resolution_atomic.py`** — migrated from `resolve_atomic` to `step`. One test renamed (`test_resolution_doesnt_advance_current_player` → `test_step_advances_current_player_after_atomic`, with inverted assertion: `step` DOES alternate, by design). Added `test_step_atomic_leaves_empty_stack`.
- **`tests/test_state.py`** — added four tests for the new `PlayerState` and `GameState` fields.

### Design conversation (pre-implementation)

The design conversation that produced TASK_5.md was substantial. Key design decisions, all settled before implementation began:

- **Actions are a flat tagged union of frozen dataclasses** under the `Action` alias. `ChooseSubAction(name: str)` is parameterized by a string (mirroring `PlaceWorker(space: str)`); commit types are separate dataclasses because their parameters differ.
- **No `SkipTrigger` action.** Declining a trigger is implicit (the player picks a commit or another trigger instead). This eliminates the thorny one-ply-lookahead helper that an explicit skip would have needed. Documented in CLAUDE.md's pending-stack subsection.
- **Pending decisions are a typed union** stored as a tuple on `GameState.pending_stack`. Every pending carries `player_idx` to support out-of-turn trigger frames (none in Task 5; mechanism present).
- **`step` performs no legality validation.** Callers assert `action in legal_actions(state)`. Single source of truth.
- **`step` does NOT auto-resolve singleton player decisions.** Every observed decision is a `step` boundary. Trace consistency for MCTS / replay / debug.
- **Player alternation lives in `step`, not in `_advance_until_decision`.** Alternation requires knowing "an action was just applied," which only `step` has access to. `_advance_until_decision` is state-driven and idempotent.
- **`_advance_until_decision` only handles system transitions** (phase changes), not player alternation. Phases walk through as `WORK → RETURN_HOME → PREPARATION → WORK`. The harvest is deferred; Task 5 halts at `Phase.BEFORE_SCORING` after round 4's RETURN_HOME.
- **`triggers_resolved` is scoped to a pending frame's lifetime.** Per-pending, not per-player. Each new bake action gets a fresh `PendingBakeBread` with an empty set, so Potter Ceramics re-becomes-eligible every Bake Bread action.
- **Trigger frames push on top of their parent pending, never between frames.** Stack invariant — guarantees `state.pending_stack[-1]` after a commit-pop is the parent.
- **Two-registry card design:** `TRIGGERS` (event-keyed) for "what fires on event X?" queries; `CARDS` (card-id-keyed) for direct lookup by `_apply_fire_trigger`.
- **Card-extension pattern for legality helpers** (`BAKE_BREAD_ELIGIBILITY_EXTENSIONS`): `base_check(state, p) or any(ext(state, p) for ext in EXTENSIONS)`. Documented in `IMPLEMENTATION_CHOICES.md` items 10 and 11.
- **Known unhandled compound interactions:** the extension pattern handles single-card eligibility broadening (Potter Ceramics) cleanly, but does NOT handle cases where one card's effect enables another's eligibility (canonical example: Pan Baker + Potter Ceramics, where Pan Baker's on-placement clay grant enables Potter's clay→grain conversion, allowing baking from a 0-clay-0-grain state). Flagged in `TASK_5.md`'s "Known limitation: compound card interactions" section, in `CLAUDE.md`'s "Card implementation status", and in `IMPLEMENTATION_CHOICES.md` item 11.

For the full design discussion thread (including discarded alternatives like `SkipTrigger`, separate intent-vs-execution pendings, narrowing `BAKING_IMPROVEMENTS`, and a sub-phase split of RETURN_HOME / PREPARATION), see `TASK_5.md` (the design doc).

### Out of scope (deliberate)

- Non-atomic resolution for the other ten non-atomic spaces (Farmland, Farm Expansion, Side Job, Sheep/Pig/Cattle Market, Major Improvement, House Redevelopment, Cultivation, Farm Redevelopment). They remain legal targets via `legal_actions`; `step` raises `NotImplementedError` if the agent picks one. The test scaffolding's `filter_implemented` helper prevents the random agent from selecting them.
- `fencing` legality and resolution — requires enumerating valid fence configurations.
- Harvest phases (HARVEST_FIELD / FEED / BREED) — entirely deferred; the engine halts at `Phase.BEFORE_SCORING` after round 4's RETURN_HOME.
- Rounds 5–14 — unreachable in Task 5.
- Cards other than Potter Ceramics, and the action spaces that would play minors/occupations (Lessons remains permanently illegal in the Family game anyway; the other minor-playing paths just aren't implemented).
- A higher-level driver function (`play_round`, `play_game`, MCTS rollout). The engine exports only `step` + `legal_actions`; callers compose what they need. The agent loop's typical shape (`legal_actions` → `pick` → `step` → repeat) is documented in TASK_5.md.

### Bugs caught during implementation

Just one, and it was a test rather than the engine:

- `tests/test_resolution_atomic.py::test_resolution_doesnt_advance_current_player` was an explicit assertion that `resolve_atomic` didn't alternate the current player. With Task 5 the migration is to `step`, which by design DOES alternate. The test was renamed to `test_step_advances_current_player_after_atomic` and the assertion was inverted. The test now confirms the new behavior.

No engine bugs surfaced. The TASK_5.md design doc was thorough enough that the implementation followed it directly with no significant divergences.

### Test count after Task 5

| File | Tests |
|---|---|
| `tests/test_state.py` | 22 (+4: pending_stack, future_resources, minor_improvements, occupations defaults) |
| `tests/test_helpers.py` | 37 (unchanged) |
| `tests/test_scoring.py` | 8 (unchanged) |
| `tests/test_legality_atomic.py` | 27 (unchanged) |
| `tests/test_legality_non_atomic.py` | 56 (unchanged) |
| `tests/test_resolution_atomic.py` | 25 (+1: net change after renaming the alternation test and adding stack-emptiness test) |
| `tests/test_engine.py` | **28** (new — including 10 parameterized random-agent runs) |
| `tests/test_grain_utilization.py` | **22** (new) |
| `tests/test_potter_ceramics.py` | **11** (new) |
| **Total** | **236** |

170 → 236, net +66. `tests/test_utils.py` and `tests/factories.py` are test infrastructure modules, not collected by pytest (no `test_*` functions).

### Documentation cascade

Concurrent doc updates landed alongside the implementation:

- **`CLAUDE.md`** — new "Engine and Turn Resolution Architecture" section with three subsections (engine, pending stack, card implementation status); Current Status table updated with nine new completion rows and test count 170 → 236; Directory Structure updated with new files and the `cards/` subpackage; Python File Descriptions rewritten for `state.py`, `constants.py`, `actions.py`, `legality.py`, `resolution.py`, and added for `pending.py`, `engine.py`, `cards/__init__.py`, `cards/triggers.py`, `cards/potter_ceramics.py`, `tests/factories.py`, `tests/test_utils.py`, `tests/test_engine.py`, `tests/test_grain_utilization.py`, `tests/test_potter_ceramics.py`. The new architecture section was written during the design conversation, before implementation; the per-file descriptions were updated after implementation.
- **`IMPLEMENTATION_CHOICES.md`** — item 4 updated to reflect the `future_food` → `future_resources` migration; items 10, 11, 12, 13 added (card-extension pattern, compound-card limitation, `triggers_resolved` scoping, sub-phase decomposition deferred).
- **`TASK_5.md`** — created during the design conversation, refined across multiple passes. ~2068 lines covering implementation plan, worked examples (sow + bake with and without Potter Ceramics), test plan, factories, and the known compound-card limitation.

### Next task — open questions

The next task is likely non-atomic resolution for one or more of the other ten spaces. Suggested order (Family-game complexity, ascending):
- **Farmland** — single plow choice. Simplest non-atomic; useful warm-up.
- **Side Job** — and/or (1 stable, bake bread). Re-uses bake-bread infrastructure.
- **Farm Expansion** — and/or (rooms, stables). Multi-build sub-actions; first space where stack might grow to >2 frames in a single resolution.
- **Cultivation** — and/or (plow, sow). Re-uses sow infrastructure; the plow→sow chain (plow first, then sow the newly plowed field in the same action) is the first place ordering matters within an and/or space.
- **House Redevelopment / Farm Redevelopment** — renovation + optional improvement; introduces renovation logic.
- **Major Improvement** — purchase logic; introduces the per-improvement effect dispatch.
- **Sheep/Pig/Cattle Market** — animal accommodation choice via Pareto frontier. Already has infrastructure in `helpers.py`.
- **Fencing** — last, as it requires the deferred fence-enumeration legality.

Harvest is its own multi-task entity (HARVEST_FIELD / FEED / BREED, each with player decisions). Compound-card-interaction machinery (per "Known limitation" in TASK_5.md) is the major card-system prerequisite.

---

<a name="task-5b"></a>
## Task 5B — Dispatch Cleanup (2026-05-14)

### What was built

A focused follow-up refactor to Task 5. Reorganized resolution-layer code, introduced a `CommitSubAction` hierarchy with a single generic dispatcher, added provenance metadata to pending dataclasses, and codified forward-compat conventions for the card system. Touched five modules; all 236 tests pass unchanged (modulo `initiated_by_id=` kwargs added to a handful of `Pending*` construction calls in test bodies). See **`TASK_5B_DISPATCH_CLEANUP.md`** for the design doc with Part 1 (changes) + Part 2 (conventions), and **`CHANGES.md`** Change 4 for the summarized retrospective.

Six concrete changes:

1. **Renamed `_resolve_grain_utilization` → `_initiate_grain_utilization`.** The function pushes a pending and exits — it doesn't fully resolve anything. The new `_initiate_*` prefix is honest about that. Atomic-space resolvers keep their `_resolve_*` names for now; they'll be renamed only when their behavior changes (when atomic spaces start pushing trigger-host pendings post-cards).
2. **Relocated non-atomic dispatch.** Moved `NONATOMIC_HANDLERS`, `CHOOSE_SUBACTION_HANDLERS`, `_initiate_grain_utilization`, and `_choose_subaction_grain_utilization` from `engine.py` to `resolution.py`. The three function-pointer dispatch tables (`ATOMIC_HANDLERS`, `NONATOMIC_HANDLERS`, `CHOOSE_SUBACTION_HANDLERS`) now live uniformly with their handler functions.
3. **Stack helpers moved to `pending.py`.** `_push`, `_pop`, `_replace_top` → `push`, `pop`, `replace_top` (underscores dropped, since they cross module boundaries). `pending.py` becomes the cohesive home for both the pending dataclasses and the stack operations on them.
4. **`CommitSubAction` marker base class.** Added `CommitSubAction` (frozen dataclass, empty) in `actions.py`. `CommitSow` and `CommitBake` inherit from it. `_execute_sow` and `_execute_bake` signatures changed to take the commit action object directly (`(state, player_idx, commit)`) so a single dispatcher can call any effect uniformly.
5. **Pending provenance fields.** Every pending class now carries `initiated_by_id: str` (mandatory instance field; identifies what pushed this frame) and `PENDING_ID: ClassVar[str]` (identifies the kind of pending — `"grain_utilization"`, `"sow"`, `"bake_bread"`). Top-level pendings pushed by `PlaceWorker` use `initiated_by_id="worker_placement"` (a reserved event class string); sub-action pendings inherit the parent's `PENDING_ID`; card-pushed pendings would carry the card's id.
6. **Unified commit dispatcher.** Replaced `_apply_commit_sow` and `_apply_commit_bake` with a single `_apply_commit_subaction` driven by `COMMIT_SUBACTION_HANDLERS` (metadata table mapping `CommitX → (PendingX, "x_done", _execute_x)`, co-located in `engine.py`). The dispatcher uses `if state.pending_stack:` + identity check (`parent.PENDING_ID == popped.initiated_by_id`) + field-existence check (`parent_flag in type(parent).__dataclass_fields__`) before writing to the parent — load-bearing for card-driven cross-cutting sub-actions. `_apply_action` now has exactly five `isinstance` branches.

### Design conversation

A long iterative design pass produced `TASK_5B_DISPATCH_CLEANUP.md` before any code changed. Key decisions, settled before implementation:

- **`_resolve_*` vs `_initiate_*` naming.** Prefix encodes the function's contract; the dispatch dicts (`HANDLERS`) stay generic. Atomic spaces stay `_resolve_*` until their behavior changes.
- **`COMMIT_SUBACTION_HANDLERS` lives in `engine.py`, not `resolution.py`.** It's metadata for the engine's own dispatcher (tuples of `(pending_type, parent_flag, effect_fn)`), not a function-pointer table parallel to `ATOMIC_HANDLERS` etc. Co-located with its sole consumer.
- **`initiated_by_id` for `PlaceWorker`-pushed pendings is the event class `"worker_placement"`, not the space-id.** Avoids the redundancy where a top-level pending's `PENDING_ID` and `initiated_by_id` would otherwise be the same string. The field's semantic is "why am I on the stack?", not "who am I?".
- **Every pending class carries `PENDING_ID`** — parents (`PendingGrainUtilization.PENDING_ID = "grain_utilization"`), generic sub-actions (`PendingSow.PENDING_ID = "sow"`, `PendingBakeBread.PENDING_ID = "bake_bread"`), and any future card-specific class. Enables uniform identity checks across nested stacks. Trigger event names follow `"before_<PENDING_ID>"` / `"after_<PENDING_ID>"`.
- **Non-atomic spaces always push a parent pending.** Even genuinely single-sub-action spaces (Farmland with its single plow). The parent serves two purposes: sub-action progress tracking AND hosting the trigger event for cards that attach to that space. A proposed exception ("single-sub-action spaces don't push a parent") was raised and retracted once the trigger-hosting purpose became clear — the parent earns its keep even without multiple sub-actions.
- **Dispatcher uses `parent_flag in type(parent).__dataclass_fields__` directly** (O(1) dict lookup) over `dataclasses.fields(parent)` (filtered, O(n) every call). The ClassVar-collision risk is structurally prevented by the naming convention (`*_done` lowercase parent_flag values vs. `ALL_CAPS` ClassVar names). Inline code comment documents the safeguard.
- **Dispatcher checks are load-bearing, NOT defensive cruft.** Explicit `do NOT refactor` warning in the code comment. The `if state.pending_stack:` + identity + field-existence triple-check absorbs two forward-compat cases (sub-action chains with no parent; card-pushed cross-cutting sub-actions whose immediate stack frame isn't its architectural owner). Removing the checks looks like a simplification but breaks card forward-compat silently.
- **`CommitSubAction` is a frozen dataclass, not a plain marker class.** Consistent with the project's "every action object is a frozen dataclass" principle. Bare `CommitSubAction()` is technically instantiable but would `KeyError` loudly in `_apply_commit_subaction`.

The conversation also explored two cards Day Laborer–attached card forward-compat (Cottager fires before, Hardware Store fires after) and concluded that atomic spaces will eventually push trigger-host pendings with two trigger events per space, phase tracking on the pending, and an explicit phase-transition mechanism. These remain deferred to the card task.

### Bugs caught during implementation

None significant. Implementation followed the design doc directly. Test factories that built `Pending*` instances directly had to add `initiated_by_id=` kwargs — that's a construction-call update enforced by the mandatory-no-default design (so omissions raise `TypeError` at construction time, not silent bugs downstream), not a bug.

### Test count after Task 5B

Unchanged from Task 5: 236 total. No new tests required; this was a pure refactor — the behavior surface is unchanged.

### Documentation cascade

- **`TASK_5B_DISPATCH_CLEANUP.md`** — created during the design conversation. Two-part structure: Part 1 lists the concrete changes; Part 2 documents conventions and forward-compat for future code. Has a "this task doc goes silent once implemented" framing; Part 2's stable conventions were migrated into CLAUDE.md so future sessions see them without needing the task doc.
- **`CLAUDE.md`** — added a function-name prefix taxonomy under "Additional Design Principles"; new "Pending provenance metadata" subsection under "The pending-decision stack" with both the `PENDING_ID` three-shape table and the `initiated_by_id` three-category table; two new design-philosophy bullets ("Non-atomic spaces push a parent pending", "Commit sub-actions inherit from `CommitSubAction`"); expanded "The architecture is built with cards in mind" with three new bullets (pending provenance, atomic spaces will push trigger-host pendings, two trigger events per space); extended "Card implementation status" with three deferred open questions (card-specific pending `PENDING_ID`/`initiated_by_id` redundancy, atomic-space phase tracking, atomic-space phase-transition mechanism); rewrote per-file descriptions for `pending.py`, `resolution.py`, `engine.py`, `actions.py`; added `TASK_5B_DISPATCH_CLEANUP.md` to the Documentation Files list.
- **`CHANGES.md`** — Change 4 added (cross-cutting summary; the refactor touched five modules).
- **Code comments in `engine.py`** — three load-bearing notes attached to the code they protect: above `COMMIT_SUBACTION_HANDLERS` (the `parent_flag` string-coupling caveat), and inside `_apply_commit_subaction` (the "checks are NOT defensive cruft" warning + the `__dataclass_fields__` ClassVar-collision safeguard). These caveats are kept in code rather than CLAUDE.md so they reach the right audience: someone editing engine.py, at the moment they might "clean up" the dispatcher.

### Conventions established (stable, documented in CLAUDE.md)

- Function-name prefix taxonomy: `_resolve_<atomic_space>` / `_initiate_<nonatomic_space>` / `_choose_subaction_<space>` / `_execute_<sub_action>` / `_resolve_<phase>` (the last is in `engine.py`, not `resolution.py`).
- Non-atomic spaces always push a parent pending (sub-action tracking + trigger event hosting).
- Every pending class has `PENDING_ID`; the three shapes are parent (space-id), generic sub-action (sub-action name), and card-specific (card-id).
- `initiated_by_id` has three value shapes by push category: parent's `PENDING_ID` for sub-actions; `"worker_placement"` for top-level pushed by `PlaceWorker`; card's id for card-pushed.
- Trigger event names follow `"before_<PENDING_ID>"` / `"after_<PENDING_ID>"`.
- Space-ids and card-ids share a single namespace (snake_case); uniqueness enforced at card-registration time. `"worker_placement"` is reserved.
- Adding a new `Commit*` sub-action is a 4-step extension (`actions.py` dataclass + Action union; `resolution.py` effect function; row in `COMMIT_SUBACTION_HANDLERS`; `*_done` field on relevant parent pendings). No edits to `_apply_action`.

### Next task

Unchanged from Task 5's "Next task — open questions": non-atomic resolution for one or more of the other ten spaces. The dispatch infrastructure is now in place for them to land cleanly. Harvest, compound-card-interaction machinery, and the deferred open questions (card-specific pending redundancy, atomic-space phase tracking + transition) remain on the longer-term roadmap.

---

<a name="task-5c"></a>
## Task 5C — Eight Non-Atomic Spaces + Convention Shifts (2026-05-15)

### What was built

Non-atomic resolution for the eight Family-game spaces not yet implemented (Farmland, Cultivation, Side Job, Sheep/Pig/Cattle Markets, Major Improvement, House Redevelopment), plus four cross-cutting convention shifts that touched existing code. Only Farm Expansion, Farm Redevelopment, and Fencing remain deferred. See **`TASK_5C.md`** for the implementation plan, design rationale, and per-space breakdowns; **`CHANGES.md`** Change 5 for the cross-cutting summary; and **`CLAUDE.md`** ("Engine and Turn Resolution Architecture" + "Code Conventions" + "Additional Design Principles → Sub-action cost handling") for the conceptual frame.

**Eight spaces gained non-atomic resolution:**

- **Farmland** — single plow choice. Pushes `PendingFarmland`, awaits `ChooseSubAction("plow")` → `PendingPlow` → `CommitPlow(row, col)` → `Stop`.
- **Cultivation** — plow and/or sow. Pushes `PendingCultivation`; the plow→sow chain (plow first, then sow the newly plowed field in the same action) falls out naturally because legality re-enumerates after each commit.
- **Side Job** — build 1 stable (1 wood) and/or bake bread. Pushes `PendingSideJob`; reuses the existing `PendingBakeBread` machinery for the bake half.
- **Sheep Market / Pig Market / Cattle Market** — take all accumulated animals, accommodate or release. Each market pushes its own parent pending with `gained: int` staged on the pending (not yet on the player); `CommitAccommodate(sheep, boar, cattle)` lands directly on the parent and finalizes. No Stop step; the commit pops the parent. The enumerator computes the legal frontier via the existing `pareto_frontier` helper.
- **Major Improvement** — purchase one of the 10 majors. Pushes `PendingMajorMinorImprovement` (the family-game equivalent of "Major or Minor Improvement"; minor path is forward-compat); `ChooseSubAction("build_major")` → `PendingBuildMajor` → `CommitBuildMajor(major_idx, return_fireplace_idx)`. For Clay Oven / Stone Oven, the commit pushes a `PendingClayOven` / `PendingStoneOven` wrapper hosting the optional free Bake Bread; for non-oven majors the wrapper isn't pushed and `PendingBuildMajor` is popped immediately. The Cooking Hearth payment options (pay 4 or 5 clay, or return Fireplace idx 0 or 1) are emitted as flat `CommitBuildMajor` variants. Well's "+1 food on each of the next 5 round spaces" effect writes into the owner's `future_resources`.
- **House Redevelopment** — renovate (mandatory first) then optional Major/Minor Improvement. Pushes `PendingHouseRedevelopment`; the renovate step pushes `PendingRenovate` (with the renovation cost computed at choose-time and stored on `pending.cost`); the optional improvement step pushes `PendingMajorMinorImprovement` and goes through the same Major Improvement flow.

**Four cross-cutting convention shifts:**

1. **Choose-time flag-setting.** Parent `*_chosen` flags are now set in `_choose_subaction_*` handlers at push time (before the sub-action pending is pushed), not by the generic commit dispatcher. `_apply_commit_subaction` no longer touches parent state; its sole job is assert + effect + pop. `COMMIT_SUBACTION_HANDLERS` entries shrank from 3-tuples `(expected_pending_type, parent_flag, effect_fn)` to 2-tuples `(expected_pending_type, effect_fn)`. Existing field names renamed: `sow_done` → `sow_chosen`, `bake_done` → `bake_chosen` on `PendingGrainUtilization`.

2. **Provenance prefix scheme.** Top-level pendings pushed by `PlaceWorker` now have `initiated_by_id = "space:<space_id>"` (was `"worker_placement"`). Card-pushed top-level pendings will use `"card:<card_id>"`. Sub-action pendings pushed by `ChooseSubAction` unchanged (still the parent's `PENDING_ID`). The `"worker_placement"` reserved-string carve-out is eliminated; the `"space:"` and `"card:"` prefixes are disjoint by construction.

3. **`Resources.__sub__` operator.** Added alongside `__add__` and `__bool__`. Allows pure-subtraction sites to use `p.resources - cost` instead of the 7-field-negated-component pattern. Migration: `_execute_sow` updated to the cleaner form. Mixed subtract-and-add sites (`_execute_bake`, `potter_ceramics._apply`) stay in the single-`Resources` form with negative components — splitting them would add operands without clarity gain.

4. **Bake Bread support for Clay Oven and Stone Oven.** `_execute_bake` previously raised `NotImplementedError` for Clay-Oven-only or Stone-Oven-only owners; it now does greedy-by-rate allocation across all owned baking improvements via the new `baking_specs_for_player` helper. New constants in `agricola/constants.py`: `MAJOR_IMPROVEMENT_COSTS` (cost tuple indexed by major_idx), `BAKING_IMPROVEMENT_SPECS` (per-improvement `(cap, rate)` dict), `FIREPLACE_INDICES`, `COOKING_HEARTH_INDICES`. `BAKING_IMPROVEMENTS` migrated here from `legality.py`. New `BAKING_SPEC_EXTENSIONS` registry in `legality.py` lets future cards (e.g., Iron Oven minor improvement) register their baking source via `register_baking_spec_extension(fn)` without editing `_execute_bake` or `_enumerate_pending_bake_bread`.

**Eleven new pending dataclasses** in `agricola/pending.py`: four sub-action pendings (`PendingPlow`, `PendingBuildStable`, `PendingBuildMajor`, `PendingRenovate`); five space-level parent pendings (`PendingFarmland`, `PendingCultivation`, `PendingSideJob`, three animal market parents, `PendingMajorMinorImprovement`, `PendingHouseRedevelopment`); two oven wrapper pendings (`PendingClayOven`, `PendingStoneOven`). `PendingBuildStable` and `PendingRenovate` carry a `cost: Resources` field set at push time by the choose handler (the "cost-on-pending" pattern; see Code Conventions).

**Five new commit action classes** in `agricola/actions.py`: `CommitPlow`, `CommitBuildStable`, `CommitBuildMajor`, `CommitRenovate`, `CommitAccommodate`. All added to the `Action` union. `CommitBuildMajor` is dispatched via a special-case branch in `_apply_action` (not through the generic dispatcher) because oven majors keep `PendingBuildMajor` on the stack and push a wrapper on top, incompatible with the dispatcher's unconditional pop.

**Six new test files** plus `__sub__` tests added to `tests/test_state.py` and field-rename updates to `tests/test_grain_utilization.py` and `tests/test_potter_ceramics.py`. See "Test count after Task 5C" below.

### Design conversation (pre-implementation)

A long iterative design pass produced `TASK_5C.md` before any code changed. Key decisions, settled before implementation:

- **Choose-time vs. commit-time flag-setting.** The original Task 5 / Task 5B convention set the parent flag in the commit dispatcher after popping the sub-action pending, using an identity check + field-existence check on the new top. Choose-time setting was proposed during the design conversation as more local (flag management adjacent to the push that creates the sub-action) and removed a structural coupling between the dispatcher and parent dataclass fields. Trade-off: choose-time setting required dropping the identity check's role as a card-cross-cutting safety net, but the safety net was speculative — choose-time setting makes flag-setting explicit at every push site, which is arguably better.

- **Cost-on-pending convention for sub-actions with parameterizable costs.** Three buckets: (1) no cost (PendingPlow); (2) caller-parameterizable cost stored on the pending as `cost: Resources` (PendingBuildStable for the 1-wood Side Job stable; PendingRenovate computed from house material and room count); (3) commit-time-parameterizable cost looked up from a const table by the commit's parameter (PendingBuildMajor's `commit.major_idx` keys into `MAJOR_IMPROVEMENT_COSTS`). Default for new sub-actions is bucket 2 — most flexible for card-driven cost modifications. Documented in "Additional Design Principles → Sub-action cost handling".

- **Animal markets don't push a sub-action pending.** Unlike other non-atomic spaces, the three markets have a single mandatory commit (CommitAccommodate) that lands directly on the parent pending and pops it. The market's parent pending stages `gained: int` so the player's `Animals` field stays in a physically-accommodatable state until the commit. The choice-of-frontier-point happens at the parent pending's enumerator (which uses the existing `pareto_frontier` helper).

- **Major Improvement: flat enumeration for Cooking Hearth payment options.** Cooking Hearth (idx 2, idx 3) has two payment modes: pay clay, or return a Fireplace. Each is emitted as a separate `CommitBuildMajor` variant (with `return_fireplace_idx=None` for pay-clay, or `return_fireplace_idx=0`/`1` for return-Fireplace). For the convention case where multiple payment options exist, the agent sees them as flat sibling actions rather than via a nested "choose payment" pending. Discussed as an alternative; flat enumeration won.

- **Major Improvement: oven free-bake via wrapper pending.** When Clay Oven or Stone Oven is purchased, the player gets a free Bake Bread action. The architectural alternatives considered: (a) trigger fired on commit, (b) speculative-legality predicate for `do_bake=True` on CommitBuildMajor, (c) a wrapper pending pushed by the commit handler. Option (c) was chosen because it lets the bake's legality (which depends on the post-purchase state, including any Potter Ceramics extension) be checked against the actual state rather than a hypothetical. The wrapper pending (PendingClayOven / PendingStoneOven) is non-top-level (sits below the rest of the major-improvement stack), keeps `PendingBuildMajor` on the stack while resolving, and is popped via Stop. Distinct `PendingClayOven` / `PendingStoneOven` classes (rather than one parameterized class) so `PENDING_ID` stays static and the provenance breadcrumb on the inner `PendingBakeBread` carries the specific oven name.

- **`_execute_build_major` does its own stack manipulation.** Originally planned as two functions — a separate `_apply_commit_build_major` dispatcher (in `engine.py`) + `_execute_build_major` effect (in `resolution.py`). Folded together during design after concluding the split was virtual: the push/pop decision depends on `major_idx`, which `_execute_build_major` already inspects. The function lives in `resolution.py` (following the `_execute_*` prefix) but stretches the taxonomy slightly because it handles stack manipulation in addition to the effect. This is documented in CLAUDE.md's prefix-taxonomy table as an acknowledged stretch.

- **Iron Oven and other future card-driven baking sources.** Discussion of the Iron Oven minor improvement ("exactly 1 grain → 6 food on Bake Bread") motivated the `BAKING_SPEC_EXTENSIONS` registry. Without it, adding Iron Oven would require edits to both `_execute_bake` and `_enumerate_pending_bake_bread`. With it, an Iron Oven card module just calls `register_baking_spec_extension(fn)` and contributes its `(cap, rate)` tuple. Iron Oven itself wasn't implemented; the registry is forward-compat.

- **Renovation cost: 1 reed total, not per-room.** RULES.md previously read "1 clay + 1 reed per room" which is ambiguous — could mean (1 clay + 1 reed) per room, or 1 clay per room + 1 reed total. The existing `_can_renovate` legality check used `reed >= 1` (total). The first draft of `_execute_renovate` mistakenly used `reed = num_rooms` (per-room). The bug was caught during a final-review pass; RULES.md was clarified to "1 clay per room + 1 reed" with an explicit parenthetical, and `_execute_renovate` was fixed before any tests were written.

- **`_can_afford_major_idx` consolidated with existing `_can_afford_major`.** The initial plan referenced a new `_can_afford_major_idx(state, p_idx, idx)` helper; on inspection the existing `_can_afford_major(state, p, idx)` already handles the same logic (including Cooking Hearth's return-Fireplace path). No new helper added.

- **Several style conventions codified during the design conversation** were also collected into a new "Code Conventions" section in CLAUDE.md (see Documentation cascade below): ClassVar field ordering (first), action constructor keyword form, enumerator signatures `(state, pending: PendingX)`, effect function signatures `(state, player_idx, commit)`, `actions: list[Action] = []` typing, `replace_top` one-line preference, `new_player` variable naming, `_update_player`/`_update_space` preferred over manual state construction, choose-time parent-flag setting, variable binding at top of handlers.

For the full design discussion thread (including discarded alternatives like the flat-enumeration approach for the free oven bake, separate `_apply_commit_build_major` dispatcher, `with_house_material` factory helper name, per-pending vs. global cost-lookup for build-stable), see `TASK_5C.md`.

### Out of scope (deliberate)

- **Farm Expansion**, **Farm Redevelopment**, **Fencing** remain deferred — selecting them via `PlaceWorker(...)` still raises `NotImplementedError`. Farm Expansion will reuse `PendingBuildStable` (with cost = `Resources(wood=2)`) plus new room-build infrastructure. Farm Redevelopment will reuse `PendingRenovate` plus fence-build infrastructure. Fencing needs its own enumeration logic (the deferred fence-validity problem).
- Harvest phases (HARVEST_FIELD / HARVEST_FEED / HARVEST_BREED) — entirely deferred; the engine still halts at `Phase.BEFORE_SCORING` after round 4's RETURN_HOME.
- Rounds 5–14 — unreachable in current scope.
- Cards other than Potter Ceramics. The optional minor-improvement paths at Basic Wish for Children, House Redevelopment ("Major or Minor Improvement"), Major Improvement, and Farm Redevelopment all depend on minor-card support arriving; the `ChooseSubAction("play_minor")` path in `_choose_subaction_major_minor_improvement` raises `NotImplementedError` to flag the gap clearly.
- **`PendingBuildRoom`** for room construction — not added because no in-scope space uses it. Will follow the cost-on-pending pattern when introduced.

### Bugs caught during implementation

- **Reed cost in `_execute_renovate` was per-room in the first draft** instead of 1 total. Caught during a final-review pass before any tests ran; fixed in TASK_5C.md and propagated to RULES.md (which had ambiguous wording that contributed to the confusion).
- **`new_p` outliers in effect functions.** The "use `new_player` not `new_p`" convention was established mid-conversation but a handful of code stubs still used `new_p`. Caught during a sweep of all `dataclasses.replace` sites; renamed.
- **Animal market tests over-allocated animals.** The first draft of `tests/test_animal_markets.py` tried to take 2 animals via `CommitAccommodate`, but with no pastures and only the house-pet slot, max accommodation is 1. Caught when the test failed; reduced `accumulated=2` to `accumulated=1` (or 1-animal commit) where appropriate.
- **Cultivation tests didn't expose the space.** Cultivation is a stage-5 card; the first draft of `tests/test_cultivation.py` didn't reveal it via `with_space(..., round_revealed=1)`, so `PlaceWorker(cultivation)` was illegal in round 1. Fixed in `_cult_setup`.
- **`Documentation Files` table in CLAUDE.md had an erroneous individual row for `TASK_5B_DISPATCH_CLEANUP.md`** when the convention is one catch-all `TASK_*.md` row. The row was removed as part of the Task 5C documentation pass.
- **TOC in TASK_5C.md was inaccurate** — said "Three preliminary refactors" when there were four (Change 4 = `Resources.__sub__` was added after the initial TOC was drafted), and the Part 4/Part 5 swap (Tests / Documentation updates) wasn't propagated into the front-matter bullet list. Both fixed.

### Test count after Task 5C

| File | Tests |
|---|---|
| `tests/test_state.py` | 28 (+6: `__sub__` tests) |
| `tests/test_helpers.py` | 37 (unchanged) |
| `tests/test_scoring.py` | 8 (unchanged) |
| `tests/test_legality_atomic.py` | 27 (unchanged) |
| `tests/test_legality_non_atomic.py` | 56 (unchanged) |
| `tests/test_resolution_atomic.py` | 25 (unchanged) |
| `tests/test_engine.py` | 28 (unchanged) |
| `tests/test_grain_utilization.py` | 24 (+2: split the original 2 "writes flag on parent" tests into 4 covering choose-time set and commit-time non-touch separately) |
| `tests/test_potter_ceramics.py` | 11 (unchanged; field-name updates only) |
| `tests/test_bake_bread.py` | **16** (new — 13 parametrized matrix cases + 3 extension-registry tests) |
| `tests/test_farmland.py` | **8** (new) |
| `tests/test_cultivation.py` | **7** (new) |
| `tests/test_side_job.py` | **8** (new) |
| `tests/test_animal_markets.py` | **13** (new — parametrized across the three markets) |
| `tests/test_major_improvement.py` | **9** (new — integration tests for the full purchase-then-bake chain) |
| `tests/test_house_redevelopment.py` | **10** (new) |
| **Total** | **315** |

236 → 315, net +79.

### Documentation cascade

Concurrent doc updates landed alongside the implementation:

- **`TASK_5C.md`** — created during the design conversation across many iterations, ~1800 lines. Structure: Part 1 (four preliminary refactors), Part 2 (shared sub-action pending machinery), Part 3 (per-space implementations), Part 4 (tests), Part 5 (documentation updates), Part 6 (order of work), Part 7 (acceptance criteria), plus two appendices.
- **`CLAUDE.md`** — extensive updates: rewrote the "Pending provenance metadata" subsection's `initiated_by_id` table for the `"space:"`/`"card:"` prefix scheme; rewrote the commit-dispatcher paragraph to describe assert+effect+pop (no parent flag); updated the "Lifecycle of a non-atomic turn" bullet for choose-time flag-setting; added two new bullets to the design-philosophies list (one-frame-per-PlaceWorker/ChooseSubAction invariant + choose-time flag-setting convention); rewrote the "Pending provenance via initiated_by_id + PENDING_ID" bullet in "The architecture is built with cards in mind"; removed the "Card-specific pending classes: PENDING_ID vs initiated_by_id redundancy" deferred-question paragraph (resolved by the prefix scheme); removed the erroneous individual `TASK_5B_DISPATCH_CLEANUP.md` row from the Documentation Files table; added 13 rows to the Current Status table (3 for TASK_5B, 10 for TASK_5C) and rewrote the "Not yet implemented" paragraph; new top-level "Code Conventions" section between "Additional Design Principles" and "Engine and Turn Resolution Architecture" with 11 syntactic/style conventions; new "Sub-action cost handling" subsection under "Additional Design Principles"; new "stretch of the taxonomy" note under the function-name prefix table for `_execute_build_major`; expanded per-file descriptions for `agricola/resources.py` (`__sub__`), `agricola/constants.py` (new constants), `agricola/actions.py` (new commit subclasses), `agricola/pending.py` (now 11 new pending classes, split into sub-action and parent buckets), `agricola/legality.py` (new helpers + `BAKING_SPEC_EXTENSIONS` registry), `agricola/resolution.py` (new effect functions + cost-on-pending convention note), `agricola/engine.py` (special-case `CommitBuildMajor` branch); added per-file descriptions for the six new test files; test count 236 → 315.
- **`CHANGES.md`** — Change 5 added (cross-cutting summary of all four convention shifts + the implementation of eight spaces).
- **`RULES.md`** — clarified the renovation cost wording ("1 clay per room + 1 reed" / "1 stone per room + 1 reed") with an explicit parenthetical to remove ambiguity.

### Conventions established (stable, documented in CLAUDE.md)

The Task 5C design conversation produced or codified the following conventions, now in CLAUDE.md's "Code Conventions" (syntactic / style) and "Additional Design Principles" (architectural):

**Code Conventions (syntactic / style):**
- Dataclass field ordering: ClassVars first, instance fields after.
- Action constructor calls: keyword form uniformly (`PlaceWorker(space="forest")`, `ChooseSubAction(name="sow")`, `CommitSow(grain=1, veg=0)`, etc.).
- Per-pending enumerator signatures: `(state, pending: PendingX) -> list[Action]`.
- Effect function signatures: `(state, player_idx, commit: CommitX) -> GameState`. Effect functions MAY read `state.pending_stack[-1]` to access their own pending (the dispatcher guarantees it's still on top).
- Resource arithmetic: `p.resources - cost` for pure subtraction; single-`Resources` form with negative components for mixed subtract-and-add.
- `replace_top` call form: one-line when the inner `dataclasses.replace` fits; named variable when long or multi-field.
- Variable naming for replaced `PlayerState`: `new_player`.
- Choose-time parent-flag setting: every `_choose_subaction_*` handler sets the parent's `*_chosen` field BEFORE pushing the sub-action pending. The commit dispatcher does NOT touch parent state.
- `actions: list[Action] = []` (typed) inside enumerators.
- Variable binding at top of handlers: `ap = state.current_player; p = state.players[ap]` once, then reuse the locals.
- `_update_player` / `_update_space` helpers preferred over manual `dataclasses.replace(state, ...)`. (Card modules construct the players tuple themselves — accepted exception due to module ordering.)

**Additional Design Principles:**
- **Sub-action cost handling**: three buckets — (1) no cost, (2) caller-parameterizable cost on pending as `cost: Resources` (default for new sub-actions), (3) commit-time-parameterizable cost looked up from a const table. Bucket 2 maximizes flexibility for card-driven cost modifications.

**Other conventions (in CLAUDE.md "Engine and Turn Resolution Architecture"):**
- Provenance prefix scheme: top-level pendings use `"space:<space_id>"`; card-pushed pendings use `"card:<card_id>"`; sub-action pendings unchanged (still the parent's `PENDING_ID`).
- One pending frame pushed per `PlaceWorker` or `ChooseSubAction` (load-bearing for clean trigger ordering between frames).
- `_execute_*` traditionally means effect-only via the generic dispatcher; `_execute_build_major` is an acknowledged stretch (handles its own stack manipulation, dispatched via a special-case branch in `_apply_action`).

### Next task

Implementation surface is now ~90% complete for the Family game's work phase. Remaining work in roughly increasing complexity / decreasing immediacy:

- **Farm Expansion** — room and stable construction. Will reuse `PendingBuildStable` (cost = `Resources(wood=2)`) plus new room-build infrastructure (`PendingBuildRoom` following the cost-on-pending pattern).
- **Farm Redevelopment** — renovate + optional fence build. Will reuse `PendingRenovate`; needs fence-build infrastructure shared with Fencing.
- **Fencing** — the deferred fence-validity enumeration problem. Likely the hardest of the three remaining spaces.
- **Harvest phases** (HARVEST_FIELD / HARVEST_FEED / HARVEST_BREED) — multi-step harvest logic with player decisions.
- **Rounds 5–14** — unblocked once the harvest is implemented.
- **Compound-card-interaction machinery** — needed before complex cards like Pan Baker + Potter Ceramics work correctly.
- **Cards beyond Potter Ceramics** — the full card system is a major separate task.

---

<a name="task-5d"></a>
## Task 5D — Farm Expansion + Multi-Shot Sub-Action Pendings (2026-05-16)

### What was built

Farm Expansion non-atomic resolution lands, introducing the **multi-shot sub-action pending pattern** — a sub-action category that hosts multiple commits within one invocation before the player explicitly Stops. The pattern is a new abstraction the codebase will reuse for Farm Redevelopment and Fencing later. Side Job migrates onto the same multi-shot machinery (with `max_builds=1`); the old singular `PendingBuildStable` retires. Five behavior-preserving Part 1 refactors land first as preparatory cleanup. The latent pasture-cache bug in Task 5C's `_execute_build_stable` is fixed as a side effect. See **`TASK_5D.md`** for the implementation plan and **`CHANGES.md`** Change 6 for the cross-cutting summary.

After Task 5D, `step()` raises `NotImplementedError` only for `farm_redevelopment` and `fencing` — implementation surface for the Family game's work phase is essentially complete pending those two and the harvest.

**The multi-shot sub-action pending pattern.** Pendings carry `max_builds: int | None` (caller-imposed cap; `None` = no cap) and `num_built: int = 0`. The effect function is registered with `auto_pop=False` in `COMMIT_SUBACTION_HANDLERS`. Each commit applies its effect, increments `num_built`, and `replace_top`s — does not pop. `Stop` is the explicit exit, legal at `num_built >= 1`. Per-pending legality offers `Commit*` actions only while the cap permits AND remaining buildability constraints (supply, affordability, cell availability) permit. When no commit is legal but `num_built >= 1`, `Stop` becomes the only legal action — the singleton-`Stop` state arises uniformly regardless of which constraint binds. Card-trigger fields (`triggers_resolved`, `TRIGGER_EVENT`) are intentionally absent on the new pendings, deferred until the first card needs them.

**Farm Expansion** — `PendingFarmExpansion` parent with `room_chosen` / `stable_chosen` flags (once-per-category rule). `ChooseSubAction(name="build_rooms")` pushes `PendingBuildRooms(cost=ROOM_COSTS[house_material], max_builds=None)`; `ChooseSubAction(name="build_stables")` pushes `PendingBuildStables(cost=Resources(wood=2), max_builds=None)`. The multi-room build's within-action adjacency chaining falls out automatically: each commit replaces the farmyard, and the next call to `_enumerate_pending_build_rooms` reads the new state.

**Five Part 1 preliminary refactors:**

1. **`auto_pop` flag on `COMMIT_SUBACTION_HANDLERS`.** Entries grew a third element: `(expected_pending_type, effect_fn, auto_pop)`. `auto_pop=True` is default behavior (dispatcher pops); `auto_pop=False` means the dispatcher steps back and the effect function owns any stack manipulation.
2. **`_execute_build_major` absorbed into the generic dispatch path.** Previously special-cased in `_apply_action`. Now registered as `(PendingBuildMajor, _execute_build_major, False)`. The function body is unchanged — it already owned its conditional stack manipulation (pop for non-ovens, push wrapper for ovens). The four-line special-case branch in `_apply_action` is deleted; its docstring is updated.
3. **`ROOM_COSTS` constant + `_can_afford(p, cost)` helper + simplified `_can_afford_room`.** `ROOM_COSTS: dict[HouseMaterial, Resources]` in `constants.py` mirrors the existing `MAJOR_IMPROVEMENT_COSTS` shape. `_can_afford(p, cost) -> bool` in `legality.py` does generic component-wise affordability checks. `_can_afford_room` collapses to a one-liner over both. Used by both `_choose_subaction_farm_expansion` and `_enumerate_pending_build_rooms`.
4. **Predicate-enumerator deduplication.** Three predicates in `legality.py` duplicated their cell enumerators' logic. `_can_plow(p)` → `bool(_legal_plow_cells(p))`. `_has_room_placement(p)` → `bool(_legal_room_cells(p))` (with new `_legal_room_cells` enumerator added). `_has_stable_placement` *deleted*, replaced by parameterized `_can_build_stable(p, cost)` that combines empty-cell + supply + affordability — three call sites migrated.
5. **`_new_grid_with_cell` helper.** Extracted from the nested-tuple-comprehension pattern in `_execute_plow` and the now-replaced singular `_execute_build_stable`. Used by `_execute_plow`, the new `_execute_build_stable`, and `_execute_build_room`.

**Latent pasture-cache bug fix in `_execute_build_stable`.** Task 5C's version omitted the pasture recompute when placing a stable. The bug couldn't be triggered in current gameplay (no resolver creates fences, so `_legal_stable_cells` never returned a cell inside any pasture) but would have manifested the moment Fencing landed. The new (post-rename, multi-shot) `_execute_build_stable` constructs the new `Farmyard` with explicit `pastures=compute_pastures_from_arrays(...)`, matching the documented convention for pasture-changing resolvers. Directly exercised by `tests/test_farm_expansion.py::test_stable_inside_pasture_recomputes_pasture_cache` (factory-prefabs a state with an existing pasture and asserts the cache updates).

**Side Job migration + `PendingBuildStable` retirement.** Side Job's `_choose_subaction_side_job` now pushes `PendingBuildStables(max_builds=1)` instead of `PendingBuildStable`. The dispatch table for `CommitBuildStable` re-points at the multi-shot effect function. The old singular `_execute_build_stable` body is deleted; the new multi-shot function (introduced under the plural name `_execute_build_stables` during step 6) is renamed back to the singular `_execute_build_stable` at the same time. `PendingBuildStable` and `_enumerate_pending_build_stable` are deleted; the union shrinks by one. Side Job's trace shape grew by one step (commit + Stop instead of self-popping commit); `tests/test_side_job.py` updated accordingly.

**Two new pending dataclasses** in `agricola/pending.py`: `PendingBuildStables` and `PendingBuildRooms`. Both carry the multi-shot fields (`cost`, `max_builds`, `num_built`) but no trigger fields. Plus one parent pending: `PendingFarmExpansion` (also no trigger fields yet, deferred). `PendingBuildStable` (singular) deleted.

**One new commit action class** in `agricola/actions.py`: `CommitBuildRoom(row, col)`. Added to the `Action` union.

**One new test file** (`tests/test_farm_expansion.py`, 25 tests) plus updates to `tests/test_side_job.py`, `tests/test_legality_non_atomic.py`, and `tests/test_engine.py`. See "Test count after Task 5D" below.

### Design conversation (pre-implementation)

A long iterative design pass produced `TASK_5D.md` before any code changed. The conversation covered multiple alternatives at each decision point; only the chosen path is summarized here.

- **Atomic fat commit vs. one-at-a-time-with-nested-plural-pending.** The first option would emit a single `CommitBuildStables(cells: frozenset[(int,int)])` per build session — enumerating all subsets, ~C(13,4) ≈ 715 worst case for stables, more complex for rooms (where within-action adjacency chains). The second option (chosen) keeps per-step legality bounded by farm cells (~13) + Stop, and is far better-shaped for the future NN policy head than a one-shot decision with hundreds of options.

- **Where to pop the multi-shot pending: Approach 1 (effect function auto-pops when `num_built == max_builds`) vs. Approach 2 (effect function never pops; Stop is always the explicit exit).** Approach 2 won on consistency — the affordability/empty-cell case already requires a singleton-`Stop` state somewhere (player runs out of wood mid-action, no cap involved), so special-casing the cap-reached state to auto-pop introduces a divergence with no upside. Also aligns with the engine's "no auto-resolved singleton player decisions" principle. Side effect: Side Job's trace grew by one step.

- **`max_builds` as caller-imposed cap, supply/affordability/cell-availability as separate legality checks.** Initially the design conflated these (`max_builds = stables_in_supply` at push time). Decoupled after recognizing the distinction: `max_builds` encodes the **caller's intent** (Side Job: hard cap of 1 from the space's rules); supply / affordability / cell availability are global constraints checked dynamically in the enumerator. Forward-compat for cards that impose real caps (e.g., a hypothetical "build at most 2 stables this turn"). Farm Expansion sets `max_builds=None`.

- **Card-trigger fields on the new pendings: deferred entirely.** Earlier drafts had `triggers_resolved` reset per commit; mid-conversation we flipped to "don't reset" (one multi-shot session is one action with multiple builds, per the rules "in a single action, you can build as many rooms as you can afford, one after another"); finally settled on "don't add the fields at all yet." Card-trigger machinery will be added per-pending when the first card needs it. The question of reset-vs-persist will be settled then per the relevant rules interpretation.

- **Function naming under the function-name prefix taxonomy.** The taxonomy prefers singular Commit-derived names (`_execute_<sub_action>` where `<sub_action>` matches the singular Commit it handles): `_execute_sow`, `_execute_plow`, `_execute_build_stable`. The multi-shot effect function would conflict with the existing singular `_execute_build_stable` (alive during the Task 5C → Task 5D coexistence). Resolution: introduce the new function under the temporary plural name `_execute_build_stables` during step 6 (coexisting with the old), then rename to singular in step 7 when the old is deleted. Final state matches the taxonomy.

- **ChooseSubAction category names: `"build_stables"` / `"build_rooms"` (plural) vs. `"build_stable"` / `"build_room"` (singular).** Side Job uses singular `"build_stable"` — the rules read "Build 1 stable and/or Bake Bread", singular. Farm Expansion uses plural `"build_stables"` / `"build_rooms"` — the rules read "Build rooms and/or build stables", plural. The split is meaningful and rule-faithful: each space's category names follow its own rule text. (An earlier draft normalized both to singular for internal consistency; rejected after recognizing it overrode genuine rule-text differences.)

- **`auto_pop=False` semantics: "don't pop" vs. "effect function owns stack management".** The flag describes the dispatcher's behavior, not the effect function's. What an `auto_pop=False` effect function does varies — multi-shot pendings leave themselves on top via `replace_top`; `_execute_build_major` pops for non-ovens and pushes wrappers for ovens. The flag is consistently "dispatcher steps back," with the effect function free to do whatever its semantics require.

- **Order of work — the dispatch-table conflict.** Original step order put Farm Expansion wiring (step 6) before Side Job migration (step 8). Caught during design that this would leave a window where `_choose_subaction_farm_expansion` could push `PendingBuildStables` but `COMMIT_SUBACTION_HANDLERS[CommitBuildStable]` still pointed at the singular `PendingBuildStable` — `_apply_commit_subaction`'s `isinstance` assertion would fail. Reordered: Side Job migration (now step 7) precedes Farm Expansion wiring (step 8). Avoids the conflict; everything else falls out.

- **Pasture-cache fix in the new effect function (not a separate cleanup).** Spotted during the convention sweep — Task 5C's `_execute_build_stable` didn't recompute pastures, and CLAUDE.md explicitly listed it as a pasture-changing resolver. Folded the fix into the new function rather than a separate one-line patch to the old: since the old function was being deleted at step 7 anyway, fixing it twice would have been wasted work. The fix is directly exercised by a dedicated test in `tests/test_farm_expansion.py` that prefabs a state with an existing pasture and asserts the cache updates.

- **Helper-organization sweep beyond the strict Farm Expansion need.** The plan initially proposed only `_can_build_stable_farm_expansion(p)` and inline `_room_cost(material)`. A first-principles re-examination revealed broader deduplication opportunities: `_can_plow` and `_has_room_placement` duplicated their enumerators' logic; `_has_stable_placement` could fold into a parameterized `_can_build_stable(p, cost)`; `_can_afford_room` could be a one-liner over `ROOM_COSTS` + `_can_afford`. The sweep included `_can_plow → bool(_legal_plow_cells)` as opportunistic cleanup of an unrelated predicate. Bundled into Part 1 Changes 3–5 as behavior-preserving refactors.

- **Cost handling: `Resources.__ge__` vs. `_can_afford(p, cost)` helper.** The new multi-shot enumerators need to ask "can the player afford this cost?" Two options: add `Resources.__ge__` for `p.resources >= cost` semantics, or add a per-`(player, cost)` helper. Chose the helper because (a) `Resources` partial-ordering opens a small can of worms (`__ge__` paired with `__le__`/`__lt__`/`__gt__` for consistency? `total_ordering` decorator?); (b) affordability is naturally per-player, so a function over `(p, cost)` reads as cleanly as the operator at call sites.

For the full design discussion thread (including discarded alternatives like per-individual-build trigger events, the plural-named-throughout naming choice, deferred discussion of `Resources.__ge__`), see `TASK_5D.md`.

### Out of scope (deliberate)

- **Farm Redevelopment** and **Fencing** remain `NotImplementedError`. Farm Redevelopment will reuse `PendingRenovate` and a new `PendingBuildFences`. Fencing introduces `PendingBuildFences` and the deferred fence-configuration legality (which lacks even a placement-legality predicate today).
- **Harvest phases** (HARVEST_FIELD / HARVEST_FEED / HARVEST_BREED) and rounds 5–14 — entirely deferred. Engine still halts at `Phase.BEFORE_SCORING` after round 4's RETURN_HOME.
- **Card-trigger machinery on the new pendings.** `PendingFarmExpansion`, `PendingBuildStables`, and `PendingBuildRooms` were introduced **without** `triggers_resolved` fields or `TRIGGER_EVENT` classvars. When the first card needing to fire on `"before_build_stable"`, `"before_build_room"`, or `"before_farm_expansion"` is implemented, the relevant pending(s) gain the field + classvar at that time, and the question of whether the field persists across commits or resets per commit is settled then.
- **Once-per-turn card pattern.** Sketched during the design conversation — a future `triggered_this_turn: frozenset[str]` field on `PlayerState`, cleared in `_apply_place_worker`, populated by once-per-turn cards' `apply_fn`s. No Family-game card needs this today; both the field and its lifecycle are deferred until the first such card lands.
- **`PendingBuildRoom` (singular).** Not introduced. Room construction shares `PendingBuildRooms` (plural multi-shot) across all current and likely future callers (Farm Expansion today; future cards that grant room builds will share the same pending). The naming asymmetry with the now-retired singular `PendingBuildStable` is intentional — there's no current need for both shapes.
- **Compound-card-interaction machinery** — still deferred (per `IMPLEMENTATION_CHOICES.md` item 11).
- **Atomic-space trigger hosting** (phase tracking, phase-transition mechanism) — still deferred.

### Bugs caught during implementation

Implementation went unusually cleanly — most of the design conversation happened up front, and the order-of-work + Part 1 refactor sequencing meant every step had a clear green-tests checkpoint. The only test that broke during implementation was `tests/test_engine.py::test_step_raises_on_unimplemented_non_atomic`, which had used `farm_expansion` as its example of an unimplemented space — updated at step 8 to use `farm_redevelopment` instead.

The biggest single risk — step 7's coordinated edit (delete old singular function, rename new function in, delete old pending, update dispatch table, migrate Side Job, update Side Job tests) — landed first try. Helped by the pre-task design conversation that surfaced the dispatch-table conflict (forcing the reorder) and the function-naming question (forcing the temporary-plural-name choice).

The pasture-cache fix was *not* a bug caught during implementation — it was caught during the design conversation when CLAUDE.md's "pasture-changing resolvers" list was cross-checked against the actual `_execute_build_stable` code. The new effect function fixed it from the start; a dedicated test confirms.

### Test count after Task 5D

| File | Tests |
|---|---|
| `tests/test_state.py` | 28 (unchanged) |
| `tests/test_helpers.py` | 37 (unchanged) |
| `tests/test_scoring.py` | 8 (unchanged) |
| `tests/test_legality_atomic.py` | 27 (unchanged) |
| `tests/test_legality_non_atomic.py` | 58 (+2: three `_has_stable_placement` tests replaced with five `_can_build_stable` tests covering the cost dimension) |
| `tests/test_resolution_atomic.py` | 25 (unchanged) |
| `tests/test_engine.py` | 28 (unchanged; one test rewritten to use `farm_redevelopment` after `farm_expansion` was implemented) |
| `tests/test_grain_utilization.py` | 24 (unchanged) |
| `tests/test_potter_ceramics.py` | 11 (unchanged) |
| `tests/test_bake_bread.py` | 16 (unchanged) |
| `tests/test_farmland.py` | 8 (unchanged) |
| `tests/test_cultivation.py` | 7 (unchanged) |
| `tests/test_side_job.py` | 9 (+1: `test_side_job_stable_singleton_stop_after_commit` covering the Approach-2 singleton-Stop state; the existing tests' trace shapes also updated for commit + Stop) |
| `tests/test_animal_markets.py` | 13 (unchanged) |
| `tests/test_major_improvement.py` | 9 (unchanged — verified the `_execute_build_major` absorption introduced no observable change) |
| `tests/test_house_redevelopment.py` | 10 (unchanged) |
| `tests/test_farm_expansion.py` | **25** (new) |
| **Total** | **343** |

315 → 343, net +28.

`random_agent_play` across seeds 0–99 (run both before and after the changes per the acceptance criterion) all pass; Farm Expansion is selected by the random agent in 40 of 100 seeds.

### Documentation cascade

Concurrent doc updates landed alongside the implementation:

- **`TASK_5D.md`** — created during the design conversation, ~900 lines covering all 10 implementation steps, the pre-implementation discussion, ordering rationale (especially the Part 4 → Part 3 swap), test plan, and acceptance criteria. Includes a dedicated note on the pasture-cache fix and its dedicated test.
- **`CLAUDE.md`** — extensive updates: status table grew by 7 rows for the Task 5D items; "Not yet implemented" trimmed from three spaces to two. New "Multi-shot sub-action pendings" subsection under "Additional Design Principles" describing the full pattern. "Lifecycle of a non-atomic turn" bullet updated with the multi-shot variant parenthetical. Sub-action cost handling bucket-2 examples updated. Per-file descriptions updated for `constants.py` (`ROOM_COSTS`), `actions.py` (`CommitBuildRoom`, updated `CommitBuildStable`/`CommitBuildMajor` descriptions, updated `CommitSubAction` framing now that all commits go through the generic path), `pending.py` (added `PendingBuildStables`/`PendingBuildRooms`/`PendingFarmExpansion`, removed `PendingBuildStable`), `legality.py` (added `_can_afford`/`_can_build_stable`/`_legal_room_cells`; noted predicates that are now one-liners), `resolution.py` (added `_new_grid_with_cell` utility; updated effect function descriptions including the pasture recompute; updated `_execute_build_major` description to reflect the generic dispatch path; updated handler counts), `engine.py` (updated `_apply_action` branch count and `_apply_commit_subaction` description for `auto_pop`). Per-file description added for `tests/test_farm_expansion.py`; `tests/test_side_job.py` description updated for the multi-shot trace shape. Directory tree filled in (also caught a Task 5C oversight — the tree had been missing all Task 5C test files). A subsequent cleanup pass (after Task 5D landed) removed two stale CLAUDE.md sentences that no longer described current code: the `_execute_build_major` "acknowledged stretch" bullet under the function-name prefix taxonomy, and the `pasture.py` "separate file" rationale referencing `Farmyard.__post_init__` (which was disabled in CHANGES.md Change 3). Three "pop" phrasings under the dispatcher description were tightened to mention `auto_pop`-conditional popping. `POSSIBLE_NEXT_STEPS.md` added to the Documentation Files table.
- **`CHANGES.md`** — Change 6 added (cross-cutting summary of all Part 1 refactors + the multi-shot pattern + the pasture-cache fix + the `PendingBuildStable` retirement). Test counts updated to 343.
- **`POSSIBLE_NEXT_STEPS.md`** — updated earlier in the session (before Task 5D implementation) to reflect that Farm Expansion was selected as the next task; afterwards stays accurate for the next phase (Farm Redevelopment / Fencing / harvest).
- **`RULES.md`** — added a clarification to the "And/or" vs "And Afterward" subsection: "Each sub-action category may be taken at most once within the action; you cannot return to a category after switching to the other (e.g., on Farm Expansion: rooms-then-stables or stables-then-rooms, but not rooms-then-stables-then-rooms)." Rule was implicit but the wording was ambiguous; clarified before implementation locked in the once-per-category interpretation.
- **`agricola/state.py`** — opportunistic cleanup during the post-Task-5D documentation pass: removed a dead import (`from agricola.pasture import compute_pastures_from_arrays`, only referenced in commented-out code) and the long commented-out `__post_init__` block. The design rationale for the disabled auto-fill lives in CHANGES.md Change 3 and the cache-discipline note in CLAUDE.md; the commented code itself is preserved history that those docs cover.

### Conventions established (stable, documented in CLAUDE.md)

- **`auto_pop: bool` flag on `COMMIT_SUBACTION_HANDLERS` entries.** Describes the dispatcher's behavior; `True` = pop after the effect, `False` = leave the stack alone. Documented in CLAUDE.md "agricola/engine.py" per-file description and the new "Multi-shot sub-action pendings" subsection.
- **Multi-shot sub-action pending pattern.** Pendings with `max_builds: int | None` + `num_built: int` + effect function with `auto_pop=False` + Stop-as-explicit-exit. Documented in the new "Multi-shot sub-action pendings" subsection under "Additional Design Principles".
- **`max_builds` as caller-imposed cap.** Distinct from global constraints (supply, affordability, cell availability), which are checked separately in the enumerator. Documented in the multi-shot subsection.
- **Singleton-`Stop` arises uniformly regardless of binding constraint.** Whether the cap, supply, affordability, or cell-availability constraint is what blocks further commits, the player sees the same singleton-`Stop` state — preserves trace consistency for MCTS / replay.
- **ChooseSubAction category names follow each space's rule text.** Side Job uses singular `"build_stable"` (rules say "Build 1 stable"); Farm Expansion uses plural `"build_stables"` / `"build_rooms"` (rules say "Build rooms and/or build stables"). The split is meaningful, not an inconsistency.
- **Card-trigger machinery is deferred to per-pending need.** New pendings don't carry `triggers_resolved` / `TRIGGER_EVENT` until a card actually needs to fire on them. When added, the question of cross-commit persistence will be settled per the rules interpretation. Documented in the multi-shot subsection's final paragraph.
- **`ROOM_COSTS: dict[HouseMaterial, Resources]` as a constant.** Mirrors `MAJOR_IMPROVEMENT_COSTS` shape; lives in `constants.py`; consumed by both `_can_afford_room` (legality) and `_choose_subaction_farm_expansion` (resolution). Pattern: per-material cost data lives as a static dict in constants.
- **Predicate-shadows-enumerator pattern.** Existence predicates that ask "is there a legal cell?" should be one-liners over their cell enumerator (`_can_plow → bool(_legal_plow_cells(p))`). Single source of truth for "where can X go" lives in the enumerator; predicates derive.
- **`_can_afford(p, cost)` for generic affordability checks.** Component-wise comparison helper in `legality.py`. Pattern: parameterized affordability checks compose with per-action cost lookups (e.g., `ROOM_COSTS[material]`, `MAJOR_IMPROVEMENT_COSTS[idx]`).
- **`_can_build_stable(p, cost)` parameterized predicate.** Combined supply + cell-availability + affordability in one call. Replaces the deleted `_has_stable_placement` + inline cost checks across four sites. Pattern: per-action predicates take their cost as a parameter, so each call site supplies its own (Side Job: 1 wood; Farm Expansion: 2 wood; future cards: as stated).
- **`_new_grid_with_cell` helper in `resolution.py`.** Small utility wrapper sitting alongside `_update_player` / `_update_space`. Used by `_execute_plow`, `_execute_build_stable`, `_execute_build_room` (and future cell-placing effects) instead of inline nested tuple-comprehensions.

### Process improvements adopted mid-task

- **Run pre-task baselines (test count + random-agent 100-seed sweep) before any code edits.** Established as a pre-flight habit during Task 5D. Captures the regression baseline cleanly; the 100-seed sweep also validates the random-agent harness itself.
- **One commit per implementation step with descriptive messages.** Each commit carries a clear "what / why / test count" message. Enables future `git bisect` if a regression surfaces; gives the reviewer a 10-step narrative rather than one monolithic diff. Established during Task 5D's git-init pass.
- **Convention sweep against CLAUDE.md after each major task.** Walks CLAUDE.md looking for stale phrasings ("special-case branch" after the branch is deleted; "and pops" after the pop becomes conditional) and applies the doc's own framing ("describe current code, not history") to trim accumulated cruft.

### Next task

Implementation surface for the Family game's work phase is now essentially complete pending three pieces, in increasing complexity:

- **Farm Redevelopment** — renovate (mandatory first) + fence build. Will reuse `PendingRenovate`; needs the `PendingBuildFences` infrastructure shared with Fencing.
- **Fencing** — the deferred fence-validity enumeration problem. The hardest of the three remaining spaces because it lacks even a legality predicate today. May be best paired with Farm Redevelopment (both need fence-build machinery).
- **Harvest phases** (HARVEST_FIELD / HARVEST_FEED / HARVEST_BREED) — multi-step harvest logic with player decisions (which goods to convert, how to feed, whether to beg). The decision points in HARVEST_FEED are the first real "strategic choice" decisions the engine surfaces beyond worker placement. Probably the highest-value addition to gameplay realism after the three remaining spaces land. Unblocks rounds 5–14.

The card-system work (compound-card-interaction machinery, then cards beyond Potter Ceramics) is a separate parallel track. Updated planning in `POSSIBLE_NEXT_STEPS.md`.

---

<a name="task-6-pre"></a>
## Task 6_pre — Fencing Universe Enumeration (2026-05-19)

### What was built

A precursor to the broader Fencing implementation (TASK_6). This task stands up the precomputed universe of pasture shapes that `legal_actions` will iterate over at Fencing-time, validates the layered-universe design from `FENCE_IDEAS.md`, and ships the supporting module + tests. The engine itself is unchanged — `step()` still raises `NotImplementedError` for `fencing` and `farm_redevelopment`. The actual action space, pending dataclass, commit action, legality predicate, resolution, and engine wiring are deferred to TASK_6.

**Two new files**, both standalone (`agricola/fences.py` imports only stdlib; `tests/test_fences.py` imports only from `agricola.fences`):

- `agricola/fences.py` — four precomputed universes of candidate pasture-shape bitmaps for the 3×5 farmyard. Built once at module import; ~0.22 seconds.
- `tests/test_fences.py` — 83 tests covering grid constants, filter primitives, and universe construction.

**The four universes**, in containment-chain order `RESTRICTED ⊆ EXTENDED ⊆ FAMILY ⊆ FULL`:

| Universe | Size | Filter | Purpose |
|---|---|---|---|
| `UNIVERSE_FULL` | 1518 | internal-fence ≤ 15, connected, no donut, no starting-room overlap | broadest baseline (accommodates a full-game card granting extra perimeter fences) |
| `UNIVERSE_FAMILY` | 762 | as FULL but with **total**-fence ≤ 15 | rules-correct for Family game mode (no perimeter-fence card) |
| `UNIVERSE_EXTENDED` | 192 | strategist-curated shape categories (rectangles, 3- and 4-cell L's, etc.) on PASTURE_CELLS | policy-network output space; relaxation buffer above RESTRICTED |
| `UNIVERSE_RESTRICTED` | 108 | tightest strategist-curated set (17 shape categories) | runtime default for `legal_actions` |

Each universe is exported as a `(tuple, frozenset)` pair: the tuple gives deterministic lex-on-cells iteration (sort key `_cells_of(bm)` returns the cells in row-major order); the frozenset gives O(1) membership lookup.

**Four filter primitives** in `fences.py`: `_is_connected` (BFS), `_internal_fence_count` (scan of 22 internal grid edges), `_perimeter_fence_count` (popcount-weighted sum via `PERIMETER_EDGE_COUNT_PER_CELL`), `_total_fence_count` (sum of the two), `_has_hole` (complement flood-fill with two edge-case branches: empty complement → no hole; complement entirely interior → guaranteed hole).

**Shape-category helpers** for the curated universes: `_enum_rects` (all `rows × cols` rectangles in scope), `_enum_3cell_Ls`, `_enum_3cell_Ls_2right_1left`, `_enum_4cell_Ls`, `_adjacents_of`, `_enum_5cell_2x2_plus1`, `_enum_6cell_2x2_plus2`. Each takes a `scope` frozenset and returns a list of frozensets; set semantics in the calling enumerator absorb duplicates from overlapping categories.

**`__main__` block** prints the four universe sizes when invoked as `python -m agricola.fences`. Stays silent on regular `import`. Used during implementation to capture the exact-equality assertions for the four `test_size_is_recorded` tests.

### Design conversation (pre-implementation)

A long iterative design pass produced `FENCE_IDEAS.md` (217 lines, the broader Fencing rationale) and `TASK_6_pre.md` (~1100 lines) before any code changed. The conversation covered multiple alternatives at each decision point; only the chosen path is summarized here.

- **Universe construction strategy: fixed-list with bitmaps vs on-the-fly construction.** Section 3 of FENCE_IDEAS strongly recommended fixed-list. Settled directly on fixed-list — 32K-candidate scans are sub-second at module load, bitmap-encoded entries make per-call legality checks O(1), and hand-curation of the restricted universe is trivial (just drop entries). On-the-fly is kept as a documented fallback if universe-materialization ever breaks down.

- **One universe vs three vs four.** Started with one (just `UNIVERSE_FULL`), grew to three (FULL + EXTENDED + RESTRICTED, per FENCE_IDEAS Section 3's layered-restriction pattern), then to four after the user pointed out that internal-fence-only ≤ 15 anticipates a full-game card grants extra perimeter fences but **the Family game has no such card**. Added `UNIVERSE_FAMILY` (total-fence ≤ 15) as the rules-correct universe for the currently-implemented game mode. FULL remains as the broader rules-permissible baseline for future-proofing.

- **The strategist-curated `UNIVERSE_RESTRICTED` and `UNIVERSE_EXTENDED`.** The user (a world-class Agricola player) specified 17 shape categories for RESTRICTED — built from `PASTURE_CELLS` (cols 1-4, excluding column 0 by strategic preference) and `NARROW_CELLS` (cols 2-4, tighter sub-grid). EXTENDED relaxes most NARROW_CELLS-scoped categories to PASTURE_CELLS, adds all 4-cell L's, adds a 6-cell `2×2 + 2-adjacent-extras` category, and includes two ad-hoc shapes (`PASTURE_CELLS - {(0,1)}` and `PASTURE_CELLS - {(0,1), (0,2)}`). The two ad-hoc shapes are explicitly present in *both* RESTRICTED and EXTENDED. The strategic exclusion of `(0,0)` from the square scope is loosened only for the 5-cell `2×2 + 1` category, where the user explicitly allowed `(0,0)` as the extra cell.

- **Internal-fence filter rationale flipped mid-conversation.** Initially documented as "the player has 15 fence pieces; pastures requiring > 15 internal fences are unbuildable." The user clarified: a full-game card grants additional fence pieces only for perimeter placements, so the internal-only ≤ 15 cap is the cards-friendly upper bound. Family game tightens this to total ≤ 15 (no such card). This re-framing produced the FAMILY universe.

- **Sort order: bitmap-numeric vs lex-on-cells.** The first draft used bitmap-numeric order (`sorted(bms)`). User pointed out that lex-on-cells is more intuitive for human inspection (`{(0,0)} < {(0,0), (0,1)} < {(0,1)}` matches reading order). Lex-on-cells is implemented via `_cells_of(bm)` which converts a bitmap back to cells in row-major iteration order — the resulting tuple comparison is exactly lex on sorted cells. Used as the sort key in all four enumerators.

- **`UNIVERSE_FULL` filter: starting-room overlap.** Cells `(1, 0)` and `(2, 0)` are permanent starting rooms placed by `setup` in every game. Per game rules, cells with rooms cannot be enclosed by fences. Encoded into the universe as `bm & STARTING_ROOM_BM == 0` — cheapest of the four filters, applied first as a short-circuit. The exclusion is rules-derived (structural fact about the engine), distinct from the strategist-curated `(0,0)` exclusion in `PASTURE_CELLS` (which is a heuristic about strategic value).

- **Donut detection: complement flood-fill.** Picture the 3×5 grid embedded in the infinite plane. A pasture is topologically a donut iff its complement has a connected component that doesn't touch the grid perimeter. Detected by flood-filling the complement starting from every perimeter cell in the complement; any unreached complement cell is an enclosed pocket. Three branches: empty complement (cells_bm fills the grid → no hole); complement contains no perimeter cell (interior-only complement → guaranteed donut); BFS branch (the general case).

- **YAGNI on pending-dataclass fields.** During the broader FENCE_IDEAS design, the user articulated a principle: don't add fields to pending dataclasses purely to anticipate future cards. Applied here by *not* including `max_builds` on the future `PendingBuildFences` (will be added when a card actually needs to cap fence builds per action). `triggers_resolved` / `TRIGGER_EVENT` are still planned to be included on `PendingBuildFences` because they back the existing trigger architecture — the principle distinguishes fields backing already-shipped uniform machinery from fields that would sit inert until cards.

- **Lower-bound size placeholders in tests.** Earlier drafts used `assert len(UNIVERSE_FULL) >= 500` as placeholder lower bounds. User asked whether these matter once exact values are pinned. Honest answer: not really — `test_non_empty` already catches the empty case, and the lower bound is overwritten with the exact value in the same commit. Dropped the placeholder framing in favor of going directly to exact-equality assertions once `python -m agricola.fences` produced the four sizes.

- **Resolve-on-pop hook briefly considered.** During the broader Fencing design, the user proposed adding a generic `resolve` function on every pending type, called at Stop-time. Walked through all 19 existing pending types — none would benefit. Per-commit cost (matching `PendingBuildStables` / `PendingBuildRooms`) handles fence-cost accounting cleanly without deferred state. The hook can be added later when an `after_build_fences`-style trigger card actually needs it.

For the full design discussion thread including discarded alternatives (flat full-edge-configuration enumeration, goal-state specification, verify-only / try-and-reject, multi-step one-fence-at-a-time, Pareto-capacity pruning, etc.), see `FENCE_IDEAS.md` Section 7.

### Out of scope (deliberate)

All deferred to TASK_6:

- `PendingBuildFences` dataclass, `CommitBuildPasture(cells: frozenset[(int, int)])` action class, and the related changes to `agricola/pending.py` and `agricola/actions.py`.
- `_can_fence` predicate (top-level Fencing legality), `_enumerate_pending_build_fences` (per-pending sub-action enumerator), `NON_ATOMIC_LEGALITY` and `PENDING_ENUMERATORS` registration.
- `_initiate_fencing` and `_execute_build_pasture` in `agricola/resolution.py`; `NONATOMIC_HANDLERS` and `COMMIT_SUBACTION_HANDLERS` registration.
- Removal of the `fencing` `NotImplementedError` branch in `agricola/engine.py`.
- **Per-entry metadata** (boundary fence-edge bitmaps `h_boundary` / `v_boundary`, cell-adjacency bitmap, frozenset-of-cells for `CommitBuildPasture` construction). Currently each universe entry is just a 15-bit integer; consumers in TASK_6 will need metadata to derive new fence edges, check pasture-adjacency, etc.
- **Per-commit cost-modifier registry for cards** — Section 4 of FENCE_IDEAS flagged fence-building's cost handling as a 4th bucket alongside the three already-documented (no cost / cost-on-pending / commit-time-keyed lookup). Fences' cost is a pure function of state plus commit parameters, computed by the effect function. The CLAUDE.md documentation for this 4th bucket also lands in TASK_6.
- **`after_build_fences` trigger mechanism** — Section 9 of FENCE_IDEAS flagged the user's vegetable-card example ("each time you build N fences where N ≥ current round, gain 1 vegetable") as a candidate consumer for an `after_X` trigger event. The codebase has precedent for `before_X` events but no precedent for `after_X` events yet. Deferred until the first such card needs it.

### Bugs caught during implementation

Implementation went very cleanly — the extensive pre-task design conversation surfaced essentially all the edge cases up front. Two minor things:

- **`agricola-ref/` directory had unrelated import errors** when running `pytest` from the project root. That directory contains a reference implementation from elsewhere; the errors are pre-existing and unrelated to fences.py. Worked around by running `pytest tests/` instead. Not a regression.

- **No silent bugs surfaced.** The 83 new tests pass on first run, including the cross-cutting `test_excludes_pasture_cells_plus_0_0` which explicitly exercises the FULL-vs-FAMILY divergence (PASTURE_CELLS + (0,0) is in FULL but not FAMILY because its total fence count is 16 > 15). The containment chain holds: 108 ⊆ 192 ⊆ 762 ⊆ 1518.

### Test count after Task 6_pre

| File | Tests |
|---|---|
| (all Task 5D files) | 343 (unchanged) |
| `tests/test_fences.py` | **83** (new) |
| **Total** | **426** |

343 → 426, net +83.

The 83 new tests break down as:
- `TestGridConstants` (5): NUM_ROWS / NUM_COLS / NUM_CELLS, `FULL_GRID_BM`, `STARTING_ROOM_BM`, `PERIMETER_BM`, two `NEIGHBOR_BM` spot checks.
- `TestIsConnected` (7): single cell, two-adjacent (horizontal + vertical), two non-adjacent, L-shape, disconnected corners, two-diagonal-cells (orthogonal-only check).
- `TestInternalFenceCount` (6): corner / center / edge cell, full grid, full grid minus center, 2×2 at origin.
- `TestPerimeterEdgeCountPerCell` (4): corners=2, non-corner perimeter=1, interior=0, total=16.
- `TestPerimeterFenceCount` (5): corner / edge / interior cell, full grid, PASTURE_CELLS.
- `TestTotalFenceCount` (5): corner / interior cell, full grid, PASTURE_CELLS, additive-identity sanity.
- `TestHasHole` (6): single-cell / L-shape / full-grid (no hole); donut-around-center (seed_bm=0 branch) and donut-in-pasture-cells (BFS branch); top-and-bottom-rows (no hole, complement is connected to outside).
- `TestUniverseFull` (12): non-empty, no duplicates, lex sort, set-matches-tuple, every-entry-passes-all-filters, starting-room exclusion, full-grid excluded, donut excluded (cleanly isolated via PASTURE_CELLS - (1,2)), single-cell-pasture inclusion, PASTURE_CELLS / NARROW_CELLS inclusion, size=1518.
- `TestUniverseFamily` (9): non-empty, no duplicates, lex sort, subset-of-full, every-entry-passes-filters, full-grid excluded, PASTURE_CELLS included, the FULL-vs-FAMILY divergence test, size=762.
- `TestUniverseExtended` (9): non-empty, no duplicates, lex sort, subset-of-family, subset-of-full, ad-hoc-shape inclusion (×2), 4-cell-L beyond the named four, size=192.
- `TestUniverseRestricted` (12): non-empty, no duplicates, lex sort, subset-of-extended, subset-of-family, subset-of-full, named 4-cell L's (×4), PASTURE_CELLS / NARROW_CELLS inclusion, narrow-minus-corner (×4), ad-hoc shape inclusion (×2), 1×4 absence, size=108.

`random_agent_play` across the existing 100-seed sweep continues to pass (fences.py doesn't touch the engine, so this was a sanity check, not a regression risk).

### Documentation cascade

Concurrent doc updates landed alongside the implementation:

- **`FENCE_IDEAS.md`** — 217-line design document covering the broader Fencing rationale: enumeration strategy (Section 3), the unified pasture-commit design (Section 4), MCTS interaction (Section 5), alternative approaches considered (Section 7), and open problems (Section 9). Lives at the project root. Authored before TASK_6_pre.md.
- **`TASK_6_pre.md`** — the implementation plan for this task, ~1100 lines. Parts 1-9 cover module layout, the four filters, restricted/extended enumerators, module-level constants + size-print entry point, tests, CLAUDE.md edits, order of work, acceptance criteria, and open questions deferred to TASK_6.
- **`CLAUDE.md`** — directory tree updated to add `agricola/fences.py` and `tests/test_fences.py`. Two new file descriptions added (the `fences.py` description was tightened from an 8-bullet implementation-heavy form to a 3-bullet purpose-and-outputs form during a doc-quality pass at the user's request). Status table grew one row. Test count updated 343 → 426.

### Conventions established (stable, documented in CLAUDE.md)

- **Bitmap encoding for cell-sets**: cell `(r, c)` ↔ bit `r * NUM_COLS + c` (row-major). Used by `fences.py` today; downstream `_enumerate_pending_build_fences` and `_execute_build_pasture` (TASK_6) will use the same encoding for interop.
- **Layered universes pattern.** `(tuple, frozenset)` pairs exported per universe — tuple for ordered iteration, frozenset for O(1) membership. Standard form for any future state-independent action universe (e.g., if Farm Redevelopment ever needs a precomputed fence-configuration universe, it would mirror this shape).
- **Lex-on-cells sort key.** `_cells_of(bm)` returns cells in row-major iteration order; sorting bitmaps by this key produces lex order on the sorted-cell-tuple. More intuitive than bitmap-numeric order for human inspection of test output and trace logs.
- **`__main__` size-printer entry point.** `python -m agricola.fences` prints the four universe sizes. Used to capture exact-equality assertions for size tests; pattern is reusable for any future module with similar precomputed-universe characteristics.
- **YAGNI on card-anticipating pending-dataclass fields.** Articulated during this task's design conversation: fields that integrate with already-shipped uniform engine machinery (e.g., `triggers_resolved` / `TRIGGER_EVENT`) are OK to add proactively; bespoke per-pending fields with no current engine consumer (e.g., `max_builds` on a future `PendingBuildFences`) wait until a real consumer arrives. Surfaces concretely in TASK_6 when `PendingBuildFences` lands.

### Process notes

- **The "/loop" of design → implement → sweep iterations.** The user drove a long pre-task design pass (multiple sessions across FENCE_IDEAS and TASK_6_pre) before any code was touched. Each design round produced revisions to the plan; the final TASK_6_pre.md was ~1100 lines with the full algorithm pseudocode and test specs. Implementation itself took one round — write fences.py, run `python -m agricola.fences` to get sizes, write test_fences.py with exact assertions, run all tests. 426/426 passed on first run. This is the pattern Task 5D established and Task 6_pre confirms: front-load design, run implementation as a mechanical pass, finish with a documentation sweep.

### Next task

**TASK_6 (the actual Fencing implementation).** Builds on this precursor by introducing:

- `PendingBuildFences` (with `triggers_resolved` and `TRIGGER_EVENT = "before_build_fences"`, but no `max_builds`).
- `CommitBuildPasture(cells: frozenset[(int, int)])` action class.
- Per-entry metadata on each universe entry (boundary fence-edge bitmaps, adjacency bitmap, frozenset-of-cells for commit construction).
- `_can_fence` predicate, `_enumerate_pending_build_fences` enumerator (with subdivision-canonicalization-via-complement-lookup), `_initiate_fencing`, `_execute_build_pasture` (with per-commit cost handling — the 4th sub-action-cost bucket).
- Engine wiring: removal of the `fencing` NotImplementedError, `COMMIT_SUBACTION_HANDLERS` entry, `auto_pop=False` for the multi-shot pattern.

Farm Redevelopment can land as a separate small task after TASK_6 — it reuses `PendingRenovate` and pushes `PendingBuildFences` after renovation. Then the harvest phases (HARVEST_FIELD / HARVEST_FEED / HARVEST_BREED) unblock rounds 5–14.

---

<a name="task-6"></a>
## Task 6 — Fencing, Build Fences, and Farm Redevelopment (2026-05-19)

### What was built

The Fencing and Farm Redevelopment action spaces — the last two non-atomic spaces still raising `NotImplementedError` after Task 5D — both now have working resolution paths. The architectural centerpiece is a reusable `PendingBuildFences` sub-action that both spaces (and some future card effects) push to do the actual fence-building work.

**Files modified:**

- `agricola/fences.py` — extended with edge metadata (per-shape boundary fence-edge bitmaps + adjacency bitmap + cells frozenset), four parallel `UNIVERSE_*_ENTRIES` tuples of `PastureCandidate` dataclasses, four `UNIVERSE_*_SMALLEST_ENTRIES` fast-path tuples (the 1×1 subset of each universe), `ENTRIES_BY_BM` bitmap-keyed lookup dict, fence-array pack/apply helpers, the `compute_new_fence_edges` shared cost helper, and the 1×1-at-(0, 0) addition to RESTRICTED (108→109) and EXTENDED (192→193). The pre-existing universe constants from Task 6_pre are untouched.

- `agricola/pending.py` — three new pending dataclasses: `PendingFencing` (thin parent above PendingBuildFences hosting the `before_fencing` trigger event), `PendingBuildFences` (multi-shot sub-action with `pastures_built` / `fences_built` counters and the `subdivision_started` ordering-rule flag), `PendingFarmRedevelopment` (mirrors `PendingHouseRedevelopment` with `build_fences` as the optional second step).

- `agricola/actions.py` — `CommitBuildPasture(cells)` action class added to the `Action` union.

- `agricola/legality.py` — three new `ACTIVE_FENCE_UNIVERSE_*` module constants for the runtime universe selector, `_legal_fencing` placement predicate, `_any_legal_pasture_commit` helper (two-pass 1×1 fast path), `_check_entry_legal` shared per-entry legality chain, and three new enumerators (`_enumerate_pending_fencing`, `_enumerate_pending_build_fences`, `_enumerate_pending_farm_redevelopment`). All registered.

- `agricola/resolution.py` — `_initiate_fencing`, `_choose_subaction_fencing`, `_execute_build_pasture` (multi-shot fence effect, the second pasture-changing effect function alongside `_execute_build_stable`), `_initiate_farm_redevelopment`, `_choose_subaction_farm_redevelopment`. All registered.

- `agricola/engine.py` — the explicit `NotImplementedError` branch for `fencing` and `farm_redevelopment` is dropped; the surviving fallback raise is a defensive guard for unknown space-IDs (only `lessons` qualifies and `legal_placements` excludes it). `CommitBuildPasture` registered in `COMMIT_SUBACTION_HANDLERS` with `auto_pop=False`.

**Test files modified/created:**

- `tests/test_fences.py` — extended with 39 new tests covering `PastureCandidate` shape, boundary/adjacency bitmap correctness, parallel `_ENTRIES` tuples, `ENTRIES_BY_BM` coverage, `SMALLEST_ENTRIES` correctness, the (0, 0) addition, fence-array pack/apply round-trip, `compute_new_fence_edges`. Existing size pins updated for RESTRICTED 108→109 and EXTENDED 192→193.

- `tests/test_fencing.py` (new) — 35 engine-level integration tests covering single + multi-pasture walks, subdivision + canonicalization, first-pasture-anywhere + adjacency, the enclosable filter, wood + fences-in-supply affordability, re-state-existing rejection, Stop legality at both pendings, counter updates, the builds-before-subdivisions ordering rule (three tests), stack invariants, `_legal_fencing` predicate matrix, universe swap via kwarg + via module constant, pasture cache recompute, and random-agent end-to-end smoke across 10 seeds.

- `tests/test_farm_redevelopment.py` (new) — 20 engine-level integration tests covering renovate-only walk, renovate-then-build-fences walk, Build Fences requires renovate first, Stop legality, WOOD→CLAY and CLAY→STONE progression, STONE blocked, renovation cost on pending, inner PendingBuildFences provenance distinct from Fencing's path, Build Fences engine reuse with the ordering rule still active, `_legal_farm_redevelopment` predicate matrix, Build Fences optional and gated, full-walk stack invariants.

- Two stale pre-Task-6 tests updated:
  - `tests/test_engine.py::test_step_raises_on_unimplemented_non_atomic` renamed to `test_step_raises_on_unknown_space` and changed to test `PlaceWorker("lessons")` (the only space-ID without a registered handler post-TASK_6).
  - `tests/test_legality_non_atomic.py::test_fencing_absent_from_legal_placements` renamed and inverted: fencing now appears in legal_placements when wood + supply are available.

**Engine-level result:** `step()` no longer raises `NotImplementedError` for any action that `legal_placements` ever returns. Every non-atomic space implemented today has a working resolution path; only the harvest phases (HARVEST_FIELD / HARVEST_FEED / HARVEST_BREED) and rounds 5–14 remain as engine-level unimplemented pieces.

### Design conversation (pre-implementation)

A long iterative design pass produced `TASK_6.md` (~1100 lines) across roughly 5 design-conversation rounds before any code changed. Key decisions:

- **PendingFencing + PendingBuildFences split.** Build Fences is the reusable primitive; PendingFencing is the space-specific parent that hosts the `before_fencing` trigger event. Farm Redevelopment pushes PendingBuildFences directly (with distinct `initiated_by_id="farm_redevelopment"` for future cards that gate on entry point).

- **Cost handling as 4th bucket.** Fence cost is neither push-time fixed (bucket 2) nor a const-table lookup keyed on commit parameters (bucket 3). It's a pure function of `(state, commit cells)` computed at execute time by a shared helper (`compute_new_fence_edges`). Multi-shot pasture commits need this because per-commit cost depends on which boundary edges prior commits already placed. Documented as the 4th bucket in CLAUDE.md's "Sub-action cost handling" section.

- **Builds-before-subdivisions ordering rule.** Within one Build Fences action, all new-pasture commits must precede any subdivisions. Once any subdivision lands (`subdivision_started=True`), new-pasture commits drop out of legal_actions. The rule cuts MCTS path-level inflation (factor `C(K+L, K)` for K new + L subdivisions) by eliminating duplicate-end-state paths from commit-order permutations.

  - **Direction matters.** The reverse direction (subdivisions before builds) would break reachability under curated universes: end states reachable only via "build P, subdivide P naming Q1 (Q2 falls out)" — where Q2 isn't in the active universe — would become unreachable. Builds-first preserves reachability under any universe.

  - The user pushed back firmly on this when an early draft had the direction reversed; after working through the reachability argument carefully, reversed to the correct direction.

- **Fixed-list with bitmaps vs on-the-fly enumeration.** Settled directly on fixed-list with precomputed PastureCandidate metadata (one entry per universe shape, carrying boundary bitmaps + adjacency bitmap + cells frozenset). Per-call legality is a filter over the universe with cheap bitwise checks against precomputed per-shape metadata. On-the-fly enumeration would have been simpler but couldn't share the per-shape metadata across calls. Aligned with FENCE_IDEAS.md Section 3.

- **Three runtime active-universe constants.** `ACTIVE_FENCE_UNIVERSE_ENTRIES` / `_SMALLEST_ENTRIES` / `_SET` in `legality.py`, all three pointing at the same universe (kept aligned by construction in `fences.py`). The third constant (SMALLEST) was added during design discussion when the user pushed for full-speed fast-path iteration rather than runtime popcount filtering — the user explicitly said "duplication is fine; speed matters."

- **1×1 at (0, 0) addition to RESTRICTED and EXTENDED.** The strategist's original RESTRICTED universe excluded `(0, 0)` from 1×1 shapes (only PASTURE_CELLS = cols 1-4). For the `_any_legal_pasture_commit` fast-path to work correctly — "if any commit is legal, some 1×1 commit is legal" — every enclosable cell needs a 1×1 candidate in the active universe. Fixed with a one-character change in the category-1 enumerators (`PASTURE_CELLS` → `ENCLOSABLE_CELLS`). Sizes grew RESTRICTED 108→109 and EXTENDED 192→193. Consistent with the existing strategist treatment of `(0, 0)` as a permitted "+1" extra cell in the 5-cell 2×2-plus-1 category.

- **YAGNI on pending-dataclass fields.** Continued from Task 6_pre. Included `triggers_resolved` / `TRIGGER_EVENT` on `PendingBuildFences` (back the shipped trigger architecture); excluded `max_builds` (would be inert without a card actually setting it); excluded a free-fence counter (purely card-driven). The user articulated this distinction explicitly and it was saved to project memory as `feedback_pending_field_yagni.md`.

- **Naming-convention rename.** Initial draft named the placement predicate `_can_fence` to match a task-file shorthand. Re-reading legality.py during implementation showed every other space placement predicate is `_legal_<space>`. Renamed to `_legal_fencing` for consistency. (The `_can_*` prefix is for player-keyed building-block predicates like `_can_renovate(p)`, `_can_bake_bread(state, p)`; `_legal_*` is for placement predicates that take `(state)` and derive the active player.) Also discovered `_legal_farm_redevelopment` already existed in legality.py from a previous task and did exactly what was needed — reused as-is rather than adding a new function.

- **Universe-selector kwarg duplication considered, then settled.** During design discussion, the option of collapsing the three module-level constants into a single bundle/NamedTuple was considered, to avoid the three-constants synchronization burden. Settled on the duplicative-but-explicit shape: three constants + three kwargs, all kept aligned by the fences.py construction. Simpler at every call site.

### Bugs caught during implementation

- **Initially wrote the ordering rule in the wrong direction.** First draft had `subdivisions_started` in the design discussion but I implemented `builds_started` in the dataclass ("after builds, no more subdivisions"). User caught the inconsistency between the field name and the rule intent; reversed to the correct direction (builds first, subdivisions follow; `subdivision_started` flips True on the first subdivision commit). The reachability argument also confirmed this direction. Fixed in TASK_6.md before code was touched.

- **`UniverseEntry` opaque name.** Initial dataclass name was `UniverseEntry`. User pointed out it's unclear that the dataclass stores a pasture. Renamed to `PastureCandidate` throughout TASK_6.md before implementation.

- **`_compute_new_fence_edges` underscore.** Initially named the cross-module cost helper with an underscore. Convention used elsewhere in `fences.py` (`pack_fences_h`, `apply_fence_edges_h`) drops the underscore on functions exposed across modules. Renamed to `compute_new_fence_edges` throughout TASK_6.md before implementation.

- **Stale references in CLAUDE.md caught by the post-implementation sweep:**
  - "the four pasture-changing resolvers" → updated to "the two pasture-changing effect functions" (now that the two functions are factually `_execute_build_stable` and `_execute_build_pasture`).
  - "`PendingBuildFences` will follow the same pattern when introduced" — pre-TASK_6 sentence in the bucket-2 description. Removed (PendingBuildFences uses bucket 4, not bucket 2).
  - "Raises `NotImplementedError` for `PlaceWorker` on `farm_redevelopment` or `fencing`" in the engine.py description. Replaced with the defensive-guard framing.

- **`_check_entry_legal` factored to a shared helper.** Both `_any_legal_pasture_commit` and `_enumerate_pending_build_fences` apply the same per-entry legality chain. Initially inlined in both; factored to a single helper with the per-call state bitmaps passed as kwargs (a deliberate explicit-argument shape rather than a dataclass context, to keep the bitwise hot path tight).

### Test count after Task 6

| File | Tests | Δ vs Task 6_pre |
|---|---|---|
| (all Task 5D + Task 6_pre files except test_fences.py) | 343 | unchanged |
| `tests/test_fences.py` | 122 (was 83) | +39 |
| `tests/test_fencing.py` (new) | 35 | +35 |
| `tests/test_farm_redevelopment.py` (new) | 20 | +20 |
| **Total** | **520** | **+94** |

426 → 520, net +94 tests.

The 35 new tests in `test_fencing.py` break down roughly:
- Basic walks (single + multi-pasture): 2
- Subdivision + canonicalization: 2
- First-pasture-anywhere + adjacency: 2
- Enclosable filter: 1
- Affordability (wood + fences-in-supply): 2
- Re-state-existing rejection: 1
- Stop legality at both pendings: 2
- Counter updates: 1
- Builds-before-subdivisions ordering rule: 3
- Stack invariants: 1
- `_legal_fencing` predicate matrix: 4
- Universe swap (kwarg + module constant + default check): 3
- Pasture cache recompute: 1
- Random-agent end-to-end smoke (parametrized, 10 seeds): 10

The 20 in `test_farm_redevelopment.py` mirror `test_house_redevelopment.py` structurally — basic walks, Stop legality, material progression — plus additional cases covering the Build Fences integration and the inner-PendingBuildFences provenance distinct from Fencing's path.

### Documentation cascade

Concurrent doc updates landed alongside the implementation:

- **`TASK_6.md`** — the implementation plan, ~1100 lines. Parts 1–12 cover edge metadata in fences.py, three pending dataclasses, the new commit action, the legality additions, the resolution additions, engine wiring, two new test files, additions to test_fences.py, CLAUDE.md updates, order of work, acceptance criteria, and open questions deferred to future tasks.

- **`CLAUDE.md`** — substantial updates:
  - Status table grew 8 rows for TASK_6 work.
  - "Not yet implemented" list shrunk to harvest phases + rounds 5-14 + cards-other-than-Potter-Ceramics. Closing sentence added noting the `NotImplementedError` branch is now a defensive guard for unknown space-IDs.
  - "Sub-action cost handling" expanded from 3 to 4 buckets.
  - **New subsection "Reusable sub-action pendings"** added to "Additional Design Principles" — placed second, between "Player parameter convention" and "Function-name prefix taxonomy." Documents the default of single-reusable-pending-with-caller-supplied-provenance, the current 6 reusable sub-action pendings, the caller-supplied state mechanism (cost, max_builds, initiated_by_id), exceptions, and a cross-reference to the pending-stack mechanism.
  - **New subsection "Fencing and Build Fences"** added to "Engine and Turn Resolution Architecture" — placed between "The pending-decision stack" and "Card implementation status." Covers the problem (enormous action space, difficult to enumerate either in principle or per state), Build Fences as a reusable primitive sub-action, the multi-step framing (build *pastures* not *fences*; commit semantic intent, engine derives fence delta), the builds-before-subdivisions ordering rule, the bitmap-based per-call enumeration, cost handling via the bucket-4 helper, and the two load-bearing implementation choices (fixed-list-of-pastures with policy-head motivation, and hand-curated RESTRICTED universe with the layering pattern).
  - Per-file descriptions updated for `state.py`'s Farmyard (pasture-cache caller-discipline now references the two effect functions), `actions.py` (CommitBuildPasture added), `pending.py` (three new pendings), `legality.py` (active-universe constants, helpers, three new enumerators), `resolution.py` (initiate + choose handlers + the new effect function), `fences.py` (completely rewritten — edge bitmaps, PastureCandidate, parallel tuples, SMALLEST tuples, ENTRIES_BY_BM, pack/apply helpers, compute_new_fence_edges).
  - New test-file descriptions for `test_fencing.py` and `test_farm_redevelopment.py`. `test_fences.py` description split into two layers (TASK_6_pre + TASK_6).
  - Test count updated 426 → 520.

- **`SESSION_HISTORY.md`** — this entry.

### Conventions established (stable, documented in CLAUDE.md)

- **Bucket 4 sub-action cost handling: pure function of (state, commit params).** New cost-handling pattern for sub-actions whose per-commit cost depends on the current state. Cost is computed at execute time by a shared helper called from both the enumerator (affordability filtering) and the effect function (debit). Fencing is the canonical example; future card effects that modify per-edge fence cost will plug into the same helper.

- **Builds-before-subdivisions ordering rule.** Within a Build Fences action, all new-pasture commits precede any subdivisions. Documented in CLAUDE.md's PendingBuildFences description and in the "Fencing and Build Fences" architecture subsection, with cross-references to TASK_6.md Part 2.3 for the reachability argument. Pattern is local to Build Fences today but generalizes: "use a directional ordering rule at the action-space layer to cut path-level MCTS redundancy when reachability can be preserved by a direction."

- **Reusable sub-action pendings as the default design.** New subsection in Additional Design Principles. When designing a new sub-action, default to a single reusable pending pushable from any caller with caller-supplied `initiated_by_id`, not a space-specific specialization. Every current sub-action pending fits this pattern.

- **Fixed-list-with-bitmaps for high-branching action enumeration.** Documented in CLAUDE.md's "Fencing and Build Fences" subsection. When an action space's legal set is too large to enumerate from scratch per call, precompute a state-independent universe of action objects with metadata, and per-call legality becomes a filter over the universe. Stable policy-head dimension is a side benefit.

- **Three-constant runtime universe selector pattern.** Module-level constants paired with per-call kwarg overrides, for swapping enumeration universes globally or per-call. Tests use the per-call form to avoid disturbing other tests; experiments use the global form.

- **1×1 fast-path for any-legal-commit predicates.** When checking "is at least one commit legal here?", iterate the precomputed 1×1 subset of the universe first. Capitalizes on the property "any legal larger shape implies some legal 1×1" (with the (0, 0) addition ensuring full enclosable-cell coverage).

### Memory saved during this task

`feedback_pending_field_yagni.md` saved to project memory. Articulates the user's principle: don't add fields to pending dataclasses purely to anticipate cards. The principle distinguishes fields that integrate with already-shipped engine machinery (like `triggers_resolved` / `TRIGGER_EVENT`, which back the uniform trigger system) — fine to add proactively — from bespoke per-pending fields that would be inert until a card sets them (like `max_builds` on PendingBuildFences). Will guide future pending-design decisions.

### Process notes

- **The design-first pattern continues to pay off.** TASK_6.md went through ~5 substantial design-conversation rounds before code. Each round produced revisions: introducing PendingFencing as the parent; switching the ordering rule from subdivisions-first to builds-first; renaming UniverseEntry to PastureCandidate; renaming `_can_fence` to `_legal_fencing`; etc. By the time implementation started, the file structure, function names, and key invariants were fully pinned. Implementation itself ran as a mechanical pass — 8 of the 11 ordered steps landed with zero rework; the 2 stale-test failures and 1 directional bug in the ordering rule (in the dataclass field name) were caught during implementation and fixed within the same session.

- **520/520 first-time pass.** All 39 new test_fences.py additions + 35 new test_fencing.py + 20 new test_farm_redevelopment.py tests passed on first run. The 2 pre-existing tests that needed updating were caught by the regression sweep before the new test files landed. No additional iteration needed once the implementation was in.

- **Mid-implementation interruption + recovery.** The session was interrupted while editing test files; resumed cleanly by checking the file state, running the regression suite (which confirmed everything-so-far still passed at 465 tests), and continuing from the next pending todo. The todo list and the existing-state of the files were sufficient to resume without re-deriving context.

### Next task

The next two natural targets:

1. **Harvest phases (HARVEST_FIELD / HARVEST_FEED / HARVEST_BREED).** Currently the engine halts at `Phase.BEFORE_SCORING` after round 4's RETURN_HOME. Implementing the three harvest phases would unblock rounds 5–14 and make the engine feature-complete for the Family game. Field harvest is straightforward (take 1 from each planted field); feeding has the begging-marker / cooking-conversion fork; breeding has the per-type breeding-fires logic via `breeding_frontier`.

2. **Random-agent end-to-end across all 14 rounds.** Once the harvest phases land, the random-agent driver can play complete games. This is the first point in the project where end-to-end games complete; tooling for trace analysis, score distribution, and game-length variance becomes possible.

Cards beyond Potter Ceramics are a separate large effort. Several open design questions remain (compound card interactions, after-X trigger mechanics, atomic-space trigger hosting, free-fence accounting) — they're documented in CLAUDE.md "Card implementation status" and in FENCE_IDEAS.md Section 9. Deferred until a concrete card system task lands.

---

<a name="task-7-design"></a>
## Task 7 design — Harvest Implementation Spec + `breeding_frontier` Pareto-Dim Fix (2026-05-20)

> **Note (2026-05-20 follow-up):** The `breeding_frontier` food-as-Pareto-dim change documented in this entry was reverted later the same day after a principled re-examination. The canonical convention is now animal-counts-only Pareto (matching `pareto_frontier`), formalized as the "Preserving optionality" Key Design Principle in CLAUDE.md. See the next section ("Task 7 design follow-up") for the revert and the corrected design.

Design-only session. Produced the full implementation spec for Task 7 (harvest phases) but did not land the implementation itself — that's a follow-up session. The one code change made this session was a targeted fix to `breeding_frontier` in `agricola/helpers.py` to include food as a Pareto dimension, surfaced and prompted by the design discussion.

### What was produced

- **`TASK_7.md`** — 1300-line implementation spec for the three harvest sub-phases (FIELD / FEED / BREED) and the round-5-to-14 unblock. Top-down narrative: engine wiring & phase machine first (Part 2), state objects (Part 3), resolution functions (Part 4), legality enumerators (Part 5), algorithmic primitives (Part 6), integration glue (Part 7), tests (Part 8), documentation (Part 9), order of work (Part 10), acceptance criteria (Part 11), out of scope (Appendix A).

- **`POSSIBLE_NEXT_STEPS.md`** entry E added — captures the "Pareto dominance over upstream goods" principle for eventual addition to CLAUDE.md as a design principle. Documents that food is a one-way downstream derivative of crops/animals; preserving upstream goods strictly dominates preserving the food they could produce; `food_payment_frontier` and `harvest_feed_frontier` follow this; `breeding_frontier` is the deliberate exception (food IS a Pareto dim there because the "release for food" strategic option would otherwise vanish).

- **`agricola/helpers.py`** — `breeding_frontier` updated. The pre-existing dominance check filtered over animal counts only and computed food after the filter — which silently excluded all release-for-food options when an animal type's max-keep config was feasible. Removed the local `dominates()` helper, inlined the dominance check, and added food as a Pareto dim. Updated the docstring to call out that this is an intentional exception to the upstream-goods principle, with the rationale.

- **`tests/test_helpers.py`** — four pre-existing breeding tests adapted to the new behavior (now expect multi-point frontiers in the cooking-rates-non-zero cases), plus one new test `test_breeding_two_pastures_two_sheep_two_boar` asserting the full 10-point frontier for the "two 1×1 pastures, 2 sheep + 2 boar, Fireplace" scenario. The new test demonstrates the constraint that the house pet slot is shared — only one type can breed at a time when both types have a dedicated pasture.

### Why design-only this session

The harvest sub-phase machinery is meaningfully different from prior tasks (which each added a single conceptual unit — Fencing space, Farm Expansion, etc.). Harvest adds:
- Three coordinated phases with shared state.
- The first real strategic decision surface outside worker placement (FEED's "what to convert + whether to beg").
- A new "phase-driven" pending push pattern, distinct from the existing space-driven `_initiate_<nonatomic_space>` pattern.
- A new Pareto-frontier helper (`food_payment_frontier`) usable for future card payments.

Getting the design pinned before implementation began — same pattern as TASK_6 — let the conversation surface and resolve several non-obvious design questions before any code was written. Key questions settled during the session:

- **3-phase vs 5-phase engine state machine.** Initial sketch had `HARVEST_FEED_WAIT` and `HARVEST_BREED_WAIT` to distinguish "pending pushed" from "pending popped." Settled on 3 phases (no new enum values) where `HARVEST_FEED` / `HARVEST_BREED` carry dual meaning by stack state — non-empty = interactive, empty = exit signal. `_resolve_harvest_field` does mechanical work + pushes FEED pendings + transitions phase, mirroring `_resolve_preparation`'s multi-concern shape.

- **Doc ordering.** Original draft was bottom-up (preliminary refactor → helpers → action types → pendings → resolution → legality → engine wiring). For harvest, top-down reads better — show the phase machine first, then drill into specifics. Restructured the doc; Part 10 (order of work) stays bottom-up because implementation order ≠ narrative order.

- **Pareto dominance over upstream goods.** The principle is: when comparing configurations via Pareto filter, compare over upstream goods only, never include downstream derivatives like food. Three rounds of design discussion before the principle was settled correctly. The principle now governs `food_payment_frontier` and `harvest_feed_frontier`. `breeding_frontier` is the documented exception (food IS a Pareto dim there). Principle queued for CLAUDE.md (`POSSIBLE_NEXT_STEPS.md` entry E).

- **Natural-fit filter in `harvest_feed_frontier`.** First sketch had a loop-over-paid composition where the same config could land in the candidate set multiple times with different begging tags ("ghost begging"); Pareto filter cleaned them up but at the cost of redundant work. Refined to a natural-fit filter (`paid == min(food_generated, food_owed)`) that admits each config exactly once, with the correct begging value. Same final frontier, no wasted candidates.

- **REMAINING vs CONSUMED convention for action types.** `pareto_frontier` and `breeding_frontier` return REMAINING tuples (matched by `CommitAccommodate` and `CommitBreed`). The new `food_payment_frontier` and `harvest_feed_frontier` also return REMAINING. But `CommitConvert` was switched to CONSUMED amounts — the values are bounded by per-good caps in the frontier, uniform across player states (`(0,0,0,0,0)` always means "consume nothing"), and map cleanly to "convert these goods." The enumerator inverts the REMAINING frontier tuples → CONSUMED CommitConvert values. `CommitBreed` and `CommitAccommodate` stay REMAINING because they represent post-event states that combine subtraction with addition (newborns / market gains).

- **`_initiate_*` naming convention extension.** `_initiate_<X>` was originally for non-atomic worker placement entry. Extended (with documentation) to cover phase-driven pending push (`_initiate_harvest_feed`, `_initiate_harvest_breed`). Both live in `engine.py` adjacent to `_resolve_harvest_field`, alongside the existing `_resolve_return_home` / `_resolve_preparation`.

### Conventions established (some queued for CLAUDE.md)

- **Pareto dominance over upstream goods.** When two goods are connected by a one-way conversion (e.g., grain → food but not food → grain), Pareto comparisons should be over the upstream goods only. The downstream good is a derived quantity whose surplus does not contribute Pareto value because the upstream goods can produce it on demand. Applied uniformly across `food_payment_frontier` and `harvest_feed_frontier`. `breeding_frontier` is the deliberate exception — food IS a Pareto dim there because in BREED the only outcome of releasing animals is food, and without food in the comparison the frontier would collapse to "keep max animals" and the player would never have a release-for-food choice. Principle is documented in `POSSIBLE_NEXT_STEPS.md` entry E for eventual CLAUDE.md addition.

- **Dual-meaning phase values.** `HARVEST_FEED` and `HARVEST_BREED` carry two structural meanings depending on stack state: non-empty = player is deciding, empty = phase-exit signal. The discriminator works because the only way to reach phase=X with empty stack is for the entry-resolver to have pushed pendings (now drained). No new phase values or boolean flags needed. Documented in TASK_7.md Part 2.1 and queued for CLAUDE.md as part of the harvest documentation cascade.

- **Three provenance prefix categories.** `"space:<id>"` (existing) / `"card:<id>"` (existing) / `"phase:<id>"` (new). Phase-driven pending pushes use `"phase:harvest_feed"` / `"phase:harvest_breed"`. No risk of namespace collision; prefixes are disjoint by construction.

- **`CommitConvert` uses CONSUMED amounts.** Distinct from `CommitBreed` / `CommitAccommodate` (which use REMAINING/final counts). Rationale: `CommitConvert` is pure subtraction, the values are bounded by per-good caps in the food-payment frontier (small fixed range, friendly to NN policy heads), and `(0,0,0,0,0)` uniformly means "consume nothing" regardless of player state. The enumerator inverts the REMAINING frontier tuples when constructing `CommitConvert`.

- **`HARVEST_CONVERSIONS` registry pattern.** New module `agricola/cards/harvest_conversions.py` parallels the existing `agricola/cards/triggers.py` registry. Built-in entries for Joinery, Pottery, Basketmaker. `register_harvest_conversion(spec)` extension hook for future cards (e.g., Stone Sculptor). Imported from `agricola/cards/__init__.py` so entries register at package-import time.

### Test count change

| File | Before | After | Δ |
|---|---|---|---|
| `tests/test_helpers.py` | (subset) | (subset) | +1 |
| **Total** | **520** | **521** | **+1** |

The +1 is the new `test_breeding_two_pastures_two_sheep_two_boar` test. Four other breeding tests in `test_helpers.py` were modified in-place to assert the new multi-point frontier behavior; their count is unchanged.

### Process notes

- **The design-first pattern continued to pay off, but with longer iteration than Task 6.** Roughly 8 substantial design-conversation rounds before the spec stabilized — Task 6's design phase took ~5. Each round produced revisions: doc restructure (top-down), Pareto principle refinement (three rounds before the upstream-goods rule was stable), natural-fit filter for harvest_feed_frontier, REMAINING-vs-CONSUMED convention for CommitConvert, breeding_frontier food-as-Pareto-dim exception. Several rounds caught design errors that would have been expensive to undo in code (the food_surplus-as-Pareto-dim mistake; the loop-over-paid algorithm with ghost-begging entries; the original 5-phase state machine).

- **The Pareto principle was the design pivot of the session.** Multiple iterations on whether food belongs as a Pareto dim. Settled: NO for `food_payment_frontier` / `harvest_feed_frontier` (upstream goods can produce food on demand → preserving upstream strictly dominates), YES for `breeding_frontier` (without food in the comparison, the frontier collapses and strategic options vanish). The asymmetry is honest — the principle applies when food is "reproducibly downstream," and BREED has a specific structural reason it isn't (the in-phase release-for-food is the only food-production mechanism for animals during BREED, and forgone release is forgone forever).

- **One existing-code fix surfaced organically from the design discussion.** The breeding_frontier Pareto-dim issue was identified while reviewing the design doc; it had been a latent inconsistency in helpers.py since Task 3. Fixed in this session along with the four existing tests it affected. No other existing code changes; all other helpers.py / tests/* changes await the Task 7 implementation session.

- **Read-through review caught real issues.** A deep-dive end-to-end read of the 1300-line doc surfaced: a wrong frontier claim in test 8.3 (4 points claimed, actually 1 point under old behavior or 3 under new behavior); a self-contradicting paragraph in test_utils.py notes; a duplicate-sentence bug in Part 10; double `---` separators in two places; several stale Part X.Y cross-references. All fixed in the same review pass.

### Next task

**Task 7 implementation.** TASK_7.md's "Order of Work" (Part 10) lays out 15 sequential implementation steps, bottom-up: cooking_rates 4-tuple → PlayerState field → HARVEST_CONVERSIONS registry → frontier helpers → action types → pendings → effect functions + enumerators → engine-loop wiring → tests → documentation. After implementation, the engine plays a complete 14-round Family game end-to-end with all 6 harvests resolved. `random_agent_play` across seeds 0–99 to BEFORE_SCORING is the acceptance benchmark.

---

<a name="task-7-design-followup"></a>
## Task 7 design follow-up — `breeding_frontier` revert + "Preserving optionality" principle (2026-05-20)

The food-as-Pareto-dim change to `breeding_frontier` made earlier the same day was reverted in a follow-up session. Under closer scrutiny the change was determined to be incorrect: the "release for food" options it was retaining are themselves strategically dominated by simply keeping the animals (the animals can be converted to food at any future moment via the same Fireplace/Hearth — eaten animals can't be brought back). The deliberate-exception framing didn't survive its first principled examination.

**Reverted:**

- `agricola/helpers.py` — `breeding_frontier` restored to animal-counts-only Pareto, matching `pareto_frontier`. Food is returned alongside each frontier point as the deterministic consequence of the chosen end-state, not as a Pareto dimension.
- `tests/test_helpers.py` — the four pre-existing breeding tests restored to their single-point assertions (`test_breeding_food_from_excess`, `test_breeding_worked_example`, `test_breeding_formula_sF_ge_3`, `test_breeding_formula_sF_lt_3`).
- `tests/test_helpers.py` — `test_breeding_two_pastures_two_sheep_two_boar` retained (rather than deleted) but updated to assert the correct 2-point frontier `{(3,2,0): 0, (2,3,0): 0}` — the symmetric "one type breeds, the other keeps both parents" outcomes. Both options surface because the shared house pet slot can host either type's newborn but not both.

Test count: still 521 (no net change).

**Added in CLAUDE.md as the fifth Key Design Principle:**

- **"Preserving optionality."** Statement: never surface an action that is *both* irreversible and "at any time" (deferrable to any future moment) as a standalone bot decision unless the proceeds are needed at that moment. The Pareto-on-upstream-goods rule (which governs `pareto_frontier`, `breeding_frontier`, and the future `food_payment_frontier` / `harvest_feed_frontier`) is the concrete prescription that drops out of this principle. `breeding_frontier` is no longer an exception — it follows the same convention as the other frontier helpers, and the principle's note-for-future-sessions paragraph is calibrated for exactly the failure mode that produced the food-as-Pareto-dim mistake.

  The principle also articulates one feeding-specific refinement: in `harvest_feed_frontier`, begging markers *are* a Pareto dim (they represent a strategic cost the player chose to incur, with a known −3 scoring cost). Surplus food remains excluded. The asymmetry: downstream costs the player chose to incur are Pareto dimensions; downstream byproducts of over-conversion are not.

**TASK_7.md updates landed alongside the revert:**

- The "Note: `breeding_frontier` is an exception" paragraph in `food_payment_frontier`'s docstring was removed. The docstring now states that the three frontier helpers all follow the rule uniformly.
- Test 8.3 (HARVEST_BREED tests) bullets updated to reflect single-point frontiers — the food-as-Pareto-dim filter had been producing 3-point and 5-point frontiers in cases where animal-only Pareto produces 1-point or 2-point.
- The confused "Cooking Hearth rates" bullet was deleted (it claimed Hearth rates would shift the frontier; under animal-only Pareto, cooking rates don't change the frontier shape — only the food values reported for each point).

**Lesson:** the principled answer to "should we surface a release-for-food option at breeding?" is no, because the player can release-and-convert later at any time without losing anything (in fact, deferring gains optionality — the animal can be reassigned, can breed in a future harvest, can score). The deliberate-exception framing felt right in the moment because release-for-food *is* a real-feeling strategic choice. But "real-feeling" isn't the same as "load-bearing" — under the preserving-optionality lens, the release-for-food configurations were dominated all along by their kept-animal counterparts. The note-for-future-sessions paragraph in CLAUDE.md is the corrective hook for next time.

---

<a name="task-7-impl"></a>
## Task 7 implementation — Harvest phases + rounds 5–14 + Cooking-Hearth fix + non-negative invariant (2026-05-20)

The implementation pass for Task 7. After this session the engine plays a complete 14-round Family game end-to-end with all 6 harvests resolved. As a side effect of running random games to verify the end-to-end flow, a pre-existing engine bug was surfaced and fixed, and a non-negative-resources invariant was added at the `step()` boundary as a permanent safety net.

521 → 599 tests after the harvest implementation; 599 → 601 after the Cooking-Hearth regression tests.

### Pre-implementation prep

Before any code changed:

- **TASK_7.md Part 9 (Documentation) was restructured.** The original spec predated the CLAUDE.md split into FILE_DESCRIPTIONS.md and TEST_DESCRIPTIONS.md, so its file-by-file description bullets all targeted CLAUDE.md. The restructure split Part 9 into four subsections — CLAUDE.md (narrative + one-liners only), FILE_DESCRIPTIONS.md (per-file detail), TEST_DESCRIPTIONS.md (per-test-file coverage), CHANGES.md (Change 7 entry). The Card-implementation-status bullet picked up a forward-look about trigger-style opt-in sub-decision pendings (the shape `PendingHarvestFeed` instantiates for crafts). The Change 7 entry dropped the "multi-shot" framing for `PendingHarvestFeed` and reframed it as the trigger-style pattern instantiated for the three craft majors.

- **Three clarifying questions resolved before code:**
  1. Newborn clearing — confirmed pre-existing behavior. `_resolve_preparation` clears `newborns=0` at the top of each new round; `_resolve_return_home` deliberately does not (newborns must survive into HARVEST_FEED for the 1-food discount).
  2. `PendingHarvestFeed`'s shape — reframed from "multi-shot" to "trigger-style opt-in sub-decisions plus one main commit," per the user's articulation that once cards land, almost every pending will work this way.
  3. Empty-list return of `food_payment_frontier` — confirmed harmless in this task (the harvest-only `harvest_feed_frontier` wrapper always has at least the no-conversion + max-begging entry); future card-cost payment paths that call `food_payment_frontier` directly are responsible for feasibility pre-checks.

- **POSSIBLE_NEXT_STEPS.md gained a new section: Pareto-frontier pruning optimizations** (anchor pruning + the geometric generalization). Worked through applicability to all four frontier helpers (clean fit for `pareto_frontier` and `breeding_frontier`; partial fit for `food_payment_frontier`; not applicable to `harvest_feed_frontier` because the do-nothing config is the worst on −begging). Renumbered E–N to F–O and updated cross-references.

### Implementation (15 ordered steps, per TASK_7.md Part 10)

The steps landed bottom-up, smallest pieces first. Each step left the test suite green before proceeding to the next.

**Step 1 — `cooking_rates` to 4-tuple.** Extended from `(sheep, boar, cattle)` to `(sheep, boar, cattle, veg)`. Cooking Hearth → `(2, 3, 4, 3)`, Fireplace → `(2, 2, 3, 2)`, neither → `(0, 0, 0, 1)`. The veg row has a 1:1 fallback per RULES.md (vegetables count as 1 food even without a cooking improvement); animal rates have no such fallback. Two call sites (legality.py:1109, resolution.py:1009) slice with `cooking_rates(...)[:3]` since their consumers — `pareto_frontier` and `_execute_accommodate` — only handle animals. Four `cooking_rates` test assertions in `test_helpers.py` updated to the 4-tuple shape.

**Step 2 — `PlayerState.harvest_conversions_used: frozenset[str]`.** Added to `state.py` with default `frozenset()`. Records both `use=True` and `use=False` decisions (a "decided" set, not a "used" set) so the enumerator stops offering a conversion once decided. Reset to `frozenset()` in `_resolve_harvest_field` at the start of each harvest. `setup.py` updated to pass the explicit default in `_make_player`.

**Step 3 — `HARVEST_CONVERSIONS` registry.** New module `agricola/cards/harvest_conversions.py`. Parallels `agricola/cards/triggers.py` in shape: a `HarvestConversionSpec` dataclass (`conversion_id`, `input_cost: Resources`, `food_out: int`, `is_owned_fn`, `side_effect_fn: Optional[Callable]`), a mutable `HARVEST_CONVERSIONS: dict[str, HarvestConversionSpec]` populated at import time, and a `register_harvest_conversion(spec)` hook for future card extensions. Three built-in entries register at module load: `joinery` (1 wood → 2 food, owns major idx 7), `pottery` (1 clay → 2 food, owns major idx 8), `basketmaker` (1 reed → 3 food, owns major idx 9). The new module is imported from `agricola/cards/__init__.py`.

**Step 4 — `food_payment_frontier` and `harvest_feed_frontier` in `helpers.py`.** The general-purpose food-payment frontier returns Pareto-optimal `(grain_rem, veg_rem, sheep_rem, boar_rem, cattle_rem)` REMAINING-goods tuples for fully paying `food_owed`. Per-good consumption caps trim enumeration (`grain_cap = min(player.grain, food_owed)`, `veg_cap = min(player.veg, ceil(food_owed/vR))`, etc.); the Pareto-filter drops over-conversion configs that are dominated by the same-amount-paid configs that consume fewer goods. `food_owed=0` short-circuits to the no-conversion config. The harvest-only wrapper `harvest_feed_frontier` composes `food_payment_frontier` across paid levels in `[0, food_owed]`, admitting each config at its natural fit (`paid == min(food_generated, food_owed)`) — a pre-filter that avoids ghost-begging duplicates before the 6-dim `(5 goods, -begging)` Pareto pass. Pareto dimensions exclude food_surplus per the "Preserving optionality" principle, but include `-begging` as a strategic-cost dim. Always non-empty for `food_owed > 0` (the no-conversion + max-begging entry is always on the frontier). 11 new tests in `test_helpers.py` cover both helpers including the food_owed=0 shortcut, partial-pay configs, over-conversion exclusion, and the begging-zero-subset invariant.

**Step 5 — Three new action types in `actions.py`.** `CommitHarvestConversion(conversion_id: str, use: bool)`, `CommitConvert(grain, veg, sheep, boar, cattle: int)` (CONSUMED amounts — inverted from frontier REMAINING tuples by the enumerator), `CommitBreed(sheep, boar, cattle: int)` (post-event-state counts, matching `CommitAccommodate`). All inherit from `CommitSubAction`. Added to the `Action` union.

**Step 6 — Two new pendings in `pending.py`.** `PendingHarvestFeed(player_idx, initiated_by_id, food_owed, conversion_done=False)` and `PendingHarvestBreed(player_idx, initiated_by_id, breed_chosen=False)`. Both added to the `PendingDecision` union. Both use `"phase:harvest_feed"` / `"phase:harvest_breed"` provenance — a third namespace alongside `"space:..."` and `"card:..."`. Neither carries `triggers_resolved` / `TRIGGER_EVENT` yet (Task 5D precedent — added per-pending when the first card needs them).

**Step 7 — Effect functions in `resolution.py` and legality enumerators in `legality.py`.** `_execute_harvest_conversion` records the decision (both branches) and, if `use=True`, pays input cost + produces food applied against `food_owed` with surplus going to supply + invokes `spec.side_effect_fn` if any. `_execute_convert` consumes the named goods, computes `food_produced` via the 4-tuple `cooking_rates`, applies to `food_owed`, sends surplus to supply, and assigns any remaining owed to begging markers — begging is assigned here, not at Stop, preserving the Stop-only-pops convention. `_execute_breed` sets the chosen post-breed animals and adds the frontier's `food_gained` to supply (the food formula stays owned by `breeding_frontier` — single source of truth; the effect looks up the chosen point's `food_gained` rather than recomputing). All three registered in `COMMIT_SUBACTION_HANDLERS` with `auto_pop=False` — the trailing Stop is the explicit exit. The two new enumerators in `legality.py` are `_enumerate_pending_harvest_feed` (offers undecided owned conversions + all Pareto-frontier convert points; only Stop after `conversion_done`) and `_enumerate_pending_harvest_breed` (one CommitBreed per Pareto-frontier point; only Stop after `breed_chosen`). Both registered in `PENDING_ENUMERATORS`.

**Steps 8–9 — Engine wiring.** `_initiate_harvest_feed(state)` and `_initiate_harvest_breed(state)` push one pending per player with the SP's frame on top (push order `[1-sp, sp]`). FEED pre-debits food per the "Cannot withhold food tokens" rule (`spent = min(need, p.resources.food)` debited upfront; `food_owed = need - spent` becomes the pending's `food_owed`, with `need = 2*people_total - newborns`). BREED has no pre-debit. `_resolve_harvest_field(state)` does mechanical FIELD work (take 1 crop from each planted field — grain takes precedence over veg in the elif chain), resets `harvest_conversions_used = frozenset()` on both players, calls `_initiate_harvest_feed`, and sets `phase=HARVEST_FEED`. Pasture cache rides along untouched via `dataclasses.replace` (fields cannot lie inside pastures).

**Step 10 — `_advance_until_decision` + `_resolve_return_home` extension.** Three new phase branches: `HARVEST_FIELD` calls `_resolve_harvest_field`; `HARVEST_FEED` with empty stack (the exit signal — all FEED pendings have been Stop'd) pushes BREED pendings via `_initiate_harvest_breed` and transitions to `HARVEST_BREED`; `HARVEST_BREED` with empty stack transitions to `PREPARATION` (round < 14) or `BEFORE_SCORING` (round == 14). The dual-meaning phase pattern (stack non-empty = a player is deciding; stack empty = phase-exit) is enforced by construction — the only way to reach `phase=HARVEST_X` with empty stack is for the entry-resolver to have pushed pendings now drained by Stop. `_resolve_return_home` now routes to `Phase.HARVEST_FIELD` on `HARVEST_ROUNDS = {4, 7, 9, 11, 13, 14}` instead of the Task-5-era `BEFORE_SCORING` halt after round 4.

**Steps 11–13 — Four new test files.**
  - `tests/test_harvest_field.py` (11 tests) — mechanical resolution, budget reset, phase transition, pre-debit semantics.
  - `tests/test_harvest_feed.py` (19 tests) — pre-debit + begging, trivial-FEED gratuitous floor, grain/veg/animal conversions at all cooking rates, once-per-harvest craft conversions, Stop gating, push order, Pareto excludes over-conversion.
  - `tests/test_harvest_breed.py` (8 tests) — trivial breed, single-type breeding, multi-type breeding with house-pet contention, `breed_chosen` gating, push order, capacity-forced release with cooking.
  - `tests/test_harvest_integration.py` (28 tests) — random-agent over 20 seeds reaches BEFORE_SCORING; harvest phases reached across 10 seeds; round-14 → BEFORE_SCORING transition; round-4 → PREPARATION → round 5 transition; multi-harvest budget reset; begging-marker propagation to `score()`; pending-stack evolution through FEED → BREED; newborn discount; all 6 harvests fire at the expected rounds.

**Step 14 — `tests/test_utils.py` docstring update.** The `_is_implemented_action` filter doesn't need a code change — it only filters `PlaceWorker` actions; all other action types (including the three new harvest commits) pass through unconditionally. Updated the docstring to make this explicit.

**Step 15 — Documentation cascade.** CLAUDE.md gained a new "Harvest sub-phases" subsection in the Engine Architecture section, a `"phase:<id>"` row in the provenance-prefix table, harvest-conversions and forward-look additions to the Card-implementation-status section, status-table additions, and directory one-liners for the new files. FILE_DESCRIPTIONS.md got updated entries for the 8 modified `agricola/*.py` files plus a new entry for `cards/harvest_conversions.py`. TEST_DESCRIPTIONS.md got entries for the 4 new test files and updates to the `test_helpers.py` and `test_engine.py` entries. CHANGES.md gained Change 7 documenting the harvest architecture end-to-end.

### Test fixes downstream of harvest landing

Two pre-existing tests had to be updated because their premises changed when the engine extended past round 4:

- `tests/test_engine.py::test_round_4_return_home_transitions_to_before_scoring` — premise obsolete (round 4 no longer halts; it routes to `HARVEST_FIELD`). Renamed to `test_harvest_round_return_home_transitions_to_harvest_field` and added a sibling `test_non_harvest_round_return_home_transitions_to_preparation`.

- `tests/test_engine.py::test_random_agent_plays_four_rounds` — premise extended. Renamed to `test_random_agent_plays_full_game` and updated to assert `round_number == 14`.

- `tests/test_engine.py::test_random_agent_invariants` — the decider-rule alignment invariant (`pending_stack[-1].player_idx == state.current_player` when stack non-empty) had to be scoped to `phase == Phase.WORK`. Harvest pendings can legitimately have a different `player_idx` than `current_player` because no worker is placed during harvest — the stack alone identifies the decider. Loosening the invariant is the correct call, not tightening engine behavior, because (per TASK_7 Part 2.1) the stack is authoritative during harvest by design.

### Bugs caught during implementation

- **`harvest_breed` test's pre-food hardcoded constant.** First draft of `test_single_type_breeding_sheep_no_cooking` assumed `pre_food = 2` based on a guess about seed-0's starting-player food assignment. The seed-0 game's actual starting-food split (SP gets 2, non-SP gets 3) put player 0 at food=3 since the original starting player was 1, even though the test forced `starting_player=0`. The food assignment happens in `setup` before any reassignment. Fixed by reading `pre_food = state.players[0].resources.food` dynamically.

- **`test_random_agent_plays_four_rounds` failures.** When the round-4 RETURN_HOME branch started routing to HARVEST_FIELD instead of BEFORE_SCORING, the random-agent driver continued past round 4 and surfaced the decider-rule invariant violation described above. Both fixes (rename + invariant loosening) landed inline.

### Side-quest: random-vs-random game runner

After the harvest landed and the suite was green at 599, a top-level `play_random_game.py` script was created to play one full game between two random agents and report the score. The script wraps `random_agent_play` and `score`, prints the full per-category breakdown, applies the tiebreaker on score ties, and supports a `--trace` flag that walks the action list and prints a per-round narrative grouping worker-placement chains and harvest sub-phases. The `--trace` format uses a `P{n}:` prefix for lead actions (every `PlaceWorker` plus first-action-of-pending) with indented continuations for the same player's sub-actions, plus `-- HARVEST_FEED --` / `-- HARVEST_BREED --` dividers within the round. Action shorthand (`place forest`, `plow (2,1)`, `sow g=2,v=0`, `breed (3,0,0)`, `convert g=1`, `pasture {(0,2),(1,2),(2,2)}`, `major idx=9`, etc.) keeps each round's narrative readable in ~10–20 lines.

### Side-quest discovery: pre-existing Cooking-Hearth enumeration bug

First run of `play_random_game.py` on seed 100 produced `Resources(clay=-6)` on player 0 at game end. Tracing the negative clay through the action list pinpointed `CommitBuildMajor(major_idx=2, return_fireplace_idx=None)` as the culprit — Cooking Hearth (cost 4 clay) was committed with only 1 clay on hand.

The bug was in `_enumerate_pending_build_major` at `legality.py:1007`. The standard-payment option was gated on `_can_afford_major(state, p, idx)`, which for Cooking Hearth (idx 2, 3) returns True if `clay ≥ 4 OR owns_fireplace`. The permissive "either pathway works" semantics is correct for the placement-legality call site (`_can_afford_any_major_improvement`) but wrong as a gate for the standard-payment option specifically — a player with Fireplace + 0 clay passed the check and got offered the standard-payment commit, which then drove clay to −3 (with another harvest later pushing it to −6).

**Fix:** the standard-payment option is now gated on `_can_afford(p, MAJOR_IMPROVEMENT_COSTS[idx])` — the precise raw cost. The Fireplace-return alternative is emitted separately in the same enumerator and remains correctly gated on Fireplace ownership. `_can_afford_major`'s semantics are unchanged (it still answers the broader "can afford the major somehow" question for placement legality).

Pre-existing, not introduced by Task 7 — the path triggered on round 4 WORK, which has been reachable since Task 5C. Task 7 just made it 6× more likely to surface by extending play to 14 rounds.

**Two regression tests** added to `tests/test_major_improvement.py`:
- `test_cooking_hearth_standard_payment_gated_on_clay_not_on_fireplace` — direct repro.
- `test_clay_oven_standard_payment_gated_on_full_cost` — sibling case (Clay Oven has no alternative-payment path, so 0 clay should yield no Clay Oven option at all regardless of Fireplace ownership).

### Engine invariant added

The negative-clay bug went undetected by 599 tests because `Resources.__sub__` silently produces negative components. A non-negative-resources invariant was added at the `step()` boundary as a permanent safety net.

`step()` now ends with `_assert_nonnegative_state(state, action)`, which asserts every player's resources (`wood`/`clay`/`reed`/`stone`/`food`/`grain`/`veg`) and animals (`sheep`/`boar`/`cattle`) are ≥ 0. The assertion message names the offending action and player, so any future enumerator gate that misses an affordability check fires immediately at the assertion boundary with the offending sub-action effect or enumerator one source-grep away. Safety net — should never fire in correct code.

Cost: an `O(2 × 10)` check per step, negligible.

Tests after the fix + the invariant: 599 → 601 (the two regression tests).

### Random-vs-random tournament

After the engine was clean across 20-seed sweeps, a 10-game tournament across seeds 0–9 was run to characterize random-play behavior. P0 record: 4–6–0. Average scores P0 −6.2 / P1 −0.9. Score range P0 [−29, 5] / P1 [−15, 13]. Action counts 150–180 per game. Both players in negative-score territory most of the time (random play doesn't manage feeding well — begging-marker tallies of −15 to −36 are common; the +6 from "people" alone isn't enough to offset). No engine assertions tripped across all 30+ games run this session (10 single + 20 sweep).

### Files modified or created (summary)

**New (6):**

- `agricola/cards/harvest_conversions.py`
- `tests/test_harvest_field.py`
- `tests/test_harvest_feed.py`
- `tests/test_harvest_breed.py`
- `tests/test_harvest_integration.py`
- `play_random_game.py`

**Modified (15):**

- `agricola/{actions,cards/__init__,engine,helpers,legality,pending,resolution,setup,state}.py`
- `tests/{test_engine,test_helpers,test_major_improvement,test_utils}.py`
- `CHANGES.md`, `CLAUDE.md`, `FILE_DESCRIPTIONS.md`, `POSSIBLE_NEXT_STEPS.md`, `TASK_7.md`, `TEST_DESCRIPTIONS.md`

### Test count after Task 7

| Bucket | Tests | Δ vs Task 7 design baseline |
|---|---|---|
| Pre-existing files (with cooking_rates 4-tuple updates + test_engine renames + harvest_conversions_used reset compatibility) | 532 | +11 (food_payment_frontier + harvest_feed_frontier tests in test_helpers.py) |
| `tests/test_harvest_field.py` (new) | 11 | +11 |
| `tests/test_harvest_feed.py` (new) | 19 | +19 |
| `tests/test_harvest_breed.py` (new) | 8 | +8 |
| `tests/test_harvest_integration.py` (new) | 28 | +28 |
| `tests/test_major_improvement.py` (regression: Cooking-Hearth + Clay-Oven gating) | +2 | +2 |
| **Total** | **601** | **+80** |

521 → 601, net +80 tests. The engine has no remaining unimplemented phases.

### Conventions established or refined (stable, documented)

- **`"phase:<id>"` provenance namespace.** Third namespace for `initiated_by_id` alongside `"space:<id>"` and `"card:<id>"`. Phase-driven pending pushes use this prefix. Today: `"phase:harvest_feed"` and `"phase:harvest_breed"`. Documented in CLAUDE.md's pending-provenance section.

- **Dual-meaning phase pattern.** Phase values can carry two meanings depending on stack state: stack non-empty = a player is deciding; stack empty = phase-exit signal. `HARVEST_FEED` and `HARVEST_BREED` use this today. The discriminator works because the only way to reach phase=X with empty stack is for the entry-resolver to have pushed pendings now drained by Stop. Documented in CLAUDE.md's "Harvest sub-phases" subsection.

- **4-tuple `cooking_rates` with veg fallback.** The fourth element captures the at-any-time veg conversion rate, with a 1:1 fallback even without a cooking improvement per RULES.md. Animal rates have no fallback. Callers that need only the animal triple slice with `cooking_rates(...)[:3]`.

- **Non-negative resources/animals invariant at `step()` boundary.** Engine-level safety net asserted on every step. Catches enumerator-gate misses immediately, before they cascade through subsequent gameplay. Should never fire in correct code.

- **Begging-marker assignment by `_execute_convert`, not by Stop.** Preserves the Stop-only-pops convention. The food-payment decision is final at the moment of `CommitConvert` (no further craft uses or other food sources can fire after `conversion_done` is set), so begging is fully determined there.

- **Trigger-style pendings as the future-default shape.** `PendingHarvestFeed` exhibits the shape future card-trigger pendings will reuse: opt-in `Commit*` sub-decisions (the craft conversions, analogous to future card triggers) followed by one main commit. Captured in CLAUDE.md's Card-implementation-status forward-look.

### Process notes

- **80 new tests, 0 cascading failures.** Each implementation step was tested before moving on. The two test-update items (decider-rule invariant + round-4 RETURN_HOME) surfaced when the engine wiring went in at step 10 — that's the natural seam for those updates, not a process failure.

- **Side-quests were value-positive.** The random-vs-random script surfaced the Cooking-Hearth bug on its first run (seed 100). The bug had been latent since Task 5C — random play in Task 5D / Task 6 era halted at round 4 before harvest, so a player accumulating Fireplace + low clay would only attempt the bad Cooking-Hearth path occasionally pre-Task-7. Task 7's 14-round extension made the path 6× more common (one harvest-vulnerable round became six rounds of opportunity to leak negative clay). Running real games is a different surface than unit tests.

- **Doc-restructuring before code paid off.** Restructuring TASK_7.md Part 9 into four subsections (CLAUDE.md / FILE_DESCRIPTIONS.md / TEST_DESCRIPTIONS.md / CHANGES.md) before implementation made the documentation cascade trivially mechanical at the end — each subsection had a target file and a known scope, no untangling needed mid-edit.

### Next task

The engine is feature-complete for the Family game. The next high-leverage targets, per POSSIBLE_NEXT_STEPS.md:

1. **B — `BoardState.action_spaces` hashability refactor.** Required for state-hashed legal-actions caching and DAG-MCTS. Mechanical refactor; the tricky part is the canonical ordering choice and updating every call site that currently keys by string.

2. **C — Performance profiling of `legal_actions` and `step`.** Nothing is known to be slow, but no one has measured. Useful before MCTS scaling exposes per-call cost as a bottleneck.

3. **F — Heuristic agent.** First non-random agent. Should push these random-play scores (avg −3.5 across both players) up by 30–50 points just by avoiding begging markers and unused cells.

4. **E (newly added in POSSIBLE_NEXT_STEPS.md this session) — Pareto-frontier pruning optimizations.** Anchor pruning and the broader incremental geometric pruning. Defer until profiling (C) identifies the helpers as a hot path.

Cards beyond Potter Ceramics remain a larger separate effort with the open design questions documented in CLAUDE.md's "Card implementation status."

---

<a name="hashability-refactor"></a>
## Hashability refactor — `BoardState.action_spaces` dict → canonical tuple (2026-05-21)

Short focused session landing item B from POSSIBLE_NEXT_STEPS.md: convert `BoardState.action_spaces` from a `dict[str, ActionSpaceState]` to a fixed-order `tuple[ActionSpaceState, ...]` so that `BoardState` and (transitively) `GameState` become hashable. State-hashed caching layers — a transposition table for MCTS, per-state legal-action memoization, simple `dict[GameState, X]` experiments — were structurally blocked by the dict. This change removes the blocker. No new tests; 613 → 613.

### What was built

- **`agricola/constants.py`** — added `SPACE_IDS` (length-25 canonical tuple) and `SPACE_INDEX: dict[str, int]` reverse lookup. `SPACE_IDS` is built at module load from the existing `PERMANENT_ACTION_SPACES` list (in its given order) followed by the 14 stage cards in stage order. The user confirmed the permanent-space order verbatim before code went in.

- **`agricola/state.py`** — `BoardState.action_spaces: dict` → `tuple` with an updated comment. Two new free-function helpers:
  - `get_space(board, space_id) -> ActionSpaceState` for reads.
  - `with_space(board, space_id, new_space) -> BoardState` for single-space writes (tuple slice + concat, returning a fresh `BoardState`).
  - Free functions, not methods, matching the codebase's preference for `cooking_rates(state, p)`-style helpers.

- **`agricola/setup.py`** — `_make_action_spaces(round_card_order)` return type `dict` → `tuple`. The body still builds the dict internally (one branch per accumulation-rate dispatch), then returns `tuple(by_id[sid] for sid in SPACE_IDS)`.

- **`agricola/resolution.py`** — `_update_space(state, space_id, **kwargs)` rewritten in three lines using the new helpers (read via `get_space`, write via `with_space`). Public signature unchanged; only internals shifted. Eight read sites in the per-handler resolution code (`_resolve_building_accumulation`, `_resolve_food_accumulation`, `_initiate_sheep_market` / `_initiate_pig_market` / `_initiate_cattle_market`, two worker-placement sites) migrated to `get_space`.

- **`agricola/legality.py`** — 10 read sites converted: `_is_available`, the building-resource predicates (`_legal_fishing`, `_legal_forest`, `_legal_clay_pit`, `_legal_reed_bank`, `_legal_western_quarry`, `_legal_eastern_quarry`), the market predicates (`_legal_sheep_market`, `_legal_pig_market`, `_legal_cattle_market`).

- **`agricola/engine.py`** — two bulk-update loops rewritten:
  - `_resolve_return_home`'s "reset every worker" generator now iterates the tuple directly (no `.items()` / dict rebuild).
  - `_resolve_preparation`'s "refill revealed accumulation spaces" loop uses `enumerate(list(...))` with `SPACE_IDS[i]` to recover the space-id string for the per-rate dispatch. The only place `SPACE_IDS` appears in production logic.

- **`tests/factories.py`** — `with_space(state, space_id, **kwargs)` rewritten as a thin shim over `state.get_space` + `state.with_space`. The state-level helpers are imported under aliases (`_get_space` / `_board_with_space`) to avoid colliding with the test-side `with_space` name.

- **`tests/test_*.py`** — five test files updated: read sites use `get_space`; the two test-local `_set_space` write helpers (in `test_legality_atomic.py` and `test_legality_non_atomic.py` and `test_resolution_atomic.py`) use `with_space`; `dict.items()` / `dict.values()` iteration sites become `zip(SPACE_IDS, state.board.action_spaces)` or direct tuple iteration. Read sites in `test_resolution_atomic.py` (16 sites in assertion expressions) were converted with a regex-driven mechanical pass — every `<X>.board.action_spaces["<id>"]` became `get_space(<X>.board, "<id>")`.

- **`play.py`, `play_web.py`** — UI read sites updated. `play.py:render_action_board` reads via `get_space`. `play.py:_placeworker_sort_key`'s `dict.get(...)`-with-None-fallback became a `try`/`except KeyError` around `get_space`, preserving the same fall-through behavior for unknown space-ids. `play_web.py:_board_to_dict` iterates with `zip(SPACE_IDS, state.board.action_spaces)`.

- **`POSSIBLE_NEXT_STEPS.md`** — item B marked completed with a "Landed" paragraph noting the canonical-ordering choice, the new helpers, and the test count.

- **`CHANGES.md` Change 8** — full refactor entry covering motivation, ordering choice, helpers, per-file changes, and the forward look (MCTS-side transposition-table work unblocked, no code yet wired to take advantage).

- **`CLAUDE.md`** — Status-table row added pointing to Change 8; test count updated 599 → 613; one-liner descriptions for `constants.py` and `state.py` in the directory tree extended to mention `SPACE_IDS` / `SPACE_INDEX` and `get_space` / `with_space`; doc-table description of `CHANGES.md` updated to mention the new refactor.

- **`FILE_DESCRIPTIONS.md`** — `BoardState` description rewritten to describe the tuple shape, the canonical-ordering rule, the hashability consequence, and the access helpers. `_make_action_spaces` return type updated. New entries in the `constants.py` section for `SPACE_IDS` and `SPACE_INDEX`.

### Process notes

- **One regex-driven sweep is fine when the pattern is unambiguous.** `test_resolution_atomic.py` had 16 nearly-identical bracketed-access sites; a one-shot Python `re.sub` over `(\w+)\.board\.action_spaces\["([a-z_]+)"\]` → `get_space(\1.board, "\2")` handled them all in one pass. No manual review of individual lines required because the pattern had no false-positive risk.

- **The two test-side helpers named `with_space` are distinct from the new state-level `with_space`.** Both take different shapes (state + kwargs vs. board + new_space). Imported the state-level helpers under aliases inside `tests/factories.py` rather than renaming either. The test-side public API stays the same; only internals changed.

- **No new tests added.** Behavior is identical; the refactor is purely structural. Verified end-to-end with a smoke check that confirms `hash(GameState)` works and that two states reached by `setup(seed=0)` → `step(..., PlaceWorker(space="day_laborer"))` from parallel calls compare equal and hash to the same value.

- **Estimated and delivered "well under 30 minutes."** The user's estimate was right — the core change is small (one type, two helpers, ~20 read-site conversions, two bulk-loop rewrites). The long tail was mostly mechanical test-side cleanups.

### Files modified or created

**New (0):** —

**Modified (15):**

- `agricola/{constants,state,setup,resolution,legality,engine}.py`
- `tests/factories.py`, `tests/test_{legality_atomic,legality_non_atomic,resolution_atomic,engine,animal_markets}.py`
- `play.py`, `play_web.py`
- `POSSIBLE_NEXT_STEPS.md`, `CHANGES.md`, `CLAUDE.md`, `FILE_DESCRIPTIONS.md`, `SESSION_HISTORY.md`

### Next task

Per POSSIBLE_NEXT_STEPS.md: (C) performance profiling of `legal_actions` / `step` before MCTS scaling exposes per-call cost as a bottleneck, (F) the heuristic agent (first non-random agent), or (G) MCTS scaffolding — which is the direct beneficiary of this refactor.

---

<a name="perf-pass"></a>
## Engine performance pass — profiling, `fast_replace`, `legal_actions_cache`, assertion gate (2026-05-21)

Item C from POSSIBLE_NEXT_STEPS.md, plus three adjacent optimizations the profiling pass surfaced. Built a reusable profiling harness from scratch, walked the data, agreed on changes through several rounds of measurement, and landed a first wave: `fast_replace`, the opt-in `legal_actions_cache()`, the `__debug__` gate on the non-negative assertion, and the round-end-reset guard. 613 → 636 tests passing.

### Phase 1 — profiling infrastructure (out-of-tree)

A new top-level `scripts/` directory holds re-runnable utilities; no files under `agricola/` or `tests/` were modified for the infrastructure itself.

- **`scripts/profile_states.py`** — 9 prefab `GameState` factories across early/mid/late game, composed from existing `tests.factories` helpers. The round-14 state alone makes every action space legal except `lessons` (permanently illegal in the Family game) — the coverage requirement for Workload C below. Includes a self-validator: `python scripts/profile_states.py` audits each state and reports which spaces are legal where, then confirms the union covers everything.

- **`scripts/profile_engine.py`** — three-workload runner under cProfile + wall-clock timing:
  - Workload A: `random_agent_play` from `setup()` across seeds 0-9 (end-to-end baseline).
  - Workload B: same but starting from the wealthy prefab state, exercising action spaces random play from a fresh setup rarely reaches (Major Improvement, Farm Expansion's room-build, Farm Redevelopment, Fencing).
  - Workload C: micro-bench loop calling `legal_actions(state)` and `step(state, action)` 1000× on each prefab, isolating per-call cost from game-walk overhead.

- **`scripts/count_replaces.py`** — monkey-patches `dataclasses.replace` (and later `fast_replace`) to count call shapes by `(class_name, fields_changed)`. Surfaced two findings: the round-end-reset over-call, and that `GameState.{players}` updates are surprisingly less frequent than `ActionSpaceState.{workers}` updates due to that same over-call.

- **`scripts/bench_replace.py`** — `timeit`-based apples-to-apples microbench for replace variants. Built mid-session to settle a measurement disagreement: cProfile's per-function self-time accounting credited `fast_replace` with a 45% speedup; `timeit` showed the honest number was closer to 20% (cProfile counted `fast_replace`'s inner generator + getattr as separate lines, while `dataclasses.replace` does everything in one body and gets all the credit).

### Phase 2 — read the data

cProfile + wall-clock numbers identified six recommendations (R1-R6) documented in **PROFILING.md**. Top hot paths:

1. `dataclasses.replace` — 27 ms self-time on Workload A (16% of total). #1 by self time.
2. `legal_placements` evaluating all 24 predicates every call — 7.5 us per state, 24×9009 = 216,216 `_is_available` invocations in Workload C.
3. `can_accommodate` + Pareto inner generators — 22 ms self-time on Workload B mid-game (much higher than early-game), 5.5× the Workload A cost.
4. `_any_legal_pasture_commit` + `_check_entry_legal` — Fencing universe walk, ~12 ms total, mitigated by the 1×1 fast-path.
5. `_assert_nonnegative_state` — 4 ms / 1613 calls, 2.5 us per `step()`, pure safety net.

The user explicitly pushed back on relative-only numbers ("5.5× more expensive" without anchoring), prompting absolute-cost framing in the recommendations. PROFILING.md was rewritten to use absolute numbers and explicit uncertainty.

### Phase 3 — first-wave optimizations (Change 9 in CHANGES.md)

Four changes landed, in roughly this order:

**R1 — `legal_actions_cache()` opt-in memoizer.** New context manager in `agricola/legality.py` (96 added lines). Activates an identity-keyed cache (`dict[int, tuple[GameState, list[Action]]]`) for `legal_actions(state)` results. Identity-keyed because `hash(GameState)` recursively hashes thousands of nested fields (~26 us), nearly the cost of enumeration itself; `id(state)` is ~10 ns. Cache value pairs `(state_ref, result)` so the cache pins the state object alive — solves the id-recycling-on-GC problem. Thread-local, dropped on exit. Zero cost when no `with` block is open. Consumer status: dormant; MCTS will be the first user via `with legal_actions_cache(): ...` around its search loop. 7 tests in `tests/test_engine.py`.

**R2 — `__debug__` gate on `_assert_nonnegative_state`.** One-line wrap in `step()`: `if __debug__: _assert_nonnegative_state(state, action)`. Under standard `python`, behavior unchanged. Under `python -O` (or `PYTHONOPTIMIZE=1`), the branch is compiled out — saves ~2.5 us per `step()` (≈4% of step's cost) in production / self-play / training. The assertion has caught exactly one bug (Task 7's Cooking-Hearth gate, since fixed); the safety net remains live in dev/CI.

**Round-end-reset guard in `_resolve_return_home`.** Surfaced by `count_replaces.py`. The reset loop rebuilt every `ActionSpaceState` unconditionally, even spaces with `workers=(0, 0)`. After: skip the replace for already-empty spaces. Cut total `replace` calls per Workload-B run from 13,117 → 10,613 — a 19% reduction. Single biggest contributor to the Workload-C `step`-per-call improvement on the round-14 state (88 us → 16 us), since round 14 has a fully-revealed but mostly-empty board at RETURN_HOME.

**R3 — `fast_replace` (Form A) in new `agricola/replace.py`.** Drop-in faster equivalent of `dataclasses.replace` that caches each class's init-field name tuple at first use and constructs the new instance positionally. Skips per-call type checks, Field descriptor iteration, the no-non-init-in-changes guard, and `**kwargs` unpacking. Microbenchmarked ~20% per-call speedup on the dataclass shapes used in the engine. Migration: 89 call sites across 4 production files (`agricola/engine.py`, `agricola/resolution.py`, `agricola/pending.py`, `agricola/cards/potter_ceramics.py`). Test code (`tests/`) was deliberately not migrated — stdlib `dataclasses.replace` stays as the reference implementation for the 14 equivalence tests in `tests/test_replace.py`.

A subtle gotcha caught during implementation: `cls.__dataclass_fields__` includes `ClassVar` entries (CPython detail); `dataclasses.fields(cls)` is the canonical filter that excludes them. `PendingSow` and friends carry `PENDING_ID: ClassVar[str]`, so this matters. The fix was to use `dataclasses.fields()` (cached per class) in `fast_replace`'s field-discovery path.

### Honest framing arc (the measurement story)

Three measurement errors were caught mid-session by the user, each prompting a tighter follow-up:

1. **"19% call-count drop attributed to fast_replace"** — actually came from the round-end-reset guard, which landed *before* `fast_replace`. The two changes happened in sequence; I conflated them in a single before/after table. Corrected with separated attribution.

2. **"45% per-call speedup from fast_replace"** — based on dividing cProfile self-times, which credit `fast_replace`'s wrapper but separately count its inner generator + `getattr` calls. `timeit` (a clean apples-to-apples microbench) revealed the honest number is ~20%. PROFILING.md and the proposal language were tightened.

3. **"R5 expected speedup"** — original PROFILING.md estimate ("~2-4% wall-clock") survived measurement, but the broader R-list was reordered post-data: R3's contribution to overall wall-clock was within noise (~1-2%), so the recommended order shifted from "R2 → R1 → R3 → R4 → R5" to "R2 → R1 → R3 → re-profile → R4 if Pareto is still hot".

The pattern: discuss → measure → implement → re-measure → discuss again. Each measurement round corrected a claim that had been made with too much confidence. The user's pushback on relative-only numbers was the key intervention that pulled the conversation toward absolute, anchored data.

### Documentation cascade

Substantial doc work alongside the code:

- **PROFILING.md** (new, repo root) — methodology, headline numbers, R1-R6 recommendations with corrected magnitudes.
- **POSSIBLE_SPEEDUPS.md** (new, repo root) — living catalog of future optimizations (S1-S6), explicitly forked from the perf side of POSSIBLE_NEXT_STEPS.md so direction work and performance work can live in separate files.
- **CHANGES.md Change 9** — engine performance pass, full write-up of all four landed pieces with measurement provenance.
- **POSSIBLE_NEXT_STEPS.md** restructured — old items C (profiling) and E (Pareto pruning) folded into one new item C that points at POSSIBLE_SPEEDUPS.md with summaries; F-O unchanged.
- **CLAUDE.md** updates: test count 613 → 636, new status-table row for the perf pass, directory-tree entries for `agricola/replace.py` and the new `scripts/` directory, new "Use `fast_replace`, not `dataclasses.replace`" Code Convention, examples in `replace_top call form` / `Variable naming` / `Parent *_chosen flags` updated to `fast_replace`. Doc table grew entries for POSSIBLE_SPEEDUPS.md and PROFILING.md.
- **FILE_DESCRIPTIONS.md** — new `agricola/replace.py` entry with `fast_replace` signature, speedup numbers, and the `dataclasses.fields()` vs `__dataclass_fields__` gotcha.
- **TEST_DESCRIPTIONS.md** — bullet under `test_engine.py` for the 7 `legal_actions_cache()` tests; new top-level entry for `test_replace.py`.

Deliberately deferred: a `legal_actions_cache()` subsection in CLAUDE.md's Engine Architecture section. The cache is engine infrastructure but its only consumer will be MCTS; the natural place to document it is inside an MCTS section when that work begins. The function has a docstring, CHANGES.md Change 9 covers rationale, and POSSIBLE_NEXT_STEPS.md item G explicitly says "all MCTS needs is `with legal_actions_cache(): ...`" — three pointers a future-me will hit immediately.

### Process notes

- **Out-of-tree profiling infrastructure paid off.** Putting profiling utilities in `scripts/` (rather than under `tests/` or `agricola/`) made the rule "no engine changes from this work" structurally enforceable, kept the harness re-runnable independent of test selection, and made it natural to add new measurement scripts (`count_replaces.py`, `bench_replace.py`) as the conversation unearthed new questions.

- **Microbenchmarks reveal what cProfile obscures.** cProfile is good for finding hot functions; it's misleading for comparing two implementations of the same function when one delegates work to nested Python-level callees (genexpr, dict.get) and the other doesn't. The `bench_replace.py` `timeit` harness was the right tool for the "is `fast_replace` actually faster?" question, and the answer (~20% per call, not 45%) was significantly less impressive than the cProfile read suggested.

- **User-driven correction of estimate inflation worked.** Three rounds of "wait, those numbers don't add up" → "you're right, let me re-measure" → revised numbers → revised recommendation order. The discipline came from the user, not from me. Worth internalizing.

- **The PROFILING.md → POSSIBLE_SPEEDUPS.md split is structurally sound.** PROFILING.md captures a snapshot ("here's what was hot on this date"). POSSIBLE_SPEEDUPS.md is forward-looking ("here are ideas that may be worth implementing"). The two docs cite each other but don't duplicate; if a future profiling pass produces different numbers, PROFILING.md's snapshot is replaced and POSSIBLE_SPEEDUPS.md is updated to match.

- **`legal_actions_cache()` is dormant on purpose.** Landing it now (before MCTS exists) is a small cost — no consumer to break, tests cover correctness in isolation — and removes a future distraction for the MCTS implementer who'd otherwise have to design memoization from scratch while also designing tree mechanics.

### Files modified or created

**New (out-of-tree):**

- `scripts/profile_states.py`, `scripts/profile_engine.py`, `scripts/count_replaces.py`, `scripts/bench_replace.py`

**New (root):**

- `PROFILING.md`, `POSSIBLE_SPEEDUPS.md`

**New (in-tree):**

- `agricola/replace.py` (~30 lines), `tests/test_replace.py` (14 tests)

**Modified (in-tree):**

- `agricola/engine.py` — `__debug__` gate around the assertion call; round-end-reset guard in `_resolve_return_home`; 25 `dataclasses.replace` → `fast_replace` migrations.
- `agricola/legality.py` — `legal_actions_cache()` context manager + thread-local plumbing (~96 lines).
- `agricola/resolution.py` — 59 `dataclasses.replace` → `fast_replace` migrations.
- `agricola/pending.py` — 3 `dataclasses.replace` → `fast_replace` migrations.
- `agricola/cards/potter_ceramics.py` — 2 `dataclasses.replace` → `fast_replace` migrations.
- `tests/test_engine.py` — 7 new `legal_actions_cache()` tests.

**Modified (docs):**

- `CHANGES.md` — Change 9 entry.
- `POSSIBLE_NEXT_STEPS.md` — restructured; old C+E folded into new C pointing at POSSIBLE_SPEEDUPS.md.
- `CLAUDE.md` — test count, status table, directory tree, conventions, doc table.
- `FILE_DESCRIPTIONS.md` — `agricola/replace.py` entry.
- `TEST_DESCRIPTIONS.md` — `legal_actions_cache()` tests bullet, `test_replace.py` entry.
- `SESSION_HISTORY.md` — this entry.

### Test count after this session

| Bucket | Count | Δ |
|---|---:|---:|
| Baseline (pre-session) | 613 | — |
| `tests/test_engine.py` | +7 | `legal_actions_cache()` tests |
| `tests/test_replace.py` (new) | +14 | `fast_replace` equivalence tests across every engine dataclass shape |
| Other minor adjustments | +2 | small additions during the session |
| **Total** | **636** | **+23** |

### Next task

Per POSSIBLE_NEXT_STEPS.md "My take": **the heuristic agent (F)** is the highest-impact next step. The engine has been profiled, optimized, and made MCTS-ready, but no agent yet plays it competently. F is the first chance to set a real baseline and surface edge cases random play never hits. After F, MCTS scaffolding (G) is the natural follow-on — fully unblocked by Changes 8 and 9.

POSSIBLE_SPEEDUPS.md S1 (anchor Pareto pruning) is the highest-ROI remaining performance optimization based on current profiles. Defer unless / until MCTS scaling makes per-rollout cost the bottleneck — but the catalog entry is fleshed-out enough to act on quickly when the time comes.

---

## Heuristic agents (item F) — SimpleHeuristic + HubrisHeuristic V1/V2 (2026-05-22)

Built the first competent agents from scratch. Two evaluator variants (`SimpleHeuristic` MVP + `HubrisHeuristic` full-spec) share a generic `HeuristicAgent` infrastructure class doing 1-turn lookahead with singleton-skip and softmax-with-temperature action selection. HubrisHeuristic itself ended up as two versions (V1 and V2) after a mid-session experiment surfaced an interesting "the bug helps" finding. 636 → 661 tests passing.

### Phase 1 — design conversation + MVP

The user laid out heuristic ideas in four broad shapes: placement-order priors, resource→points value functions, turn-order traps, and resource-cutoff thresholds. We agreed on a state-evaluation function + 1-action lookahead architecture, with softmax-temperature for diversity, deterministic by default. The first cut shipped quickly:

- `agricola/agents/__init__.py`, `base.py` (Agent protocol, `RandomAgent`, generic `HeuristicAgent`, `play_game` driver), `heuristic.py` (`HeuristicConfig` dataclass + `SimpleHeuristic` + `HubrisHeuristic`).
- `play_heuristic_game.py` top-level driver, mirroring `play_random_game.py` but accepting any combination of random / simple / hubris in either seat.
- 25 smoke tests in `tests/test_agents_heuristic.py`.

First benchmark was a surprise: agents *lost* to random with 1-action lookahead. Cause: post-PlaceWorker states for non-atomic spaces look identical to no-action states (no sub-actions committed yet, so Farm Expansion can't be distinguished from Fencing). Switched to **1-turn lookahead** (greedy rollout through the decider's own subsequent decisions until control hands off, then evaluate). Made it the default; "action" mode stays available. Immediately: Hubris 20-0-0 vs Random, +32 vs −5.

The user had predicted this in our pre-implementation discussion ("n steps deep should mean n meaningful decisions"). Their instinct was right; my "1-action lookahead is enough for v1" was wrong.

### Phase 2 — four rounds of evaluator iteration

The next several conversational rounds were user-driven iteration on V1's evaluator terms. Pattern: user spots a behavior, asks why, we trace, we adjust. Selected items:

**Cooking-improvement double-count.** Original Hubris credited each Fireplace at 4 pts and each Hearth at 6 pts. User pointed out: a player owning both Hearth + Fireplace gets credited 10 for "cooking utility," but the Fireplace is dead weight (Hearth has strictly-better rates). Fixed: only the *primary* cooking implement (Hearth > Fireplace) gets utility value; any redundant ones get printed VP (1pt). Hearth+Fireplace = 6+1 = 7, not 10.

**Wood/clay/stone diminishing returns.** User flagged the hoarding failure mode: 14 wood with no fences built shouldn't be valued at 11.2 (= 14 × 0.8). Added 3-tier piecewise valuation via a `_three_tier` helper. Wood: first 6 at 0.8, next 5 at 0.5, rest at 0.15. Clay-without-cookware: first 5 at 1.0 (incentivize buying Fireplace), rest at 0.3. Stone: first 5 at 0.8, rest at 0.3. Hubris-vs-Random average went 31.9 → 34.5 (more aggressive spending of resources).

**Cooking-implement decay by round bucket.** User-proposed: bonus value of cookware declines over time since the instrumental value is captured by the food-conversion comparison. Tiered: rounds 1-11 full / 12-13 half / 14 just printed VP.

**Renovation EV (proposed, attempted, reverted, replaced).** Renovation Wood→Clay was roughly EV-neutral in the heuristic. First fix: lower clay/stone rates so renovation came out +EV (clay_per_wood_room 0.8 → 0.55, stone_value 0.8 → 0.6). User pushed back: don't lower clay/stone globally; add a small renovation bonus instead. Replaced rate-lowering with `_hubris_renovation_bonus` (per-step credit, larger in stages 5-6). At end of session the user said "comment it out, decide later" — so the helper and config fields are kept but the call site in `evaluate_hubris_v1` is commented out.

**Newborn family-value discount (proposed, rejected).** I added a discount on newborn family members' future value (they can't act in their birth round). User rejected: the symmetric opportunity cost is also a turn (the parent's placement creates the newborn). Reverted. Then user pointed out the *real* under-count was at-home members getting only `rounds_future` plays when they should get `rounds_future + 1` (current round + future). Fixed by adding an at-home current-round bonus to the formula.

**Pasture location bonus.** I added a center-cell bonus mirroring fields' (cells (0,1),(0,2),(1,1),(1,2)). User corrected: pasture bonus should apply to all cells with `c >= 2` (right half), since the strategic motivation is "leave the left clear for room expansion." Fixed the cell set.

**Pair-bonus bug.** During a debugging conversation, user spotted that the crop+field pair bonus was firing with zero plowed fields. I'd implemented it against "empty unenclosed cells" (cells that could become fields); the user's intent was "plowed empty fields" (field tiles ready to receive crops). Fixed — grain_seeds eval in round 1 dropped from +3.1 to +2.5, exactly matching the user's expectation.

Several other small adds landed cleanly: Pottery/BMW bonus caps (match the actual end-game craft-bonus thresholds), starting-player bonus (+1.0 for SP-token holder), and stage-1 resource value multiplier (×1.5 in rounds 1-4 for the wood/clay/reed/stone tiers).

### Phase 3 — the V2 experiment

User flagged the conceptually-cleanest issue: the food/begging term assumes convertibles get converted (reducing the begging penalty) while `score()` simultaneously credits those same goods at full direct value. A double-count.

**V1 snapshot + V2 implementation.** We versioned: renamed `evaluate_hubris` → `evaluate_hubris_v1`, `HubrisHeuristic` → `HubrisHeuristicV1`, kept `HubrisHeuristic` as a backward-compat alias to V1. Implemented `evaluate_hubris_v2` using `harvest_feed_frontier` (Pareto enumeration of feeding configurations), valuing each option as `goods_score(post-conversion) + food_pts + begging_pts` and taking the max. Theoretically correct.

**The surprise.** V2 *lost* head-to-head against V1 (6-13-1 in one 20-seed sample). Worked example: 5 sheep / 0 food / need 4 / Fireplace.

- V1: `_score_sheep(5)` = +2, convertibles ≥ need so no penalty, total +2. (The "bug" — credits goods AND treats them as covering food.)
- V2: best frontier option is "convert 2 sheep → 4 food, keep 3 sheep," `_score_sheep(3)` = +1, no begging, total +1.

V2 is *technically* correct. But in the Family game, food shortfalls are rare — players usually preserve goods to scoring. V1's "I have lots of goods AND no penalty" is locally wrong but *empirically aligned* with the typical end-state. The conceptual gap: what we'd really want is max over (post-conversion outcome, no-conversion outcome) weighted by probability of conversion — V1 approximates the no-conversion case, V2 approximates the will-convert case, neither weighs them.

User's decision: keep V1 as the default; V2 remains opt-in for future work. Both are wired into `play_web.py` (`hubris_v1`, `hubris_v2` seat types) and `play_heuristic_game.py`.

### Phase 4 — web UI for AI-vs-AI watching

User requested the ability to watch AI vs AI in the browser, stepping one move at a time (Enter or button click). Substantial frontend + backend work:

- **Backend.** `--seats AGENT AGENT` replaces `--players` / `--human-seat`. New `/api/step_ai` endpoint advances one AI move. `Session` constructor takes per-seat agent types; builds agent objects for non-human seats. When at least one seat is human, AI seats fast-forward (existing behavior); when both are AI, the game waits for explicit step calls.
- **Frontend.** Per-seat agent picker in the New-game dialog (prompt-style for consistency with existing UX). Seat-type tag in player headers, color-coded (green = human, blue = simple, red = hubris). When the current decider is AI, the decision panel shows an "Advance" button + hint that Enter works. Global Enter-key handler advances one AI move when an AI is on the clock (with single-flight protection so held-Enter doesn't stack requests).

### Phase 5 — record progress

User explicitly asked to checkpoint before continuing tuning experiments. Comprehensive doc work:

- **`HEURISTIC_TUNING_PLAN.md`** (new) — three threads for the next sessions: self-play tuning harness (CMA-ES over the ~50 `HeuristicConfig` fields), time-varying parameters (per-stage tuples with monotonic constraints), score-leaf reweighting (to address the early-grain bias from the score-leaf 0→1 jump).

- **`HUBRIS_V1_NOTES.md`** (new, 605 lines) — design reference for V1: per-term function / motivation / shape / magnitude reasoning for every term in `evaluate_hubris_v1`, the V1-vs-V2 finding with worked example, deferred / rejected alternatives with reasoning, known limitations / failure modes (the A-J list with current status). Organized by design domain, not chronology — per user preference ("I want to have something that allows a reader to understand the function, motivation, and reasoning behind the current code"). Cross-referenced from CLAUDE.md and HEURISTIC_TUNING_PLAN.md so future sessions discover it.

- **CLAUDE.md, FILE_DESCRIPTIONS.md, TEST_DESCRIPTIONS.md, POSSIBLE_NEXT_STEPS.md** — status-table rows, per-module / per-test descriptions, F marked done with pointer to the tuning plan.

### Honest framing arc

Several places I over-implemented during this session:

1. **Newborn discount (B).** I added it from my own brainstorm list, framing it as a "high signal, easy fix." User correctly pointed out the symmetric-opportunity-cost reasoning. Reverted. Lesson: brainstorm items aren't user-approved by default; ask before landing.

2. **Renovation rate-lowering (C).** Same pattern. Implemented as part of the A/B/C "should I go ahead?" batch. User-preferred reframe (post-state bonus instead of global rate-lowering) made the original change moot.

3. **`pasture_center_bonus`** initially used center cells (mirroring field bonus). User clarified the strategic motivation was different (right-half, not center). Re-fixed. Lesson: when a user says "similar to X," they may mean "small magnitude like X" rather than "same target set as X."

The recovery pattern in each case: user notices, I correct, we proceed. The user explicitly noted "you implemented some of my ideas that I wrote as simple brainstorming ideas" as a meta-observation. Useful intervention — informs my behavior in future sessions where the user is explicitly thinking-out-loud vs. authorizing implementation.

### Process notes

- **The "bug that helps" finding is genuine, not a fluke.** Three follow-up benches across config tweaks all show V1 either tied with or beating V2. V2 systematically under-values animal/grain acquisition because its frontier optimization assumes mid-game conversion that empirically rarely happens. This is the kind of insight that's hard to discover without actually running the matches — pure code review of the two evaluators would have concluded V2 is strictly better.

- **One-turn lookahead with greedy rollout is enough for V1.** The user predicted this from first principles ("n meaningful decisions") and it played out in the bench numbers. The greedy 1-ply choice at each rollout step doesn't seem to materially hurt vs. deeper search — the evaluator's signal is the bottleneck, not the search.

- **The action-board pricing trace was the right diagnostic tool.** Several debugging sessions used the same shape: take an agent state, list each candidate action's eval delta, find the surprising one, decompose to find which term is doing the work. This is essentially the agent's own decision view; reading it out loud surfaced the pair-bonus bug, the stage-1 calibration question, and the grain_seeds +3.1 → +2.5 conversation.

- **`HUBRIS_V1_NOTES.md` is unusual for the project but probably right.** Other features have their rationale in CHANGES.md (cross-cutting refactors) or TASK_*.md (frozen task specs). The heuristic agent's *coefficient choices* don't fit either: they were iterated through conversation, not designed up-front, and they'll be tuned by future sessions. A standalone "why does V1 look like this?" reference is the natural home. Future versions (V2, V3) would get their own notes; this one freezes V1's reasoning.

### Files modified or created

**New (in-tree):**

- `agricola/agents/__init__.py`, `agricola/agents/base.py`, `agricola/agents/heuristic.py`
- `tests/test_agents_heuristic.py` (25 tests)

**New (root):**

- `play_heuristic_game.py` (top-level driver)
- `HEURISTIC_TUNING_PLAN.md` (forward plan)
- `HUBRIS_V1_NOTES.md` (V1 design reference)

**Modified:**

- `play_web.py` — AI-vs-AI mode, `--seats`, `/api/step_ai`
- `static/app.js` — Advance button, Enter handler, seat-picker prompts
- `static/style.css` — seat-tag color coding, Advance button styling
- `CLAUDE.md` — status table rows, directory tree, doc table
- `FILE_DESCRIPTIONS.md` — `agricola/agents/*` entries
- `TEST_DESCRIPTIONS.md` — `test_agents_heuristic.py` entry
- `POSSIBLE_NEXT_STEPS.md` — item F marked done with pointer to tuning plan
- `SESSION_HISTORY.md` — this entry

### Test count after this session

| Bucket | Count | Δ |
|---|---:|---:|
| Baseline (pre-session) | 636 | — |
| `tests/test_agents_heuristic.py` (new) | +25 | smoke tests for both agents, both evaluators, breeding-helper anchors |
| **Total** | **661** | **+25** |

### Bench summary (20 seeds, default `HeuristicConfig`)

| Match | Result | Avg score | Notes |
|---|---|---|---|
| V1 vs Random | 20-0-0 | +32.2 vs −3.8 | Default Hubris dominates random |
| V1 vs Simple | 20-0-0 | +28.8 vs +15.9 | Stage-1 boost made V1 strictly better than V1-pre-boost |
| V2 vs V1 | 7-10-3 | +24.4 vs +26.4 | The surprise — V2's joint-frontier loses to V1's "bug" |

### Next task

Per `HEURISTIC_TUNING_PLAN.md`: build the **self-play tuning harness** (Thread A) first. It's the infrastructure that makes every subsequent heuristic change measurable. Then **score-leaf reweighting** (Thread C — cheap to implement, addresses the early-grain bias). Then **time-varying parameter space** (Thread B — once Threads A and C have produced a baseline tuning result and we know which scalars are doing the most work).

In parallel: **MCTS scaffolding (item G in POSSIBLE_NEXT_STEPS.md)** is the natural next-track work. HubrisHeuristic V1 becomes the rollout policy. `legal_actions_cache()` (Change 9) is the search-loop memoizer. If MCTS rollout cost becomes a problem, `POSSIBLE_SPEEDUPS.md` S1 (anchor Pareto pruning) is the highest-ROI remaining optimization.

---

<a name="current-state"></a>
## Current State

All 661 tests pass. The codebase has:

- Complete state dataclasses and setup (`agricola/state.py`, `agricola/setup.py`, `agricola/constants.py`), with the Task 5D additions of `ROOM_COSTS` alongside the existing `MAJOR_IMPROVEMENT_COSTS`, `BAKING_IMPROVEMENT_SPECS`, etc. `PlayerState` carries `harvest_conversions_used: frozenset[str]` as of Task 7 — the once-per-harvest conversion-decision budget, reset in `_resolve_harvest_field`. `BoardState.action_spaces` is a canonical-ordered `tuple[ActionSpaceState, ...]` indexed by `constants.SPACE_INDEX` (Change 8), making `BoardState` and `GameState` fully hashable. Access helpers `get_space(board, space_id)` / `with_space(board, space_id, new_space)` live in `state.py`.
- Resource types with `__add__`, `__sub__`, and `__bool__` (`agricola/resources.py`). The non-negative invariant for resources / animals is enforced at the `step()` boundary, not inside `__sub__` itself.
- Pasture cache on `Farmyard` (`agricola/pasture.py`, `agricola/state.py`); auto-fill `__post_init__` disabled per `CHANGES.md` Change 3. Pasture-changing resolvers (including the post-Task-5D `_execute_build_stable`) recompute via `compute_pastures_from_arrays` explicitly.
- All helper functions through Task 3 plus the `enclosed_cells` legality helper (`agricola/helpers.py`). `cooking_rates` is a 4-tuple `(sheep, boar, cattle, veg)` as of Task 7. `food_payment_frontier` and `harvest_feed_frontier` (Task 7) provide Pareto-filtered conversion options for paying food. `breeding_frontier` is animal-counts-only Pareto per the "Preserving optionality" Key Design Principle (the Task 7 design's food-as-Pareto-dim attempt was reverted).
- Scoring and tiebreaker (`agricola/scoring.py`).
- Action union (`agricola/actions.py`): `PlaceWorker`, `ChooseSubAction`, `CommitSow`, `CommitBake`, `CommitPlow`, `CommitBuildStable`, `CommitBuildRoom`, `CommitBuildMajor`, `CommitRenovate`, `CommitAccommodate`, `CommitBuildPasture`, `CommitHarvestConversion`, `CommitConvert`, `CommitBreed`, `FireTrigger`, `Stop`. `CommitSubAction` is the frozen-dataclass marker base; all concrete commits dispatch through the generic `_apply_commit_subaction`.
- Pending types and stack operations (`agricola/pending.py`): 20 concrete pendings — sub-action pendings (host `CommitX`), parent pendings (host `ChooseSubAction`/`Stop`), and the two phase-driven harvest pendings `PendingHarvestFeed` / `PendingHarvestBreed`. Every pending carries `initiated_by_id` (mandatory) + `PENDING_ID` (ClassVar). The three provenance namespaces are `"space:<id>"`, `"phase:<id>"`, and `"card:<id>"`. Multi-shot sub-action pendings (`PendingBuildStables`, `PendingBuildRooms`) carry `cost: Resources` + `max_builds: int | None` + `num_built: int = 0`. `PendingBuildFences` follows the same multi-shot pattern with `pastures_built` / `fences_built` counters and the `subdivision_started` ordering-rule flag (no `cost` — bucket-4 cost handling). `PendingHarvestFeed` carries `food_owed` + `conversion_done` (gates Stop legality); `PendingHarvestBreed` carries `breed_chosen`. Stack helpers `push` / `pop` / `replace_top` live here.
- Unified legality (`agricola/legality.py`): `legal_actions(state)` as the top-level entry point. `NON_ATOMIC_LEGALITY` covers all 12 non-atomic spaces. Three `ACTIVE_FENCE_UNIVERSE_*` module constants set the default fence universe (RESTRICTED) with per-call kwarg overrides on the build-fences enumerator. Card extension registries: `BAKE_BREAD_ELIGIBILITY_EXTENSIONS`, `BAKING_SPEC_EXTENSIONS`. Helpers from Task 6: `_legal_fencing`, `_any_legal_pasture_commit`, `_check_entry_legal`, `_enclosable_cells_bm`, `_cells_bm_of_pasture`. From Task 7: `_enumerate_pending_harvest_feed`, `_enumerate_pending_harvest_breed`. All enumerators take `(state, pending: PendingX)`; the build-fences enumerator additionally accepts universe kwargs.
- Per-space resolution (`agricola/resolution.py`): atomic handlers (12 spaces), non-atomic initiators (all 12), choose-sub-action handlers (11: animal markets have no choose step). Sub-action effect functions: `_execute_sow`, `_execute_bake`, `_execute_plow`, `_execute_build_stable`, `_execute_build_room`, `_execute_build_major`, `_execute_renovate`, `_execute_accommodate`, `_execute_build_pasture`, plus Task 7's `_execute_harvest_conversion`, `_execute_convert`, `_execute_breed`. `_execute_build_stable` and `_execute_build_pasture` are the two pasture-changing effect functions; both recompute `Farmyard.pastures` via `compute_pastures_from_arrays` per the caller-discipline rule. Three function-pointer dispatch tables fully populated.
- The engine (`agricola/engine.py`): `step` + `_advance_until_decision` + phase resolvers + `_advance_current_player`. `_apply_action` has five branches (PlaceWorker, ChooseSubAction, CommitSubAction generic, FireTrigger, Stop). `_apply_commit_subaction` reads `auto_pop` and conditionally pops. `COMMIT_SUBACTION_HANDLERS` entries are 3-tuples; harvest entries (`CommitHarvestConversion`, `CommitConvert`, `CommitBreed`) all use `auto_pop=False`. **All 14 rounds and all 6 harvests are playable**: `_resolve_return_home` routes to `HARVEST_FIELD` on `HARVEST_ROUNDS = {4, 7, 9, 11, 13, 14}`; `_resolve_harvest_field` + `_initiate_harvest_feed` + `_initiate_harvest_breed` drive the harvest phases; `_advance_until_decision` has dual-meaning branches for `HARVEST_FEED` / `HARVEST_BREED` (stack non-empty = a player is deciding; stack empty = phase-exit signal). The terminal transition (HARVEST_BREED empty stack after round 14 → BEFORE_SCORING) lives in the engine loop. `step()` ends with `_assert_nonnegative_state(state, action)` — a non-negative invariant on every player's resources and animals that catches enumerator-gate misses immediately at the assertion boundary. The `NotImplementedError` branch in `_apply_place_worker` is only a defensive guard for unknown space-IDs.
- Card framework (`agricola/cards/`): `triggers.py` (event-keyed + card-id-keyed registries) + `harvest_conversions.py` (Task 7 — once-per-harvest conversion registry with three built-in craft majors and a `register_harvest_conversion(spec)` hook for future cards). One card: `potter_ceramics.py`. Forward-compat hooks remain.
- **Fencing universes and edge metadata** — `agricola/fences.py` ships four precomputed pasture-shape universes (Task 6_pre) plus per-shape edge metadata (Task 6). Sizes: FULL=1518, FAMILY=762, EXTENDED=193, RESTRICTED=109. Each universe also has a parallel `_ENTRIES` tuple of `PastureCandidate` dataclasses and a `_SMALLEST_ENTRIES` fast-path tuple. `ENTRIES_BY_BM` for off-hot-path lookup. Fence-array pack/apply helpers and the `compute_new_fence_edges` cost helper (bucket 4) are exposed.
- **Reusable sub-action pendings.** Six sub-action pendings are shared across multiple entry points: `PendingPlow` (Farmland + Cultivation), `PendingSow` (Grain Utilization + Cultivation), `PendingBakeBread` (Grain Utilization + Side Job + Clay Oven + Stone Oven), `PendingRenovate` (House Redev + Farm Redev), `PendingBuildStables` (Side Job + Farm Expansion), `PendingBuildFences` (Fencing + Farm Redev). Caller-supplied `initiated_by_id` provides provenance; per-call variance (cost, caps) is captured in pending fields set at push time.
- Test infrastructure: `tests/factories.py` for prefabricated states, `tests/test_utils.py` for `run_actions` and `random_agent_play`. `_is_implemented_action` only filters `PlaceWorker` actions; all other action types (including the three new harvest commits) pass through unconditionally.
- Top-level `play_random_game.py` script: plays one full random-vs-random game and prints the scoreboard with per-category breakdown, tiebreaker, and winner. `--trace` flag prints a per-round narrative grouping worker-placement chains and harvest sub-phases.
- **Heuristic agents** (`agricola/agents/`): generic `HeuristicAgent` infrastructure with 1-turn lookahead + always-on singleton-skip + softmax-with-temperature; `SimpleHeuristic` (MVP — score + linear resource bonuses + food/begging) and `HubrisHeuristic` (full-spec, ~50 coefficients in `HeuristicConfig`). Two Hubris versions: V1 (the iterated default; `HubrisHeuristic` alias) and V2 (uses `harvest_feed_frontier` for joint goods-or-food optimization; theoretically more correct but loses head-to-head to V1 due to the "won't actually convert if game ends first" effect — see HUBRIS_V1_NOTES.md §4). `play_heuristic_game.py` is the matchup driver. `play_web.py` supports any combination of human / random / simple / hubris / hubris_v1 / hubris_v2 in either seat, with manual step-through (Enter / "Advance" button) for AI-vs-AI watching.
- Full test coverage: **661 tests** across all test files. Includes the Task 7 harvest test files, the 11 frontier-helper tests in `test_helpers.py`, the 2 Cooking-Hearth regression tests in `test_major_improvement.py`, the 10 `tests/test_fencing.py` cases for the `fence_universe` context manager / `restrict_to` builder (item D), the 7 `legal_actions_cache()` tests in `tests/test_engine.py` (Change 9), the 14 `fast_replace` equivalence tests in `tests/test_replace.py` (Change 9), the 25 heuristic-agent smoke tests in `tests/test_agents_heuristic.py`, and the post-Task-7 deferred-food-payment / web-UI / context-manager work. Random-agent end-to-end runs to BEFORE_SCORING across many seeds (20+ verified clean) with the non-negative invariant active throughout.
- Performance harness (`scripts/profile_engine.py`, `scripts/profile_states.py`, `scripts/count_replaces.py`, `scripts/bench_replace.py`) — re-runnable from the repo root; no dependencies under `agricola/` or `tests/`. Used to produce the PROFILING.md snapshot and to validate that subsequent changes don't regress.

**Next task**: Engine is feature-complete for the Family game, `GameState` is hashable (B done, Change 8), and the engine has been profiled and first-wave-optimized (Change 9: `fast_replace`, `legal_actions_cache()`, `__debug__` assertion gate, round-end-reset guard). Per POSSIBLE_NEXT_STEPS.md, the highest-impact next step is **(F) the heuristic agent** — the first non-random agent, which surfaces edge cases random play never hits and sets a real baseline. After F, **(G) MCTS scaffolding** is fully unblocked by Changes 8+9. Further performance work is catalogued in **POSSIBLE_SPEEDUPS.md** (S1-S6); the highest-ROI remaining item is S1 (anchor Pareto pruning), defer until MCTS makes rollout cost the bottleneck. Cards beyond Potter Ceramics remain a larger separate effort with the open design questions documented in CLAUDE.md's "Card implementation status."
