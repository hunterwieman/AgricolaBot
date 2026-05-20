# Python File Descriptions

Detailed per-file descriptions of every Python module and test-infrastructure file in the codebase. Offloaded from CLAUDE.md to reduce session-start context — the enriched Directory Structure in CLAUDE.md gives 1-2 sentence summaries; this file is the deeper reference.

For per-file test coverage (`tests/test_*.py`), see **`TEST_DESCRIPTIONS.md`**.

---

### `agricola/__init__.py`

Empty package marker. Makes `agricola` importable as a Python package. No code here.

---

### `agricola/resources.py`

Defines two small data containers that hold quantities of things:

- **`Resources`** — holds counts of the seven goods a player can have in their personal supply: `wood`, `clay`, `reed`, `stone`, `food`, `grain`, `veg`. Supports addition (`r1 + r2`), subtraction (`r1 - r2`), and truthiness (`bool(r)` is `True` if any field is nonzero). All three operators return new instances; nothing mutates. Subtraction is used at pure-subtraction cost-debit sites (e.g. `p.resources - cost`); mixed subtract-and-add operations stay in the `r + Resources(field=-x, ...)` form (see CLAUDE.md "Code Conventions" → "Resource arithmetic").

- **`Animals`** — holds counts of the three animal types: `sheep`, `boar`, `cattle`.

Both are frozen dataclasses (immutable). They were originally in `state.py` but were extracted here so that `constants.py` could import them without creating a circular import.

---

### `agricola/constants.py`

All the named enumerations and lookup tables the engine uses. Nothing in here is computed at runtime — it is all fixed game data.

- **`Phase`** enum — the seven phases a `GameState` can be in: `WORK`, `RETURN_HOME`, `PREPARATION`, `HARVEST_FIELD`, `HARVEST_FEED`, `HARVEST_BREED`, `BEFORE_SCORING`. (`PREPARATION` and `BEFORE_SCORING` added in Task 5; harvest phases remain unused until the harvest task.)
- **`HouseMaterial`** enum — `WOOD`, `CLAY`, `STONE`.
- **`CellType`** enum — `EMPTY`, `ROOM`, `FIELD`, `STABLE`.
- **`PERMANENT_ACTION_SPACES`** — ordered list of the 11 action space IDs that are always on the board.
- **`STAGE_CARDS`** — dict mapping stage number (1–6) to the list of action space IDs that appear in that stage (in random order within the stage).
- **`BUILDING_ACCUMULATION_RATES`** — maps the 5 building-resource accumulation space IDs (`forest`, `clay_pit`, etc.) to a `Resources` object representing how much accumulates per round. Using `Resources` objects here (rather than plain integers) is what allows cards like the Geologist occupation to change what accumulates on a space without special-casing in resolution.
- **`FOOD_ANIMAL_ACCUMULATION_RATES`** — maps the 5 food/animal accumulation space IDs (`fishing`, `sheep_market`, etc.) to `(field_name, rate)` tuples. These use a plain integer scalar instead of a `Resources` object because they are never modified by cards in the same way.
- **`ACCUMULATION_SPACES`** — a frozenset of all 10 accumulation space IDs, derived as the union of the two dicts above.
- **`HARVEST_ROUNDS`**, **`NUM_ROUNDS`**, **`NUM_MAJOR_IMPROVEMENTS`** — numeric constants.
- **`STAGE_ROUNDS`** — convenience dict mapping stage number to its `(first_round, last_round)` inclusive, used in tests.
- **`MAJOR_IMPROVEMENT_COSTS`** — tuple of length 10, indexed by major_idx, giving each major improvement's standard cost as a `Resources` object. The Cooking Hearth alternate-payment path (return a Fireplace) is handled in resolution code, not encoded here.
- **`ROOM_COSTS`** — dict keyed by `HouseMaterial` (WOOD / CLAY / STONE) giving each material's per-room cost as a `Resources` object (5 of the material + 2 reed). Mirrors the `MAJOR_IMPROVEMENT_COSTS` shape. Used by both `_can_afford_room` in `legality.py` and `_choose_subaction_farm_expansion` in `resolution.py`.
- **`BAKING_IMPROVEMENT_SPECS`** — dict keyed by major_idx (0, 1, 2, 3, 5, 6) giving each baking improvement's per-action `(max_grain_per_action, food_per_grain)` tuple. `None` cap means "any amount" (Fireplace, Cooking Hearth). Used by the greedy-by-rate allocator in `_execute_bake` and the per-action grain-cap computation in `_enumerate_pending_bake_bread`.
- **`FIREPLACE_INDICES`**, **`COOKING_HEARTH_INDICES`** — tuples of the two indices for each cookware family. Used in legality predicates for Cooking Hearth's alternate payment (return a Fireplace).
- **`BAKING_IMPROVEMENTS`** — frozenset of all major-improvement indices that grant a Bake Bread capability. Derived from `BAKING_IMPROVEMENT_SPECS.keys()`. Previously lived in `legality.py`; migrated to `constants.py` in Change 5 for centralized constants.

---

### `agricola/pasture.py`

Small standalone module that owns the `Pasture` dataclass and the BFS that turns raw `(grid, horizontal_fences, vertical_fences)` arrays into a tuple of `Pasture` objects.

- **`Pasture`** — frozen dataclass with three fields: `cells: frozenset[(row, col)]` (the cells that make up this pasture), `num_stables: int` (stables inside the pasture), and `capacity: int` (precomputed as `2 × num_cells × (2 ** num_stables)`).
- **`compute_pastures_from_arrays(grid, horizontal_fences, vertical_fences) -> tuple[Pasture, ...]`** — the public function. Implements the flood-fill from outside the grid, identifies enclosed connected components, and packages each as a `Pasture`. Returns the tuple sorted canonically by `min(p.cells)` (lexicographic on `(row, col)`) so equivalent farmyards always produce equal `pastures` tuples — required for `Farmyard.__eq__` and hashing across MCTS.
- **`_are_connected(horizontal_fences, vertical_fences, r1, c1, r2, c2)`** — private helper used by the BFS. Returns `True` if two orthogonally adjacent cells have no fence between them.

`pasture.py` imports only from `agricola.constants` (for `CellType`) and reads `grid[r][c].cell_type` via duck typing rather than importing `Cell` — a deliberate module-layering choice that keeps `pasture.py` independent of `state.py`.

---

### `agricola/state.py`

All the frozen dataclasses that together represent a complete snapshot of a game in progress. Nothing is ever mutated; all transitions use `dataclasses.replace(...)` to produce new objects.

- **`Cell`** — one cell of a player's 3×5 farmyard grid. Stores the cell type (`EMPTY`, `ROOM`, `FIELD`, `STABLE`) and any grain/veg counts if it is a field. House material is stored on `PlayerState`, not on `Cell` (see CLEANUP.md Cleanup 1).

- **`Farmyard`** — the complete farmyard for one player. Contains the 3×5 `grid` of `Cell` objects (stored as a tuple of tuples), two fence arrays, and a cached `pastures: tuple[Pasture, ...]` decomposition. The two fence arrays are: `horizontal_fences` (shape 4×5, one bool per horizontal edge between rows) and `vertical_fences` (shape 3×6, one bool per vertical edge between columns). See `ARCHITECTURE.md` for the exact index conventions. The `pastures` cache is canonically ordered by `min(p.cells)` so equivalent farmyards always compare equal — required for `Farmyard.__eq__` and hashing across MCTS. The cache is maintained by caller discipline: the two pasture-changing effect functions — `_execute_build_stable` (used by Side Job and Farm Expansion via `CommitBuildStable`) and `_execute_build_pasture` (used by Fencing and Farm Redevelopment via `CommitBuildPasture`) — construct the new `Farmyard` with an explicit `pastures=compute_pastures_from_arrays(new_grid, new_h, new_v)` kwarg. All other `Farmyard` mutations use `dataclasses.replace(farmyard, ...)` and leave `pastures` alone, which is correct because these mutations cannot change pastures. A fresh `Farmyard` constructed without any fences or stables (e.g. by `setup`) correctly has `pastures=()` via the placeholder default. This is the first accepted exception to "Derived data, not cached data" — see CHANGES.md Change 2 (and CHANGES.md Change 3 for why auto-fill in `__post_init__`, the obvious structural alternative, is not used).

- **`ActionSpaceState`** — the state of one action space on the board. Tracks how many workers each player has placed on it (`workers`, a 2-tuple of ints), any accumulated building resources (`accumulated`, a `Resources` object — used for the 5 building-resource spaces), any accumulated food/animals (`accumulated_amount`, a plain int — used for the 5 food/animal spaces), and which round the space is first revealed (`round_revealed`, 0 for permanent spaces).

- **`PlayerState`** — everything about one player: their `Resources`, their `Animals`, their `Farmyard`, how many people they have in total and how many are currently at home, how many newborns were born during the current round (cleared by `_resolve_preparation` of the next round; if a harvest immediately follows, these newborns cost 1 food at that harvest instead of 2), begging markers, a `future_resources: tuple[Resources, ...]` of length 14 (per-round promised goods — populated by the Well major improvement when implemented), and frozensets `minor_improvements` and `occupations` recording played card IDs.

- **`BoardState`** — the shared board: a dict mapping action space ID strings to `ActionSpaceState` objects, a tuple recording who owns each of the 10 major improvements, and the `round_card_order` tuple (the randomly-ordered stage cards).

- **`GameState`** — the top-level snapshot. Holds the round number, phase, which player is currently acting (`current_player`: whose worker placement is currently being resolved), who holds the starting player token, the two `PlayerState` objects, the `BoardState`, and `pending_stack: tuple[PendingDecision, ...]` (the stack of in-progress sub-decisions). (A `next_starting_player` field was briefly present but removed as redundant — `starting_player` is updated immediately when Meeting Place is taken. See CLEANUP.md Cleanup 3.)

---

### `agricola/setup.py`

Contains the single public function `setup(seed: int) -> GameState`, which builds the initial game state for a 2-player Family game.

Internally it uses a seeded NumPy RNG (`numpy.random.default_rng(seed)`) to determine the starting player and shuffle the stage cards within each stage. All randomness is resolved here; after `setup` returns the engine is fully deterministic.

The private helpers inside this file are:
- `_make_round_card_order(rng)` — shuffles cards within each stage and concatenates them into a 14-element tuple.
- `_make_action_spaces(round_card_order)` — builds the initial `ActionSpaceState` for all 25 spaces, pre-loading round-1 accumulated goods onto the accumulation spaces.
- `_make_farmyard()` — builds a fresh farmyard with wood rooms at cells (1,0) and (2,0) and all fences False.
- `_make_player(food)` — builds a starting `PlayerState` with the given food amount, 2 people, and an empty farmyard.

---

### `agricola/helpers.py`

Pure functions for derived quantities and the animal accommodation logic. These are the computational workhorses that other modules call; none of them mutate state.

**Simple derived quantities:**
- `fences_in_supply(farmyard)` — counts True values in both fence arrays, subtracts from 15.
- `stables_in_supply(farmyard)` — counts `STABLE` cells, subtracts from 4.
- `cooking_rates(state, player_idx)` — returns a `(sheep_rate, boar_rate, cattle_rate)` tuple based on which cooking improvement the player owns. Cooking Hearth returns `(2, 3, 4)`, Fireplace returns `(2, 2, 3)`, neither returns `(0, 0, 0)`.

**Pasture-derived helpers:**

The `Pasture` dataclass and the BFS that builds the pasture decomposition live in `agricola/pasture.py`. The decomposition itself is cached on `Farmyard.pastures` (see the `Farmyard` description above for how the cache is maintained), so reading it is O(1). Helpers in `helpers.py` derive from that cache:

- `enclosed_cells(farmyard) -> frozenset[(row, col)]` — returns the union of all cells inside any pasture. Used by legality code that needs membership lookups (e.g. "can a field be placed at this cell?").

**Animal accommodation:**
- `extract_slots(player_state)` — returns `(pasture_capacities, num_flexible)`. Reads `player_state.farmyard.pastures` (the cached decomposition) and returns the list of pasture capacities plus the count of single-animal flexible slots (one per standalone (unfenced) stable, plus one always for the house pet).
- `can_accommodate(pasture_capacities, num_flexible, sheep, boar, cattle)` — checks whether a given animal count is physically accommodatable on the farm. Each pasture holds exactly one animal type. The algorithm tries all possible type-to-pasture assignments (brute force over the small number of pastures) and returns `True` if any assignment leaves no more overflow animals than there are flexible slots.
- `pareto_frontier(player_state, gained, rates)` — used when a player gains animals (e.g. takes the Sheep Market). Enumerates all achievable `(sheep, boar, cattle)` configurations (bounded by current inventory + gained, and by farm capacity), Pareto-filters over animal counts only, and returns a list of `(Animals, food_gained)` pairs. Food is the deterministic consequence of the chosen configuration and cooking rates — not a Pareto dimension; see CLAUDE.md "Preserving optionality" Key Design Principle. The agent picks one point from this frontier.
- `breeding_frontier(player_state, rates)` — same animal-counts-only Pareto logic as `pareto_frontier`, but for the breeding phase of harvest. The upper bound for each animal type is `current + 1` if the player has ≥ 2 (breeding fires), otherwise `current`. The food formula accounts for whether breeding fired when computing how many animals were consumed pre-breeding; the returned food value is the consequence of the chosen end-state, not a Pareto dimension.

---

### `agricola/actions.py`

Defines the action types the engine's `step` accepts. Every action is a frozen dataclass. Dispatched via `isinstance` checks in `engine._apply_action`.

- **`PlaceWorker(space: str)`** — place the active player's worker on a named action space. For atomic spaces this is the complete action. For non-atomic spaces this initiates the chain of sub-decisions.
- **`ChooseSubAction(name: str)`** — pick a sub-action category at a non-atomic space's pending decision. Categories are space-specific strings (e.g., `"sow"`, `"bake_bread"` at Grain Utilization).
- **`CommitSubAction`** — frozen-dataclass marker base for all `Commit*` sub-action types. Empty (no fields). Concrete subclasses inherit from it. All are dispatched uniformly by `_apply_commit_subaction` in `engine.py` via the `COMMIT_SUBACTION_HANDLERS` table (post-Task-5D: `CommitBuildMajor` was absorbed into the generic path with `auto_pop=False`).
- **`CommitSow(grain: int, veg: int)`** — commit a sow. Pops `PendingSow`.
- **`CommitBake(grain: int)`** — commit a Bake Bread with the chosen grain amount. Pops `PendingBakeBread`.
- **`CommitPlow(row: int, col: int)`** — commit a plow at the chosen cell. Pops `PendingPlow`.
- **`CommitBuildStable(row: int, col: int)`** — commit a stable build at the chosen cell. The cost paid is read from the host `PendingBuildStables.cost` field. Does NOT pop `PendingBuildStables` (multi-shot pattern, `auto_pop=False`); `Stop` pops it.
- **`CommitBuildRoom(row: int, col: int)`** — commit a room build at the chosen cell. The cost paid is read from the host `PendingBuildRooms.cost` field (set from `ROOM_COSTS[p.house_material]` at push time). Does NOT pop `PendingBuildRooms` (multi-shot pattern, `auto_pop=False`); `Stop` pops it.
- **`CommitBuildMajor(major_idx: int, return_fireplace_idx: int | None = None)`** — purchase a major improvement. For Cooking Hearth, `return_fireplace_idx` may be 0 or 1 to pay by returning that Fireplace. Dispatched via the generic commit dispatcher with `auto_pop=False`; the effect function owns the conditional stack manipulation (pop for non-ovens, push wrapper for Clay/Stone Oven).
- **`CommitRenovate()`** — commit a renovation (parameterless; the cost and material transition are derived from current state and `pending.cost`). Pops `PendingRenovate`.
- **`CommitAccommodate(sheep: int, boar: int, cattle: int)`** — commit the final animal configuration after taking from a market. Lands directly on `PendingSheepMarket` / `PendingPigMarket` / `PendingCattleMarket` (no separate sub-action pending). Dispatcher entry uses a tuple of pending types.
- **`CommitBuildPasture(cells: frozenset[tuple[int, int]])`** — commit one pasture build at `PendingBuildFences`. `cells` is the cell-set of the named pasture — must match an entry in the active fence universe (default `UNIVERSE_RESTRICTED`). `frozenset` provides content-based equality and hashing. Cost is NOT a field on this commit — it is computed as a pure function of `(state, commit.cells)` by `compute_new_fence_edges` in `fences.py` (the 4th sub-action cost-handling bucket). Dispatched via `auto_pop=False`; the effect function leaves `PendingBuildFences` on top with updated counters; `Stop` pops it.
- **`FireTrigger(card_id: str)`** — fire a specific card trigger that's currently eligible at the top pending.
- **`Stop()`** — end the current non-atomic action (pop the top pending frame). Legal at parent pendings once at least one sub-action has been chosen.
- **`Action`** — the union alias listing the concrete subclasses (`PlaceWorker | ChooseSubAction | CommitSow | CommitBake | CommitPlow | CommitBuildStable | CommitBuildRoom | CommitBuildMajor | CommitRenovate | CommitAccommodate | CommitBuildPasture | FireTrigger | Stop`). The `CommitSubAction` base is intentionally not in the union — concrete subclasses are listed so legality enumerators and type checkers see the real options. There is no `SkipTrigger`: declining a trigger is implicit.

---

### `agricola/pending.py`

Frozen pending-decision dataclasses *and* the stack operations on them. The stack itself lives on `GameState.pending_stack`; this module owns both the element types and the three pure functions for manipulating the stack. Imports `GameState` from `state.py` (no cycle: `state.py` stores `pending_stack: tuple` without parameterizing the type).

**Pending dataclasses.** Every pending class carries:
- `player_idx: int` — whose decision this frame is for.
- `initiated_by_id: str` (mandatory, no default) — what pushed this frame onto the stack. See CLAUDE.md "Pending provenance metadata".
- `PENDING_ID: ClassVar[str]` — the kind of pending (flow or event it represents).

**Sub-action pendings** host a single `CommitX` action; pushed by `ChooseSubAction` at a parent or by a card trigger; popped when the commit fires.

- **`PendingSow(player_idx, initiated_by_id)`** — `PENDING_ID = "sow"`. Pushed by `ChooseSubAction("sow")`. Pops on `CommitSow`.
- **`PendingBakeBread(player_idx, initiated_by_id, triggers_resolved=frozenset())`** — `PENDING_ID = "bake_bread"`, `TRIGGER_EVENT = "before_bake_bread"`. `triggers_resolved` is scoped to this frame's lifetime.
- **`PendingPlow(player_idx, initiated_by_id, triggers_resolved=frozenset())`** — `PENDING_ID = "plow"`, `TRIGGER_EVENT = "before_plow"`. Used by Farmland and Cultivation.
- **`PendingBuildStables(player_idx, initiated_by_id, cost, max_builds, num_built=0)`** — `PENDING_ID = "build_stables"`. Multi-shot pending: each `CommitBuildStable` increments `num_built` and leaves the pending on top (`auto_pop=False`); `Stop` is the explicit exit. `cost: Resources` is per-commit (1 wood for Side Job; 2 wood for Farm Expansion; future cards may inject other costs). `max_builds: int | None` is a caller-imposed cap (`None` = no cap; Side Job sets 1; Farm Expansion sets None). Supply/affordability/cell checks live in the enumerator. No card-trigger fields yet (`triggers_resolved` / `TRIGGER_EVENT` deferred until a card needs them). See CLAUDE.md "Sub-action cost handling" → bucket 2, and "Multi-shot sub-action pendings".
- **`PendingBuildRooms(player_idx, initiated_by_id, cost, max_builds, num_built=0)`** — `PENDING_ID = "build_rooms"`. Multi-shot pending mirroring `PendingBuildStables`. `cost: Resources` is set at push time from `ROOM_COSTS[p.house_material]`. Farm Expansion pushes with `max_builds=None`; future cards may set integer caps.
- **`PendingBuildMajor(player_idx, initiated_by_id, build_chosen=False, triggers_resolved=frozenset())`** — `PENDING_ID = "build_major"`, `TRIGGER_EVENT = "before_build_major"`. `build_chosen` is set by `_execute_build_major` and matters only for oven majors (Clay/Stone Oven), where `PendingBuildMajor` lingers below the oven wrapper while the optional free bake resolves. Cost is NOT on this pending — it's looked up in `MAJOR_IMPROVEMENT_COSTS` by `commit.major_idx`. See CLAUDE.md "Sub-action cost handling" → bucket 3.
- **`PendingRenovate(player_idx, initiated_by_id, cost, triggers_resolved=frozenset())`** — `PENDING_ID = "renovate"`, `TRIGGER_EVENT = "before_renovate"`. `cost: Resources` is set at push time by `_choose_subaction_house_redevelopment` based on current house material and room count.

**Parent pendings** host `ChooseSubAction` and (after a flag flips) `Stop`. Include both top-level pendings pushed by `PlaceWorker` and non-top-level wrapper pendings pushed by special-case commit handlers.

- **`PendingGrainUtilization(player_idx, initiated_by_id, sow_chosen=False, bake_chosen=False)`** — `PENDING_ID = "grain_utilization"`. Stop-legality requires `sow_chosen or bake_chosen`.
- **`PendingFarmExpansion(player_idx, initiated_by_id, room_chosen=False, stable_chosen=False)`** — `PENDING_ID = "farm_expansion"`. Stop-legality requires `room_chosen or stable_chosen`. Once-per-category: a player who chooses build_rooms, exits via Stop, and returns to the parent cannot re-enter build_rooms. No `triggers_resolved` / `TRIGGER_EVENT` yet (deferred until cards need them).
- **`PendingFarmland(player_idx, initiated_by_id, plow_chosen=False, triggers_resolved=frozenset())`** — `PENDING_ID = "farmland"`. Stop-legality requires `plow_chosen`.
- **`PendingCultivation(player_idx, initiated_by_id, plow_chosen=False, sow_chosen=False, triggers_resolved=frozenset())`** — `PENDING_ID = "cultivation"`. Stop-legality requires at least one of `plow_chosen`/`sow_chosen`.
- **`PendingSideJob(player_idx, initiated_by_id, stable_chosen=False, bake_chosen=False, triggers_resolved=frozenset())`** — `PENDING_ID = "side_job"`. Stop-legality requires at least one of `stable_chosen`/`bake_chosen`.
- **`PendingSheepMarket`, `PendingPigMarket`, `PendingCattleMarket(player_idx, initiated_by_id, gained, triggers_resolved=frozenset())`** — `PENDING_ID`s `"sheep_market"`, `"pig_market"`, `"cattle_market"`. The `gained: int` field stages animals taken from the market (not yet on the player) until `CommitAccommodate` finalizes the configuration. No ChooseSubAction; `CommitAccommodate` lands directly on the parent and pops it.
- **`PendingMajorMinorImprovement(player_idx, initiated_by_id, major_chosen=False, minor_chosen=False, triggers_resolved=frozenset())`** — `PENDING_ID = "major_minor_improvement"`. `minor_chosen` is forward-compat (no path to set it in Family scope).
- **`PendingHouseRedevelopment(player_idx, initiated_by_id, renovate_chosen=False, improvement_chosen=False, triggers_resolved=frozenset())`** — `PENDING_ID = "house_redevelopment"`. `Stop` is legal only after `renovate_chosen` is True (renovate is mandatory first).
- **`PendingClayOven(player_idx, initiated_by_id, bake_chosen=False)`** — non-top-level wrapper pending pushed by `_execute_build_major` when `major_idx == 5`. Hosts the optional free Bake Bread offered by Clay Oven purchase. No `TRIGGER_EVENT` — cards that trigger on oven-purchase-bake attach to the inner `PendingBakeBread`'s `"before_bake_bread"` event.
- **`PendingStoneOven(player_idx, initiated_by_id, bake_chosen=False)`** — mirror of `PendingClayOven` for Stone Oven (`major_idx == 6`).
- **`PendingFencing(player_idx, initiated_by_id, build_fences_chosen=False, triggers_resolved=frozenset())`** — `PENDING_ID = "fencing"`, `TRIGGER_EVENT = "before_fencing"`. Thin top-level parent above `PendingBuildFences`. The space has a single sub-action category (`build_fences`); the parent exists for two reasons: (1) `build_fences_chosen` gates Stop-legality (matches the uniform parent-pending pattern across non-atomic spaces), and (2) the parent hosts the space-specific `before_fencing` trigger event for future cards — distinct from `before_build_fences`, which fires at the sub-action layer whenever Build Fences is reached (via Fencing, Farm Redevelopment, or a card effect). Stop on this pending is legal once `build_fences_chosen=True` (i.e., the player has entered and exited the inner Build Fences sub-action).
- **`PendingBuildFences(player_idx, initiated_by_id, pastures_built=0, fences_built=0, subdivision_started=False, triggers_resolved=frozenset())`** — `PENDING_ID = "build_fences"`, `TRIGGER_EVENT = "before_build_fences"`. Multi-shot sub-action pending for fence building. Each `CommitBuildPasture` increments `pastures_built` (by 1) and `fences_built` (by the number of new edges placed) and leaves the pending on top (`auto_pop=False`); `Stop` is the explicit exit, legal once `pastures_built >= 1`. `subdivision_started` flips True the first time a subdivision commit lands; once True, new-pasture commits are no longer offered (the builds-before-subdivisions ordering rule — see CLAUDE.md "Fencing and Build Fences"). `fences_built` carries forward to satisfy card patterns like "every time you build N fences ≥ current round, get 1 vegetable". Cost is NOT on this pending — it is a pure function of `(state, commit.cells)` computed by `compute_new_fence_edges` (see CLAUDE.md "Sub-action cost handling" → bucket 4).
- **`PendingFarmRedevelopment(player_idx, initiated_by_id, renovate_chosen=False, build_fences_chosen=False, triggers_resolved=frozenset())`** — `PENDING_ID = "farm_redevelopment"`, `TRIGGER_EVENT = "before_farm_redevelopment"`. Top-level parent for the Farm Redevelopment action space. Mirrors `PendingHouseRedevelopment` structurally — renovate mandatory first (Stop illegal until `renovate_chosen=True`), then optionally an "and afterward" sub-action. The optional sub-action here is `build_fences` (vs House Redev's `improvement`); it pushes the same `PendingBuildFences` as the Fencing space but with `initiated_by_id="farm_redevelopment"` (the parent's `PENDING_ID`), distinct from Fencing's `"fencing"`. The provenance lets future cards gate on entry point.

- **`PendingDecision`** — the union alias over all pending types above. Future pending types are added here as more non-atomic spaces' resolutions are implemented.

**Stack operations.** Pure functions; all return new `GameState` objects (never mutate). Used by `engine.py` and `resolution.py`.
- `push(state, frame)` — append a frame to `state.pending_stack`.
- `pop(state)` — drop the top frame.
- `replace_top(state, new_top)` — replace the top frame.

---

### `agricola/legality.py`

Determines which actions are legal from a given game state. Covers all 12 **atomic** action spaces and all 12 **non-atomic** action spaces. `lessons` is permanently illegal in the Family game and is intentionally absent from every dispatch table. Also provides per-pending sub-action enumerators.

- The 12 atomic spaces: `day_laborer`, `fishing`, `forest`, `clay_pit`, `reed_bank`, `grain_seeds`, `meeting_place`, `western_quarry`, `vegetable_seeds`, `eastern_quarry`, `basic_wish_for_children`, `urgent_wish_for_children`.
- The 12 non-atomic spaces with legality predicates: `farm_expansion`, `farmland`, `side_job`, `grain_utilization`, `sheep_market`, `pig_market`, `cattle_market`, `major_improvement`, `house_redevelopment`, `cultivation`, `farm_redevelopment`, `fencing`. All have implemented resolution paths after TASK_6.

**Active-universe constants** (TASK_6): three module-level constants imported from `agricola.fences` set the default universe for fence-action enumeration:
  - `ACTIVE_FENCE_UNIVERSE_ENTRIES: tuple = UNIVERSE_RESTRICTED_ENTRIES` — entries iterated by the enumerator.
  - `ACTIVE_FENCE_UNIVERSE_SMALLEST_ENTRIES: tuple = UNIVERSE_RESTRICTED_SMALLEST_ENTRIES` — 1×1 fast-path tuple iterated by `_any_legal_pasture_commit`.
  - `ACTIVE_FENCE_UNIVERSE_SET: frozenset = UNIVERSE_RESTRICTED_SET` — bitmap set used for subdivision canonicalization complement-lookup.
All three must point at the same universe; the `fences.py` construction guarantees they're aligned (RESTRICTED_ENTRIES ↔ RESTRICTED_SMALLEST_ENTRIES ↔ RESTRICTED_SET). To switch globally, reassign all three; to switch for one call, pass corresponding kwargs to the enumerator.

Internal structure:
- `_is_available(state, space)` — the cross-cutting check shared by all spaces: the space must be unoccupied (`workers == (0, 0)`) and currently revealed (`round_revealed <= round_number`).
- One private predicate function per space, adding space-specific checks on top of `_is_available`. Most accumulation spaces require at least one accumulated good to be present (it is illegal to take an empty accumulation space). The Wish for Children spaces additionally require that the current player has fewer than 5 people and (for Basic Wish) has more rooms than people. Non-atomic predicates check the player can actually execute at least one of the space's effects.
- Shared helpers used across non-atomic predicates: `_owns_baker(state, p)`, `_can_bake_bread(state, p)`, `_can_sow(p)`, `_can_plow(p)`, `_can_build_stable(p, cost)`, `_can_afford(p, cost)`, `_can_afford_room(p)`, `_has_room_placement(p)`, `_can_build_room(p)`, `_can_renovate(p)`, `_can_afford_major(state, p, idx)`, `_can_afford_any_major_improvement(state, p)`. These follow the player-parameter convention in CLAUDE.md "Additional Design Principles". `BAKING_IMPROVEMENTS` lives in `constants.py`. `ROOM_COSTS` (per-material room cost dict) lives in `constants.py`. `_can_afford_room` is a one-liner over `_can_afford(p, ROOM_COSTS[p.house_material])`. `_can_build_stable(p, cost)` combines supply + cell-availability + affordability and replaces the deleted `_has_stable_placement` (which had no cost dimension).
- Cell-enumeration helpers: `_legal_plow_cells(p)` (used by `_enumerate_pending_plow` and by `_can_plow`, which is now a one-liner over it), `_legal_stable_cells(p)` (used by `_enumerate_pending_build_stables` and by `_can_build_stable`), `_legal_room_cells(p)` (used by `_enumerate_pending_build_rooms` and by `_has_room_placement`, which is now a one-liner over it).
- **Card extension registries**:
  - `BAKE_BREAD_ELIGIBILITY_EXTENSIONS: list[Callable]` — card-supplied predicates that may broaden `_can_bake_bread`. Cards register via `register_bake_bread_extension(fn)`. (Potter Ceramics registers an extension that accepts clay >= 1 as a valid baking precondition.)
  - `BAKING_SPEC_EXTENSIONS: list[Callable]` — card-supplied baking source contributors. Each registered fn takes `(state, player_idx)` and returns a list of `(max_grain_per_action, food_per_grain)` tuples. Cards register via `register_baking_spec_extension(fn)`. The helper `baking_specs_for_player(state, player_idx)` combines major-improvement specs (from `BAKING_IMPROVEMENT_SPECS`) with card-driven contributions; both `_execute_bake` and `_enumerate_pending_bake_bread` consume this combined list.
- Per-pending enumerators: `_enumerate_pending_X` for each pending type, dispatched via `PENDING_ENUMERATORS`. Signature `(state, pending: PendingX) -> list[Action]` — see CLAUDE.md "Code Conventions" → "Per-pending enumerator signatures". The three fence-action enumerators are: `_enumerate_pending_fencing` (parent: offers `ChooseSubAction("build_fences")` if not yet chosen, else `Stop`), `_enumerate_pending_build_fences` (multi-shot — walks the active universe, applies the per-entry legality chain via `_check_entry_legal`, emits `CommitBuildPasture` per legal entry plus `Stop` once `pastures_built >= 1`; accepts `entries=` and `universe_set=` kwargs for per-call universe override), and `_enumerate_pending_farm_redevelopment` (parent: mirrors House Redev with `build_fences` as the optional second step, gated on `_any_legal_pasture_commit`).
- **Fence-action helpers** (TASK_6):
  - `_enclosable_cells_bm(farmyard) -> int` — bitmap of EMPTY/STABLE cells (rooms and fields excluded).
  - `_cells_bm_of_pasture(pasture) -> int` — cell-set of a `Pasture` as a bitmap.
  - `_check_entry_legal(entry, *, ...)` — applies the unified pasture-commit legality chain (enclosable / subdivision-vs-new / ordering rule / adjacency / affordability / fences-supply / ≥1 new edge / subdivision canonicalization) against precomputed per-call state bitmaps. Returns `(is_legal, h_new_bm, v_new_bm)`. Shared by the enumerator and `_any_legal_pasture_commit`.
  - `_any_legal_pasture_commit(state, p, *, entries, smallest_entries, universe_set) -> bool` — returns True on the first legal commit. Two-pass iteration: walks `smallest_entries` (precomputed 1×1 fast path) first, then the slow path skipping 1×1's. Used by `_legal_fencing` (placement legality) and by `_enumerate_pending_farm_redevelopment` (to gate the optional `build_fences` sub-action offer).
  - `_legal_fencing(state) -> bool` — placement predicate. Requires space available + ≥1 wood + ≥1 fence in supply + at least one legal pasture commit. Registered in `NON_ATOMIC_LEGALITY`.
- Dispatch dicts: `ATOMIC_LEGALITY`, `NON_ATOMIC_LEGALITY` (now 12 entries), the combined `ALL_LEGALITY = {**ATOMIC_LEGALITY, **NON_ATOMIC_LEGALITY}`, and `PENDING_ENUMERATORS`.
- `legal_placements(state)` — internal helper. Returns a list of `PlaceWorker` actions, one for each space (atomic or non-atomic) whose predicate returns `True`. Returns an empty list if the current player has no workers left. Never returns `lessons`.
- **`legal_actions(state)`** — the top-level public legality entry point. Dispatches on stack state: empty stack + WORK phase → `legal_placements`; non-empty stack → `_enumerate_pending` on the top frame; `BEFORE_SCORING` → empty list. All callers (agent loops, tests) should use `legal_actions` rather than `legal_placements` directly.

---

### `agricola/resolution.py`

Per-space resolution code. Atomic and non-atomic space handlers, sub-action effect functions, and the function-pointer dispatch tables for them. Imported by `agricola.engine` for dispatch. Never mutates state — always uses `dataclasses.replace(...)`.

Three utility wrappers:
- `_update_player(state, ap, new_player)` — new `GameState` with one player replaced.
- `_update_space(state, space_id, **kwargs)` — new `GameState` with one action space's fields updated.
- `_new_grid_with_cell(grid, row, col, cell)` — new 3×5 grid identical to `grid` except at `(row, col)`, which is replaced. Used by `_execute_plow`, `_execute_build_stable`, and `_execute_build_room` instead of inline nested tuple-comprehensions.

**Cross-cutting bookkeeping.**
- `_apply_worker_placement(state, space_id)` — increments `workers[ap]` on the space and decrements `people_home` on the active player. Run for every worker placement.

**Atomic handlers.** Per-space `_resolve_<space>` functions for the 12 atomic spaces, each receiving the state *after* `_apply_worker_placement` and applying the space's specific effect (adding goods to the player's supply, resetting accumulated goods, updating the starting player token, etc.). Two shared helpers — `_resolve_building_accumulation` (for `forest`, `clay_pit`, `reed_bank`, `western_quarry`, `eastern_quarry`) and `_resolve_food_accumulation` (for `fishing` and `meeting_place`) — avoid repetition.

**Non-atomic initiators.** `_initiate_<space>` functions push the space's parent pending. Implemented for all 12 non-atomic spaces: `grain_utilization`, `farmland`, `cultivation`, `side_job`, `sheep_market`, `pig_market`, `cattle_market`, `major_improvement`, `house_redevelopment`, `farm_expansion`, `fencing`, `farm_redevelopment`. Each pushes its respective `Pending<Space>` with `initiated_by_id="space:<space_id>"`. The three market initiators additionally read `accumulated_amount` off the action space, zero it, and stage the count on the pending as `gained`.

**Choose-sub-action handlers.** `_choose_subaction_<space>` functions handle `ChooseSubAction` at that space's parent pending. Each follows the choose-time convention: set the corresponding `*_chosen` flag on the parent via `replace_top`, then push the sub-action pending with `initiated_by_id=top.PENDING_ID`. Implemented for: grain_utilization, farmland, cultivation, side_job, major_minor_improvement, clay_oven, stone_oven, house_redevelopment, farm_expansion, fencing, farm_redevelopment. (Animal markets have no choose step — commit lands directly on the parent.) Note: `_choose_subaction_farm_redevelopment` computes the renovate cost identically to House Redev's choose handler, then pushes `PendingRenovate` (renovate branch) or `PendingBuildFences` (build_fences branch) with `initiated_by_id=top.PENDING_ID` (i.e., `"farm_redevelopment"`).

**Sub-action effect functions.** `_execute_<sub_action>(state, player_idx, commit)` functions apply the effect of a committed sub-action. Each takes the commit action object as the third argument so a single dispatcher can call any effect uniformly. Effect functions MAY read `state.pending_stack[-1]` to access their own pending frame (the dispatcher guarantees it is still on top during effect execution); this is how cost-on-pending sub-actions (`_execute_build_stable`, `_execute_build_room`, `_execute_renovate`) recover their cost.
- `_execute_sow(state, player_idx, commit)` — fills empty fields with grain or veg.
- `_execute_bake(state, player_idx, commit)` — greedy-by-rate allocation across all owned baking improvements. Consults `baking_specs_for_player` (in `legality.py`) to collect `(cap, rate)` tuples from `BAKING_IMPROVEMENT_SPECS` plus any card-registered sources, processes sources in rate-descending order.
- `_execute_plow(state, player_idx, commit)` — places a `FIELD` cell at `(commit.row, commit.col)`.
- `_execute_build_stable(state, player_idx, commit)` — multi-shot stable effect. Places a `STABLE` cell at `(commit.row, commit.col)`, debits `pending.cost`, increments `pending.num_built`. Does NOT pop (`auto_pop=False`); `Stop` is the explicit exit. Recomputes `Farmyard.pastures` explicitly via `compute_pastures_from_arrays` — required because a stable placed inside an existing pasture changes that pasture's `num_stables`/`capacity`. (Post-Task-5D rewrite; the body was renamed in from `_execute_build_stables` during step 7's atomic swap.)
- `_execute_build_room(state, player_idx, commit)` — multi-shot room effect. Places a `ROOM` cell at `(commit.row, commit.col)`, debits `pending.cost`, increments `pending.num_built`. Does NOT pop. No pasture recompute needed — rooms cannot legally land in enclosed cells (`_legal_room_cells` enforces). `people_total` unchanged; new rooms are empty until a Wish for Children populates them.
- `_execute_renovate(state, player_idx, commit)` — advances the player's `house_material` and debits `pending.cost`. Material transition (WOOD→CLAY, CLAY→STONE) derived from current material.
- `_execute_build_major(state, player_idx, commit)` — pays cost (either standard or via Fireplace-return for Cooking Hearth), assigns ownership, writes Well's `+1 food` into the next 5 future-resource entries if applicable, sets `build_chosen=True` on `PendingBuildMajor`, then either pops `PendingBuildMajor` (non-oven) or pushes `PendingClayOven`/`PendingStoneOven` (oven majors). Dispatched via the generic `COMMIT_SUBACTION_HANDLERS` path with `auto_pop=False` — the dispatcher does not pop after the effect; the function owns its own conditional pop/push.
- `_execute_accommodate(state, player_idx, commit)` — sets the player's animals to the chosen frontier point and converts excess to food at the player's cooking rates. Lands on any of the three animal-market pendings via tuple-of-types dispatch in `COMMIT_SUBACTION_HANDLERS`.
- `_execute_build_pasture(state, player_idx, commit)` — multi-shot pasture effect (TASK_6). Packs `commit.cells` to a bitmap, determines new-pasture vs subdivision against the pre-commit farmyard (for the ordering-rule flag), computes new fence edges + wood cost via `compute_new_fence_edges`, applies the new edges to the fence arrays, recomputes `Farmyard.pastures` via `compute_pastures_from_arrays`, debits wood, and updates `PendingBuildFences` counters (`pastures_built += 1`, `fences_built += wood_cost`, `subdivision_started |= is_subdivision`). Does NOT pop (`auto_pop=False`); `Stop` is the explicit exit. **Second pasture-changing effect function** alongside `_execute_build_stable` — both must construct the new `Farmyard` with an explicit `pastures=compute_pastures_from_arrays(...)` kwarg (the caller-discipline rule for the pasture cache). Shared between the Fencing space's path and the Farm Redev path; the only resolver that derives the subdivision/new-pasture distinction at execute time.

**Function-pointer dispatch tables**, each keyed by space-id or pending-type:
- `ATOMIC_HANDLERS: dict[str, callable]` — `space_id → _resolve_<space>`.
- `NONATOMIC_HANDLERS: dict[str, callable]` — `space_id → _initiate_<space>`. Now contains 12 entries (every non-atomic space).
- `CHOOSE_SUBACTION_HANDLERS: dict[type, callable]` — `pending_type → _choose_subaction_<space>`. Now contains 11 entries (animal markets have no entry because they have no choose step).

The metadata dispatch table for `Commit*` sub-actions (`COMMIT_SUBACTION_HANDLERS`) lives in `engine.py` — it's metadata for the engine's generic commit dispatcher, not a function-pointer table.

---

### `agricola/engine.py`

The state-transition engine. Public API: `step(state, action) -> GameState`. Pure transition function; the loop that drives a game lives outside this module (typically the agent loop in tests).

- **`step(state, action)`** — apply one action and auto-advance through system transitions. Raises `RuntimeError` if called with `Phase.BEFORE_SCORING`. Does NOT validate legality — callers assert via `legal_actions`. The `NotImplementedError` branch in `_apply_place_worker` is a defensive guard for unknown space-IDs (e.g., `lessons`); every space surfaced by `legal_placements` has a registered handler post-TASK_6.
- **`_apply_action(state, action)`** — dispatches on action type via five `isinstance` branches: `PlaceWorker`, `ChooseSubAction`, `CommitSubAction` (matches every concrete commit subclass including `CommitBuildMajor` post-Task-5D), `FireTrigger`, `Stop`. (Pre-Task-5D had a special-case branch for `CommitBuildMajor`; absorbed into the generic dispatcher when `auto_pop=False` was added.)
- **`_apply_place_worker(state, action)`** — runs `_apply_worker_placement` (from `resolution.py`) then dispatches via `ATOMIC_HANDLERS` (atomic spaces) or `NONATOMIC_HANDLERS` (non-atomic spaces). Raises `NotImplementedError` if the space is in neither dict — defensive guard for unknown space-IDs (only `lessons` qualifies today, and it never surfaces via `legal_placements`).
- **`_apply_choose_sub_action(state, action)`** — dispatches via `CHOOSE_SUBACTION_HANDLERS` keyed by the top pending's type.
- **`_apply_commit_subaction(state, action)`** — generic handler for any `CommitSubAction` subclass. Dispatches via `COMMIT_SUBACTION_HANDLERS` (defined in this module). For each commit type the table holds `(expected_pending_type, effect_fn, auto_pop)` — `expected_pending_type` may be a single type or a tuple of types (animal markets use a tuple). The handler asserts the expected pending is on top, applies the effect, and pops the sub-action pending only if `auto_pop=True`. When `auto_pop=False` the effect function owns any stack manipulation (multi-shot pendings leave themselves on top via `replace_top`; `_execute_build_major` pops for non-ovens or pushes the oven wrapper). The dispatcher does NOT touch parent state — parent `*_chosen` flags are set earlier, at choose-time, by the `_choose_subaction_*` handler that pushed the sub-action pending.
- **`_apply_fire_trigger`** — looks up the trigger via `CARDS[card_id]` (direct O(1) lookup), applies its `apply_fn`, adds `card_id` to the top frame's `triggers_resolved`.
- **`_apply_stop`** — pops the top pending frame. Does NOT assert the stack becomes empty afterward (future cards may have deeper stacks).
- **`_advance_current_player(state)`** — rotates `current_player` to the next player with workers, using modular arithmetic. Called inside `step` only when the stack is empty AND phase is WORK (i.e., a worker placement just completed). NOT called from `_advance_until_decision`.
- **`_advance_until_decision(state)`** — auto-advance loop. Walks system-driven phase transitions until the next agent decision or game-over. Pure state-driven and idempotent. Phase handling: stack non-empty → return; `BEFORE_SCORING` → return; WORK with workers remaining → return; WORK with both players at 0 workers → transition to `RETURN_HOME`; `RETURN_HOME` → `_resolve_return_home`; `PREPARATION` → `_resolve_preparation`. Harvest phases (HARVEST_*) are unimplemented (TODO comment in place).
- **`_resolve_return_home(state)`** — end-of-round bookkeeping: reset every action space's `workers` to `(0, 0)`; set each player's `people_home = people_total`. Does NOT clear `newborns` (those must survive to HARVEST_FEED for the discount). Transitions to `PREPARATION` for rounds < 4, or to `BEFORE_SCORING` for round 4 (current halt point).
- **`_resolve_preparation(state)`** — set up the new round: increment `round_number`, refill every revealed accumulation space, distribute each player's `future_resources[round_number - 1]` into their supply, clear `newborns`, set `current_player = starting_player`, transition to WORK.

**Dispatch table in this module.**
- `COMMIT_SUBACTION_HANDLERS: dict[type, tuple]` — `CommitX → (PendingX_or_tuple_of_types, _execute_x, auto_pop: bool)`. Metadata table for the generic commit dispatcher; co-located with its sole consumer rather than placed alongside the function-pointer dispatch tables in `resolution.py`. Includes `CommitBuildMajor` (with `auto_pop=False`), `CommitBuildStable` (with `PendingBuildStables` and `auto_pop=False` for the multi-shot pattern), and `CommitBuildRoom` (with `PendingBuildRooms` and `auto_pop=False`).

**Stack operations** (`push`, `pop`, `replace_top`) are imported from `pending.py`.

See CLAUDE.md "Engine and Turn Resolution Architecture" for the design philosophies and TASK_5.md / TASK_5B_DISPATCH_CLEANUP.md for the full implementation breakdown.

---

### `agricola/cards/__init__.py`

Card package marker. Imports each card module so their `register()` calls run at module load time, populating the registries in `agricola.cards.triggers` and `BAKE_BREAD_ELIGIBILITY_EXTENSIONS` in `agricola.legality`. Currently imports `potter_ceramics`; future card modules are added here.

---

### `agricola/cards/triggers.py`

The card-trigger registry. Two parallel dicts populated at import time:

- **`TRIGGERS: dict[str, list[TriggerEntry]]`** — event-keyed registry. `TRIGGERS["before_bake_bread"]` returns the list of entries for cards that fire on that event. Used by `legal_actions` enumerators at pending frames to find eligible unfired triggers.
- **`CARDS: dict[str, TriggerEntry]`** — card-id-keyed registry. Direct O(1) lookup by `card_id`. Used by `_apply_fire_trigger` to apply a chosen trigger's effect.
- **`TriggerEntry`** — frozen dataclass with `card_id`, `event`, `eligibility_fn`, `apply_fn`. The same entry appears in both registries.
- **`register(event, card_id, eligibility_fn, apply_fn)`** — called at import time by each card module. Adds the entry to both `TRIGGERS[event]` and `CARDS[card_id]`.

---

### `agricola/cards/potter_ceramics.py`

The one card implemented in Task 5. Effect: "Each time before a Bake Bread action, the owner may exchange exactly 1 clay for 1 grain. At most once per Bake Bread action."

Module contents:
- `CARD_ID = "potter_ceramics"`.
- `_eligible(state, player_idx, triggers_resolved)` — eligibility predicate: card played + clay >= 1 + not already fired this action.
- `_apply(state, player_idx)` — effect: `-1 clay, +1 grain`.
- `_can_bake_bread_extension(state, p)` — broadens `_can_bake_bread` to accept "owns Potter Ceramics + owns baker + clay >= 1" as sufficient (the trigger will swap clay for grain mid-action).
- Module-level `register(...)` and `register_bake_bread_extension(...)` calls fire at import time.

See CLAUDE.md "Card implementation status" for the broader card-system design and the known limitation around compound card interactions.

---

### `agricola/fences.py`

Precomputed universes of candidate pasture shapes for the Fencing action, plus per-shape edge metadata + shared utilities consumed by the legality and resolution layers. Standalone module; built once at module import. Imports only `from __future__ import annotations` and stdlib `dataclasses` — no engine dependencies.

- **Bitmap encodings**: cell `(r, c)` ↔ bit `r * NUM_COLS + c` (15 bits). Horizontal edges `horizontal_fences[r][c]` ↔ bit `r * NUM_COLS + c` (20 bits). Vertical edges `vertical_fences[r][c]` ↔ bit `r * (NUM_COLS + 1) + c` (18 bits). Adjacency is 4-neighbor (orthogonal).

- **Module-level universe constants**: four `(tuple, frozenset)` pairs — `UNIVERSE_FULL` / `UNIVERSE_FAMILY` / `UNIVERSE_EXTENDED` / `UNIVERSE_RESTRICTED`, each paired with a `_SET` for O(1) membership. Sizes 1518 / 762 / 193 / 109 (TASK_6 grew RESTRICTED 108→109 and EXTENDED 192→193 by switching the category-1 1×1 scope from `PASTURE_CELLS` to `ENCLOSABLE_CELLS`, adding the 1×1 at (0, 0)). Containment chain: `RESTRICTED ⊆ EXTENDED ⊆ FAMILY ⊆ FULL`.

- **Why four universes**: `UNIVERSE_FULL` is the broadest baseline (accommodates a full-game card that grants extra perimeter fences). `UNIVERSE_FAMILY` is the rules-correct universe for the Family game mode (no such card; total fences ≤ 15). `UNIVERSE_RESTRICTED` is the strategist-curated set used at legality-check time. `UNIVERSE_EXTENDED` sits between RESTRICTED and FAMILY as the policy-network output space, allowing relaxation without retraining if the restricted set turns out to omit a move.

- **`PastureCandidate` frozen dataclass**: one per universe entry. Fields: `cells_bm` (15-bit), `h_boundary_bm` (20-bit), `v_boundary_bm` (18-bit), `adjacency_bm` (15-bit; in-grid orthogonal neighbors not in the cell-set), `cells: frozenset[tuple[int, int]]` (for `CommitBuildPasture` construction). All four metadata fields are pure functions of `cells_bm`; computed at module import by `_boundary_h_bm`, `_boundary_v_bm`, `_adjacency_bm`.

- **Parallel `UNIVERSE_*_ENTRIES` tuples**: same order and length as the bitmap tuples; one `PastureCandidate` per entry. Built by `_make_entries(bm_tuple)`.

- **Fast-path `UNIVERSE_*_SMALLEST_ENTRIES` tuples**: the popcount-1 subset of each universe (13 entries each — one per ENCLOSABLE cell after the (0, 0) addition). Used by `_any_legal_pasture_commit` in `legality.py` to walk cheap 1×1 candidates first. Built by `_filter_singletons(entries)`.

- **`ENTRIES_BY_BM: dict[int, PastureCandidate]`**: bitmap-keyed lookup. Used off the hot path — by `_execute_build_pasture` (receives `commit.cells`, packs to bitmap, looks up the entry's boundary metadata) and by `compute_new_fence_edges`. Keyed off `UNIVERSE_FULL_ENTRIES`, which by the containment chain covers every bitmap in any universe.

- **Fence-array packing helpers**: `pack_fences_h(h_arr) -> int` and `pack_fences_v(v_arr) -> int` convert `Farmyard.horizontal_fences` (4×5) / `vertical_fences` (3×6) tuple-of-tuple-of-bool into the corresponding 20/18-bit bitmaps. Symmetric apply helpers `apply_fence_edges_h(h_arr, new_h_bm) -> tuple` and `apply_fence_edges_v(v_arr, new_v_bm) -> tuple` flip new bits back into nested-tuple form (purely additive union with existing True entries). All four are module-level (no underscore) — consumed across modules.

- **`compute_new_fence_edges(farmyard, cells_bm) -> (h_new_bm, v_new_bm, wood_cost)`**: shared bucket-4 cost helper. Computes the new fence-edges to place (boundary AND NOT current fences) and the total wood cost (default rule: 1 wood per new edge). `farmyard` is duck-typed (only `.horizontal_fences` and `.vertical_fences` read). Both `_execute_build_pasture` (for the debit) and tests call it; the legality-hot-path `_check_entry_legal` inlines the same calc against pre-computed per-call bitmaps for speed.

Filter primitives, shape categories, and the original verification approach live in `TASK_6_pre.md`. Edge metadata and the (0, 0) addition are introduced in `TASK_6.md`.

---

### `agricola/scoring.py`

Computes a player's end-of-game score.

- **`ScoreBreakdown`** dataclass — holds a separate integer for each scoring category (field tiles, pastures, grain, vegetables, sheep, boar, cattle, unused spaces, fenced stables, clay rooms, stone rooms, people, begging markers, major improvement points, craft building bonus points) plus the total. Not frozen — it is only used as a return value, not stored in game state.
- `score(state, player_idx)` — returns `(total_score, ScoreBreakdown)`. Computes each category by reading from the player's farmyard, resources, animals, and the board's major improvement ownership record. Reads `farmyard.pastures` (the cached decomposition) directly for the pasture, fenced-stables, and unused-cell categories.
- `tiebreaker(state, player_idx)` — returns the tiebreaker value: total building resources (wood + clay + reed + stone) in the player's personal supply, after subtracting any resources consumed by craft building end-game bonuses (Joinery, Pottery, Basketmaker's Workshop).
- `_craft_bonus_spending(state, player_idx)` — private helper shared by both `score` and `tiebreaker`. Computes how many bonus points the player earns from their craft buildings and how many resources are consumed in the process.

The scoring tables (how many points for 0 fields, 1 field, 2 fields, etc.) are implemented as small private lookup functions at the top of the file. See **`RULES.md`** for the complete scoring table.

---

### `tests/__init__.py`

Empty package marker. Makes `tests` importable as a Python package. No code here.

---

### `tests/factories.py`

Prefabricated-state helpers used across test files. Each helper takes a state and returns a NEW state (no mutation). Helpers include `with_resources`, `add_resources`, `with_animals`, `with_house`, `with_majors`, `with_minors`, `with_grid`, `with_fields`, `with_sown_fields`, `with_space`, `with_pending_stack`, `with_phase`, `with_round`, `with_current_player`, `with_people`. Tests compose them to reach any state — including states unreachable through gameplay (e.g., a player who has played Potter Ceramics, which requires minor-improvement card play paths that aren't implemented yet). This is the project-wide convention for test state construction; see TASK_5.md "Testing principle: prefabricated states" for rationale.

### `tests/test_utils.py`

Test-side multi-action helpers and the random-agent driver. NOT a test file despite the `test_` prefix — pytest collects no test functions from it because none start with `test_`.

- `run_actions(state, actions)` — apply a scripted sequence of actions; validate each is legal before applying. Used by tests that walk through a specific scenario.
- `IMPLEMENTED_NON_ATOMIC_SPACES`, `_is_implemented_action`, `filter_implemented(actions)` — filter `legal_actions` output to actions `step` can apply. `IMPLEMENTED_NON_ATOMIC_SPACES = frozenset(NONATOMIC_HANDLERS.keys())` — currently covers every non-atomic space (all 12), so the filter is effectively a no-op today; it stays in place for forward-compat as new action types (e.g., harvest sub-actions in Task 7) may surface in `legal_actions` before their `step` handler does.
- `random_agent_play(state, seed)` — plays a random-action game to `Phase.BEFORE_SCORING`. Returns `(terminal_state, trace)`. Raises if the agent gets stuck (would indicate a bug). Used by the end-to-end engine smoke test.

---

Per-file coverage descriptions for each `tests/test_*.py` live in **`TEST_DESCRIPTIONS.md`**.
