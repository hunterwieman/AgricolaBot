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

<a name="current-state"></a>
## Current State

All 343 tests pass. The codebase has:

- Complete state dataclasses and setup (`agricola/state.py`, `agricola/setup.py`, `agricola/constants.py`), with the Task 5D additions of `ROOM_COSTS` alongside the existing `MAJOR_IMPROVEMENT_COSTS`, `BAKING_IMPROVEMENT_SPECS`, etc.
- Resource types with `__add__`, `__sub__`, and `__bool__` (`agricola/resources.py`).
- Pasture cache on `Farmyard` (`agricola/pasture.py`, `agricola/state.py`); auto-fill `__post_init__` disabled per `CHANGES.md` Change 3. Pasture-changing resolvers (including the post-Task-5D `_execute_build_stable`) recompute via `compute_pastures_from_arrays` explicitly.
- All helper functions through Task 3 plus the `enclosed_cells` legality helper (`agricola/helpers.py`).
- Scoring and tiebreaker (`agricola/scoring.py`).
- Action union (`agricola/actions.py`): `PlaceWorker`, `ChooseSubAction`, `CommitSow`, `CommitBake`, `CommitPlow`, `CommitBuildStable`, `CommitBuildRoom`, `CommitBuildMajor`, `CommitRenovate`, `CommitAccommodate`, `FireTrigger`, `Stop`. `CommitSubAction` is the frozen-dataclass marker base; all concrete commits dispatch through the generic `_apply_commit_subaction` (the Task 5C `CommitBuildMajor` special-case was absorbed in Task 5D step 2).
- Pending types and stack operations (`agricola/pending.py`): 15 concrete pendings split into sub-action pendings (host `CommitX`) and parent pendings (host `ChooseSubAction`/`Stop`). Every pending carries `initiated_by_id` (mandatory) + `PENDING_ID` (ClassVar). Multi-shot sub-action pendings (`PendingBuildStables`, `PendingBuildRooms`) additionally carry `cost: Resources` + `max_builds: int | None` + `num_built: int = 0`; their effect functions don't pop, leaving Stop as the explicit exit. Stack helpers `push` / `pop` / `replace_top` live here.
- Unified legality (`agricola/legality.py`): `legal_actions(state)` as the top-level entry point. Helpers include the new `_can_afford(p, cost)`, `_can_build_stable(p, cost)`, `_legal_room_cells(p)` from Task 5D; existing predicates `_can_plow` / `_has_room_placement` / `_can_afford_room` are now one-liners over their underlying enumerators or constants. Two card-extension registries: `BAKE_BREAD_ELIGIBILITY_EXTENSIONS` and `BAKING_SPEC_EXTENSIONS`. All enumerators take `(state, pending: PendingX)`.
- Per-space resolution (`agricola/resolution.py`): atomic handlers (12 spaces), non-atomic initiators (10: grain_utilization + Task 5C's 8 + Task 5D's farm_expansion), choose-sub-action handlers (9: grain_utilization plus 8 parent pendings that have a choose step; animal markets have no choose step). Sub-action effect functions (`_execute_sow`, `_execute_bake`, `_execute_plow`, `_execute_build_stable`, `_execute_build_room`, `_execute_build_major`, `_execute_renovate`, `_execute_accommodate`). `_execute_build_stable` and `_execute_build_room` are multi-shot (`auto_pop=False`, increment `num_built`, don't pop). `_execute_build_stable` recomputes pastures (fix for the latent Task 5C bug). New utility: `_new_grid_with_cell`. The three function-pointer dispatch tables fully populated.
- The engine (`agricola/engine.py`): `step` + `_advance_until_decision` + phase resolvers + `_advance_current_player`. `_apply_action` has five branches (PlaceWorker, ChooseSubAction, CommitSubAction generic, FireTrigger, Stop). `_apply_commit_subaction` reads `auto_pop` and conditionally pops after the effect. `COMMIT_SUBACTION_HANDLERS` entries are 3-tuples `(expected_pending_type_or_tuple_of_types, effect_fn, auto_pop: bool)`. Rounds 1 → 4 fully playable; halts at `Phase.BEFORE_SCORING` after round 4's RETURN_HOME. Only `farm_redevelopment` and `fencing` still raise `NotImplementedError`.
- Card framework (`agricola/cards/`): unchanged from Task 5C — `triggers.py` registries + `register()`; one card (`potter_ceramics.py`). Forward-compat hooks remain.
- Test infrastructure: `tests/factories.py` for prefabricated states, `tests/test_utils.py` for `run_actions` and `random_agent_play`. `IMPLEMENTED_NON_ATOMIC_SPACES` now contains all 10 implemented non-atomic spaces (auto-derived from `NONATOMIC_HANDLERS.keys()`).
- Full test coverage including the new `tests/test_farm_expansion.py` (25 tests covering basic walks, multi-shot semantics, singleton-Stop states, the pasture-cache recompute, once-per-category, placement legality, and stack invariants) plus updated `tests/test_side_job.py` for the multi-shot trace shape. Random-agent plays succeed across 100 seeds with Farm Expansion exercised in roughly 40% of them.

**Next task**: pick from `POSSIBLE_NEXT_STEPS.md`. Highest-impact directions are Farm Redevelopment + Fencing (the last two non-atomic spaces; Fencing the harder of the two due to the deferred fence-configuration legality), followed by the harvest (HARVEST_FIELD / HARVEST_FEED / HARVEST_BREED), which together unblock rounds 5–14 and make the engine feature-complete for the Family game.
