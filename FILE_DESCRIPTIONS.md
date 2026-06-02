# Python File Descriptions

Detailed per-file descriptions of every Python module and test-infrastructure file in the codebase. Offloaded from CLAUDE.md to reduce session-start context — the enriched Directory Structure in CLAUDE.md gives 1-2 sentence summaries; this file is the deeper reference.

For per-file test coverage (`tests/test_*.py`), see **`TEST_DESCRIPTIONS.md`**.

---

### `agricola/__init__.py`

Empty package marker. Makes `agricola` importable as a Python package. No code here.

---

### `agricola/resources.py`

Defines two small data containers that hold quantities of things:

- **`Resources`** — holds counts of the seven goods a player can have in their personal supply: `wood`, `clay`, `reed`, `stone`, `food`, `grain`, `veg`. Supports addition (`r1 + r2`), subtraction (`r1 - r2`), and truthiness (`bool(r)` is `True` if any field is nonzero). All three operators return new instances; nothing mutates. Subtraction is used at pure-subtraction cost-debit sites (e.g. `p.resources - cost`); mixed subtract-and-add operations stay in the `r + Resources(field=-x, ...)` form (see ENGINE_IMPLEMENTATION.md §5 — Coding conventions, Resource arithmetic).

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
- **`SPACE_IDS`** — length-25 tuple of all action space IDs in canonical order: `PERMANENT_ACTION_SPACES` (in its given order) followed by the stage cards in stage order. Fixed across all games — the per-game stage-card shuffle is recorded separately in `BoardState.round_card_order`. Indexes `BoardState.action_spaces`.
- **`SPACE_INDEX`** — `dict[str, int]` reverse lookup from space-id to its position in `SPACE_IDS`. Used by `state.get_space` / `state.with_space` (and transitively by everywhere the codebase reads or writes a single action space). See CHANGES.md Change 8.
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

### `agricola/replace.py`

Performance helper for frozen-dataclass field updates. Exports a single function — `fast_replace(obj, /, **changes)` — that is a drop-in faster equivalent of stdlib `dataclasses.replace(obj, **changes)`. Used at every state-mutation site in production code (`engine.py`, `resolution.py`, `pending.py`, `cards/`).

- **`fast_replace(obj, /, **changes)`** — return a new instance of `type(obj)` with the given field changes. Behaviorally equivalent to `dataclasses.replace` for every dataclass shape in the engine. Microbenchmarked at ~20% faster per call across the dataclass shapes used in the engine (1.84 us → 1.35 us on Resources; 2.79 us → 2.07 us on PlayerState; etc).

The implementation caches each class's init-field name tuple in a module-level dict (`_FIELDS_CACHE`) at first use and constructs the new instance positionally. The speedup vs stdlib comes from skipping per-call type checks, Field descriptor iteration, the no-non-init-in-changes guard, and `**kwargs` unpacking.

Field discovery uses `dataclasses.fields(cls)` rather than `cls.__dataclass_fields__` directly — the latter includes `ClassVar` entries (a CPython implementation detail) which would cause positional construction to fail. `dataclasses.fields()` is the canonical filter. The cost is amortized: it runs once per class and is cached for the lifetime of the process.

Unknown field names in `changes` are silently ignored rather than raising (stdlib raises `TypeError` on the constructor); the equivalence tests in `tests/test_replace.py` cover every dataclass shape the engine uses, so a real typo would surface as a test failure.

`replace.py` imports only from `dataclasses` (stdlib) — no other `agricola.*` dependencies. See CHANGES.md Change 9 for the rationale.

---

### `agricola/state.py`

All the frozen dataclasses that together represent a complete snapshot of a game in progress. Nothing is ever mutated; all transitions use `dataclasses.replace(...)` to produce new objects.

- **`Cell`** — one cell of a player's 3×5 farmyard grid. Stores the cell type (`EMPTY`, `ROOM`, `FIELD`, `STABLE`) and any grain/veg counts if it is a field. House material is stored on `PlayerState`, not on `Cell` (see CLEANUP.md Cleanup 1).

- **`Farmyard`** — the complete farmyard for one player. Contains the 3×5 `grid` of `Cell` objects (stored as a tuple of tuples), two fence arrays, and a cached `pastures: tuple[Pasture, ...]` decomposition. The two fence arrays are: `horizontal_fences` (shape 4×5, one bool per horizontal edge between rows) and `vertical_fences` (shape 3×6, one bool per vertical edge between columns). See `task_files/ARCHITECTURE.md` for the exact index conventions. The `pastures` cache is canonically ordered by `min(p.cells)` so equivalent farmyards always compare equal — required for `Farmyard.__eq__` and hashing across MCTS. The cache is maintained by caller discipline: the two pasture-changing effect functions — `_execute_build_stable` (used by Side Job and Farm Expansion via `CommitBuildStable`) and `_execute_build_pasture` (used by Fencing and Farm Redevelopment via `CommitBuildPasture`) — construct the new `Farmyard` with an explicit `pastures=compute_pastures_from_arrays(new_grid, new_h, new_v)` kwarg. All other `Farmyard` mutations use `dataclasses.replace(farmyard, ...)` and leave `pastures` alone, which is correct because these mutations cannot change pastures. A fresh `Farmyard` constructed without any fences or stables (e.g. by `setup`) correctly has `pastures=()` via the placeholder default. This is the first accepted exception to "Derived data, not cached data" (ENGINE_IMPLEMENTATION.md §4.1 — the Farmyard.pastures caching exception) — see CHANGES.md Change 2 (and CHANGES.md Change 3 for why auto-fill in `__post_init__`, the obvious structural alternative, is not used).

- **`ActionSpaceState`** — the state of one action space on the board. Tracks how many workers each player has placed on it (`workers`, a 2-tuple of ints), any accumulated building resources (`accumulated`, a `Resources` object — used for the 5 building-resource spaces), any accumulated food/animals (`accumulated_amount`, a plain int — used for the 5 food/animal spaces), and which round the space is first revealed (`round_revealed`, 0 for permanent spaces).

- **`PlayerState`** — everything about one player: their `Resources`, their `Animals`, their `Farmyard`, how many people they have in total and how many are currently at home, how many newborns were born during the current round (cleared by `_resolve_preparation` of the next round; if a harvest immediately follows, these newborns cost 1 food at that harvest instead of 2), begging markers, a `future_resources: tuple[Resources, ...]` of length 14 (per-round promised goods — populated by the Well major improvement when implemented), frozensets `minor_improvements` and `occupations` recording played card IDs, and `harvest_conversions_used: frozenset[str]` — the once-per-harvest conversion-decision budget (records both `use=True` and `use=False` decisions for joinery / pottery / basketmaker plus any future card-registered conversions, so the FEED enumerator stops offering a conversion once decided). Reset to `frozenset()` inside `engine._resolve_harvest_field` at the start of each harvest. Lives on `PlayerState` (not on `PendingHarvestFeed`) per the "per-card budgets that span events live on `PlayerState`" convention (ENGINE_IMPLEMENTATION.md §2).

- **`BoardState`** — the shared board: a `tuple[ActionSpaceState, ...]` of length 25 indexed by `constants.SPACE_INDEX[space_id]` (canonical ordering — 11 permanent spaces in `PERMANENT_ACTION_SPACES` order, then 14 stage cards in stage order; same across all games regardless of stage-card shuffle), a tuple recording who owns each of the 10 major improvements, and the `round_card_order` tuple (the randomly-ordered stage cards). The tuple shape makes `BoardState` — and transitively `GameState` — fully hashable. Callers access spaces via the `get_space(board, space_id)` / `with_space(board, space_id, new_space)` free functions defined in this module (see also `resolution._update_space`, the higher-level wrapper that combines `dataclasses.replace` on the underlying `ActionSpaceState` with `with_space`). See CHANGES.md Change 8 for the refactor.

- **`GameState`** — the top-level snapshot. Holds the round number, phase, which player is currently acting (`current_player`: whose worker placement is currently being resolved), who holds the starting player token, the two `PlayerState` objects, the `BoardState`, and `pending_stack: tuple[PendingDecision, ...]` (the stack of in-progress sub-decisions). (A `next_starting_player` field was briefly present but removed as redundant — `starting_player` is updated immediately when Meeting Place is taken. See CLEANUP.md Cleanup 3.)

---

### `agricola/setup.py`

Contains the single public function `setup(seed: int) -> GameState`, which builds the initial game state for a 2-player Family game.

Internally it uses a seeded NumPy RNG (`numpy.random.default_rng(seed)`) to determine the starting player and shuffle the stage cards within each stage. All randomness is resolved here; after `setup` returns the engine is fully deterministic.

The private helpers inside this file are:
- `_make_round_card_order(rng)` — shuffles cards within each stage and concatenates them into a 14-element tuple.
- `_make_action_spaces(round_card_order)` — builds the initial `ActionSpaceState` for all 25 spaces, pre-loading round-1 accumulated goods onto the accumulation spaces, and returns them as a canonical-ordered tuple (length 25, indexed by `constants.SPACE_INDEX`).
- `_make_farmyard()` — builds a fresh farmyard with wood rooms at cells (1,0) and (2,0) and all fences False.
- `_make_player(food)` — builds a starting `PlayerState` with the given food amount, 2 people, an empty farmyard, and `harvest_conversions_used=frozenset()`.

---

### `agricola/helpers.py`

Pure functions for derived quantities and the animal accommodation logic. These are the computational workhorses that other modules call; none of them mutate state.

**Simple derived quantities:**
- `fences_in_supply(farmyard)` — counts True values in both fence arrays, subtracts from 15.
- `stables_in_supply(farmyard)` — counts `STABLE` cells, subtracts from 4.
- `cooking_rates(state, player_idx)` — returns a 4-tuple `(sheep_rate, boar_rate, cattle_rate, veg_rate)` for at-any-time food conversion. Cooking Hearth returns `(2, 3, 4, 3)`, Fireplace returns `(2, 2, 3, 2)`, neither returns `(0, 0, 0, 1)`. The veg row has a raw 1:1 fallback per RULES.md feeding rules (vegetables count as 1 food without a cooking improvement); animal rates have no such fallback. Callers that only need the animal triple (`pareto_frontier`, `breeding_frontier`) slice with `cooking_rates(...)[:3]`.

**Pasture-derived helpers:**

The `Pasture` dataclass and the BFS that builds the pasture decomposition live in `agricola/pasture.py`. The decomposition itself is cached on `Farmyard.pastures` (see the `Farmyard` description above for how the cache is maintained), so reading it is O(1). Helpers in `helpers.py` derive from that cache:

- `enclosed_cells(farmyard) -> frozenset[(row, col)]` — returns the union of all cells inside any pasture. Used by legality code that needs membership lookups (e.g. "can a field be placed at this cell?").

**Animal accommodation:**
- `extract_slots(player_state)` — returns `(pasture_capacities, num_flexible)`. Reads `player_state.farmyard.pastures` (the cached decomposition) and returns the list of pasture capacities plus the count of single-animal flexible slots (one per standalone (unfenced) stable, plus one always for the house pet).
- `can_accommodate(pasture_capacities, num_flexible, sheep, boar, cattle)` — checks whether a given animal count is physically accommodatable on the farm. Each pasture holds exactly one animal type. The algorithm tries all possible type-to-pasture assignments (brute force over the small number of pastures) and returns `True` if any assignment leaves no more overflow animals than there are flexible slots.
- `pareto_frontier(player_state, gained, rates)` — used when a player gains animals (e.g. takes the Sheep Market). Enumerates all achievable `(sheep, boar, cattle)` configurations (bounded by current inventory + gained, and by farm capacity), Pareto-filters over animal counts only, and returns a list of `(Animals, food_gained)` pairs. Food is the deterministic consequence of the chosen configuration and cooking rates — not a Pareto dimension; see CLAUDE.md Foundations (Preserving optionality). The agent picks one point from this frontier.
- `breeding_frontier(player_state, rates)` — same animal-counts-only Pareto logic as `pareto_frontier`, but for the breeding phase of harvest. The upper bound for each animal type is `current + 1` if the player has ≥ 2 (breeding fires), otherwise `current`. Each frontier point's food value is computed via `breeding_food_gained` (below); it is the consequence of the chosen end-state, not a Pareto dimension.
- `breeding_food_gained(pre, post, rates)` — the breeding food formula, factored out as the single source of truth shared by `breeding_frontier` (tabulates it per frontier point) and `_execute_breed` (applies it to the one chosen point, avoiding a frontier re-enumeration). Per type: if breeding fired (`pre ≥ 2`) and the newborn was kept (`post ≥ 3`), pre-breed removals = `pre + 1 - post`; otherwise `pre - post`; each removal converts to food at the type's rate. See CLEANUP.md Cleanup 4.

**Food-payment frontiers (Task 7).** General-purpose Pareto-frontier helpers for the harvest FEED phase. Marker comment in source notes these may move to a dedicated `harvest.py` if the harvest grows enough auxiliary helpers to warrant its own module.

- `food_payment_frontier(player_state, food_owed, rates)` — Pareto-optimal `(grain_rem, veg_rem, sheep_rem, boar_rem, cattle_rem)` REMAINING-goods tuples for FULLY paying `food_owed` food. Per-good consumption caps trim the enumeration (e.g. `grain_cap = min(player.grain, food_owed)`; `veg_cap = min(player.veg, ceil(food_owed/vR))`); the Pareto-filter then drops over-conversion configs that are dominated by the same-amount-paid configs that consume fewer goods. `food_owed=0` short-circuits with the no-conversion config; `food_owed > 0` with insufficient player capacity returns `[]`. The general helper applies wherever food must be paid — harvest feeding (via `harvest_feed_frontier`) plus future card-cost payment actions.
- `harvest_feed_frontier(player_state, food_owed, rates)` — Pareto-optimal `((remaining_goods), begging)` pairs for paying as much of `food_owed` as the player chooses and begging the rest. Composes `food_payment_frontier` across paid levels in `[0, food_owed]`, admitting each config exactly once at its natural fit (`paid == min(food_generated, food_owed)`) — a fast pre-filter that avoids ghost-begging duplicates before the 6-dim `(5 goods, -begging)` Pareto pass. Pareto dimensions exclude food_surplus per CLAUDE.md Foundations (Preserving optionality), but include `-begging` as a strategic-cost dim (the player has a genuine choice to incur begging in exchange for goods preservation). Always non-empty for `food_owed > 0` (the no-conversion + max-begging entry is always on the frontier).

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
- **`CommitHarvestConversion(conversion_id: str, use: bool)`** — commit one once-per-harvest conversion decision at `PendingHarvestFeed`. `conversion_id` is a key in `HARVEST_CONVERSIONS` (joinery / pottery / basketmaker, plus future card-registered ids). `use=True` fires the conversion (pays `spec.input_cost`, adds the full `spec.food_out` to the player's supply, invokes `spec.side_effect_fn` if any). `use=False` records the decision without firing. Either way, the conversion_id is added to `player.harvest_conversions_used` so the enumerator no longer offers it for the rest of this harvest's FEED. Dispatched with `auto_pop=False`; the pending stays on top to host further craft decisions and the final `CommitConvert`. Food payment is deferred to the final `CommitConvert` — crafts simply increase the player's food supply, which is then drawn from at commit time.
- **`CommitConvert(grain: int, veg: int, sheep: int, boar: int, cattle: int)`** — commit the player's chosen goods-to-food conversion configuration at `PendingHarvestFeed` AND pay the feeding cost from the resulting supply. Fields hold CONSUMED amounts (subtracted from the player's supply) — contrast with `CommitAccommodate` / `CommitBreed`, which hold post-event-state counts. The CONSUMED convention fits because the values are bounded by per-good caps in `food_payment_frontier` and `(0,0,0,0,0)` always means "consume nothing" regardless of player state. The legality enumerator constructs `CommitConvert` by inverting REMAINING-goods tuples from `harvest_feed_frontier` (consumed = player_max - remaining). After commit: `_execute_convert` adds `food_produced` to supply, pays `min(need, supply + food_produced)` to feeding, leaves surplus in supply, and assigns the shortfall as begging markers (assigned by `_execute_convert`, not by `Stop`, preserving the Stop-only-pops convention). Sets `pending.conversion_done=True`. Dispatched with `auto_pop=False`; the trailing `Stop` is the explicit exit.
- **`CommitBreed(sheep: int, boar: int, cattle: int)`** — commit the final post-breed animal configuration at `PendingHarvestBreed`. Fields hold post-breed counts (matches `CommitAccommodate`'s convention). The triple must match a Pareto-optimal point from `breeding_frontier(p, rates[:3])`; the enumerator only emits frontier points. The effect function sets the chosen counts and adds the food computed by `breeding_food_gained(p.animals, chosen, rates[:3])` to supply. Dispatched with `auto_pop=False`; trailing `Stop` is the explicit exit.
- **`Action`** — the union alias listing the concrete subclasses (`PlaceWorker | ChooseSubAction | CommitSow | CommitBake | CommitPlow | CommitBuildStable | CommitBuildRoom | CommitBuildMajor | CommitRenovate | CommitAccommodate | CommitBuildPasture | CommitHarvestConversion | CommitConvert | CommitBreed | FireTrigger | Stop`). The `CommitSubAction` base is intentionally not in the union — concrete subclasses are listed so legality enumerators and type checkers see the real options. There is no `SkipTrigger`: declining a trigger is implicit.

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
- **`PendingBuildStables(player_idx, initiated_by_id, cost, max_builds, num_built=0)`** — `PENDING_ID = "build_stables"`. Multi-shot pending: each `CommitBuildStable` increments `num_built` and leaves the pending on top (`auto_pop=False`); `Stop` is the explicit exit. `cost: Resources` is per-commit (1 wood for Side Job; 2 wood for Farm Expansion; future cards may inject other costs). `max_builds: int | None` is a caller-imposed cap (`None` = no cap; Side Job sets 1; Farm Expansion sets None). Supply/affordability/cell checks live in the enumerator. No card-trigger fields yet (`triggers_resolved` / `TRIGGER_EVENT` deferred until a card needs them). See ENGINE_IMPLEMENTATION.md §3 (sub-action cost handling → bucket 2, and multi-shot pendings).
- **`PendingBuildRooms(player_idx, initiated_by_id, cost, max_builds, num_built=0)`** — `PENDING_ID = "build_rooms"`. Multi-shot pending mirroring `PendingBuildStables`. `cost: Resources` is set at push time from `ROOM_COSTS[p.house_material]`. Farm Expansion pushes with `max_builds=None`; future cards may set integer caps.
- **`PendingBuildMajor(player_idx, initiated_by_id, build_chosen=False, triggers_resolved=frozenset())`** — `PENDING_ID = "build_major"`, `TRIGGER_EVENT = "before_build_major"`. `build_chosen` is set by `_execute_build_major` and matters only for oven majors (Clay/Stone Oven), where `PendingBuildMajor` lingers below the oven wrapper while the optional free bake resolves. Cost is NOT on this pending — it's looked up in `MAJOR_IMPROVEMENT_COSTS` by `commit.major_idx`. See ENGINE_IMPLEMENTATION.md §3 (sub-action cost handling → bucket 3).
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
- **`PendingBuildFences(player_idx, initiated_by_id, pastures_built=0, fences_built=0, subdivision_started=False, triggers_resolved=frozenset())`** — `PENDING_ID = "build_fences"`, `TRIGGER_EVENT = "before_build_fences"`. Multi-shot sub-action pending for fence building. Each `CommitBuildPasture` increments `pastures_built` (by 1) and `fences_built` (by the number of new edges placed) and leaves the pending on top (`auto_pop=False`); `Stop` is the explicit exit, legal once `pastures_built >= 1`. `subdivision_started` flips True the first time a subdivision commit lands; once True, new-pasture commits are no longer offered (the builds-before-subdivisions ordering rule — see ENGINE_IMPLEMENTATION.md §4.1 (Fencing & Build Fences)). `fences_built` carries forward to satisfy card patterns like "every time you build N fences ≥ current round, get 1 vegetable". Cost is NOT on this pending — it is a pure function of `(state, commit.cells)` computed by `compute_new_fence_edges` (see ENGINE_IMPLEMENTATION.md §3 — sub-action cost handling → bucket 4).
- **`PendingFarmRedevelopment(player_idx, initiated_by_id, renovate_chosen=False, build_fences_chosen=False, triggers_resolved=frozenset())`** — `PENDING_ID = "farm_redevelopment"`, `TRIGGER_EVENT = "before_farm_redevelopment"`. Top-level parent for the Farm Redevelopment action space. Mirrors `PendingHouseRedevelopment` structurally — renovate mandatory first (Stop illegal until `renovate_chosen=True`), then optionally an "and afterward" sub-action. The optional sub-action here is `build_fences` (vs House Redev's `improvement`); it pushes the same `PendingBuildFences` as the Fencing space but with `initiated_by_id="farm_redevelopment"` (the parent's `PENDING_ID`), distinct from Fencing's `"fencing"`. The provenance lets future cards gate on entry point.

**Phase-driven pendings (Task 7).** Pushed by phase resolvers (`engine._initiate_harvest_feed` and `engine._initiate_harvest_breed`), not by `PlaceWorker` or `ChooseSubAction`. Use the `"phase:<phase_id>"` provenance prefix — disjoint from `"space:"` and `"card:"` by construction.

- **`PendingHarvestFeed(player_idx, initiated_by_id, conversion_done=False)`** — `PENDING_ID = "harvest_feed"`. One per player during HARVEST_FEED; `initiated_by_id="phase:harvest_feed"`. Hosts trigger-style opt-in sub-decisions (the three craft majors via `CommitHarvestConversion`) followed by one main `CommitConvert`. Food payment is deferred to `CommitConvert` (see `_execute_convert`); the pending carries no `food_owed` field. `food_owed` is a derived value (`max(0, need - p.resources.food)`), recomputed in `_enumerate_pending_harvest_feed` from the live player state on each legality call (per CLAUDE.md Foundations, Derived data, not cached data — recomputing also means food-mutating card effects during feeding will reflect immediately in the next legal-actions call). `conversion_done` gates Stop legality — `Stop` is legal only after `CommitConvert`. No `triggers_resolved` / `TRIGGER_EVENT` yet (Task 5D precedent — natural future events: `before_harvest_feed`, `after_harvest_feed`).
- **`PendingHarvestBreed(player_idx, initiated_by_id, breed_chosen=False)`** — `PENDING_ID = "harvest_breed"`. One per player during HARVEST_BREED; `initiated_by_id="phase:harvest_breed"`. Simpler shape than FEED — one `CommitBreed` (chosen from `breeding_frontier`) followed by Stop. No pre-debit. `breed_chosen` gates Stop. No `triggers_resolved` / `TRIGGER_EVENT` yet.

- **`PendingDecision`** — the union alias over all pending types above (now including `PendingHarvestFeed` and `PendingHarvestBreed`). Future pending types are added here as more non-atomic spaces' resolutions are implemented.

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
All three must point at the same universe; the `fences.py` construction guarantees they're aligned (RESTRICTED_ENTRIES ↔ RESTRICTED_SMALLEST_ENTRIES ↔ RESTRICTED_SET). To switch globally, reassign all three (or use `active_universe(...)` from `agricola.fence_universe` — recommended); to switch for one call, pass corresponding kwargs to the enumerator. The two universe-aware enumerators (`_any_legal_pasture_commit`, `_enumerate_pending_build_fences`) resolve the active universe at CALL time (defaults are `None` sentinels; each function falls back to the `ACTIVE_FENCE_UNIVERSE_*` constants when the kwarg is omitted). This is what makes reassignment of the module constants — and therefore the `active_universe(...)` context manager — effective for default-kwarg call sites including all production paths.

Internal structure:
- `_is_available(state, space)` — the cross-cutting check shared by all spaces: the space must be unoccupied (`workers == (0, 0)`) and currently revealed (`round_revealed <= round_number`).
- One private predicate function per space, adding space-specific checks on top of `_is_available`. Most accumulation spaces require at least one accumulated good to be present (it is illegal to take an empty accumulation space). The Wish for Children spaces additionally require that the current player has fewer than 5 people and (for Basic Wish) has more rooms than people. Non-atomic predicates check the player can actually execute at least one of the space's effects.
- Shared helpers used across non-atomic predicates: `_owns_baker(state, p)`, `_can_bake_bread(state, p)`, `_can_sow(p)`, `_can_plow(p)`, `_can_build_stable(p, cost)`, `_can_afford(p, cost)`, `_can_afford_room(p)`, `_has_room_placement(p)`, `_can_build_room(p)`, `_can_renovate(p)`, `_can_afford_major(state, p, idx)`, `_can_afford_any_major_improvement(state, p)`. These follow the player-parameter convention in ENGINE_IMPLEMENTATION.md §5 (Coding conventions). `BAKING_IMPROVEMENTS` lives in `constants.py`. `ROOM_COSTS` (per-material room cost dict) lives in `constants.py`. `_can_afford_room` is a one-liner over `_can_afford(p, ROOM_COSTS[p.house_material])`. `_can_build_stable(p, cost)` combines supply + cell-availability + affordability and replaces the deleted `_has_stable_placement` (which had no cost dimension).
- Cell-enumeration helpers: `_legal_plow_cells(p)` (used by `_enumerate_pending_plow` and by `_can_plow`, which is now a one-liner over it), `_legal_stable_cells(p)` (used by `_enumerate_pending_build_stables` and by `_can_build_stable`), `_legal_room_cells(p)` (used by `_enumerate_pending_build_rooms` and by `_has_room_placement`, which is now a one-liner over it).
- **Card extension registries**:
  - `BAKE_BREAD_ELIGIBILITY_EXTENSIONS: list[Callable]` — card-supplied predicates that may broaden `_can_bake_bread`. Cards register via `register_bake_bread_extension(fn)`. (Potter Ceramics registers an extension that accepts clay >= 1 as a valid baking precondition.)
  - `BAKING_SPEC_EXTENSIONS: list[Callable]` — card-supplied baking source contributors. Each registered fn takes `(state, player_idx)` and returns a list of `(max_grain_per_action, food_per_grain)` tuples. Cards register via `register_baking_spec_extension(fn)`. The helper `baking_specs_for_player(state, player_idx)` combines major-improvement specs (from `BAKING_IMPROVEMENT_SPECS`) with card-driven contributions; both `_execute_bake` and `_enumerate_pending_bake_bread` consume this combined list.
- Per-pending enumerators: `_enumerate_pending_X` for each pending type, dispatched via `PENDING_ENUMERATORS`. Signature `(state, pending: PendingX) -> list[Action]` — see ENGINE_IMPLEMENTATION.md §5 (Coding conventions — per-pending enumerator signatures). The three fence-action enumerators are: `_enumerate_pending_fencing` (parent: offers `ChooseSubAction("build_fences")` if not yet chosen, else `Stop`), `_enumerate_pending_build_fences` (multi-shot — walks the active universe, applies the per-entry legality chain via `_check_entry_legal`, emits `CommitBuildPasture` per legal entry plus `Stop` once `pastures_built >= 1`; accepts `entries=` and `universe_set=` kwargs for per-call universe override), and `_enumerate_pending_farm_redevelopment` (parent: mirrors House Redev with `build_fences` as the optional second step, gated on `_any_legal_pasture_commit`). The two harvest enumerators (Task 7) are: `_enumerate_pending_harvest_feed` (offers undecided owned `HARVEST_CONVERSIONS` entries — both `use=True` (if affordable) and `use=False` — plus every Pareto-frontier `CommitConvert` point from `harvest_feed_frontier` (REMAINING-tuples inverted to CONSUMED amounts); once `conversion_done`, only `Stop`) and `_enumerate_pending_harvest_breed` (one `CommitBreed` per Pareto-frontier point from `breeding_frontier`; once `breed_chosen`, only `Stop`).
- **Fence-action helpers** (TASK_6):
  - `_enclosable_cells_bm(farmyard) -> int` — bitmap of EMPTY/STABLE cells (rooms and fields excluded).
  - `_cells_bm_of_pasture(pasture) -> int` — cell-set of a `Pasture` as a bitmap.
  - `_check_entry_legal(entry, *, ...)` — applies the unified pasture-commit legality chain (enclosable / subdivision-vs-new / ordering rule / adjacency / affordability / fences-supply / ≥1 new edge / subdivision canonicalization) against precomputed per-call state bitmaps. Returns `(is_legal, h_new_bm, v_new_bm)`. Shared by the enumerator and `_any_legal_pasture_commit`.
  - `_any_legal_pasture_commit(state, p, *, entries=None, smallest_entries=None, universe_set=None) -> bool` — returns True on the first legal commit. Two-pass iteration: walks `smallest_entries` (precomputed 1×1 fast path) first, then the slow path skipping 1×1's. Universe kwargs default to `None` and resolve to the `ACTIVE_FENCE_UNIVERSE_*` module constants at call time. Used by `_legal_fencing` (placement legality) and by `_enumerate_pending_farm_redevelopment` (to gate the optional `build_fences` sub-action offer).
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
- `_execute_harvest_conversion(state, player_idx, commit)` — Task 7. Applies one once-per-harvest conversion decision on `PendingHarvestFeed`. Records the decision (both `use=True` and `use=False`) by adding `commit.conversion_id` to `player.harvest_conversions_used`. If `use=True`: pays `spec.input_cost`, adds the full `spec.food_out` to the player's supply, invokes `spec.side_effect_fn` if present. No `food_owed` bookkeeping — payment is deferred to `_execute_convert`. Does NOT pop (`auto_pop=False`); the pending stays on top to host further craft decisions and the final `CommitConvert`.
- `_execute_convert(state, player_idx, commit)` — Task 7. Applies the player's chosen goods-to-food conversion on `PendingHarvestFeed` AND pays the feeding cost in a single step. `commit.{grain, veg, sheep, boar, cattle}` are CONSUMED amounts (subtracted from supply). `food_produced` computed via `cooking_rates` 4-tuple is added to `p.resources.food`; then `food_paid = min(need, total_available)` is taken from the combined pool (the "Cannot withhold food tokens" rule is enforced structurally by this `min`), with `need = 2*people_total - newborns`. Any surplus stays in supply; any shortfall becomes begging markers (assigned here, not at Stop, preserving the Stop-only-pops convention). Sets `pending.conversion_done=True` via `replace_top`. Does NOT pop; trailing `Stop` is the explicit exit.
- `_execute_breed(state, player_idx, commit)` — Task 7. Applies the chosen post-breed configuration on `PendingHarvestBreed`. The `(sheep, boar, cattle)` triple is a Pareto-optimal point from `breeding_frontier(p, rates[:3])` (the enumerator guarantees this; not re-checked, per "step does not verify legality"). Food is computed directly via `breeding_food_gained(p.animals, chosen, rates[:3])` — the shared formula helper that `breeding_frontier` also uses — rather than re-enumerating the frontier to look it up (CLEANUP.md Cleanup 4). Sets `pending.breed_chosen=True`. Does NOT pop; trailing `Stop` is the explicit exit.

**Function-pointer dispatch tables**, each keyed by space-id or pending-type:
- `ATOMIC_HANDLERS: dict[str, callable]` — `space_id → _resolve_<space>`.
- `NONATOMIC_HANDLERS: dict[str, callable]` — `space_id → _initiate_<space>`. Now contains 12 entries (every non-atomic space).
- `CHOOSE_SUBACTION_HANDLERS: dict[type, callable]` — `pending_type → _choose_subaction_<space>`. Now contains 11 entries (animal markets have no entry because they have no choose step; harvest pendings have no entry either because they have no `ChooseSubAction` path).

The metadata dispatch table for `Commit*` sub-actions (`COMMIT_SUBACTION_HANDLERS`) lives in `engine.py` — it's metadata for the engine's generic commit dispatcher, not a function-pointer table. Post-Task-7 includes three new entries: `CommitHarvestConversion` and `CommitConvert` (both on `PendingHarvestFeed`, `auto_pop=False`), and `CommitBreed` (on `PendingHarvestBreed`, `auto_pop=False`).

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
- **`_advance_until_decision(state)`** — auto-advance loop. Walks system-driven phase transitions until the next agent decision or game-over. Pure state-driven and idempotent. Phase handling: stack non-empty → return; `BEFORE_SCORING` → return; `PREPARATION` → `_resolve_preparation`; WORK with workers remaining → return; WORK with both players at 0 workers → transition to `RETURN_HOME`; `RETURN_HOME` → `_resolve_return_home`; `HARVEST_FIELD` → `_resolve_harvest_field`; `HARVEST_FEED` with empty stack (exit signal) → push BREED pendings via `_initiate_harvest_breed` and transition to HARVEST_BREED; `HARVEST_BREED` with empty stack (exit signal) → transition to PREPARATION (round < 14) or BEFORE_SCORING (round == 14). The dual-meaning phase pattern for `HARVEST_FEED` / `HARVEST_BREED` (stack non-empty = a player is deciding; stack empty = phase-exit) works because the only way to reach those phases with empty stack is for the entry-resolver to have pushed pendings now drained by `Stop`.
- **`_resolve_return_home(state)`** — end-of-round bookkeeping: reset every action space's `workers` to `(0, 0)`; set each player's `people_home = people_total`. Does NOT clear `newborns` (those must survive to HARVEST_FEED for the discount). Routes to `HARVEST_FIELD` on `HARVEST_ROUNDS` (4, 7, 9, 11, 13, 14), otherwise to `PREPARATION`. Round 14's `HARVEST_BREED` → `BEFORE_SCORING` transition lives in `_advance_until_decision`'s HARVEST_BREED-empty-stack branch, not here.
- **`_resolve_preparation(state)`** — set up the new round: increment `round_number`, refill every revealed accumulation space, distribute each player's `future_resources[round_number - 1]` into their supply, clear `newborns`, set `current_player = starting_player`, transition to WORK.
- **`_resolve_harvest_field(state)`** — Task 7. Mechanical FIELD work + once-per-harvest budget reset + push FEED pendings + transition phase. Three concerns combined (mirrors `_resolve_preparation`'s multi-concern shape — justified in TASK_7 Part 2.1): (1) take 1 crop from each planted field per player (grain takes precedence over veg in the elif chain — a field is sown with one or the other, never both); (2) reset `harvest_conversions_used = frozenset()` on both players so FEED starts with a fresh budget; (3) push FEED pendings via `_initiate_harvest_feed` and set `phase=HARVEST_FEED`. Fields cannot lie inside pastures, so the pasture cache rides along via `dataclasses.replace`'s natural pass-through.
- **`_initiate_harvest_feed(state)`** — Task 7. Push one `PendingHarvestFeed` per player, ordered so the starting player's frame is on top. Does NOT debit food — payment is deferred to `CommitConvert` (see `_execute_convert` in resolution.py), where the "Cannot withhold food tokens" rule is enforced structurally by `min(need, available)`. Push order: non-starting player pushed first (bottom of stack), starting player pushed second (top). When the starting player Stops, the non-starting player's frame becomes top automatically. Exposed standalone so tests can construct a FEED-only state without running FIELD mechanics.
- **`_initiate_harvest_breed(state)`** — Task 7. Push one `PendingHarvestBreed` per player, same push order as FEED. No pre-debit (breeding doesn't consume food upfront).

**Dispatch table in this module.**
- `COMMIT_SUBACTION_HANDLERS: dict[type, tuple]` — `CommitX → (PendingX_or_tuple_of_types, _execute_x, auto_pop: bool)`. Metadata table for the generic commit dispatcher; co-located with its sole consumer rather than placed alongside the function-pointer dispatch tables in `resolution.py`. Includes `CommitBuildMajor` (with `auto_pop=False`), `CommitBuildStable` (with `PendingBuildStables` and `auto_pop=False` for the multi-shot pattern), `CommitBuildRoom` (with `PendingBuildRooms` and `auto_pop=False`), and three Task-7 harvest entries: `CommitHarvestConversion` and `CommitConvert` (both on `PendingHarvestFeed`, `auto_pop=False`), and `CommitBreed` (on `PendingHarvestBreed`, `auto_pop=False`).

**Stack operations** (`push`, `pop`, `replace_top`) are imported from `pending.py`.

See ENGINE_IMPLEMENTATION.md §1 (Engine structure & dispatch) for the design philosophies and task_files/TASK_5.md / task_files/TASK_5B_DISPATCH_CLEANUP.md for the full implementation breakdown.

---

### `agricola/cards/__init__.py`

Card package marker. Imports each card module so their `register()` calls run at module load time, populating the registries in `agricola.cards.triggers` and `BAKE_BREAD_ELIGIBILITY_EXTENSIONS` in `agricola.legality`. Currently imports `harvest_conversions` (so the three built-in craft majors register their `HARVEST_CONVERSIONS` entries — see Task 7) and `potter_ceramics`. Future card modules are added here.

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

See ENGINE_IMPLEMENTATION.md §6 (card-trigger machinery & deferred design questions) for the broader card-system design and the known limitation around compound card interactions.

---

### `agricola/cards/harvest_conversions.py`

The once-per-harvest conversion registry (Task 7). Parallels `agricola/cards/triggers.py` — a dict of conversion specs keyed by `conversion_id`, plus a `register_harvest_conversion(spec)` function. Imported by `agricola/cards/__init__.py` so the built-in entries register at package load.

- **`HarvestConversionSpec`** — frozen dataclass with fields `conversion_id: str` (the unique key), `input_cost: Resources` (spent to fire), `food_out: int` (food produced), `is_owned_fn: Callable[[GameState, int], bool]` (true iff the player owns the source granting this conversion — major improvement, card, etc.), and `side_effect_fn: Optional[Callable[[GameState, int], GameState]]` (optional non-food effect like a hypothetical Stone Sculptor's `+1 point`; `None` for the three built-in crafts; called by `_execute_harvest_conversion` AFTER the food/resource accounting).
- **`HARVEST_CONVERSIONS: dict[str, HarvestConversionSpec]`** — the conversion-id-keyed registry. Mutable at import time; treated as read-only after package init.
- **`register_harvest_conversion(spec)`** — adds a `HarvestConversionSpec` to `HARVEST_CONVERSIONS`. Called at import time by the module that defines the conversion.
- **Built-in entries** (registered at module load):
  - `"joinery"` — 1 wood → 2 food (Joinery, major idx 7).
  - `"pottery"` — 1 clay → 2 food (Pottery, major idx 8).
  - `"basketmaker"` — 1 reed → 3 food (Basketmaker's Workshop, major idx 9).

Future cards (e.g., Stone Sculptor) register their own entries via `register_harvest_conversion(spec)` at import time. Each card module is imported from `agricola.cards.__init__`, mirroring the trigger-registry pattern.

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

Filter primitives, shape categories, and the original verification approach live in `task_files/TASK_6_pre.md`. Edge metadata and the (0, 0) addition are introduced in `task_files/TASK_6.md`.

---

### `agricola/fence_universe.py`

Experimental tooling for swapping the active fence universe — the set of candidate pastures the Build Fences enumerator considers — during research and tests. Lives separately from `fences.py` (which owns the universes themselves) and from `legality.py` (which owns the active-universe constants); this module exists purely to compose those two cleanly.

- **`Universe` type alias**: `tuple[tuple[PastureCandidate, ...], tuple[PastureCandidate, ...], frozenset]` — the (entries, smallest_entries, set) triple expected by the legality enumerators. `UniverseSpec` extends this with `str` to allow name-based lookup.

- **`NAMED_UNIVERSES: dict[str, Universe]`** — registry mapping `"restricted"` / `"extended"` / `"family"` / `"full"` to the four built-in triples from `fences.py`.

- **`current_universe() -> Universe`** — reads `legality.ACTIVE_FENCE_UNIVERSE_*` at call time and returns the active triple. Useful in tests that want to capture state before swapping.

- **`active_universe(spec: UniverseSpec) -> Iterator[Universe]`** — `@contextlib.contextmanager`. Swaps the three `legality.ACTIVE_FENCE_UNIVERSE_*` constants for the duration of a with-block, restoring them on exit (including on exception). Safe to nest. `spec` accepts a name string or an explicit `Universe` triple (typically from `restrict_to(...)`). The recommended way to switch universes in tests and experiments; replaces the prior manual save/swap/restore pattern.

- **`restrict_to(predicate, *, base="full") -> Universe`** — builds a derived universe by filtering `base` through `predicate`. The returned `smallest_entries` is the 1×1 subset of the filtered entries (preserving the fast-path semantic in `_any_legal_pasture_commit`); the returned set contains every kept entry's `cells_bm`. Order is preserved from `base`. The triple is suitable for `active_universe(triple)` or as per-call kwargs.

- **`_resolve(spec) -> Universe`** — private helper. Accepts a string (looked up in `NAMED_UNIVERSES`) or a 3-tuple, with explicit `ValueError`/`TypeError` for bad inputs.

The reason `active_universe(...)` works at all is the footgun-fix in `legality.py`: `_any_legal_pasture_commit` and `_enumerate_pending_build_fences` now default their universe kwargs to `None` and resolve to `ACTIVE_FENCE_UNIVERSE_*` at call time (rather than at function-definition time, which is how kwarg defaults are bound). Without this, reassigning the constants would only affect call sites that pass the kwargs explicitly — which would exclude every production call path.

Originally listed as item D in `POSSIBLE_NEXT_STEPS.md` ("State-independent fence-universe restriction tooling"). The pytest-fixture variant suggested there is not provided; the context manager covers the use case directly and a fixture is trivial to add later (`@pytest.fixture def extended_universe(): with active_universe("extended") as u: yield u`).

---

### `agricola/scoring.py`

Computes a player's end-of-game score.

- **`ScoreBreakdown`** dataclass — holds a separate integer for each scoring category (field tiles, pastures, grain, vegetables, sheep, boar, cattle, unused spaces, fenced stables, clay rooms, stone rooms, people, begging markers, major improvement points, craft building bonus points) plus the total. Not frozen — it is only used as a return value, not stored in game state.
- `score(state, player_idx)` — returns `(total_score, ScoreBreakdown)`. Computes each category by reading from the player's farmyard, resources, animals, and the board's major improvement ownership record. Reads `farmyard.pastures` (the cached decomposition) directly for the pasture, fenced-stables, and unused-cell categories.
- `tiebreaker(state, player_idx)` — returns the tiebreaker value: total building resources (wood + clay + reed + stone) in the player's personal supply, after subtracting any resources consumed by craft building end-game bonuses (Joinery, Pottery, Basketmaker's Workshop).
- `_craft_bonus_spending(state, player_idx)` — private helper shared by both `score` and `tiebreaker`. Computes how many bonus points the player earns from their craft buildings and how many resources are consumed in the process.

The scoring tables (how many points for 0 fields, 1 field, 2 fields, etc.) are implemented as small private lookup functions at the top of the file. See **`RULES.md`** for the complete scoring table.

---

### `agricola/agents/__init__.py`

Package marker for `agricola.agents`. Re-exports the public agent API: `Agent` protocol, `HeuristicAgent` infrastructure class, `RandomAgent`, `SimpleHeuristic`, `HubrisHeuristic` (alias to V1), `HubrisHeuristicV1`, `HubrisHeuristicV2`, **`HubrisHeuristicV3`**, the `HeuristicConfig` and **`HeuristicConfigV3`** dataclasses, named config constants **`DEFAULT_CONFIG`** / **`DEFAULT_CONFIG_V3`** / **`CONFIG_V1_T2`** / **`CONFIG_V3_T1`**, the four evaluator functions (`evaluate_simple`, `evaluate_hubris_v1`, `evaluate_hubris_v2`, `evaluate_hubris_v3`, plus `evaluate_hubris` alias), the `play_game(initial_state, agents)` driver, the **action-pruning wrappers** `restricted_legal_actions` / `strict_restricted_legal_actions` / `make_strict_restricted_legal_actions` + their priority constants (`STABLE_PRIORITY`, `ROOM_PRIORITY`, `PLOW_PRIORITY`, `FIRST_PASTURE_REQUIRED_CELLS`, `MAX_TOTAL_ROOMS`) + the `LegalActionsFn` type alias, and the **MCTS classes** `MCTSAgent` / `MCTSSearch` / `MCTSNode` / `MacroFencingAction`. Designed so that callers can write `from agricola.agents import HubrisHeuristicV3, CONFIG_V1_T2, MCTSAgent, MCTSSearch, restricted_legal_actions, play_game, ...` without dipping into submodules.

**Additional exports (post-`267530c`)**: the composable-evaluator helpers (`compose_evaluators`, `r1_force_forest_bonus`) and the differential-evaluator family (`make_differential_evaluator`, `evaluate_hubris_v3_differential`, `evaluate_hubris_v1_differential`, `HubrisHeuristicV3Differential`, `HubrisHeuristicV1Differential`). See `agricola/agents/heuristic.py` for semantics.

---

### `agricola/agents/base.py`

Agent infrastructure shared by all heuristic agents.

- **`Agent`** — `Protocol` describing the agent contract: callable as `(state) -> Action` returning one element of `filter_implemented(legal_actions(state))`.
- **`LegalActionsFn`** — type alias `Callable[[GameState], list[Action]]`. The shape both agents accept as their `legal_actions_fn` kwarg.
- **`decider_of(state)`** — small helper returning the player index whose decision is currently being awaited (`pending_stack[-1].player_idx` if the stack is non-empty, else `state.current_player`).
- **`RandomAgent`** — uniformly-random over `filter_implemented(legal_actions_fn(state))`. Takes a `legal_actions_fn` kwarg (default = `agricola.legality.legal_actions`); pass `agricola.agents.restricted.restricted_legal_actions` for a random agent operating on the action-pruned set.
- **`HeuristicAgent`** — generic 1-action-or-1-turn lookahead agent. Takes an evaluator callable `(state, player_idx, config) -> float`, a `temperature`, a `seed`, a `lookahead` mode (`"action"` or `"turn"`, default `"turn"`), and a `legal_actions_fn` (default unrestricted). Uses `legal_actions_cache()` over the lookahead, and `filter_implemented` to limit selections to engine-known actions. Always skips singleton decisions before evaluation (via the `_skip_singletons` helper) — "n steps deep = n meaningful decisions" applies uniformly, evaluated against `self.legal_actions_fn` so the action-pruned variant collapses sequences that look like singletons only after restriction. In `"turn"` mode the `_rollout_value` helper greedily plays the decider's own subsequent decisions until control hands off, then evaluates.
- **`play_game(initial_state, agents)`** — drives a full game from `initial_state` to `BEFORE_SCORING`. Returns `(terminal_state, trace)` like `tests/test_utils.random_agent_play`, but accepts any mix of agent types.

---

### `agricola/agents/heuristic.py`

All heuristic-agent code: Simple, Hubris V1, V2, V3 evaluators and agent classes, plus named config constants. See **`V3_DESIGN.md`** for the V3 architecture and **`HUBRIS_V1_NOTES.md`** for the V1 design rationale.

**V1-era components:**
- **`HeuristicConfig`** — frozen dataclass holding ~70 tunable coefficients spanning V1's evaluator terms: resource tier rates and caps, family-member per-round rates, breeding-value tiers, major-improvement utility values, location bonuses, crop+field pair bonuses, food-by-stage rates, begging-by-moves rates, time multipliers, Pottery/BMW bonus caps, starting-player bonus, renovation-bonus fields. Default values are hand-picked.
- **`DEFAULT_CONFIG`** — module-level instance of `HeuristicConfig()` (all hand-picked defaults).
- **`CONFIG_V1_T2`** — round-2-tuned `HeuristicConfig` (58 params tuned; +8.85 holdout margin vs `DEFAULT_CONFIG`; 90-1-9 record). Sourced from `tuned_configs/1779468329.json`. Used as the **`hubris` seat-alias** in all drivers.
- **`evaluate_simple(state, player_idx, config)`** — MVP evaluator: `score()` + linear resource bonuses + food term.
- **`evaluate_hubris_v1(state, player_idx, config)`** — V1 evaluator. Composes `score(state)` with major-improvement override + family-future + empty-room anticipation + unfenced-stable + breeding-opportunity + location bonuses + crop+field pair + tiered resource value + starting-player + renovation bonus + `_food_term_hubris`.
- **`evaluate_hubris_v2(state, player_idx, config)`** — V1 with the food-leaf computation replaced by `_food_and_goods_term_v2` (joint goods-or-food maximization via `harvest_feed_frontier`). Loses head-to-head to V1.
- **`SimpleHeuristic`** / **`HubrisHeuristicV1`** / **`HubrisHeuristicV2`** — thin `HeuristicAgent` subclasses. `HubrisHeuristic` is an alias to V1. `evaluate_hubris` alias to V1.

**V3 architecture (current main heuristic):**
- **`HeuristicConfigV3`** — frozen dataclass with ~70 fields (250+ scalar parameters total). Categorizes scoring-relevant state into: BLEND categories (fields, pastures × 2 vectors + alpha, grain, veg, sheep, boar, cattle, fenced stables, unused-spaces with parameterized-side fixed at 0), ADDITIVE categories (grain/veg pairs, 3 breeding-pairs with cattle>boar>sheep priority, unfenced stables), three-component resources (wood: fence-slot vector + pre-3rd-room overlay + generic; reed: room-slot vector + renovation overlay + generic; clay: cookware-status vector + renovation-per-room scalar + generic; stone: renovation-per-room scalar + generic; all gated by per-stage weight vectors), a joint-alpha modulator for uncovered score leaves (clay/stone rooms, people, craft bonuses), and V1 carry-over fields (family rates, empty-room rates, location bonuses, SP bonus, renovation bonus, full major-improvement override values, food-by-stage, begging-by-moves) — these carry-overs duck-type into the existing V1 helpers.
- **`DEFAULT_CONFIG_V3`** — module-level instance with carry-over fields seeded from `CONFIG_V1_T2`'s tuned values.
- **`evaluate_hubris_v3(state, player_idx, config)`** — V3 evaluator. Composes per-category contributions: blend (α·v3 + (1−α)·score_leaf), additive (weight·v3_value), joint-alpha (single α × multiple score_leaves), three-component resources, full-weight begging, and V1 carry-over additive terms (`_hubris_family_value`, `_hubris_empty_room_value`, `_hubris_field_location_bonus`, `_hubris_pasture_location_bonus`, `_hubris_starting_player_bonus`, `_hubris_renovation_bonus`, `_hubris_major_value`, `_food_term_hubris`).
- **`HubrisHeuristicV3`** — thin `HeuristicAgent` subclass binding `evaluate_hubris_v3` + `DEFAULT_CONFIG_V3`.
- **V3 helper functions** (with `_v3_` prefix): `_v3_clip_index`, `_v3_blend`, `_v3_count_field_tiles`, `_v3_count_plowed_empty_fields`, `_v3_total_grain` / `_total_veg`, `_v3_pasture_counts` (returns total + large), `_v3_fenced_stable_count`, `_v3_crop_field_pair_counts` (grain priority allocation), `_v3_breeding_pair_counts` (cattle > boar > sheep priority), `_v3_fences_built`, `_v3_resources_contribution`.

**Shared V1/V3 helpers**: `_three_tier` for piecewise-linear resource valuation, `_stage_of_round`, `_next_harvest_round`, `_moves_left_before_harvest`, `_feeding_need`, `_max_convertible_food`, `_has_cooking`, `_can_afford_cooking`, `_basic_wish_revealed_round`, `_num_breeding_opportunities_from_farm`, `_types_with_2_plus_animals`, `_count_unfenced_stables`, `_count_cells_of_type`, `_empty_unenclosed_cells`. The carry-over V1 helpers (`_hubris_family_value` etc.) duck-type on the config's field names — same code, called by both `evaluate_hubris_v1` and `evaluate_hubris_v3`.

All four agent subclasses (`SimpleHeuristic`, `HubrisHeuristicV1`, `HubrisHeuristicV2`, `HubrisHeuristicV3`) accept an optional `legal_actions_fn` kwarg and forward it to the base `HeuristicAgent` constructor.

**New V3 config fields (post-`267530c`)**:
- **`wood_flat_bonus: float = 0.0`** — adds `bonus * wood` to wood resource contribution OUTSIDE the per-stage weight gating. Lets baselines bias toward wood-hoarding regardless of stage. Read inside `_v3_resources_contribution`.
- **`temperature: float = 0.0`** — action-selection softmax temperature lifted onto the config so baseline JSONs can pin per-agent stochasticity. Consumed by drivers/agents that respect config-supplied T.
- **`r1_force_forest_bonus: float = 0.0`** — when > 0, `evaluate_hubris_v3` adds `bonus` at the very top of the evaluator iff `round_number == 1` and `p.resources.wood >= 3`. Effectively pins Round-1 first action to Forest (the only path to wood≥3 on R1) without distorting later-round evaluation.

**Composable evaluator pattern** (new helpers):
- **`compose_evaluators(*evaluators)`** — returns a callable `(state, player_idx, config) -> float` that sums the contributions of all input evaluators. Lets callers stack add-on evaluators (e.g. `compose_evaluators(evaluate_hubris_v3, r1_force_forest_bonus)`) without forking the V3 implementation.
- **`r1_force_forest_bonus(state, p, cfg)`** — standalone Round-1-forest-forcing evaluator. Returns `1000.0` if `round_number == 1` and `p.resources.wood >= 3`, else `0.0`. Companion to `HeuristicConfigV3.r1_force_forest_bonus`; usable independently via `compose_evaluators`.

**Differential evaluator wrappers** (new helpers). Wrap a base `(state, player_idx, config) -> float` evaluator to always return `own − opp` (instead of just `own` at non-terminal states). Useful when an agent should care about opponent's score at every node, not only at `BEFORE_SCORING`:
- **`make_differential_evaluator(base)`** — generic factory: `lambda s, p, c: base(s, p, c) - base(s, 1 - p, c)`.
- **`evaluate_hubris_v3_differential`** / **`evaluate_hubris_v1_differential`** — pre-built differential versions of the V3 and V1 evaluators.
- **`HubrisHeuristicV3Differential`** / **`HubrisHeuristicV1Differential`** — thin `HeuristicAgent` subclasses binding the differential evaluators.

---

### `agricola/agents/restricted.py`

Pure wrappers over `legal_actions(state)` applying strategic action-pruning at the agent layer (engine code is untouched). Two public entry points:

- **`restricted_legal_actions(state)`** — regular wrapper, used by the heuristic agents and the training pipeline.
- **`strict_restricted_legal_actions(state)`** — strict-mode wrapper used by MCTS (layers four MCTS-specific filters on top of the regular wrapper).
- **`make_strict_restricted_legal_actions(*, config=None, rng=None)`** — factory that builds a strict-wrapper closure with injected `HeuristicConfigV3` and `numpy.random.Generator`. MCTS uses this so the harvest-feed cap's random samples are deterministic per `MCTSSearch` instance (rather than sharing the module-level default RNG across all instances).

Plus priority constants `STABLE_PRIORITY`, `ROOM_PRIORITY`, `PLOW_PRIORITY`, `FIRST_PASTURE_REQUIRED_CELLS`, `MAX_TOTAL_ROOMS`, and the `LegalActionsFn` type alias.

**Regular-wrapper filters** (applied based on the top pending frame):
- **Sub-action ordering** at parent pendings: `PendingFarmExpansion` drops `build_stables` when `build_rooms` is on offer; `PendingCultivation` drops `sow` when `plow` is on offer; `PendingGrainUtilization` drops `bake_bread` when `sow` is on offer.
- **Cell priority** at multi-shot pendings: `PendingBuildStables` / `PendingBuildRooms` / `PendingPlow` each filter their `Commit*` actions to the single top-priority cell present in the legal set (walk the priority list in order; first hit wins; cells outside the list are never selected as long as a priority cell is available).
- **Room cap** at `PendingFarmExpansion` (drop `ChooseSubAction("build_rooms")` once at `MAX_TOTAL_ROOMS = 5`) and at `PendingBuildRooms` (drop further `CommitBuildRoom` when at cap).
- **First-pasture opener** at `PendingBuildFences` with `pastures_built == 0`: every `CommitBuildPasture` must include at least one of `(0, 4)` or `(1, 4)`. Restriction lifts on subsequent pastures.
- **Drop `use=False` craft conversions** at `PendingHarvestFeed`: every `CommitHarvestConversion(use=False)` is dropped (explicitly declining a craft is achievable via direct `CommitConvert`, so the action is redundant; saves consumers from spending evaluation on a no-op). Added per MCTS_DESIGN §7.0 but kept in the regular wrapper because it's a correctness-preserving simplification that benefits all agents.
- **Min-begging** at `PendingHarvestFeed`: among enumerated `CommitConvert` options, keep only those tying for the minimum begging count. Begging is computed directly from `cooking_rates(state, player_idx)` and the action's consumed amounts; no dependency on the harvest-feed frontier.

**Strict-wrapper additions** (per MCTS_DESIGN §7):
- **Cultivation sow-max (§7.1)** at `PendingSow` with `initiated_by_id == "cultivation"`: collapse the legal CommitSow set to the single max-`(grain+veg)` commit; grain-priority tiebreak.
- **Grain-Utilization veggie auto-max (§7.2)** at `PendingSow` with `initiated_by_id == "grain_utilization"`: for each `(grain, veg)` commit require `veg == min(veggies_in_supply, empty_fields - grain)`. The player chooses grain; veg is auto-maxed to fill remaining empty fields.
- **Fencing patterns (§7.3)** at `PendingBuildFences`: 9 hand-curated rules keyed on `(existing pastures, wood count)`. Pasture-identity semantics distinguish rule 7 (subdivision of a single 2×2) from rules 8/9 (cell-set union). Wood counts are EXACT (not lower bounds). If a state matches multiple rules, the allowed-action set is the union. If no rule matches, the filter is inert.
- **Harvest-feed cap (§7.4)** at `PendingHarvestFeed`: if more than 7 `CommitConvert` options remain, keep the top-5 by `evaluate_hubris_v3(step(state, a), decider, cfg)` ranking plus 2 random samples drawn without replacement. Crafts and any other actions always pass through unchanged — sub-sampling crafts is avoided because dropping a strategically important one would hurt and there are typically ≤3 of them.

Every filter routes through `_safe_narrow(filtered, fallback)`: if narrowing would empty the action set, the filter is skipped and the original options stand. This guarantees both wrappers are always a subset of the unrestricted set of size ≥ 1 (or 0 only when the input is empty).

The PlaceWorker layer (empty pending stack) is a no-op for both wrappers — no restriction is applied to top-level worker placement.

See **`CHANGES.md`** Change 11 for the regular wrapper's design rationale and empirical evaluation, **`MCTS_DESIGN.md`** §7 for the strict additions, and CLAUDE.md Phase 2 (action-space restriction) for the convention.

---

### `agricola/agents/mcts.py`

MCTS agent implementing the design in **`MCTS_DESIGN.md`**. Vanilla UCT + FPU + DAG-with-transpositions + leaf-evaluation (no rollouts) + macro-enumeration for Fencing.

**`MacroFencingAction(label: str)`** — MCTS-internal action type representing one complete fencing chain. Never reaches the engine; the agent translates it into a real engine-action sequence via the parent's `macro_sequences[macro_action]` lookup. `label` distinguishes macros from the same parent ("greedy", "random_0", "random_1", …).

**`MCTSNode`** — `@dataclass(eq=False)` (identity equality, identity hashing). Fields: `state` (frozen GameState), `decider` (cached `decider_of(state)`), `search` (back-reference to the owning `MCTSSearch`), `parents` (list of MCTSNode refs; in-degree typically 1-3 under transposition dedup), `children` (dict[Action, MCTSNode]), `action_from_parent` (one incoming edge, debugging only), `visits` / `value_sum` (running stats in this node's decider's frame), `macro_sequences` (populated only on fencing-trigger parents — dict[MacroFencingAction, list[Action]] keyed by macro action), `_legal_actions` / `_unvisited_actions` (lazy per-node caches; populated on first descent — direct field access ~10ns on every UCT traversal).

**`MCTSSearch`** — owns the `transpositions: dict[GameState, MCTSNode]`, the `root` ref, `legal_actions_fn` (default = a strict wrapper bound to `self.rng`), `evaluator_config` (default `DEFAULT_CONFIG_V3`), `n_random_fencing` (default 4), `rng` (numpy Generator, seeded), and `heuristic` (a `HubrisHeuristicV3` instance constructed once for greedy macro-fencing chains, using the same `legal_actions_fn`). Methods: `find_or_create_node(state, parent=None, action_from_parent=None)` (deduplicates via transpositions), `add_edge(parent, child, action)` (single choke point for DAG edge creation; dedups parent in `child.parents`), `re_root(new_root)` (BFS from new_root, prune `transpositions` to live subtree, set `self.root`), `evaluate_leaf(state)` (P0-frame margin: at terminal returns `evaluate_hubris_v3(state, 0)` directly since that already returns `own − opp` via `_terminal_margin_value`; mid-game returns `evaluate_hubris_v3(state, 0) - evaluate_hubris_v3(state, 1)`), `expand_macros(parent_node, raw_actions)` (replaces fencing-trigger actions in `raw_actions` with `MacroFencingAction` children — side effects: creates the macro child nodes via `find_or_create_node`, writes each macro's full engine-action sequence to `parent_node.macro_sequences`).

**Macro-fencing pipeline** (`_generate_fencing_macros` + helpers): three phases per macro: (1) **entry** (`_enter_pbf`) — auto-step through singleton decisions until `PendingBuildFences` is on top; needed for trigger 1 because `PlaceWorker("fencing")` pushes the wrapper `PendingFencing` before `PendingBuildFences` appears (the singleton `ChooseSubAction("build_fences")` lands us in PBF); (2) **chain body** (`_run_pbf_body`) — while `_pbf_on_top(state)` (the MCTS_DESIGN §5.4 predicate), pick one action via the policy (greedy = `self.heuristic`; random = uniform random over `legal_actions_fn`); (3) **exit / wrapper drain** (`_drain_wrapper`) — auto-step through any remaining singleton decisions of the decider so the outer `Stop(PendingFencing)` is part of the recorded macro. Skipped for trigger 2 because after PBF pops we're back at `PendingFarmRedev`, where the agent's next non-fencing decision belongs to normal MCTS. Macros dedup'd by endpoint state within this parent; greedy always added first; up to `1 + n_random_fencing` distinct macros per trigger.

**`MCTSAgent`** — implements the Agent protocol. Takes a pre-built `MCTSSearch` plus agent-level config: `sims_per_move` (default 500), `c_uct` (default 1.4), `fpu_offset` (default 0.0), `action_selection_temperature` (default 0.2), `rng_seed`. On each `__call__(state)`: if `_pending_macro_actions` is non-empty (mid-macro), pop and return the next queued engine action without running MCTS or re-rooting. Otherwise: `find_or_create_node(state)` → `re_root(root)` → run `sims_per_move` sims → pick an action via softmax over visit counts (`probs[a] ∝ counts[a]^(1/T)`, falls back to uniform when all counts are zero). If a `MacroFencingAction` is picked, queue the macro's `sequence[1:]` in `_pending_macro_actions` and return `sequence[0]` (the trigger action). Per-sim cost: ~100-200µs (descent through K existing nodes ≈ K few-µs of dict lookups + arithmetic, expansion ≈ 40µs `step` + transposition hash, leaf eval ≈ 50-100µs).

**Three usage modes:**
- **Separate trees**: each MCTSAgent has its own MCTSSearch (used for matches vs other agent types).
- **Shared tree via shared agent**: pass the same `MCTSAgent` instance to both slots in `play_game` (used for symmetric self-play).
- **Shared tree via shared MCTSSearch**: construct one `MCTSSearch` and pass it to multiple `MCTSAgent` instances (trees shared, agent-level config can differ per seat).

**Lazy-import shims** at module bottom (`_lazy_default_config_v3` / `_lazy_evaluate_hubris_v3` / `_lazy_hubris_v3_class` / `_lazy_make_strict_legal`) keep the module load cheap by deferring `agricola.agents.heuristic` imports until first use.

**Two corrections vs the original MCTS_DESIGN spec** (documented in code + in `MCTS_DESIGN.md`'s implementation-notes section): (a) the engine's `ChooseSubAction` at `PendingFarmRedevelopment` for the fencing branch is named `"build_fences"` (not `"fences"` as the spec text reads); (b) `PlaceWorker("fencing")` pushes `PendingFencing` (a wrapper) before `PendingBuildFences` is reached, so a literal "PBF on top" predicate would terminate the chain immediately — the implementation handles the wrapper via the explicit entry/exit phases, preserving `_pbf_on_top` as the chain-body predicate per the spec's intent.

---

### `agricola/agents/nn/__init__.py`

Re-exports the NN subpackage's **torch-free** public surface so external code can `from agricola.agents.nn import X` regardless of internal layout. Exports: `DATA_VERSION`, `ENCODING_VERSION`, `ENCODED_DIM`, `DecisionSnapshot`, `GameRecord`, `DataVersionMismatch`, `compute_winner`, `load_game_records`, `play_recording_game`, `encode_state`, `feature_names`.

The subpackage is split into torch-free modules (`schema.py`, `recording.py`, `encoder.py`) and torch-using modules (`dataset.py`, `model.py`, `training.py`, `agent.py`). The torch-using modules are intentionally **NOT** re-exported here — importing them eagerly would pull torch into the data-generation path, defeating the import-cost split. External code must import them explicitly: `from agricola.agents.nn.dataset import build_datasets`, `from agricola.agents.nn.model import NormalizedValueModel`, `from agricola.agents.nn.training import train`, `from agricola.agents.nn.agent import NNAgent`. See **`FIRST_NN.md`** §11.1 for the file-by-file rationale.

---

### `agricola/agents/nn/schema.py`

On-disk schema for the NN training dataset. No PyTorch dependency.

- **`DATA_VERSION: int = 1`** — guards the on-disk dataset shape. Stamped onto every `GameRecord`; verified hard-fail at load time. Bump policy in **`FIRST_NN.md`** §11.4.
- **`DecisionSnapshot`** — frozen dataclass: `state, chosen_action, decider_idx`. One per non-singleton decision; the snapshot inclusion rule (§6.2) excludes singleton states.
- **`GameRecord`** — frozen dataclass: per-game metadata (`game_idx, seed, p0_config_path, p1_config_path, p0_temperature, p1_temperature`), final scoring (`p0_final_score, p1_final_score, winner`), `terminal_state` (a `GameState` at `phase=BEFORE_SCORING`, stored once per game; used both as audit anchor and as one extra training pair per §5.1), and `decisions: tuple[DecisionSnapshot, ...]`.
- **`DataVersionMismatch`** — raised on `load_game_records` when a record's `data_version` doesn't match the current `DATA_VERSION`. Hard fail so silent drift is impossible.
- **`load_game_records(path)`** — pickle-load wrapper that runs the `DATA_VERSION` check on every loaded `GameRecord`. Returns `list[GameRecord]`.
- **`compute_winner(s0, s1, tb0, tb1)`** — score-then-tiebreaker → winning player index (0 or 1) or `None` for true tie. Used by `play_recording_game` at game-end.

---

### `agricola/agents/nn/recording.py`

Single-game recording driver. Plays one full game between two agents from an initial state to terminal; captures every non-singleton decision plus the terminal state plus final scoring into a complete `GameRecord`.

- **`play_recording_game(initial_state, p0_agent, p1_agent, *, game_idx, seed, p0_config_path, p1_config_path, p0_temperature, p1_temperature, legal_actions_fn=restricted_legal_actions)`** — the public function. Plays the game, returns a `GameRecord` stamped with the current `DATA_VERSION`.

Key invariants (documented in the function docstring):
- The snapshot's `state` field is captured **before** the agent call so it matches what the agent saw — re-ordering this code would silently store the post-step state and break training data semantics.
- Singleton states are skipped using the same `legal_actions_fn` the agent uses, so "non-singleton" matches between recorder and agent.
- No additional randomness is introduced — given pre-seeded agents and a deterministic `initial_state`, the `GameRecord` is fully reproducible (load-bearing for the resume-on-existing protocol in `scripts/nn/generate_training_data.py`).

No PyTorch dependency. Depends only on engine (`step`, `legal_actions`, `score`, `tiebreaker`) and the `Agent` protocol.

---

### `agricola/agents/nn/encoder.py`

Input-vector encoder for the NN value function. No PyTorch dependency — output is `np.ndarray(float32)`; the training pipeline converts at the model boundary via `torch.from_numpy`.

- **`ENCODING_VERSION: int = 1`** — guards the encoder's output schema (input vector shape + feature ordering baked into a trained model's first layer). Stamped into `NormStats` saved alongside checkpoints; the model's `load` path raises `EncodingVersionMismatch` when versions disagree. Bump whenever `encode_state` would produce a different output for the same input state. Bump policy in **`FIRST_NN.md`** §11.4.
- **`ENCODED_DIM: int = 170`** — flat feature-vector length. Used as the model's input dimension. Equals 54 (own-player block) + 54 (opponent block) + 54 (shared / board) + 8 (mid-action singletons).
- **`encode_state(state, player_idx) -> np.ndarray`** — flat-feature encoder per **`FIRST_NN.md`** §4. Composes `_player_features(state, player_idx)` ×2 (own + opponent), `_shared_features(state)`, `_midaction_features(state)`. Terminal states (`phase == BEFORE_SCORING`) handled per §4.5: a `game_end_indicator` bit flips on and a fixed set of next-decision features is forced to zero. Returns a length-170 float32 array.
- **`feature_names(state=None)`** — parallel list of names matching `encode_state`'s output indices. Used for per-feature debugging / interpretability / norm-stats audits. If `state` is provided, the names reflect the active pending frame's mid-action context; otherwise generic placeholders are used.

Internal helpers (`_player_features`, `_shared_features`, `_midaction_features`, `_frame_subaction_categories`, `_accum_amount`, `_assemble`) build the per-block feature tuples and flatten into the final array. The encoder is deterministic and side-effect-free.

---

### `agricola/agents/nn/dataset.py`

PyTorch dataset builders. Imports torch. Not re-exported from `__init__.py`.

- **`NormStats`** — frozen dataclass: per-feature input mean (`np.ndarray`, shape `(ENCODED_DIM,)`) + per-feature input std + scalar target-margin std + `encoding_version`. Fit on the **training split only**, then applied to all three splits. Persisted alongside the model in `save(path)` / `load(path)` so inference normalizes identically.
- **`_ExampleDescriptor`** — lightweight (game_idx, snapshot_idx_or_terminal, player_idx) tuple. Decoupled from games so descriptor enumeration is cheap and games are encoded just-in-time.
- **`_enumerate_state_keys(games)`** — produces one `(game_idx, is_terminal, snapshot_idx)` key per (state, augmentation). Used for **paired sub-sampling at state-level** so any subset of descriptors includes both perspectives of any sampled state.
- **`_expand_keys_to_descriptors(keys, games)`** / **`_expand_to_descriptors(games)`** — expand state-keys into dual-perspective `_ExampleDescriptor`s (one per player_idx).
- **`_encode_one(desc, games)`** — encodes a single descriptor to `(features, target_margin)`. Target = `score(terminal_state, descriptor.player_idx) − score(terminal_state, 1 - descriptor.player_idx)` (perspective-margin).
- **`_encode_descriptors(descriptors, games)`** — vectorized encoding loop; returns `(X, y_raw)` numpy arrays.
- **`_compute_norm_stats(X_train, y_train_raw)`** — fits `NormStats` from the train split (per-feature mean/std on inputs; scalar std on the raw margin targets).
- **`AgricolaValueDataset`** — `torch.utils.data.Dataset` wrapping a `(X, y)` pair plus its `NormStats`; `__getitem__` returns `(features, normalized_target)`. Long tensors stay on CPU; the DataLoader pins memory if GPU training is requested.
- **`load_all_games_from_runs(run_dirs)`** — concats all `GameRecord`s across one-or-more run directories (each containing `games/worker_*.pkl`).
- **`_split_games_by_index(games, train_frac, val_frac)`** — splits the game list by game-index (not by snapshot) so train/val/test never see the same game's terminal-margin.
- **`build_datasets_from_games(games, *, train_frac, val_frac, ...)`** — full pipeline from in-memory games to `(train_ds, val_ds, test_ds, stats)`. Used by tests that build small game lists ad-hoc.
- **`build_datasets(run_dirs, ...)`** — disk-side entry point. Calls `load_all_games_from_runs` then `build_datasets_from_games`. Used by `train(...)` and standalone analysis scripts.

---

### `agricola/agents/nn/model.py`

PyTorch model + normalization wrapper. Imports torch. Not re-exported from `__init__.py`.

- **`ConfigurableMLP`** — `nn.Module` with configurable input_dim, hidden_dims (list of layer widths), activation (`"gelu"` default), dropout (default 0), and optional LayerNorm between layers. The last linear projection is to `output_dim` (default 1); composable as a sub-encoder by giving a non-1 output_dim and stacking another module on top. Initialized with Kaiming-normal weights on Linear layers.
- **`NET_REGISTRY: dict[str, callable]`** — name → factory map for nets. Lets training-config JSONs name an architecture (e.g. `"mlp"`) without hard-coding the class.
- **`EncodingVersionMismatch`** — raised on `NormalizedValueModel.load(path)` when the saved checkpoint's `encoding_version` doesn't match the current `ENCODING_VERSION`. Hard fail so a model trained with a different feature layout can't be silently used.
- **`NormalizedValueModel`** — `nn.Module` wrapping a `ConfigurableMLP` (or any net with `forward(x) -> y`) plus fixed input/output normalization. Three fields registered as buffers (so they move with `.to(device)` and persist across `state_dict()`): `input_mean`, `input_std`, `target_std`. `forward(x)` returns the **normalized** output (used in training MSE loss). `predict_margin(x)` returns the **raw margin** in points (used at inference): denormalizes by multiplying by `target_std`. `save(path)` writes `{state_dict, stats}` to one `.pt` file; `load(path)` reads back and reconstructs the model + `NormStats`, raising `EncodingVersionMismatch` on version skew.

---

### `agricola/agents/nn/training.py`

Training-loop library. Imports torch + matplotlib. Not re-exported from `__init__.py`.

- **`setup_seeds(seed)`** — sets numpy + torch RNGs.
- **`make_run_id()`** — timestamp-based run id (e.g. `20260529_113000`).
- **`current_git_sha()`** — best-effort `git rev-parse HEAD`; empty string on failure.
- **`train_one_epoch(model, loader, optimizer, device)`** — one pass over the training loader. Returns mean-MSE for the epoch.
- **`evaluate(model, loader, device)`** — `model.eval()` + `torch.no_grad()` pass. Returns `{"mse": ..., "mae": ..., "preds": ndarray, "targets": ndarray}` (preds/targets in raw margin units for downstream calibration plots).
- **`print_header()` / `print_epoch_line(entry)`** — human-readable progress to stdout.
- **`save_curves_plot(log, path)` / `save_calibration_plot(preds, targets, path)`** — matplotlib helpers that gracefully no-op if matplotlib isn't available (`return False`).
- **`train(run_dirs, out_dir, *, hidden_dims=[256, 256], activation="gelu", dropout=0.0, lr=1e-3, weight_decay=1e-4, batch_size=512, max_epochs=50, early_stop_patience=8, train_frac=0.8, val_frac=0.1, ...) -> tuple[dict, Path]`** — the public programmatic entry. Loads games, builds datasets, fits `NormStats`, constructs `NormalizedValueModel`, runs AdamW + early-stop on val MSE, saves best checkpoint + training-curves plot + calibration plot + metadata JSON. Returns `(metadata_dict, best_checkpoint_path)`. The CLI wrapper at `scripts/nn/train_first.py` is just argparse + a `train(**kwargs)` call.

---

### `agricola/agents/nn/agent.py`

`NNAgent` — drop-in `HeuristicAgent` subclass backed by a trained `NormalizedValueModel`. Imports torch. Not re-exported from `__init__.py`.

- **`nn_evaluator(state, player_idx, model) -> float`** — single forward pass on `encode_state(state, player_idx)`. Returns the model's margin estimate from `player_idx`'s perspective. Relies on dual-perspective augmentation (A) at training time to handle either perspective; provides no antisymmetry guarantee at inference.
- **`nn_evaluator_differential(state, player_idx, model) -> float`** — the differential (D) evaluator from **`FIRST_NN.md`** §8. Encodes both perspectives, runs ONE batched forward pass (batch-of-2), returns `V_diff = V(encode(s, 0)) - V(encode(s, 1))` for P0 and `-V_diff` for P1. Exactly antisymmetric by construction (test in `tests/test_nn_agent.py` asserts `V_diff(s, 0) == -V_diff(s, 1)` to 1e-5).
- **`NNAgent(model, *, differential=True, lookahead="turn", seed=0, temperature=0.0, legal_actions_fn=None)`** — thin `HeuristicAgent` subclass selecting the evaluator based on `differential`. `model.eval()` set at construction; queries wrapped in `@torch.no_grad()` on both evaluators. Device queried once via `next(model.parameters()).device` so encoded inputs land on the same device.

Drop-in compatibility: works with `play_match.py`, `play_game`, the per-seat restricted/strict flags. The only behavioral difference vs `HubrisHeuristicV3` is the evaluator function.

### `tests/__init__.py`

Empty package marker. Makes `tests` importable as a Python package. No code here.

---

### `tests/factories.py`

Prefabricated-state helpers used across test files. Each helper takes a state and returns a NEW state (no mutation). Helpers include `with_resources`, `add_resources`, `with_animals`, `with_house`, `with_majors`, `with_minors`, `with_grid`, `with_fields`, `with_sown_fields`, `with_space`, `with_pending_stack`, `with_phase`, `with_round`, `with_current_player`, `with_people`. Tests compose them to reach any state — including states unreachable through gameplay (e.g., a player who has played Potter Ceramics, which requires minor-improvement card play paths that aren't implemented yet). This is the project-wide convention for test state construction; see task_files/TASK_5.md "Testing principle: prefabricated states" for rationale.

### `tests/test_utils.py`

Test-side multi-action helpers and the random-agent driver. NOT a test file despite the `test_` prefix — pytest collects no test functions from it because none start with `test_`.

- `run_actions(state, actions)` — apply a scripted sequence of actions; validate each is legal before applying. Used by tests that walk through a specific scenario.
- `IMPLEMENTED_NON_ATOMIC_SPACES`, `_is_implemented_action`, `filter_implemented(actions)` — filter `legal_actions` output to actions `step` can apply. `IMPLEMENTED_NON_ATOMIC_SPACES = frozenset(NONATOMIC_HANDLERS.keys())` — currently covers every non-atomic space (all 12), so the filter is effectively a no-op today; it stays in place for forward-compat as new action types may surface in `legal_actions` before their `step` handler does. Non-`PlaceWorker` actions (including the Task-7 harvest commits `CommitHarvestConversion` / `CommitConvert` / `CommitBreed`) are accepted unconditionally — they're only reachable when the pending stack already has an implemented frame.
- `random_agent_play(state, seed)` — plays a random-action game to `Phase.BEFORE_SCORING`. Returns `(terminal_state, trace)`. Raises if the agent gets stuck (would indicate a bug). Used by the end-to-end engine smoke test.

---

### `scripts/play_match.py`

Match-runner library + standalone CLI. Used by `scripts/tune_heuristic.py` as its inner-loop game-runner, and as a stand-alone head-to-head tool from the command line.

Library API:
- **`play_match(p0_factory, p1_factory, seeds) -> MatchResult`** — runs one game per seed; each game uses `setup(seed)` and the factories' agents; aggregates win/draw/loss counts (with tiebreaker), per-game scores and tiebreaker values, average score margin, elapsed time. Factories are `Callable[[int], Agent]` (game_seed → Agent), letting callers decide how the game seed maps to the agent's RNG seed.
- **`MatchResult`** / **`GameResult`** — frozen dataclasses for the aggregate and per-game records. `MatchResult.summary_line()` produces a one-line summary.

CLI: `python scripts/play_match.py --p0 hubris_v3 --p1 hubris --n 100`. Supports `--seeds RANGE` (e.g. `--seeds 0-29,42,1000-1099`), `--temperature`, `--lookahead`, `--per-game` (per-game output table), and per-seat **`--p0-restricted`** / **`--p1-restricted`** flags that wrap the respective seat's agent in `restricted_legal_actions` (each seat is independent — supports apples-to-apples restricted-vs-unrestricted matchups). Agent type names match the play_web/play_heuristic_game convention: `human` (not for play_match), `random`, `simple`, `hubris` (= V1+T2), `hubris_v1` (V1+default), `hubris_v2`, `hubris_v3`.

---

### `scripts/tune_heuristic.py`

CMA-ES tuner for ONE TUNABLE category at a time. Supports both V1 and V3 architectures via `--category` dispatch. See **`V3_TRAINING_PIPELINE.md`** for the full operational guide.

Core mechanics:
- **`TUNABLE`** lists (one per category, in `CATEGORIES` dict): `(name, default, lower, upper, config_path)` tuples. `config_path` is `("field",)` for scalar, `("field", idx)` for tuple, `("field", outer, inner)` for tuple-of-tuples. Each TUNABLE entry defines one CMA-ES dimension.
- **`BASE_CONFIGS`**: `{"default": (DEFAULT_CONFIG, "v1"), "t2": (CONFIG_V1_T2, "v1"), "default_v3": (DEFAULT_CONFIG_V3, "v3")}`. The `_resolve_config(spec)` helper also accepts a JSON file path; loads `best_config` and constructs the right dataclass based on the JSON's `candidate_arch` field.
- **`vector_to_config(x, base, tunable)`** — applies a CMA-ES sample vector to `base` config via the path specs; returns a new config (`dataclasses.replace`).
- **`_eval_candidate(x)`** — top-level (picklable) fitness function. Constructs candidate config + opponent agent, plays `n_seeds` games via `play_match`, returns `-avg_margin` (CMA-ES minimizes).
- **`_init_worker(seeds, baseline_cfg, baseline_arch, base_cfg, base_arch, tunable)`** — Pool initializer, populates worker-side globals so `_eval_candidate` is parameterless.

CLI flags (key ones; full list via `--help`):
- `--category` (e.g. `v3_resources`, `v3_pastures_animals`) — selects the TUNABLE list and architecture.
- `--from <name-or-path>` — warm-start base config. Either a `BASE_CONFIGS` name or a path to a previous run's JSON (loads `best_config`).
- `--baseline <name-or-path>` — opponent agent's config. Same name-or-path semantics.
- `--resume <path.cma.pkl>` — load a previously-saved CMA-ES state and continue. `--max-gens` becomes "additional gens" from the resumed countiter. The script bumps `es.opts["maxiter"]` and calls `es.stop(ignore_list=["maxiter"])` to avoid the saved cap short-circuiting the loop.
- `--n-seeds` (default 50), `--max-gens` (default 10), `--popsize`, `--sigma0`, `--cma-seed`, `--holdout-start`/`--holdout-n` (default 1000/100), `--jobs` (default `cpu_count()`), `--output`.
- **`--restricted`** / **`--no-restricted`** (`argparse.BooleanOptionalAction`, default **ON**). When ON, candidate, baseline, and holdout agents are all constructed with `legal_actions_fn=restricted_legal_actions`. The flag is recorded as `"restricted": bool` in the output JSON; the worker pool's `_init_worker` propagates it via the new `_WORKER_RESTRICTED` global so `_eval_candidate` builds factories consistently across processes.

Per-generation: writes `<output>.json` (best config + history + holdout) and `<output>.cma.pkl` (pickled `CMAEvolutionStrategy`) atomically (temp-file + rename). Stdout is teed to `<output>.log`.

End-of-run logic:
- **x0 fallback**: if `es.best.f` is worse than `sanity_f0` (the fitness of x0 evaluated before the CMA-ES loop), the script overrides `best_x = x0` and reports `best_margin = sanity_margin`. Prevents chain-forward regression when a category's defaults were already near-optimal. Prints an explicit warning when triggered.
- **Auto-update `<arch>_best.json`**: at the very end, **`_enable_best_pointer_update`** (renamed from `_maybe_update_best_pointer`) reads `tuned_configs/<arch>_best.json` (if exists) and copies the new JSON there iff the new run beats the existing one. **Comparison metric changed**: was `holdout.avg_margin`, now `holdout.regression.avg_margin` — measured against a fixed reference baseline (`--regression-baseline`, default `t2`) so chained-baseline drift can't fool the gate. Adds two safety gates: refuses to promote if `regression.n < 30` (insufficient sample), and refuses to promote if the saved best's regression anchor differs from the current run's anchor (`regression_baseline` mismatch).

**Additional flags (post-`267530c`)**:
- **`--fitness {margin,sublinear,truncated,win_rate}`** + **`--fitness-k`** (default `0.5`) — per-baseline fitness aggregation. `margin` (default; legacy) = `mean(m)`. `sublinear` = `mean(sign(m) * |m|**k)` (bounds blowout influence smoothly). `truncated` = `mean(clip(m, -k, +k))` (hard cap). `win_rate` = `wins / n - 0.5` (in `[-0.5, +0.5]`). Plumbed into worker globals via `_init_worker` so the choice is consistent across the Pool.
- **`--rotate-seeds`** (default off) + **`--rotate-start INT`** (default `10000`) — each generation N uses seeds `[rotate_start + N*n_seeds, rotate_start + (N+1)*n_seeds)`. Prevents seed-specific selection bias from compounding across generations; CMA-ES gradient still well-defined within each generation's population.
- **`--validation-pool INT`** (default `0` = off) + **`--validation-pool-start INT`** (default `500`) — per-baseline and regression diagnostics use this fixed seed range, independent of training seeds. Gives a stable diagnostic across generations when `--rotate-seeds` is on (otherwise diag seeds == training seeds and `--rotate-seeds` invalidates the per-baseline cache each gen).
- **`--candidate-r1-force-forest`** (default off) — wraps the candidate's evaluator with `r1_force_forest_bonus` during fitness eval, per-baseline diagnostics, and the final holdout (baselines unaffected). Used when tuning V3 for the wood-rich post-R1 state.
- **`--no-promote`** (default off) — skip the `<arch>_best.json` auto-promotion step entirely.

**Other internal changes (post-`267530c`)**:
- **Parallelized per-baseline diagnostic** — was sequential in master; now spreads diagnostic seeds across the existing worker Pool. Records W-D-L counts per (session-best, baseline) cell (was margin-only).
- **`gen_best_x` in history** — the per-generation best sample's parameter vector is persisted alongside `best_x_so_far` (session-best) in the JSON `history` array. Lets later analysis recover any gen-best config even when session_best didn't update that generation.
- **Per-baseline cache** keyed on `(tuple(session_best_x), tuple(diag_seeds))` — invalidated automatically when rotate-seeds is on without a validation pool, since diag seeds == training seeds in that mode.
- **Baseline-label print** strips `tuned_configs/` prefix and `.json` suffix from path-style baseline specs for compact stdout/log output.

Recommended invocation: `python -O scripts/tune_heuristic.py --category v3_resources --from default_v3 --baseline t2 --max-gens 10` (the `-O` flag strips debug asserts in the engine for ~2× speedup).

---

### `scripts/run_iterative_v3.py`

Orchestrator chaining V3 category-tuning invocations as block-coordinate descent. Calls `scripts/tune_heuristic.py` as a subprocess once per (pass, category) pair. See **`V3_TRAINING_PIPELINE.md`** §5 for the full design.

Per pass, categories run in fixed order:
1. `v3_fields_crops` (60 params)
2. `v3_food` (18 params)
3. `v3_resources` (63 params)
4. `v3_pastures_animals` (101 params)

Each step's `--from` is the previous step's JSON output (cumulative warm-start within a pass). On passes 2+, each step's `--resume` is the same category's pickle from the previous pass (continues CMA-ES from where THIS category last left off, against a now-different warm-start context).

CLI:
- `--n-passes N` (default 3) — full cycles.
- `--max-gens N` (default 10) — per-step CMA-ES generations.
- `--n-seeds N` (default 100) — games per evaluation.
- `--baseline <spec>` (default `t2`) — opponent for all steps.
- `--start-from <path>` (default `tuned_configs/v3_best.json`) — warm-start base for pass 1's first step.
- `--label <str>` (default `iter`) — output filename prefix.
- `--start-step N` — skip the first N-1 steps (for resuming partially-completed iterations).
- `--initial-pickles "cat:path,cat:path"` — pre-populate the per-category pickle map (for resuming specific categories).
- `--dry-run` — print the command sequence without executing.
- **`--restricted`** / **`--no-restricted`** (`argparse.BooleanOptionalAction`, default **ON**). Forwarded to every spawned `tune_heuristic.py` subprocess; default-ON means iter3+ run inside the action-pruned space without any extra flag at the orchestrator invocation.
- `--holdout-n N` — games per category's post-tuning holdout match (default 100; user-added field for tighter auto-update decisions at higher N).

The orchestrator itself is pure-Python — all heavy lifting happens in the spawned `tune_heuristic.py` subprocesses, which write their own `.json`, `.log`, `.cma.pkl` files. The orchestrator's own stdout is captured to `tuned_configs/iter_orchestrator.log` when launched via nohup redirection; that log subsumes each subprocess's stdout (via subprocess inheritance) AND the orchestrator's own step-boundary headers.

---

### `scripts/play_mcts_match.py`

MCTS-vs-opponent match driver. Built on `scripts/play_match.py`'s aggregation pattern (`MatchResult`, `GameResult`, `_winner`), with an MCTS-specific factory and a parallel runner.

**Library API:**
- **`play_match_parallel(spec, seeds, *, jobs, progress=True)`** — runs all games in parallel via `multiprocessing.Pool`. `spec` is a `_MatchSpec` dataclass holding everything a worker needs (V3 config, agent names, MCTS knobs); workers construct agents in-process per game (avoids pickling `MCTSSearch` transposition tables). Streams a per-game line as each game completes (running win/loss/draw tally + avg margin + elapsed + ETA) when `progress=True` and `jobs > 1`. Results sorted by seed at the end for stable `--per-game` output.
- **`_build_agent(name, ...)`** — constructs one agent for a seat; supports `mcts`, `hubris_v3`, `random`. The MCTS factory uses `_MatchSpec`'s `sims_per_move` / `opp_sims_per_move` / `c_uct` / `opp_c_uct` knobs to allow asymmetric MCTS-vs-MCTS configs.
- **`_init_worker(spec)`** — Pool initializer that stashes `_MatchSpec` in worker globals so per-game tasks don't re-pass it.

**CLI** (defaults are mostly the MCTS_DESIGN spec's design defaults):
- `--opponent {hubris_v3, random, mcts}` (default `hubris_v3`) — non-MCTS seat.
- `--mcts-as-p1` — place MCTS at P1 instead of P0.
- `--v3-config <path>` (or `default_v3` / `v3_t1`) — V3 evaluator config; default `DEFAULT_CONFIG_V3`.
- `--sims N` (default 500), `--opp-sims N` — MCTS sims/move (latter for the opponent in MCTS-vs-MCTS).
- `--c-uct F` (default 1.4), `--opp-c-uct F` — UCB exploration constant.
- `--n-random-fencing N` (default 4) — random macros per fencing trigger (in addition to greedy).
- `--fpu-offset F` (default 0.0) — added to FPU virtual-Q.
- `--temperature F` (default 0.2) — action-selection softmax T.
- `--jobs N` (default `cpu_count()`) — parallel workers. For best throughput pick `--n` as a multiple of `--jobs` (a 10-seed run on 8 cores wastes 6 cores on the trailing batch of 2; 16 seeds on 8 cores fills both batches).
- `--seeds RANGE` or `--n N` (default 10) — seeds to play.
- `--per-game` — final per-game table (independent of the streaming progress lines).

Heuristic opponent always uses the same strict-restricted legality as MCTS (via `make_strict_restricted_legal_actions(config=v3_cfg, rng=...)`) — matches the training-pipeline convention so the comparison is fair.

Recommended invocation: `python -O scripts/play_mcts_match.py --opponent hubris_v3 --v3-config tuned_configs/v3_best.json --sims 500 --n 64 --jobs 8`. The `-O` flag strips engine asserts for a meaningful speedup at the per-sim hot path.

`CATEGORY_POPSIZE` maps each category to its CMA-ES popsize (`4 + ⌈3·ln(d)⌉`): 16, 13, 17, 18 for the four V3 categories respectively. `CATEGORY_ORDER` defines the fixed per-pass sequence.

---

### `scripts/nn/generate_training_data.py`

Batch generator for NN training data. Plays N games between agents drawn from an approved-config ensemble and writes the resulting `GameRecord`s to disk under `data/nn_training/runs/<run_id>/games/worker_NN.pkl`. Default ensemble = the 8 configs from **`tuned_configs/DATA_GEN_ENSEMBLE.md`**. Design spec in **`FIRST_NN.md`** §6.

Core mechanics:
- **`compute_plan(n_games, base_seed, approved_configs)`** — deterministic per-game work-item list. Each game's RNG seeded by `base_seed * 100000 + game_idx` so per-game draws are independent of base seed magnitude. Draws P0/P1 configs (with replacement) + independent per-agent temperatures from a bimodal distribution (95% uniform [0.3, 1.0] + 5% T=4). Same arguments → same plan (load-bearing for resume).
- **`partition_plan(plan, n_workers)`** — optimally-balanced contiguous slicing (max imbalance = 1 game). Contiguous (not strided) so each worker's pickle file holds a known range of game_idxs.
- **`_resolve_config_cached(spec)`** + **`_build_agent(spec, seed, temperature, legal_actions_fn)`** — agent factory. Spec dispatch: `"random"` → `RandomAgent`, `"t2"` → `HubrisHeuristicV1` + `CONFIG_V1_T2`, JSON path → load `best_config`, dispatch on `candidate_arch` (`"v1"` → `HubrisHeuristicV1`, `"v3"` → `HubrisHeuristicV3`). Per-worker cache so JSON configs aren't reloaded each game.
- **`_worker_play_games(args)`** — worker entry point. Resume: loads existing pickle (if any), skips game_idxs already complete. Atomic per-game pickle writes via `_write_pickle_atomic` (temp file + rename) so a killed mid-write doesn't corrupt the file. Per-game errors caught with full traceback, logged in the per-worker errored list, run continues.
- **`generate_dataset(n_games, *, out_dir=None, n_workers=None, base_seed=1000000, approved_configs=None, restricted=True, verbose=True)`** — programmatic entry point. Returns the final metadata dict. CLI `main()` is a thin wrapper.

CLI: `python scripts/nn/generate_training_data.py --n-games 5000 --n-workers 8`. Resume an interrupted run via `--out-dir data/nn_training/runs/<run_id>`. Other flags: `--base-seed`, `--approved-configs`, `--restricted` / `--no-restricted` (default ON).

Empirical: 1000 games on 8 workers takes ~131s; 5000 games projected at ~11 min. Storage: ~48 KB per game (~240 MB for 5000 games).

`metadata.json` records run-level state: `run_id`, `code_sha`, `host`, `approved_configs`, `temperature_distribution` (description string), `restricted`, `n_workers`, `planned_games`, `completed_games`, `errored_games`, `base_seed`, `data_version`. Updated once at startup, overwritten at end with final counts.

---

### `scripts/nn/validate_dataset.py`

Post-generation invariant checker for NN training datasets per **`FIRST_NN.md`** §6.6.

- **`discover_worker_pickles(run_dir)`** — lists `run_dir/games/worker_*.pkl` files.
- **`load_all_records(pkl_paths)`** — loads all `GameRecord`s; `load_game_records` enforces `DATA_VERSION` during load.
- **`sample_records(records, sample_size, seed)`** — optional random subset via deterministic `np.random.default_rng(seed)` sampling without replacement.
- **`check_record(rec, pkl_path=None) -> list[ValidationFailure]`** — runs all per-record invariants on one record. Continues past individual failures so the full report shows everything wrong with the record, not just the first.
- **`validate_run(run_dir, *, sample_size=None, sample_seed=0, verbose=True)`** — programmatic entry point. Returns the full failure list (empty = pass).

Invariants checked (per FIRST_NN.md §6.6):
1. `data_version == DATA_VERSION` (already enforced by loader; defensive double-check).
2. `chosen_action ∈ filter_implemented(legal_actions(snap.state))` for every snapshot (engine consistency).
3. `len(filter_implemented(legal_actions(snap.state))) > 1` for every snapshot (non-singleton snapshot inclusion rule).
4. `snap.state.phase != BEFORE_SCORING` for every snapshot (terminal states should be in `terminal_state`, not in `decisions`).
5. `len(rec.decisions) > 0` for every game.
6. Stored `p0_final_score` / `p1_final_score` match `score(terminal_state, *)` — catches scoring drift between recording and validation.
7. `snap.decider_idx == decider_of(snap.state)` for every snapshot.
8. `rec.terminal_state.phase == BEFORE_SCORING`.

Failure reports group by check type + locate offending `game_idx` + snapshot index + source `pkl_path`. Exit codes: 0 (pass), 1 (failures), 2 (invalid run dir).

CLI: `python scripts/nn/validate_dataset.py --run-dir data/nn_training/runs/<run_id>`. `--sample-size N` for random-subset validation, `--quiet` for exit-code-only mode, `--max-failures-shown N` to cap the per-failure detail output (defaults to 20).

---

### `scripts/nn/train_first.py`

Thin CLI wrapper over `agricola.agents.nn.training.train(...)`. argparse for hyperparameters (`--run-dirs`, `--out-dir`, `--hidden-dims`, `--activation`, `--dropout`, `--lr`, `--weight-decay`, `--batch-size`, `--max-epochs`, `--early-stop-patience`, `--train-frac`, `--val-frac`, `--seed`, `--verbose`) and a single `train(**kwargs)` call. Output: best-model checkpoint (`.pt`) + training-curve plot + calibration plot + metadata JSON in the configured out-dir.

CLI: `python scripts/nn/train_first.py --run-dirs data/nn_training/runs/<run_id> --out-dir nn_runs/<label> --hidden-dims 256 256 --max-epochs 50`.

---

### `scripts/nn/eval_vs_ensemble.py`

Round-robin evaluation of a trained NN checkpoint against the 8-config data-gen ensemble. Loads the checkpoint via `NormalizedValueModel.load`, wraps it in `NNAgent`, runs `play_match.py` against each ensemble entry, prints a per-opponent W-D-L + average-margin table.

CLI: `python scripts/nn/eval_vs_ensemble.py --model nn_runs/<label>/best.pt --n-games 100`. Per-opponent results printed as games complete; aggregate summary at the end.

---

## Top-level entry points

Files at the repo root that run a game, drive matches, or serve the browser UI. Not part of `agricola/` or `scripts/`; documented here for completeness.

### `play_web.py`

Browser-based human-play UI. Serves a JSON game state over HTTP to a JavaScript frontend (`templates/index.html`, `static/app.js`); shares formatting helpers with `play.py` (`HOUSE_MATERIAL_NAME`, `MAJOR_NAMES`, etc.). The Session object holds one in-flight game and exposes routes for state polling, action submission, AI step-through, and trace download.

Agent construction lives in `_build_agent(seat_type, seed)` and dispatches on a string seat label (`human`, `random`, `simple`, `hubris`, `hubris_v1`, `hubris_v2`, `hubris_v3`). The `hubris` label resolves to V1 architecture + `CONFIG_V1_T2`; `hubris_v3` resolves to V3 with the config selected by `--v3-config` (path to a `tune_heuristic.py` JSON, `best_config` field loaded), falling back to `CONFIG_V3_T1`, then `DEFAULT_CONFIG_V3`.

CLI flags:
- `--seed N` — engine RNG seed (default: time-based).
- `--seats P0 P1` — seat assignments at launch (browser dropdown can re-pick later). Choices match `AGENT_TYPES`.
- `--host`, `--port`, `--no-browser` — server config.
- `--v3-config PATH` — load a tuned V3 config from a `tune_heuristic.py` JSON file's `best_config` field. Used whenever a seat is `hubris_v3`.
- **`--restricted`** / **`--no-restricted`** (`argparse.BooleanOptionalAction`, default **ON**). When ON, every AI seat (random, simple, all heuristics) is constructed with `legal_actions_fn=restricted_legal_actions` so the browser UI agent behaves the same way it does during fitness evaluation. Matches `scripts/tune_heuristic.py` / `scripts/run_iterative_v3.py` defaults. Use `--no-restricted` to play against agents that see the full unrestricted set. The flag value is captured in a module-level `_RESTRICTED` global read by `_build_agent`, and the startup line prints `AI seats use restricted_legal_actions: ON/OFF` for visibility.

The stable command to play against the current strongest V3 with the wrapper active:

```bash
python play_web.py --seats human hubris_v3 --v3-config tuned_configs/v3_best.json
```

(No flag change needed — `--restricted` is ON by default.)

---

## `tuned_configs/` — named configs (post-`267530c`)

Persistent JSON artifacts written by `scripts/tune_heuristic.py`. Each completed tuning run produces `<label>_<timestamp>.json` (best config + history + holdout), `<label>_<timestamp>.log` (human-readable progress mirror), and `<label>_<timestamp>.cma.pkl` (full CMA-ES state for resume). The named configs below are the strategically meaningful ones — pointers used by drivers, training warm-starts, and the data-generation ensemble. Round-robin percentages refer to the 8-config data-gen ensemble round-robin. See **`tuned_configs/DATA_GEN_ENSEMBLE.md`** for the full ensemble write-up.

- **`v3_best.json`** — current champion (auto-maintained by `scripts/tune_heuristic.py`'s `_enable_best_pointer_update`). NOW points to **alphas_gen_7** (was gen_16). Holdout vs `t2`: 100-0-0 +15.32.
- **`alphas_gen_7.json`** — same config as `v3_best.json` (stable path mirror; survives future v3_best updates). Final session-best of the 6-category wood_r1 rotation; carries `r1_force_forest_bonus = 1000` baked in. Round-robin: 86.4%.
- **`alphas_gen_1.json`** — first session-best of the alphas-category step in the same rotation. Also carries `r1_force_forest_bonus = 1000`. Round-robin: 81.1%.
- **`panel_gen16.json`** — preserves the just-replaced `v3_best` (gen_16). Reed-first opener; canonical reed-tuned V3 lineage. Round-robin: 58.2%.
- **`panel_gen47.json`** — earlier V3 champion (resources-tune output, gen_47). Round-robin: 30.4%.
- **`panel_gen_25.json`** — alternative V3 (gen_25) from the original resources tune. Round-robin: 38.9%.
- **`panel_gen47_wood020.json`** — gen_47 + `wood_flat_bonus = 0.2`; wood-hoarder exploit baseline. Round-robin: 40.0%.
- **`panel_gen16_temp05.json`** — gen_47 + `temperature = 0.5`; playstyle-diversity baseline. NOT in the data-gen ensemble.
- **`panel_wood_r1.json`** — gen_16 retuned on `v3_resources` only with R1-force-forest applied (60 gens). Pre-rotation wood-tuned variant. Round-robin: 61.1%.

**Description file** alongside the JSONs:
- **`DATA_GEN_ENSEMBLE.md`** — lists the 8-config data-generation ensemble (the round-robin members) with provenance and pairing notes.

**Tuning-run artifacts** (not strategically named — produced by individual `scripts/tune_heuristic.py` invocations):
- `rot_woodr1_*.json` / `rot_woodr1_*.log` / `rot_woodr1_*.cma.pkl` — outputs of the 6-category wood_r1 rotation, one set per `(category, timestamp)`.
- `r1forest_resources_*.json` / `r1forest_resources_v2_*.json` and `.log` siblings — outputs of the R1-force-forest tuning runs on `v3_resources`.
- `round1_food_*.json` / `round2_pastures_animals_*.json` and siblings — per-category run snapshots used as warm-starts for downstream categories.

These artifact files are not separately load-bearing; they exist to support resume (`--resume <path>.cma.pkl`) and provenance auditing of the named configs above.

---

Per-file coverage descriptions for each `tests/test_*.py` live in **`TEST_DESCRIPTIONS.md`**.
