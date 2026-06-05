# AgricolaBot — Task 3: Cooking Rates, Modified pareto_frontier, breeding_frontier

## Context

All changes in this task touch `agricola/helpers.py` and `tests/test_helpers.py`.
Read ARCHITECTURE.md for architecture and TASK_2.md for what was built previously.

---

## 1. New Helper: cooking_rates

Add to `agricola/helpers.py`.

```python
def cooking_rates(state: GameState, player_idx: int) -> tuple[int, int, int]:
    """
    Returns (sheep_rate, boar_rate, cattle_rate) for animal-to-food conversion.

    Based on the best cooking improvement the player owns:
      Cooking Hearth (major idx 2 or 3) -> (2, 3, 4)
      Fireplace      (major idx 0 or 1) -> (2, 2, 3)
      Neither                           -> (0, 0, 0)

    If the player owns both a Fireplace and a Cooking Hearth, the Cooking
    Hearth rates apply (they are strictly better for every animal type).

    If rates are (0, 0, 0), the player has no cooking improvement. Excess
    animals are returned to the general supply; no food is generated.
    """
    owners = state.board.major_improvement_owners
    has_hearth   = any(owners[i] == player_idx for i in (2, 3))
    has_fireplace = any(owners[i] == player_idx for i in (0, 1))

    if has_hearth:
        return (2, 3, 4)
    elif has_fireplace:
        return (2, 2, 3)
    else:
        return (0, 0, 0)
```

---

## 2. Modified: pareto_frontier

**Do not rewrite this function from scratch.** The full implementation exists
in helpers.py from Task 2. Make only the two targeted changes:
1. Add the `rates` parameter with default `(0, 0, 0)`
2. Change the return type from `list[Animals]` to `list[tuple[Animals, int]]`
   by adding the food computation just before each yield/append in the
   existing frontier loop.

**Breaking change**: return type changes from `list[Animals]` to `list[tuple[Animals, int]]`.
Update all existing callers and tests accordingly.

### New signature

```python
def pareto_frontier(
    player_state: PlayerState,
    gained: Animals,
    rates: tuple[int, int, int] = (0, 0, 0),
) -> list[tuple[Animals, int]]:
```

### What changes

Add a `rates` parameter (default `(0, 0, 0)` so callers that don't care about food
still work without changes beyond unpacking the return value).

For each Pareto-optimal animal configuration `(sF, bF, cF)`, compute food generated:

```python
sR, bR, cR = rates
s_available = player_state.animals.sheep  + gained.sheep
b_available = player_state.animals.boar   + gained.boar
c_available = player_state.animals.cattle + gained.cattle

food = (s_available - sF) * sR \
     + (b_available - bF) * bR \
     + (c_available - cF) * cR
```

**Explanation**: `s_available` is every sheep the player has access to in this
moment (existing + just gained). `sF` is how many they keep. The difference is
the number cooked (if `sR > 0`) or returned to supply (if `sR == 0`). Either
way, `(s_available - sF) * sR` is the food contribution — zero when rates are
zero, positive when a cooking improvement is present.

The Pareto frontier itself (which configurations are non-dominated) is
**unchanged** — it is still over animal counts only. Food is computed
deterministically from the frontier point and the rates; it does not affect
which configurations are Pareto-optimal.

### Return value

A list of `(Animals, int)` tuples, one per Pareto-optimal configuration.
`Animals` is the final animal counts; `int` is total food generated.

---

## 3. New Function: breeding_frontier

Add to `agricola/helpers.py`.

```python
def breeding_frontier(
    player_state: PlayerState,
    rates: tuple[int, int, int] = (0, 0, 0),
) -> list[tuple[Animals, int]]:
```

### Context

Called at the start of the breeding phase, after feeding is complete. The player
may cook/release animals *before* breeding fires. After breeding there is no
further cooking step. The function returns all Pareto-optimal (final animals,
food generated) outcomes across all possible pre-breeding cooking choices.

### Algorithm

**Step 1 — Desired post-breed counts.**

```python
s, b, c = player_state.animals.sheep, player_state.animals.boar, player_state.animals.cattle
s_desired = s + 1 if s >= 2 else s
b_desired = b + 1 if b >= 2 else b
c_desired = c + 1 if c >= 2 else c
```

Each type with ≥ 2 animals gets one newborn if capacity allows. This is the
upper bound on what the player can end up with.

**Step 2 — Pareto frontier of achievable final configurations.**

Use `extract_slots` and `can_accommodate` (from Task 2) to enumerate all
`(sF, bF, cF)` where:
- `0 ≤ sF ≤ s_desired`, `0 ≤ bF ≤ b_desired`, `0 ≤ cF ≤ c_desired`
- `can_accommodate(pasture_capacities, num_flexible, sF, bF, cF)` is True

Then keep only non-dominated configurations, exactly as in `pareto_frontier`.

**Step 3 — Food formula.**

For each `(sF, bF, cF)` in the frontier:

```python
sR, bR, cR = rates

food_s = (s + 1 - sF) * sR if (s >= 2 and sF >= 3) else (s - sF) * sR
food_b = (b + 1 - bF) * bR if (b >= 2 and bF >= 3) else (b - bF) * bR
food_c = (c + 1 - cF) * cR if (c >= 2 and cF >= 3) else (c - cF) * cR

food = food_s + food_b + food_c
```

**Why this formula is correct:**

- `sF >= 3` with `s >= 2` is the exact condition for "sheep bred". If the player
  ended with ≥ 3 sheep and started with ≥ 2, the newborn must have been
  accommodated. The player ate `(s + 1 - sF)` sheep pre-breeding.
- `sF < 3` with `s >= 2` means breeding did not fire for sheep (either capacity
  was unavailable, or the player ate pre-breeding to prevent it). The player ate
  `(s - sF)` sheep.
- `s < 2`: breeding was never possible. The player ate `(s - sF)` sheep.

**Step 4 — Return.**

```python
return [(Animals(sheep=sF, boar=bF, cattle=cF), food)
        for (sF, bF, cF), food in ...]
```

### Key difference from pareto_frontier

`pareto_frontier` has a `gained` parameter (animals just received from an
accumulation space). `breeding_frontier` has no `gained` parameter — the
"desired" upper bound comes from the breeding rule itself, not from an external
gain. Internally, `breeding_frontier` treats `(s_desired, b_desired, c_desired)`
exactly like `pareto_frontier` treats `(current + gained)`.

---

## 4. Tests

### Updates to existing tests

All `test_pareto_frontier_*` tests must be updated to unpack `(Animals, int)`
tuples instead of bare `Animals`. Tests that don't care about food should
assert `food == 0` (since default rates are `(0, 0, 0)`).

### New tests for cooking_rates

- `test_no_cooking_improvement`: player owns no major improvements → `(0, 0, 0)`
- `test_fireplace_owned`: player owns Fireplace (idx 0) → `(2, 2, 3)`
- `test_cooking_hearth_owned`: player owns Cooking Hearth (idx 2) → `(2, 3, 4)`
- `test_hearth_beats_fireplace`: player owns both Fireplace (idx 1) and Cooking
  Hearth (idx 3) → `(2, 3, 4)` (Hearth wins)

### New tests for modified pareto_frontier

- `test_pareto_food_no_improvement`: rates `(0,0,0)`, food is always 0
- `test_pareto_food_with_fireplace`: rates `(2,2,3)`, gained 4 sheep, current 0,
  farm is 2×1 pasture only (cap 4) → frontier includes `(Animals(sheep=4), 0)`;
  verify food = 0 (all gained sheep kept)
- `test_pareto_food_partial_keep`: rates `(2,2,3)`, gained 4 sheep, current 0,
  farm is 1×1 pasture only (cap 2) → max sheep keepable = 2; frontier includes
  `(Animals(sheep=2), 4)` (2 sheep cooked × rate 2 = 4 food)
- `test_pareto_food_existing_animals_eaten`: verify that existing animals eaten
  to make room also contribute food proportionally

### New tests for breeding_frontier

- `test_breeding_no_animals`: 0 of every type → frontier is `[(Animals(), 0)]`
  (no breeding possible, no food)
- `test_breeding_one_of_each`: 1 sheep, 1 boar, 1 cattle → no breeds, frontier
  is just the current state with food 0
- `test_breeding_sheep_only_breeds`: 2 sheep, 0 boar, 0 cattle, farm has 1×1
  pasture (cap 2) → sheep cannot breed (no room for 3rd); frontier is
  `[(Animals(sheep=2), 0)]`
- `test_breeding_sheep_breeds_with_room`: 2 sheep, farm has 2×1 pasture (cap 4)
  → s_desired=3, fits; frontier is `[(Animals(sheep=3), 0)]` with no rates
- `test_breeding_food_from_excess`: 4 sheep, farm has 1×1 pasture (cap 2),
  rates `(2, 0, 0)`, s=4 ≥ 2, s_desired=5; frontier point `(Animals(sheep=2), ?)`:
  sF=2 < 3, so food_s = (s - sF) * sR = (4 - 2) * 2 = 4. Assert food = 4.
- `test_breeding_worked_example`: 4 pigs (boar), 0 sheep, farm is 2×1 pasture
  (cap 4) + 1×1 pasture (cap 2) + house (1 flexible). rates `(2, 2, 3)`.
  s=0 (no sheep), b=4, b_desired=5 (4≥2). Verify frontier contains
  `(Animals(boar=4), bR*1)` → boar can fit 4 max (2×1 + 1 overflow to house
  or 1×1). Check exact frontier contents.
- `test_breeding_formula_sF_ge_3`: construct case where s=3, rates=(2,0,0),
  farm large enough; s_desired=4; verify a frontier point with sF=3 has
  food_s = (s+1-sF)*sR = (3+1-3)*2 = 2
- `test_breeding_formula_sF_lt_3`: s=3, rates=(2,0,0), farm capacity=2 for
  sheep; s_desired=4 but max achievable sheep=2; verify food_s=(3-2)*2=2
