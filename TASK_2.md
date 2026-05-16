# AgricolaBot — Task 2: Helper Functions and Scoring

> **Note (post-task update):** This document references the original
> `compute_pastures(farmyard) -> list[Pasture]` API and the location of
> `Pasture` inside `helpers.py`. Both have since changed — `Pasture` and the
> BFS now live in `agricola/pasture.py`, the BFS function takes raw arrays
> and is named `compute_pastures_from_arrays`, and the canonical access
> pattern is `farmyard.pastures` (a cache on `Farmyard`). See
> `CHANGES.md` Change 2 for the full rename and relocation.
>
> **Note (further update — out of date):** This document also describes
> the `pastures` field as auto-filled by `Farmyard.__post_init__`. That
> auto-fill mechanism was disabled in `CHANGES.md` Change 3 — the cache
> is still on `Farmyard`, but pasture-changing resolvers now recompute
> and pass `pastures=compute_pastures_from_arrays(...)` explicitly when
> constructing a new `Farmyard`. See `CHANGES.md` Change 3 for the full
> rationale.
>
> The body of this task document is preserved as the original specification.

## What Was Built in Task 1

- `agricola/constants.py` — enums, action space IDs, stage card mapping, accumulation rates
- `agricola/state.py` — all frozen dataclasses: Resources, Animals, Cell, Farmyard, ActionSpaceState, PlayerState, BoardState, GameState
- `agricola/setup.py` — setup(seed) producing a valid 2-player Family game starting state
- `tests/test_state.py` — tests for setup correctness

---

## Files to Create in This Task

```
agricola/
    helpers.py      # Pasture dataclass, spatial helpers, pareto_frontier
    scoring.py      # end-of-game scoring
tests/
    test_helpers.py
    test_scoring.py
```

---

## Part 1: Simple Derived Quantities

These are one-liners. Add to `helpers.py`.

```python
def fences_in_supply(farmyard: Farmyard) -> int:
    """Count fence pieces not yet placed. Derived from fence arrays."""
    built = sum(sum(row) for row in farmyard.horizontal_fences) \
          + sum(sum(row) for row in farmyard.vertical_fences)
    return 15 - built

def stables_in_supply(farmyard: Farmyard) -> int:
    """Count stables not yet built. Derived from grid."""
    built = sum(
        1 for r in range(3) for c in range(5)
        if farmyard.grid[r][c].cell_type == CellType.STABLE
    )
    return 4 - built
```

---

## Part 2: Pasture Dataclass

Add to `helpers.py`. Pastures are **always derived** — never stored in state.

```python
@dataclass(frozen=True)
class Pasture:
    cells: frozenset  # frozenset of (row, col) tuples
    num_stables: int  # stables inside this pasture
    capacity: int     # 2 * num_cells * (2 ** num_stables)
```

---

## Part 3: compute_pastures

```python
def compute_pastures(farmyard: Farmyard) -> list[Pasture]:
```

### Algorithm

The fence arrays define which cell boundaries have fences. Two adjacent cells are "connected" (same pasture) if and only if there is NO fence between them. A pasture is a connected component of cells that is fully enclosed — no unfenced path to the outside of the farmyard.

**Step 1: Build adjacency.**
Two cells `(r1, c1)` and `(r2, c2)` are connected if they are orthogonally adjacent AND no fence separates them:
- Cells `(r, c)` and `(r+1, c)` (vertical neighbors): separated iff `horizontal_fences[r+1][c]` is True
- Cells `(r, c)` and `(r, c+1)` (horizontal neighbors): separated iff `vertical_fences[r][c+1]` is True

**Step 2: Find enclosed cells using "outside" flood fill.**
Rather than checking each component individually, determine which cells are NOT enclosed by flood-filling from "outside":

1. Create a virtual "outside" node.
2. Connect "outside" to any cell on the farmyard border if the border fence is absent:
   - Top row `(0, c)`: connected to outside iff `horizontal_fences[0][c]` is False
   - Bottom row `(2, c)`: connected to outside iff `horizontal_fences[3][c]` is False
   - Left column `(r, 0)`: connected to outside iff `vertical_fences[r][0]` is False
   - Right column `(r, 4)`: connected to outside iff `vertical_fences[r][5]` is False
3. Flood fill from outside using the same adjacency rules as step 1.
4. Any cell NOT reachable from outside is enclosed.

**Step 3: Group enclosed cells into pastures.**
Among enclosed cells, run a second flood fill using the same adjacency rules to find connected components. Each component is one pasture.

**Step 4: Compute each pasture's data.**
For a pasture with cells S:
- `num_stables` = count of cells in S where `cell_type == STABLE`
- `capacity` = `2 * len(S) * (2 ** num_stables)`

### Edge Case
Room tiles and field tiles do NOT act as fences (their cell borders are not fence segments). A cell with a room or field can still be enclosed by explicit fences. In practice this is unusual but must be handled correctly.

---

## Part 4: pareto_frontier

This is the most important function in this task.

```python
def pareto_frontier(player_state: PlayerState, gained: Animals) -> list[Animals]:
```

### What It Does

When a player gains animals (e.g., from an accumulation space), they must decide which animals to keep. They cannot keep more animals than their farm can accommodate, and they cannot end up with more of any type than `current + gained`.

This function returns all **Pareto-optimal achievable total animal configurations** — tuples `(sheep, boar, cattle)` such that no other achievable tuple is at least as large in every component and strictly larger in at least one.

### Two Constraints

**Constraint 1 — Inventory:** You cannot spontaneously create animals.
- `final_sheep ≤ player_state.animals.sheep + gained.sheep`
- `final_boar  ≤ player_state.animals.boar  + gained.boar`
- `final_cattle ≤ player_state.animals.cattle + gained.cattle`

Note: you CAN end up with fewer than your current count of any type — players may discard animals to the supply at any time.

**Constraint 2 — Farm capacity:** The final animal counts must be physically accommodatable on the farm. This is an assignment problem (see below).

### Farm Slots

Extract from the farmyard:

```python
def extract_slots(player_state: PlayerState) -> tuple[list[int], int]:
    """
    Returns (pasture_capacities, num_flexible_slots).

    pasture_capacities: list of ints, one per pasture
    num_flexible_slots: number of standalone (unfenced) stables + 1 (house pet)

    A standalone stable holds exactly 1 animal of any type.
    The house holds exactly 1 animal of any type (the pet).
    """
    pastures = compute_pastures(player_state.farmyard)
    pasture_capacities = [p.capacity for p in pastures]

    total_stables_built = 4 - stables_in_supply(player_state.farmyard)
    stables_in_pastures = sum(p.num_stables for p in pastures)
    standalone_stables = total_stables_built - stables_in_pastures

    num_flexible = standalone_stables + 1  # +1 for house pet

    return pasture_capacities, num_flexible
```

### can_accommodate

```python
def can_accommodate(
    pasture_capacities: list[int],
    num_flexible: int,
    sheep: int,
    boar: int,
    cattle: int,
) -> bool:
    """
    Check if (sheep, boar, cattle) animals can be assigned to the given slots.

    Each pasture holds exactly ONE type of animal (up to its capacity).
    Each flexible slot (standalone stable or house) holds exactly 1 animal of any type.

    Algorithm: try all assignments of types to pastures.
    For each assignment, compute how many animals overflow into flexible slots.
    Return True if any assignment results in total overflow ≤ num_flexible.
    """
    from itertools import product as iproduct

    counts = (sheep, boar, cattle)
    n = len(pasture_capacities)

    # Each pasture can be assigned to: empty(0), sheep(1), boar(2), cattle(3)
    for assignment in iproduct(range(4), repeat=n):
        dedicated = [0, 0, 0]  # dedicated capacity per type (index: 0=sheep, 1=boar, 2=cattle)
        for i, t in enumerate(assignment):
            if t > 0:
                dedicated[t - 1] += pasture_capacities[i]

        # Overflow = animals of each type that don't fit in their dedicated pastures
        overflow = sum(max(0, counts[t] - dedicated[t]) for t in range(3))

        if overflow <= num_flexible:
            return True

    return False
```

**Why this works:** Each flexible slot holds 1 animal of any type, so the only question for flexible slots is whether the total overflow across all types fits. If `sum(overflow) ≤ num_flexible`, we can always assign one flexible slot to each overflow animal regardless of type.

**Performance:** `n` ≤ number of pastures ≤ ~6. `4^6 = 4096` iterations maximum. Fast enough.

### pareto_frontier Implementation

```python
def pareto_frontier(player_state: PlayerState, gained: Animals) -> list[Animals]:
    pasture_capacities, num_flexible = extract_slots(player_state)

    # Inventory upper bounds
    s_max = player_state.animals.sheep  + gained.sheep
    b_max = player_state.animals.boar   + gained.boar
    c_max = player_state.animals.cattle + gained.cattle

    # Enumerate all feasible (s, b, c) within inventory bounds
    feasible = [
        Animals(sheep=s, boar=b, cattle=c)
        for s in range(s_max + 1)
        for b in range(b_max + 1)
        for c in range(c_max + 1)
        if can_accommodate(pasture_capacities, num_flexible, s, b, c)
    ]

    # Keep only non-dominated (Pareto-optimal) configurations
    def dominates(a: Animals, b: Animals) -> bool:
        """True if a is strictly better than b in every component."""
        return (a.sheep >= b.sheep and a.boar >= b.boar and a.cattle >= b.cattle
                and a != b)

    frontier = [
        candidate for candidate in feasible
        if not any(dominates(other, candidate) for other in feasible)
    ]

    return frontier
```

### Worked Example

**Setup:**
- Farm: one 2×1 pasture (capacity 4), one 1×1 pasture (capacity 2), no stables, house (1 pet)
- `pasture_capacities = [4, 2]`, `num_flexible = 1`
- Current animals: `(sheep=0, boar=4, cattle=0)`
- Gained: `(sheep=4, boar=0, cattle=0)`
- Inventory bounds: `s_max=4, b_max=4, c_max=0`

**Key checks:**
- `can_accommodate([4, 2], 1, sheep=4, boar=4, cattle=0)`:
  - Try: pasture 0 → sheep (cap 4), pasture 1 → boar (cap 2)
  - dedicated = [4, 2, 0]. overflow = max(0, 4-4) + max(0, 4-2) = 0 + 2 = 2. 2 > 1. Fail.
  - Try: pasture 0 → boar (cap 4), pasture 1 → sheep (cap 2)
  - dedicated = [2, 4, 0]. overflow = max(0, 4-2) + max(0, 4-4) = 2 + 0 = 2. 2 > 1. Fail.
  - Try: pasture 0 → sheep (cap 4), pasture 1 → sheep (cap 2). dedicated = [6, 0, 0].
  - overflow = max(0, 4-6) + max(0, 4-0) = 0 + 4 = 4. 4 > 1. Fail.
  - (All assignments fail.) → False. (4 sheep + 4 boar cannot fit.)

- `can_accommodate([4, 2], 1, sheep=4, boar=3, cattle=0)`:
  - Try: pasture 0 → boar (cap 4), pasture 1 → sheep (cap 2)
  - dedicated = [2, 4, 0]. overflow = max(0,4-2) + max(0,3-4) = 2 + 0 = 2. Fail.
  - Try: pasture 0 → sheep (cap 4), pasture 1 → boar (cap 2)
  - dedicated = [4, 2, 0]. overflow = max(0,4-4) + max(0,3-2) = 0 + 1 = 1. 1 ≤ 1. **Pass!**
  - (4 sheep in pasture 0, 2 boar in pasture 1, 1 boar in house.) → True.

- `can_accommodate([4, 2], 1, sheep=3, boar=4, cattle=0)`:
  - Try: pasture 0 → boar (cap 4), pasture 1 → sheep (cap 2)
  - dedicated = [2, 4, 0]. overflow = max(0,3-2) + max(0,4-4) = 1 + 0 = 1. 1 ≤ 1. **Pass!**
  - (3 sheep: 2 in pasture 1, 1 in house. 4 boar in pasture 0.) → True.

**Final Pareto frontier:** `[(sheep=4, boar=3, cattle=0), (sheep=3, boar=4, cattle=0)]`

**Note on (2, 5, 0):** This is NOT returned. It would require 5 boar, but `b_max = 4` (inventory constraint). The function enforces both farm capacity and inventory bounds.

---

## Part 5: Scoring Function

```python
def score(state: GameState, player_idx: int) -> int:
```

Implement end-of-game scoring per the table in ARCHITECTURE.md. Return the total integer score including all negatives. Also implement a `ScoreBreakdown` dataclass that stores each category separately (useful for the training-tool features later).

```python
@dataclass
class ScoreBreakdown:
    field_tiles: int
    pastures: int
    grain: int
    vegetables: int
    sheep: int
    boar: int
    cattle: int
    unused_spaces: int      # always ≤ 0
    fenced_stables: int
    clay_rooms: int
    stone_rooms: int
    people: int
    begging_markers: int    # always ≤ 0
    major_improvement_points: int
    bonus_points: int       # from craft building end-game exchanges
    total: int
```

### Scoring Details

**Field tiles** (count field-tile cells in grid, not card fields):
`0–1 → −1; 2 → 1; 3 → 2; 4 → 3; 5+ → 4`

**Pastures** (count from compute_pastures):
`0 → −1; 1–4 → 1 pt each; max 4`

**Grain** (supply grain + grain on all field-tile cells):
`0 → −1; 1–3 → 1; 4–5 → 2; 6–7 → 3; 8+ → 4`

**Vegetables** (supply veg + veg on all field-tile cells):
`0 → −1; 1 → 1; 2 → 2; 3 → 3; 4+ → 4`

**Sheep:** `0 → −1; 1–3 → 1; 4–5 → 2; 6–7 → 3; 8+ → 4`

**Wild Boar:** `0 → −1; 1–2 → 1; 3–4 → 2; 5–6 → 3; 7+ → 4`

**Cattle:** `0 → −1; 1 → 1; 2–3 → 2; 4–5 → 3; 6+ → 4`

**Unused farmyard spaces:** −1 per unused space.
A space is **used** if it has a room, field, or stable on it, OR is enclosed by fences (i.e., is in any pasture). Use `compute_pastures` to determine enclosed cells.

**Fenced stables:** 1 pt per stable that is inside a pasture (i.e., in a pasture returned by `compute_pastures`). Max 4.

**Clay rooms:** 1 pt each. Count room cells × 1 if `player_state.house_material == HouseMaterial.CLAY`. *(Originally specified as reading `house_material` per cell; subsequently moved to `PlayerState` — see CLEANUP.md Cleanup 1.)*

**Stone rooms:** 2 pts each. Count room cells × 2 if `player_state.house_material == HouseMaterial.STONE`. *(Same change as above.)*

**People:** 3 pts each (`player_state.people_total`).

**Begging markers:** −3 each (`player_state.begging_markers`).

**Major improvement points:**
```python
MAJOR_IMPROVEMENT_POINTS = [1, 1, 1, 1, 4, 2, 3, 2, 2, 2]  # indices 0–9
```
Sum points for each major owned by this player (check `board.major_improvement_owners`).

**Craft building bonus points** (Joinery=7, Pottery=8, Basketmaker's=9):
- Joinery (idx 7): player may spend 3/5/7 wood from their personal supply for 1/2/3 bonus pts
- Pottery (idx 8): player may spend 3/5/7 clay from their personal supply for 1/2/3 bonus pts
- Basketmaker's (idx 9): player may spend 2/4/5 reed from their personal supply for 1/2/3 bonus pts
- Award the maximum bonus the player qualifies for (they will always want maximum points).
- Resources spent on bonus ARE consumed and DO reduce the tiebreaker supply count.

**Tiebreaker** (not part of score, but return it as a separate value):
Total building resources in personal supply: `wood + clay + reed + stone` after subtracting any resources spent on craft building bonuses.

---

## Tests

### test_helpers.py

**compute_pastures tests:**
- `test_no_fences_no_pastures`: empty fence arrays → empty list
- `test_single_1x1_pasture`: manually set the 4 fence segments around cell (0,0) → one pasture with cells={(0,0)}, num_stables=0, capacity=2
- `test_2x1_pasture`: set fences for a 2×1 pasture → capacity=4
- `test_stable_in_pasture`: 1×1 pasture with a STABLE cell → num_stables=1, capacity=4
- `test_two_stables_in_2x1`: 2×1 pasture, both cells are STABLE → capacity=16
- `test_two_adjacent_pastures`: subdivided 2×1 → two pastures, each with capacity=2
- `test_unfenced_cell_not_pasture`: cell with no surrounding fences → not in any pasture

**can_accommodate tests:**
- `test_empty_farm_no_animals`: can_accommodate([], 1, 0, 0, 0) → True
- `test_fits_in_one_pasture`: pasture cap=4, can_accommodate([4], 0, 4, 0, 0) → True
- `test_overflow_to_flexible`: can_accommodate([4], 1, 4, 1, 0) → True (4 sheep in pasture, 1 boar in house)
- `test_overflow_exceeds_flexible`: can_accommodate([4], 1, 4, 2, 0) → False
- `test_two_types_two_pastures`: can_accommodate([4, 2], 1, 4, 3, 0) → True

**pareto_frontier tests:**
- `test_empty_farm`: only house → pareto frontier is {(1,0,0), (0,1,0), (0,0,1)} (can keep 1 of any type, no more)
- `test_worked_example`: the 4-pig / 4-sheep example from the design document → [(4,3,0), (3,4,0)]
- `test_inventory_constraint`: verify (2,5,0) is never returned when boar_max=4
- `test_discard_to_gain`: verify that configurations requiring discarding current animals ARE included (e.g., discarding a pig to keep more sheep)
- `test_no_gained_no_change`: gained=Animals() → frontier contains only current state (can't gain anything)

### test_scoring.py

- `test_score_empty_farm_two_people`: starting state (no development) → −6 for unused spaces (13 × −1, but 2 rooms used), −1 for each missing category (pastures, grain, veg, sheep, boar, cattle = −6), +6 for people. Compute expected total.
- `test_field_tile_scoring`: specific field tile counts → correct points
- `test_animal_scoring`: specific animal counts → correct points
- `test_begging_markers`: 2 begging markers → −6 from those
- `test_fenced_stable_scoring`: stable inside a 1×1 pasture → 1 pt fenced stable
- `test_craft_building_bonus`: player owns Joinery with 7 wood → 3 bonus pts
- `test_tiebreaker`: returns correct resource total

---

## What NOT to Implement

- `step(state, action)` — deferred
- `legal_actions(state)` — deferred
- Any game loop — deferred
- Action type definitions — deferred
- Card effects — deferred
