# AgricolaBot — Architecture Reference

> **Note:** This file is the durable architecture spec and game rules reference. It is **not** auto-read by Claude Code. The auto-read file is `CLAUDE.md`. When this file's dataclass definitions or field names differ from the actual code, the code and `CHANGES.md`/`CLEANUP.md` take precedence — inline `> **Note:**` annotations throughout this file flag known divergences.

## Project Overview

We are building an Agricola board game AI from scratch in Python. The long-term goal is a strong self-play agent using MCTS and reinforcement learning. We are starting with the **2-player Family game** (no occupation or minor improvement hand cards), which is a simplified variant of the full game that lets us validate the complete engine pipeline before adding cards.

The immediate task is: **write the state dataclasses and the `setup(seed)` initialization function**.

---

## Directory Structure

All code lives under `Desktop/Agricola/AgricolaBot/`.

```
AgricolaBot/
    agricola/
        __init__.py
        constants.py       # enums, action space IDs, major improvement IDs
        state.py           # all frozen dataclasses for game state
        setup.py           # setup(num_players, seed) -> GameState
    tests/
        test_state.py      # tests for state validity and setup correctness
    INSTRUCTIONS.md        # this file
```

---

## Architecture Decisions

These are firm decisions. Do not deviate.

1. **Immutable frozen dataclasses.** All state objects use `@dataclass(frozen=True)`. State is never mutated — transitions produce new state objects. This enables safe structural sharing for MCTS.

2. **Functional core.** Game logic lives in plain functions: `step(state, action) -> GameState`, `legal_actions(state) -> list`, `score(state, player) -> int`. No methods on state objects that modify state.

3. **Nested state structure.** `GameState` contains two `PlayerState` objects and one `BoardState`. Do not flatten everything into one giant dataclass.

4. **Determinism via seeded RNG.** All randomness (starting player determination, action card ordering within stages) is resolved in `setup(seed)`. After `setup` returns, the engine is deterministic.

5. **Dicts inside frozen dataclasses are permitted** but must be treated as immutable throughout — never mutate them after creation. True immutability enforcement (e.g. `MappingProxyType`) can be added later.

6. **Pastures are derived, not stored.** The ground truth for fencing is the two fence arrays. A helper function `compute_pastures(farmyard) -> list[Pasture]` derives pasture information when needed. Do not store pasture state. *(Superseded by CHANGES.md Change 2: `Farmyard` now caches `pastures: tuple[Pasture, ...]` as a derived-but-stored field, auto-filled by `__post_init__` from the fence arrays + grid. The cache is the single accepted exception to this principle. Public access is via `farmyard.pastures` (O(1)); the BFS algorithm now lives at `agricola.pasture.compute_pastures_from_arrays` and is treated as an implementation detail.)* *(Further updated by CHANGES.md Change 3: the cache is still on `Farmyard` and `farmyard.pastures` is still the public access pattern, but the auto-fill `__post_init__` was disabled. Pasture-changing resolvers now recompute and pass `pastures=compute_pastures_from_arrays(...)` explicitly when constructing a new `Farmyard`; all other mutations leave `pastures` alone via `dataclasses.replace`. See CHANGES.md Change 3 for the full rationale.)*

---

## Enums and Constants (`constants.py`)

> **Note:** The `ACCUMULATION_RATES` dict shown below was subsequently split into `BUILDING_ACCUMULATION_RATES: dict[str, Resources]` (for the 5 building-resource spaces) and `FOOD_ANIMAL_ACCUMULATION_RATES: dict[str, tuple]` (for food/animal spaces). Two convenience sets `ACCUMULATION_SPACES` and `PERMANENT_ACTION_SPACES_SET` were also added. See CHANGES.md Change 1 and TASK_4a_i.md.

```python
from enum import Enum, auto

class Phase(Enum):
    WORK = auto()
    RETURN_HOME = auto()
    HARVEST_FIELD = auto()
    HARVEST_FEED = auto()
    HARVEST_BREED = auto()

class HouseMaterial(Enum):
    WOOD = auto()
    CLAY = auto()
    STONE = auto()

class CellType(Enum):
    EMPTY = auto()
    ROOM = auto()
    FIELD = auto()
    STABLE = auto()

# Action space IDs (strings used as dict keys in BoardState)
# Permanent spaces (always available):
PERMANENT_ACTION_SPACES = [
    "farm_expansion",       # Build Rooms and/or Build Stables
    "meeting_place",        # Become SP + food accumulation (Family game)
    "grain_seeds",          # Get 1 Grain
    "farmland",             # Plow 1 Field
    "lessons",              # Play Occupation (unusable in Family game, but space exists)
    "day_laborer",          # Get 2 Food
    "forest",               # Accum: +3 Wood/round
    "clay_pit",             # Accum: +1 Clay/round
    "reed_bank",            # Accum: +1 Reed/round
    "fishing",              # Accum: +1 Food/round
    "side_job",             # Build 1 Stable (1 wood) and/or Bake Bread (Family game addition)
]

# Stage card IDs grouped by stage (order within each stage is randomised at setup):
STAGE_CARDS = {
    1: ["major_improvement", "fencing", "grain_utilization", "sheep_market"],
    2: ["basic_wish_for_children", "house_redevelopment", "western_quarry"],
    3: ["vegetable_seeds", "pig_market"],
    4: ["cattle_market", "eastern_quarry"],
    5: ["urgent_wish_for_children", "cultivation"],
    6: ["farm_redevelopment"],
}

# Major improvement indices (0-based, length 10):
# 0: Fireplace (2 clay)
# 1: Fireplace (3 clay)
# 2: Cooking Hearth (4 clay, or return a Fireplace)
# 3: Cooking Hearth (5 clay, or return a Fireplace)
# 4: Well (3 stone + 1 wood)
# 5: Clay Oven (3 clay + 1 stone)
# 6: Stone Oven (1 clay + 3 stone)
# 7: Joinery (2 wood + 2 stone)
# 8: Pottery (2 clay + 2 stone)
# 9: Basketmaker's Workshop (2 reed + 2 stone)
NUM_MAJOR_IMPROVEMENTS = 10

# Accumulation rates per round for each accumulating space:
ACCUMULATION_RATES = {
    "forest":         ("wood",  3),
    "clay_pit":       ("clay",  1),
    "reed_bank":      ("reed",  1),
    "fishing":        ("food",  1),
    "meeting_place":  ("food",  1),   # Family game only
    "sheep_market":   ("sheep", 1),
    "western_quarry": ("stone", 1),
    "pig_market":     ("boar",  1),
    "cattle_market":  ("cattle",1),
    "eastern_quarry": ("stone", 1),
}

HARVEST_ROUNDS = {4, 7, 9, 11, 13, 14}
NUM_ROUNDS = 14
```

---

## State Dataclasses (`state.py`)

### Resources and Animals

> **Note:** `Resources` and `Animals` were subsequently extracted from `state.py` into `agricola/resources.py`. `Resources.__add__` and `Resources.__bool__` were also added. See CHANGES.md Change 1.

```python
@dataclass(frozen=True)
class Resources:
    wood:  int = 0
    clay:  int = 0
    reed:  int = 0
    stone: int = 0
    food:  int = 0
    grain: int = 0
    veg:   int = 0

@dataclass(frozen=True)
class Animals:
    sheep: int = 0
    boar:  int = 0
    cattle: int = 0
```

### Cell

Each cell on the 3×5 farmyard grid. Rows 0–2 (0 = top), Columns 0–4 (0 = left).

> **Note:** `house_material` was subsequently removed from `Cell` and moved to `PlayerState` as a single `house_material: HouseMaterial` field. See CLEANUP.md Cleanup 1.

```python
@dataclass(frozen=True)
class Cell:
    cell_type:      CellType = CellType.EMPTY
    house_material: Optional[HouseMaterial] = None  # populated iff cell_type == ROOM  [REMOVED — see note above]
    grain:          int = 0   # populated iff cell_type == FIELD
    veg:            int = 0   # populated iff cell_type == FIELD
    # Note: a STABLE cell may also be enclosed by fences (derived from fence arrays)
```

### Farmyard

```python
@dataclass(frozen=True)
class Farmyard:
    # 3 rows × 5 columns of Cell objects
    grid: tuple  # tuple[tuple[Cell, ...], ...], shape (3, 5)

    # Fence encoding — two arrays, no redundancy:
    # horizontal_fences[r][c]: fence running east–west between row r-1 and row r at column c
    #   r=0: top boundary of farmyard
    #   r=3: bottom boundary of farmyard
    #   shape: (4, 5) — 4 rows of horizontal edges × 5 columns
    horizontal_fences: tuple  # tuple[tuple[bool, ...], ...], shape (4, 5)

    # vertical_fences[r][c]: fence running north–south between column c-1 and column c at row r
    #   c=0: left boundary of farmyard
    #   c=5: right boundary of farmyard
    #   shape: (3, 6) — 3 rows × 6 columns of vertical edges
    vertical_fences: tuple  # tuple[tuple[bool, ...], ...], shape (3, 6)
```

**Fence rules:**
- A True value in either array means a fence piece from the player's supply is placed there.
- `fences_in_supply = 15 - sum(True values across both arrays)`
- All 4 sides of a cell require explicit fence pieces (the farmyard board edge does NOT provide free fencing).
- A pasture is a connected region of cells fully enclosed by fences on all sides.
- Pasture data (which cells are enclosed, capacity, etc.) is **always derived** from the fence arrays — never stored directly.

### ActionSpaceState

> **Note:** This dataclass was subsequently changed in two ways:
> - `occupied_by` was replaced by `workers: tuple` (a `(player_0_count, player_1_count)` pair). See TASK_4a_i.md.
> - `accumulated_goods` was renamed to `accumulated_amount` and an `accumulated: Resources` field was added alongside it for building-resource spaces. See CLEANUP.md Cleanup 2 and CHANGES.md Change 1.

```python
@dataclass(frozen=True)
class ActionSpaceState:
    occupied_by:       Optional[int]  # None, 0, or 1  [REPLACED by workers: tuple — see note above]
    accumulated_goods: int = 0        # current goods on this space  [RENAMED to accumulated_amount; accumulated: Resources also added — see note above]
    round_revealed:    int = 0        # 0 = always available; 1–14 = the round this card appears
```

### PlayerState

> **Note:** Two fields were subsequently added: `house_material: HouseMaterial = HouseMaterial.WOOD` (moved from `Cell` — see CLEANUP.md Cleanup 1) and `newborns: int = 0` (see TASK_4a_i.md).

```python
@dataclass(frozen=True)
class PlayerState:
    resources:    Resources
    animals:      Animals
    farmyard:     Farmyard
    house_material: HouseMaterial  # [ADDED — moved from Cell; see note above]
    people_total: int  # total people in play (home + placed), range 2–5
    people_home:  int  # people currently at home (available to place this round)
    newborns:     int = 0  # [ADDED — see note above]
    begging_markers: int = 0

    # Goods promised at the start of each future round (from Well, etc.)
    # Indexed 0–13 corresponding to rounds 1–14.
    # In Family game, only food can be promised (from the Well major improvement).
    future_food: tuple = (0,) * 14  # tuple[int, ...], length 14
```

### BoardState

```python
@dataclass(frozen=True)
class BoardState:
    # Maps action_space_id (str) -> ActionSpaceState for all 25 spaces.
    # Treat as immutable — never mutate this dict after creation.
    action_spaces: dict  # dict[str, ActionSpaceState]

    # Who owns each of the 10 major improvements (None = still on supply board).
    # Indexed by major improvement index 0–9 (see constants.py).
    major_improvement_owners: tuple  # tuple[Optional[int], ...], length 10

    # The action space card that appears at each round 1–14.
    # round_card_order[i] is the action space ID appearing at round i+1.
    # Determined randomly at setup (randomised within each stage).
    round_card_order: tuple  # tuple[str, ...], length 14
```

### GameState

> **Note:** `next_starting_player: int` was added in TASK_4a_i.md and subsequently removed as redundant. See CLEANUP.md Cleanup 3.

```python
@dataclass(frozen=True)
class GameState:
    round_number:    int    # 1–14
    phase:           Phase
    current_player:  int    # 0 or 1 — whose turn it is during WORK phase
    starting_player: int    # 0 or 1 — who holds the starting player token
    players:         tuple  # tuple[PlayerState, PlayerState]
    board:           BoardState
```

---

## Setup Function (`setup.py`)

`setup(seed: int) -> GameState`

### What setup must do:

1. **Determine starting player** randomly (0 or 1). Starting player gets **2 food**; other player gets **3 food**.

2. **Initialise each player's farmyard.** Starting rooms at cells **(1, 0) and (2, 0)** (row 1 and row 2, column 0 — bottom-left of the 3×5 grid). Both rooms are `CellType.ROOM`. All other cells are `CellType.EMPTY`. All fences False. `house_material = HouseMaterial.WOOD` is set on `PlayerState`, not on each `Cell` — see CLEANUP.md Cleanup 1.

3. **Each player starts with:** 2 people on the farmyard (`people_total=2`), both at home (`people_home=2`), no animals, no begging markers, no future food promised.

4. **Determine round card order.** For each stage, shuffle the cards within that stage (using the seeded RNG). Concatenate all stages in order to produce `round_card_order` (length 14). The card at position `i` appears at round `i+1`.

5. **Initialise action spaces.** All 25 action spaces start with `workers=(0, 0)` (previously `occupied_by=None` — see TASK_4a_i.md). Permanent spaces have `round_revealed=0`. Stage cards have `round_revealed` = the round they are assigned to (from `round_card_order`). **Starting accumulated goods** for round 1: building-resource spaces (`forest`, `clay_pit`, `reed_bank`, `western_quarry`, `eastern_quarry`) are pre-loaded via `accumulated: Resources`; food/animal spaces (`fishing`, `meeting_place`, etc.) via `accumulated_amount: int`. See CHANGES.md Change 1.

6. **All 10 major improvements start on the supply board** (`major_improvement_owners = (None,) * 10`).

7. **Starting phase is WORK** (the preparation phase for round 1 has already been handled by setup). `current_player = starting_player`.

### RNG:

Use `numpy.random.default_rng(seed)`. Pass the rng object explicitly to any sub-function that needs it. Do not use `random` or any global state.

---

## Game Rules Reference

### Farmyard

- Grid is 3 rows × 5 columns = 15 cells. Row 0 = top, column 0 = left.
- Starting rooms occupy cells (1,0) and (2,0).
- A cell can hold: EMPTY, ROOM (with material), FIELD (with crops), or STABLE.
- A STABLE cell may be enclosed in a pasture (derived from fences) or standalone.
- **Used cell:** has a tile or stable on it, or is enclosed by fences.
- **Unused cell:** empty or has only goods on it.
- Rooms must be orthogonally adjacent to an existing room when built.
- Fields must be orthogonally adjacent to an existing field when plowed (first field can go anywhere).
- Stables have no adjacency requirement.

### House

- Starts as WOOD. Can renovate to CLAY (costs 1 clay/room + 1 reed), then to STONE (costs 1 stone/room + 1 reed).
- Must renovate ALL rooms at once.
- Room costs: WOOD room = 5 wood + 2 reed; CLAY room = 5 clay + 2 reed; STONE room = 5 stone + 2 reed.
- Each room holds 1 person. House capacity = number of rooms (plus 1 pet animal can be kept in the house).

### People

- Start with 2 people (both in the house). Up to 5 maximum.
- `people_total` = all people in play (in house + placed on action spaces).
- `people_home` = people currently in their rooms (available to place).
- Newborns: placed on the Wish for Children action space alongside the parent. Count as `people_total` immediately. Cannot act the round they are born. Require 1 food at harvest if born this round, 2 food thereafter.

### Animals

- Stored as **totals** in `Animals`. Location is not tracked.
- **Capacity check** is required when gaining animals: total animals of a type must fit across available pastures.
- **Animal capacity formula:** `2 × num_cells_in_pasture × (2 ^ num_stables_in_pasture)`
- A standalone unfenced stable holds exactly 1 animal of any type.
- The house holds exactly 1 animal (pet) of any type.
- Animals of different types must be in different pastures (one type per pasture).
- Animals can be rearranged freely at any time.
- During the **breeding phase** only: cannot convert animals to food. Breeding requires ≥2 of a type AND room for the newborn.

### Stables

- Each player has 4 stables total.
- `Farm Expansion` action: build any number of stables at 2 wood each.
- `Side Job` action: build exactly 1 stable at 1 wood.
- Various card effects: other costs (not relevant in Family game).
- Maximum 1 stable per cell. Cell must not have a tile on it.
- `stables_built` is derived: count cells with `cell_type == STABLE`.
- `stables_in_supply = 4 - stables_built`.

### Fences

- Each player has 15 fences total.
- Each fence piece costs 1 wood (on the Fencing action space).
- `fences_in_supply = 15 - count_of_True_values_in_both_fence_arrays`.
- A fence action must result in at least one fully enclosed pasture (new or subdivided).
- After building, fences cannot be removed.
- New pastures must be adjacent to an existing pasture (except the very first pasture).

### Crops

- Sowing: place 1 grain from supply on an empty field → add 2 more from general supply (total: 3 grain in field). OR place 1 veg from supply → add 1 more from general supply (total: 2 veg in field).
- Harvesting: take exactly 1 crop from each field during the field phase. Place it in supply.
- Cannot sow grain just received from Grain Seeds in the same action.

### Harvest (rounds 4, 7, 9, 11, 13, 14)

Three phases in order:

1. **Field phase:** Take 1 crop from each planted field → supply.
2. **Feeding phase:** Each adult requires 2 food; newborns born this round require 1 food. Grain and vegetables in supply count as 1 food each. If short, take 1 begging marker per missing food. In Family game, with Major Improvements: player may convert animals/vegetables to food using a Fireplace or Cooking Hearth before declaring begging.
3. **Breeding phase:** For each animal type where `count ≥ 2` AND capacity exists for one more, add 1 animal of that type. Cannot convert animals to food during this phase.

### Action Spaces

**Permanent (always available):**
| ID | Effect |
|---|---|
| `farm_expansion` | Build Rooms (5 wood/clay/stone + 2 reed each) **and/or** Build Stables (2 wood each, Farm Expansion cost) |
| `meeting_place` | Become starting player (mandatory) + collect accumulated food + optionally play Minor Improvement (none in Family game) |
| `grain_seeds` | Get 1 grain |
| `farmland` | Plow 1 field |
| `lessons` | Play 1 occupation (unusable in Family game — no occupation cards) |
| `day_laborer` | Get 2 food |
| `forest` | Take all wood (accumulates +3/round) |
| `clay_pit` | Take all clay (accumulates +1/round) |
| `reed_bank` | Take all reed (accumulates +1/round) |
| `fishing` | Take all food (accumulates +1/round) |
| `side_job` | Build exactly 1 stable (1 wood) **and/or** Bake Bread |

**Stage cards (appear at a random round within their stage):**
| ID | Stage | Effect |
|---|---|---|
| `major_improvement` | 1 | Build 1 Major Improvement or play Minor Improvement |
| `fencing` | 1 | Build Fences (1 wood/fence, must create ≥1 enclosed pasture) |
| `grain_utilization` | 1 | Sow **and/or** Bake Bread |
| `sheep_market` | 1 | Take all sheep (accumulates +1/round) |
| `basic_wish_for_children` | 2 | Family Growth (need more rooms than people) + optional Minor Improvement |
| `house_redevelopment` | 2 | Renovate **then** optionally Major or Minor Improvement |
| `western_quarry` | 2 | Take all stone (accumulates +1/round) |
| `vegetable_seeds` | 3 | Get 1 vegetable |
| `pig_market` | 3 | Take all wild boar (accumulates +1/round) |
| `cattle_market` | 4 | Take all cattle (accumulates +1/round) |
| `eastern_quarry` | 4 | Take all stone (accumulates +1/round) |
| `urgent_wish_for_children` | 5 | Family Growth Even Without Room |
| `cultivation` | 5 | Plow 1 Field **and/or** Sow |
| `farm_redevelopment` | 6 | Renovate **then** Build Fences |

### Major Improvements (Family Game — all 10 available)

| Index | Name | Cost | Effect summary |
|---|---|---|---|
| 0 | Fireplace | 2 clay | Convert veg/animals/grain (bake) to food at any time |
| 1 | Fireplace | 3 clay | Same as above |
| 2 | Cooking Hearth | 4 clay (or return Fireplace) | Better conversion rates than Fireplace |
| 3 | Cooking Hearth | 5 clay (or return Fireplace) | Same as above |
| 4 | Well | 3 stone + 1 wood | Places 1 food on each of next 5 round spaces → owner's `future_food` |
| 5 | Clay Oven | 3 clay + 1 stone | Bake exactly 1 grain → 5 food |
| 6 | Stone Oven | 1 clay + 3 stone | Bake up to 2 grain → 4 food each |
| 7 | Joinery | 2 wood + 2 stone | Harvest: convert 1 wood → 2 food; scoring bonus |
| 8 | Pottery | 2 clay + 2 stone | Harvest: convert 1 clay → 2 food; scoring bonus |
| 9 | Basketmaker's | 2 reed + 2 stone | Harvest: convert 1 reed → 3 food; scoring bonus |

A player can build a major improvement when using the `major_improvement` or `house_redevelopment` action space (or `meeting_place` for minor, but that's N/A in Family game).

### Scoring Categories

| Category | Points |
|---|---|
| Field tiles | 0–1: −1 pt; 2: 1 pt; 3: 2 pts; 4: 3 pts; 5+: 4 pts |
| Pastures | 0: −1 pt; 1–4: 1 pt each; max 4 pts |
| Grain (supply + fields) | 0: −1 pt; 1–3: 1 pt; 4–5: 2 pts; 6–7: 3 pts; 8+: 4 pts |
| Vegetables (supply + fields) | 0: −1 pt; 1–4: 1 pt each; max 4 pts |
| Sheep | 0: −1 pt; 1–3: 1 pt; 4–5: 2 pts; 6–7: 3 pts; 8+: 4 pts |
| Wild Boar | 0: −1 pt; 1–2: 1 pt; 3–4: 2 pts; 5–6: 3 pts; 7+: 4 pts |
| Cattle | 0: −1 pt; 1: 1 pt; 2–3: 2 pts; 4–5: 3 pts; 6+: 4 pts |
| Unused farmyard spaces | −1 pt each |
| Fenced stables | 1 pt each (max 4) |
| Clay rooms | 1 pt each |
| Stone rooms | 2 pts each |
| Family members | 3 pts each |
| Begging markers | −3 pts each |
| Major improvement card points | printed on card (see above) |
| Bonus points | from major improvement end-game bonuses |

**Tiebreaker:** most building resources (wood + clay + reed + stone) remaining in personal supply after subtracting any resources spent on craft building bonuses (Joinery, Pottery, Basketmaker's).

---

## Family Game Configuration

- **Hand cards:** none (no occupation or minor improvement cards dealt to players)
- **Major Improvements:** all 10 available on the supply board ✓
- **Side Job tile:** always available as a permanent action space ✓
- **Meeting Place:** accumulates 1 food per round; player who uses it collects the food ✓
- **2-player additional tile** (Copse / Resource Market / Animal Market / Modest Wish for Children): **excluded** ✗
- **Lessons action space:** exists on board but is never a legal action (no occupation cards)

---

## Current Task: State Dataclasses + Setup

### Files to create:

1. `agricola/__init__.py` — empty
2. `agricola/constants.py` — all enums and constants from this document
3. `agricola/state.py` — all frozen dataclasses: `Resources`, `Animals`, `Cell`, `Farmyard`, `ActionSpaceState`, `PlayerState`, `BoardState`, `GameState`
4. `agricola/setup.py` — `setup(seed: int) -> GameState`
5. `tests/__init__.py` — empty
6. `tests/test_state.py` — tests (see below)

### Tests to write (`test_state.py`):

- `test_setup_starting_food`: player 0 and 1 have correct starting food (2 and 3 or 3 and 2 depending on who is starting player)
- `test_setup_starting_rooms`: cells (1,0) and (2,0) are ROOM/WOOD; all others EMPTY
- `test_setup_no_fences`: all fence values are False
- `test_setup_people`: each player has `people_total=2`, `people_home=2`
- `test_setup_major_improvements_available`: all 10 owners are None
- `test_setup_round_card_count`: `round_card_order` has length 14, contains each of the 14 stage card IDs exactly once
- `test_setup_stage_ordering`: stage 1 cards appear in rounds 1–4, stage 2 in rounds 5–7, etc.
- `test_setup_deterministic`: same seed → identical GameState
- `test_setup_different_seeds`: different seeds → different starting players or different card order
- `test_fences_in_supply_derivation`: a fresh farmyard has `fences_in_supply == 15` (derived from fence arrays)
- `test_stables_in_supply_derivation`: a fresh farmyard has `stables_built == 0`

### What NOT to implement yet:

- `step(state, action)` — deferred
- `legal_actions(state)` — deferred
- `score(state, player)` — deferred
- `compute_pastures(farmyard)` — deferred (but stub it with a TODO comment) *(later implemented in Task 2; subsequently relocated and renamed in CHANGES.md Change 2 — see that entry for the current API.)*
- Any game loop, Environment wrapper, or agent — deferred
- Any card effects beyond what's already in the state structure — deferred

---

## Open Questions / TODOs

- **Sub-action context:** When the game loop is implemented, `GameState` may need a `pending_decision` field to track where in a multi-step action the agent is. Leave a TODO comment in `GameState` for this field.
- **Animal location:** Currently tracking totals only. A few full-game cards reference specific animal locations. This is acceptable for Family game. Note as a TODO.
- **Fence canonicalisation:** The `enumerate_valid_fence_actions` function (deferred) will need a canonical list of fence configurations. Document this as a TODO in `setup.py` or a separate `fencing.py`.
- **Lessons action space:** Exists in the state but is never legal in Family game. When full game is added, this becomes legal once the player has occupation cards.
