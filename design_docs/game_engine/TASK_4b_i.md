# Task 4b-i — Non-Atomic-Space Legality

This task extends `legal_atomic_placements` (or replaces it with a unified `legal_placements`) to cover all remaining non-atomic action spaces except `fencing` (which requires fence enumeration — deferred to a later task). After this task, every placement the active player could legally make — except those involving fence-building as the primary action — is correctly identified.

`farm_redevelopment` is included: its only mandatory condition is renovation, and fencing is optional. So its legality is identical to `house_redevelopment`.

## Scope

**In scope**
- Shared helper functions for reusable sub-conditions: `_can_bake_bread`, `_can_sow`, `_can_plow`, `_can_build_room`, `_has_stable_placement`, `_can_renovate`, `_can_afford_any_major_improvement`.
- Per-space legality predicates for all remaining non-atomic spaces: `farm_expansion`, `farmland`, `side_job`, `grain_utilization`, `sheep_market`, `pig_market`, `cattle_market`, `major_improvement`, `house_redevelopment`, `cultivation`, `farm_redevelopment`.
- A unified public function `legal_placements(state)` returning all legal `PlaceWorker` actions across all in-scope spaces.
- Tests for each space and each shared helper.

**Out of scope**
- Resolution (Task 4b-ii).
- `fencing` (deferred — requires fence enumeration).
- `lessons` (permanently illegal in Family game).
- Sub-decision action types (Plow, Sow, BuildRoom, BuildStable, etc.) — those are for the resolution task.
- Advancing `current_player`, phase transitions, or round logic.

---

## Audit step

Before writing anything, read the current `agricola/legality.py` and `agricola/state.py`. Confirm the following field names in use:
- `ActionSpaceState.workers`, `ActionSpaceState.accumulated`, `ActionSpaceState.accumulated_amount`, `ActionSpaceState.round_revealed`
- `PlayerState.resources` (`Resources` object with `.wood`, `.clay`, `.reed`, `.stone`, `.food`, `.grain`, `.veg`)
- `PlayerState.animals`
- `PlayerState.farmyard` (grid, horizontal_fences, vertical_fences)
- `PlayerState.people_total`, `PlayerState.people_home`
- `GameState.current_player`, `GameState.round_number`
- `BoardState.major_improvement_owners` (tuple of 10 `Optional[int]`)

If any names have drifted, follow the existing names throughout.

---

## Shared helper functions

Add these helpers to `legality.py`. Each takes `p: PlayerState` (or `state, p` when board information is needed), passed in rather than re-derived, to avoid repeated indexing. Helpers carry leading underscores by convention; tests import them by name regardless.

### `_can_bake_bread(state, p) -> bool`

The given player can execute a Bake Bread action if both conditions hold:
1. They own at least one baking improvement: Fireplace (index 0 or 1), Cooking Hearth (index 2 or 3), Clay Oven (index 5), or Stone Oven (index 6).
2. They have at least 1 grain in their personal supply (`p.resources.grain >= 1`).

The player's index is derived from `p` itself (by identity comparison against `state.players`), not from `state.current_player`. This makes the helper correct for any `p` in the state, not just the currently-active player.

```python
BAKING_IMPROVEMENTS = frozenset({0, 1, 2, 3, 5, 6})

def _can_bake_bread(state: GameState, p: PlayerState) -> bool:
    player_idx = 0 if p is state.players[0] else 1
    owns_baker = any(
        state.board.major_improvement_owners[i] == player_idx
        for i in BAKING_IMPROVEMENTS
    )
    return owns_baker and p.resources.grain >= 1
```

### `_can_sow(p) -> bool`

The player can sow if they have at least one empty field cell (`cell_type == FIELD` and `grain == 0` and `veg == 0`) AND at least one grain or vegetable in their personal supply.

```python
def _can_sow(p: PlayerState) -> bool:
    has_empty_field = any(
        p.farmyard.grid[r][c].cell_type == CellType.FIELD
        and p.farmyard.grid[r][c].grain == 0
        and p.farmyard.grid[r][c].veg == 0
        for r in range(3) for c in range(5)
    )
    has_seed = p.resources.grain >= 1 or p.resources.veg >= 1
    return has_empty_field and has_seed
```

### `_can_plow(p) -> bool`

The player can plow if there is at least one valid plow target. A plow target must be `EMPTY` **and** non-enclosed (cells inside a pasture cannot be converted to fields per RULES.md §Fields and Crops).

- If the player has no fields yet, any `EMPTY` non-enclosed cell is valid.
- If the player has at least one field, the target must additionally be orthogonally adjacent to an existing field cell.

The non-enclosed check is performed by intersecting candidate empty cells with the complement of `enclosed_cells(p.farmyard)` from `agricola.helpers`. `enclosed_cells` reads the cached `Farmyard.pastures` decomposition (O(1)) and returns the set of all cells inside any pasture.

```python
def _can_plow(p: PlayerState) -> bool:
    grid = p.farmyard.grid
    field_cells = {
        (r, c)
        for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
    }
    enclosed = enclosed_cells(p.farmyard)
    empty_cells = {
        (r, c)
        for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.EMPTY
        and (r, c) not in enclosed
    }
    if not empty_cells:
        return False
    if not field_cells:
        return True  # first field goes anywhere (any empty, non-enclosed cell)
    adjacent_to_field = {
        (r + dr, c + dc)
        for (r, c) in field_cells
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]
    }
    return bool(empty_cells & adjacent_to_field)
```

### `_has_stable_placement(p) -> bool`

Returns True if a stable can be placed somewhere on the farm — i.e. there is at least one `EMPTY` cell (no tile) and at least one stable remaining in supply. Does **not** check wood cost; that is handled per-space since the cost differs between Farm Expansion (2 wood) and Side Job (1 wood).

```python
def _has_stable_placement(p: PlayerState) -> bool:
    has_empty_cell = any(
        p.farmyard.grid[r][c].cell_type == CellType.EMPTY
        for r in range(3) for c in range(5)
    )
    return has_empty_cell and stables_in_supply(p.farmyard) >= 1
```

(`stables_in_supply` is already imported from `agricola/helpers.py`.)

### `_can_afford_room(p) -> bool`

Affordability check only — does the player's personal supply contain at least the cost of one room? Cost for one room: 5 of the current house material + 2 reed. Read the current material from `p.house_material` (see Cleanup 1 — material is stored on `PlayerState`, not on `Cell`).

This is a separate function (rather than inlined into `_can_build_room`) because cards in the full game can grant alternative room-building costs — the affordability calc will eventually branch on owned cards while the placement geometry stays the same.

```python
def _can_afford_room(p: PlayerState) -> bool:
    res = p.resources
    material = p.house_material
    if material == HouseMaterial.WOOD:
        return res.wood >= 5 and res.reed >= 2
    if material == HouseMaterial.CLAY:
        return res.clay >= 5 and res.reed >= 2
    # STONE
    return res.stone >= 5 and res.reed >= 2
```

### `_has_room_placement(p) -> bool`

Placement geometry only — is there at least one cell that is `EMPTY`, **non-enclosed**, and orthogonally adjacent to an existing room? Cells inside a pasture cannot have rooms built on them per RULES.md §House and Rooms.

```python
def _has_room_placement(p: PlayerState) -> bool:
    grid = p.farmyard.grid
    enclosed = enclosed_cells(p.farmyard)
    room_cells = {
        (r, c)
        for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.ROOM
    }
    empty_cells = {
        (r, c)
        for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.EMPTY
        and (r, c) not in enclosed
    }
    adjacent_to_room = {
        (r + dr, c + dc)
        for (r, c) in room_cells
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]
    }
    return bool(empty_cells & adjacent_to_room)
```

### `_can_build_room(p) -> bool`

Composition: at least one room can be built iff the player can afford it AND a valid placement cell exists.

```python
def _can_build_room(p: PlayerState) -> bool:
    return _can_afford_room(p) and _has_room_placement(p)
```

> **Room adjacency note:** Legality only requires that *one* valid adjacent empty non-enclosed cell exists. When multiple rooms are built in a single Farm Expansion action, each new room must be adjacent to any room that will exist after the action completes — including rooms placed earlier in the same action. This chaining is a resolution concern, not a legality concern. If at least one room can be started, the space is legal.

### `_can_renovate(p) -> bool`

The player can renovate if the house is not already stone and they can afford the cost across all rooms at once. Renovation upgrades ALL rooms simultaneously.

Cost: 1 clay per room + 1 reed (wood → clay), or 1 stone per room + 1 reed (clay → stone).

```python
def _can_renovate(p: PlayerState) -> bool:
    material = p.house_material  # see Cleanup 1 — material now on PlayerState
    if material == HouseMaterial.STONE:
        return False  # already at max
    num_rooms = sum(
        1 for r in range(3) for c in range(5)
        if p.farmyard.grid[r][c].cell_type == CellType.ROOM
    )
    res = p.resources
    if material == HouseMaterial.WOOD:
        return res.clay >= num_rooms and res.reed >= 1
    else:  # CLAY
        return res.stone >= num_rooms and res.reed >= 1
```

### `_can_afford_any_major_improvement(state, p) -> bool`

The given player can buy at least one major improvement if at least one of the 10 is unowned and the player can meet its cost.

The player's index is derived from `p` itself (by identity comparison against `state.players`), not from `state.current_player`. The same convention applies to the per-index helper `_can_afford_major(state, p, idx)`.

Costs (index → cost):
- 0: clay ≥ 2
- 1: clay ≥ 3
- 2: clay ≥ 4 **OR** owns Fireplace (index 0 or 1)
- 3: clay ≥ 5 **OR** owns Fireplace (index 0 or 1)
- 4: stone ≥ 3 and wood ≥ 1
- 5: clay ≥ 3 and stone ≥ 1
- 6: clay ≥ 1 and stone ≥ 3
- 7: wood ≥ 2 and stone ≥ 2
- 8: clay ≥ 2 and stone ≥ 2
- 9: reed ≥ 2 and stone ≥ 2

For Cooking Hearth (indices 2 and 3): the player may return a Fireplace they own (index 0 or 1) instead of paying the clay cost. Legality check: cost is met if `clay >= required_amount` OR `major_improvement_owners[0] == player_idx` OR `major_improvement_owners[1] == player_idx`, where `player_idx = 0 if p is state.players[0] else 1`.

Only unowned major improvements (`major_improvement_owners[i] is None`) are considered.

---

## Per-space legality

Throughout, `ap = state.current_player`, `p = state.players[ap]`.

### `farm_expansion`

Legal if the space is available AND at least one of:
- `_can_build_room(p)` — can afford and place at least one room
- `p.resources.wood >= 2 and _has_stable_placement(p)` — can afford and place at least one stable

### `farmland`

Legal if the space is available AND `_can_plow(p)`.

### `side_job`

Legal if the space is available AND at least one of:
- `p.resources.wood >= 1 and _has_stable_placement(p)` — can build a stable for 1 wood
- `_can_bake_bread(state, p)`

### `grain_utilization`

Legal if the space is revealed and available AND at least one of:
- `_can_sow(p)`
- `_can_bake_bread(state, p)`

### `sheep_market`

Legal if the space is revealed and available AND `accumulated_amount > 0`.

### `pig_market`

Legal if the space is revealed and available AND `accumulated_amount > 0`.

### `cattle_market`

Legal if the space is revealed and available AND `accumulated_amount > 0`.

Note: these three spaces require a pareto frontier sub-decision at resolution. Legality only checks that there are animals to take. A player who cannot accommodate any animals may still legally take the space and return everything to the general supply — `(0, 0, 0)` is always a valid pareto frontier outcome.

### `major_improvement`

Legal if the space is revealed and available AND `_can_afford_any_major_improvement(state, p)`.

### `house_redevelopment`

Legal if the space is revealed and available AND `_can_renovate(p)`.

The optional major improvement purchase after renovating does not affect legality of the placement.

### `cultivation`

Legal if the space is revealed and available AND at least one of:
- `_can_plow(p)`
- `_can_sow(p)`

### `farm_redevelopment`

Legal if the space is revealed and available AND `_can_renovate(p)`.

Fencing is the "and afterward" optional part of this space — it is not required to complete the action and does not affect legality of the placement. Resolution of the optional fencing step is deferred to the fence task.

### `fencing`

**Deferred.** Requires fence enumeration. Does not appear in `legal_placements` output.

### `lessons`

Always illegal in the Family game. Omit from the dispatch table entirely.

---

## Public API

Extend or replace `legal_atomic_placements` with a unified `legal_placements(state) -> list[PlaceWorker]` that covers all in-scope spaces. The existing atomic spaces must continue to work identically.

The function returns an empty list immediately if `state.players[state.current_player].people_home < 1`.

Maintain the existing dispatch table pattern. A clean approach is two dicts (`ATOMIC_LEGALITY` as before, `NON_ATOMIC_LEGALITY` for the new spaces) merged at call time, or a single combined `ALL_LEGALITY` dict — implementer's choice, but keep it readable.

---

## Tests

Add `tests/test_legality_non_atomic.py`. Same patterns as `test_legality_atomic.py`: construct states via `setup(seed=0)` plus `dataclasses.replace`, call `legal_placements`, assert presence or absence of specific `PlaceWorker` actions. Test the helper functions directly where noted (call the helper, not `legal_placements`).

All expected values derived by hand from the rules.

### Shared helper tests (call the helper directly)

- `test_can_bake_bread_with_fireplace_and_grain` — player owns Fireplace (index 0), has 1 grain → True
- `test_can_bake_bread_no_improvement` — no baking improvement → False
- `test_can_bake_bread_no_grain` — owns improvement, 0 grain → False
- `test_can_sow_grain_on_empty_field` — has 1 grain, one empty field cell → True
- `test_can_sow_no_empty_field` — field exists but all field cells are planted → False
- `test_can_sow_no_seeds` — empty field exists, no grain or veg in supply → False
- `test_can_plow_first_field` — no existing fields, at least one empty non-enclosed cell → True
- `test_can_plow_adjacent` — field at (0,0), empty cell at (0,1) → True
- `test_can_plow_no_adjacent` — field at (0,0), all adjacent cells occupied → False
- `test_can_plow_excludes_enclosed_cell` — fields already exist; the only EMPTY cell is enclosed by fences (a single-cell pasture); without the enclosed-cell filter the helper would incorrectly return True → must return False (exercises the subsequent-plow branch)
- `test_can_plow_first_field_excludes_enclosed_cells` — no fields exist; the 9 non-pasture cells are all ROOMs and the 6 EMPTY cells are all inside a 3×2 pasture; the first-field branch must return False (Agricola has no fixed room cap — see RULES.md §House and Rooms — so a 9-room layout is a valid test state)
- `test_has_stable_placement_legal` — empty cell exists, stables in supply → True
- `test_has_stable_placement_no_supply` — all 4 stables already built → False
- `test_has_stable_placement_no_empty_cell` — all cells occupied by tiles → False
- `test_can_afford_room_legal` — wood house, 5 wood + 2 reed → True
- `test_can_afford_room_insufficient` — wood house, 4 wood → False
- `test_has_room_placement_legal` — fresh farmyard, two starting rooms, adjacent empty cell exists → True
- `test_has_room_placement_no_adjacent_empty` — every cell adjacent to a room is occupied → False
- `test_has_room_placement_excludes_enclosed_cell` — every empty room-adjacent cell is inside a pasture → False
- `test_can_build_room_legal` — has 5 wood, 2 reed, adjacent empty cell → True
- `test_can_build_room_no_resources` — insufficient wood → False
- `test_can_build_room_no_adjacent_empty` — no empty cells adjacent to any room → False
- `test_can_renovate_wood_to_clay` — 2-room wood house, has 2 clay and 1 reed → True
- `test_can_renovate_already_stone` → False
- `test_can_renovate_insufficient_resources` — wood house, 0 clay → False
- `test_can_afford_major_improvement_basic` — clay ≥ 2, index 0 unowned → True
- `test_can_afford_major_improvement_return_fireplace` — owns Fireplace (index 0), Cooking Hearth (index 2) unowned, clay < 4 → True
- `test_can_afford_major_improvement_all_owned` — all 10 major improvements owned → False

### Per-space legal-when-conditions-met

- `test_farm_expansion_legal_can_build_room` — give player 5 wood and 2 reed
- `test_farm_expansion_legal_can_build_stable` — give player 2 wood, empty cell available
- `test_farmland_legal` — at setup, player has no fields → any empty cell is valid
- `test_side_job_legal_can_build_stable` — give player 1 wood, empty cell, stables in supply
- `test_side_job_legal_can_bake_bread` — give player Fireplace and 1 grain
- `test_grain_utilization_legal_can_sow` — reveal space, give player empty field and grain
- `test_grain_utilization_legal_can_bake_bread` — reveal space, give player Fireplace and grain
- `test_sheep_market_legal` — reveal space, set `accumulated_amount=1`
- `test_pig_market_legal` — reveal space, set `accumulated_amount=1`
- `test_cattle_market_legal` — reveal space, set `accumulated_amount=1`
- `test_major_improvement_legal` — reveal space, give player clay ≥ 2 (index 0 unowned)
- `test_house_redevelopment_legal` — reveal space, give player 2 clay and 1 reed (2-room wood house)
- `test_cultivation_legal_can_plow` — reveal space, no existing fields
- `test_cultivation_legal_can_sow` — reveal space, give player empty field and grain
- `test_farm_redevelopment_legal` — reveal space, give player 2 clay and 1 reed

### Per-space illegal-when-conditions-fail

- `test_farm_expansion_illegal_cannot_build_anything` — no wood, no reed, all 4 stables built
- `test_farmland_illegal_no_valid_cell` — all cells occupied by tiles, no empty cells
- `test_side_job_illegal_neither_option` — no wood and no baking improvement
- `test_grain_utilization_illegal_neither_option` — reveal space; no empty field and no baking improvement
- `test_sheep_market_illegal_zero_accumulation` — reveal space, `accumulated_amount=0`
- `test_pig_market_illegal_zero_accumulation`
- `test_cattle_market_illegal_zero_accumulation`
- `test_major_improvement_illegal_cannot_afford_any` — reveal space; player has 0 of everything
- `test_house_redevelopment_illegal_already_stone` — reveal space; stone house
- `test_farm_redevelopment_illegal_already_stone` — reveal space; stone house
- `test_cultivation_illegal_neither_option` — reveal space; no empty/adjacent cells for plow, no empty field or seeds for sow

### Cross-cutting

- `test_fencing_absent_from_legal_placements` — reveal space; `fencing` never appears in output
- `test_lessons_absent_from_legal_placements` — always absent

---

## Acceptance criteria

- All listed tests pass.
- All existing 110 tests still pass.
- `legal_placements` returns correct results for all newly-covered non-atomic spaces.
- `fencing` and `lessons` never appear in results.
- `farm_redevelopment` appears when and only when `_can_renovate` returns True.
- The wood cost for stables is checked per-space (not inside `_has_stable_placement`).
- Shared helper functions are tested directly, not only indirectly through `legal_placements`.
- No state is mutated; all helpers are pure reads of their inputs.
