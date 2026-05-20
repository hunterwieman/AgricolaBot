# Test Descriptions

Per-file coverage descriptions for each `tests/test_*.py`. Offloaded from CLAUDE.md to reduce session-start context; sessions modifying or adding tests can read this file when needed.

For test infrastructure (`tests/__init__.py`, `tests/factories.py`, `tests/test_utils.py`), see **`FILE_DESCRIPTIONS.md`**.

---

### `tests/test_state.py`

Tests for the state dataclasses and the `setup` function. Covers: correct starting food amounts, correct starting room positions, all fences starting False, fresh farmyards have an empty `pastures` cache, correct people counts, all major improvements starting unowned, correct number of stage cards and their correct stage-ordering, determinism (same seed → identical state), `Resources.__add__` / `Resources.__bool__` behaviour, and the Task 5 state fields (empty `pending_stack`, default-empty `future_resources`, `minor_improvements`, `occupations`).

### `tests/test_helpers.py`

Tests for everything in `helpers.py` and the `Farmyard.pastures` cache. Covers: `fences_in_supply` and `stables_in_supply` on fresh and modified farmyards; the pasture decomposition on a range of fence configurations (single-cell pasture, multi-cell, stables inside, subdivided); canonical pasture ordering and structural equality/hashing of equivalent farmyards (the property MCTS subtree sharing depends on); the `enclosed_cells` helper; `extract_slots` including the standalone stable path; `can_accommodate` for feasible and infeasible configurations; `pareto_frontier` for single and multi-type gains with and without cooking rates; `breeding_frontier` for all the breeding food formula branches. All frontier tests assert the complete frontier dict, not just membership of a specific point.

### `tests/test_scoring.py`

Tests for `scoring.py`. Covers: baseline score on a fresh game state (Wood rooms, 2 people, no resources — expected score is deeply negative due to unused spaces and few resources), individual scoring categories in isolation (fields, pastures, animals, major improvements, craft bonuses), and the tiebreaker function.

### `tests/test_legality_atomic.py`

Tests `legal_placements` for the 12 atomic spaces. One or more tests per space. Covers: legal when conditions met, illegal when space is occupied, illegal when space is not yet revealed, illegal when accumulation space is empty (for accumulation spaces), illegal when the player has no workers left to place, and the Wish-specific conditions (room count vs. people count, 5-person cap).

### `tests/test_legality_non_atomic.py`

Tests `legal_placements` for all 12 non-atomic spaces, plus direct tests of every shared helper in `legality.py` (`_can_bake_bread`, `_can_sow`, `_can_plow`, `_can_build_stable`, `_can_afford_room`, `_has_room_placement`, `_can_build_room`, `_can_renovate`, `_can_afford_any_major_improvement`). Cross-cutting checks confirm `fencing` IS present when resources/supply permit, and `lessons` never appears in `legal_placements` output.

### `tests/test_resolution_atomic.py`

Atomic-space resolution tests via `engine.step` (migrated from the removed `resolve_atomic` in Task 5). One or more tests per atomic space. Covers: goods added correctly, accumulated goods reset to zero after taking an accumulation space, worker placed on the space, `people_home` decremented, `starting_player` updated when Meeting Place is taken, Wish-specific checks (`people_total` incremented, `newborns` incremented, `people_home` not incremented for newborn), and Task 5 properties (atomic placements leave `pending_stack == ()`, `current_player` alternates).

### `tests/test_engine.py`

Tests for the engine module: `step`, `_advance_current_player`, `_advance_until_decision`, `_resolve_return_home`, `_resolve_preparation`. Covers:

- Atomic placement basics: effect applied, `people_home` decremented, workers updated, stack stays empty, current_player alternates.
- Stack invariants: atomic placements leave the stack empty; `_advance_until_decision` is idempotent on states returned by `step`.
- `_advance_current_player`: alternates when other player has workers; stays put when other has none.
- Round transitions: WORK ends when both players are at 0 workers; RETURN_HOME resets all action-space workers; RETURN_HOME returns people home but does NOT clear newborns; PREPARATION clears newborns, refills revealed accumulation spaces, increments `round_number`, resets `current_player` to `starting_player`; round-4 RETURN_HOME transitions to `BEFORE_SCORING`.
- Error behaviors: `step` raises on `BEFORE_SCORING`; raises `NotImplementedError` on unknown space-IDs (e.g., `lessons`, which is permanently illegal in the Family game and never surfaces via `legal_placements`).
- End-to-end: random-agent plays rounds 1–4 to `BEFORE_SCORING` for 10 different seeds without raising.
- A meta-invariant test confirming the decider rule (`pending_stack[-1].player_idx == state.current_player` when stack non-empty) holds throughout a deterministic play-through.

### `tests/test_grain_utilization.py`

Tests for the Grain Utilization non-atomic resolution. Uses prefabricated states from `factories.py`. Covers:

- Basic walks: sow-only, bake-only, both-sub-actions in either order yields identical end state.
- Stop legality: illegal before any sub-action committed; legal after sow or bake done; the only legal action when both are done.
- Mid-turn legality recomputation: sow becomes illegal after baking depletes grain; bake becomes illegal after sowing depletes grain; sow remains legal after a partial bake.
- Sow distribution semantics: grain fills earliest fields first, then veg; canonical (row, col) order across non-contiguous fields; `CommitSow(g, v)` with `g+v > empty_fields` is filtered from legal options.
- Cooking rates: Hearth uses 3 food/grain; Hearth wins over Fireplace when both owned; Clay-Oven-only owner reaches `CommitBake` and bakes 1 grain → 5 food (the broader Clay/Stone Oven coverage lives in `test_bake_bread.py`).
- Placement legality: illegal when neither sow nor bake is possible; legal when only one path is open.
- Stack invariants: under the choose-time convention, `ChooseSubAction("sow")` writes `sow_chosen=True` on `PendingGrainUtilization` and pushes `PendingSow`; `CommitSow` pops `PendingSow` without modifying the parent. Symmetric for `bake_chosen` / `CommitBake`.

### `tests/test_potter_ceramics.py`

Tests for the one card implemented in Task 5. Uses prefabricated states; the card cannot be acquired through Task 5 gameplay, so every test sets `minor_improvements` directly.

- `_can_bake_bread` predicate broadening: True when 0 grain + 1 clay + Potter + baker (the headline behavior); False when missing any of {clay, baker, Potter}; True via base check when grain >= 1 (extension doesn't need to fire).
- Full Grain Utilization walk-through with the trigger: setup at 0 grain + 1 clay + Fireplace + Potter, no fields; verify each step (PlaceWorker → ChooseSubAction → FireTrigger → CommitBake → Stop) produces the expected state.
- Single-fire invariant: even with 2 clay, Potter still fires at most once per Bake Bread action.
- Re-eligibility on a fresh `PendingBakeBread` (validates that `triggers_resolved` is frame-scoped, not persistent player state).
- Implicit declination via commit: with 1 grain + 1 clay + Potter, the player can `CommitBake` without firing Potter — the trigger doesn't fire, clay is preserved.
- Both options coexistence: with 1 grain + 1 clay + Potter, both `FireTrigger` and `CommitBake(1)` appear in `legal_actions`.
- Forced fire when no commit possible: with 0 grain + 1 clay + Potter, `legal_actions` returns exactly `[FireTrigger("potter_ceramics")]` (no `SkipTrigger` in this architecture).

### `tests/test_bake_bread.py`

Unit-level coverage of `_execute_bake` and `_enumerate_pending_bake_bread` across the matrix of `(owned_majors, grain_in_supply)` cases. Parametrized test with 13 cases covering each baking improvement in isolation, capped + uncapped combinations, capped-only combinations (cap-sum bounds the legal range), all four owned, and zero-grain edge cases. A separate test exercises the `BAKING_SPEC_EXTENSIONS` registry by registering a synthetic `(cap=1, rate=6)` source under a fixture and verifying the cap computation and greedy allocation pick it up.

### `tests/test_farmland.py`

Tests for the Farmland action space. Covers: basic walk (PlaceWorker → ChooseSubAction → CommitPlow → Stop); Stop legality before/after `plow_chosen`; cell-choice enumeration (non-empty cells, enclosed cells, non-adjacent cells filtered out); placement illegality when no plow target exists; choose-time flag invariant.

### `tests/test_cultivation.py`

Tests for the Cultivation action space. Covers: plow-only, sow-only, plow-then-sow on newly plowed field, sow-then-plow; Stop legality requires at least one chosen; choose-time flag invariants.

### `tests/test_side_job.py`

Tests for the Side Job action space. Post-Task-5D: uses `PendingBuildStables(max_builds=1)` (the multi-shot pending in its cap=1 degenerate case). Covers: stable-only, bake-only, both; 1-wood stable cost (debited from `PendingBuildStables.cost`); `PendingBuildStables.cost == Resources(wood=1)` and `max_builds == 1` invariants; Potter Ceramics integration; Stop legality; placement illegality when neither sub-action is possible; singleton-Stop state after the single commit (only Stop is legal because `max_builds=1` saturates).

### `tests/test_animal_markets.py`

Tests for the three animal markets (Sheep, Pig, Cattle), parametrized where structure is shared. Covers: PlaceWorker stages animals on `pending.gained` and zeroes the space's `accumulated_amount`; CommitAccommodate pops the parent directly (no Stop step); release-to-food with Cooking Hearth; no food gained without a cooking improvement; the `Stop` action is never in the legal list at a market parent pending; Pareto-dominated configurations are excluded from the legal-actions list; existing animals combine with gained animals in the frontier search.

### `tests/test_major_improvement.py`

Integration tests for the full Major Improvement purchase-then-bake chain. Covers: building each individual major; Cooking Hearth pay-clay vs return-Fireplace payment modes (both options appear in legal actions when both Fireplaces are owned); Well's future_resources update; Clay Oven purchase + free bake (1 grain → 5 food); Clay Oven purchase + skip bake; Stone Oven purchase + free bake (2 grain → 8 food); Clay Oven + Potter Ceramics 0-grain chain (Potter swaps clay for grain before the bake).

### `tests/test_house_redevelopment.py`

Tests for the House Redevelopment action space. Covers: renovate-only and renovate-then-improvement walks; improvement step requires `renovate_chosen` first; Stop legality before / after each step; material progression WOOD→CLAY→STONE; STONE house cannot renovate; renovation cost on `PendingRenovate.cost` for both transitions (1 reed total, not per-room); inner `PendingMajorMinorImprovement.initiated_by_id == "house_redevelopment"` (provenance check).

### `tests/test_farm_expansion.py`

Tests for the Farm Expansion action space — first space using the multi-shot sub-action pending pattern from Task 5D. 25 tests covering: basic walks (rooms-only, stables-only, rooms-then-stables); within-action adjacency chaining for rooms; 4-stable build saturating supply; singleton-Stop states for both supply-exhausted and affordability-exhausted constraints (Approach 2: Stop is always the explicit exit); Stop legality at num_built=0 (illegal in `PendingBuildStables` / `PendingBuildRooms`) and at the parent before any category is chosen; cost on pending parametrized over house material (wood / clay / stone); Farm Expansion's 2-wood stable cost (distinct from Side Job's 1-wood); room adjacency rule + room-inside-pasture exclusion; pasture-cache recompute when a stable lands inside an existing pasture (directly exercises the fix for the latent bug in Task 5C's `_execute_build_stable`); once-per-category rule parametrized over rooms/stables; placement legality (none / rooms-only / stables-only cases); stack invariants (choose-time flag set, no-pop on commit, Stop pops).

### `tests/test_fences.py`

Tests for `agricola/fences.py`. Two layers:

**TASK_6_pre layer (universes + filters).** Grid constant correctness, the filter primitives (`_is_connected`, `_internal_fence_count`, `_perimeter_fence_count`, `_total_fence_count`, `_has_hole`, plus `PERIMETER_EDGE_COUNT_PER_CELL`), and the four universes (sizes pinned to exact values from `python -m agricola.fences`: FULL=1518, FAMILY=762, EXTENDED=193, RESTRICTED=109; no duplicates, lex-on-cells sort, every `UNIVERSE_FULL` / `UNIVERSE_FAMILY` entry passes its four filters, named shapes present, specific shapes absent, full containment chain `UNIVERSE_RESTRICTED ⊆ UNIVERSE_EXTENDED ⊆ UNIVERSE_FAMILY ⊆ UNIVERSE_FULL`, FULL-vs-FAMILY divergence pinned by `PASTURE_CELLS + (0,0)` which is in FULL but not FAMILY).

**TASK_6 layer (edge metadata + helpers).** `PastureCandidate` shape (frozen dataclass with five fields); `_boundary_h_bm` and `_boundary_v_bm` on 1×1s, 2×2, narrow strip, full PASTURE_CELLS; `_adjacency_bm` on corner / edge / interior cells; `UNIVERSE_*_ENTRIES` parallel to `UNIVERSE_*` (same length, same order, derived metadata correct); `ENTRIES_BY_BM` keys cover every bitmap in any universe; `UNIVERSE_*_SMALLEST_ENTRIES` are popcount-1 subsets in lex-on-cells order (13 entries each after the (0, 0) addition); 1×1 at (0, 0) present in all four universes; containment chain preserved post-addition; `pack_fences_h/v` + `apply_fence_edges_h/v` round-trip and additive-union behavior; `compute_new_fence_edges` returns correct deltas + wood cost on empty and pre-fenced farmyards.

### `tests/test_fencing.py`

Engine-level integration tests for the Fencing action space (TASK_6). 35 tests covering: single-pasture basic walk (PlaceWorker → ChooseSubAction → CommitBuildPasture → Stop → Stop); multi-pasture commits in one action with adjacency between them; subdivision of an existing 2×1 into two 1×1s; subdivision canonicalization (only lex-smaller side appears in `legal_actions`); first-pasture-anywhere rule with all 13 ENCLOSABLE 1×1s enumerated; adjacency required for subsequent new pastures; enclosable filter (rooms/fields excluded); wood and fences-in-supply affordability binding; re-stating an existing pasture filtered (zero new edges); Stop legality on both `PendingBuildFences` (illegal at `pastures_built=0`) and `PendingFencing` (illegal until `build_fences_chosen=True`); counter updates across multiple commits; builds-before-subdivisions ordering rule (new pasture then subdivision OK; subdivision then new pasture blocked; `subdivision_started` flag flips on subdivisions only); stack invariants (provenance: parent `"space:fencing"`, child `"fencing"`); `_legal_fencing` predicate true/false matrix; universe swap via kwarg (passing `entries`/`smallest_entries`/`universe_set`) and via module constant rebind; `ACTIVE_FENCE_UNIVERSE_*` defaults to RESTRICTED at fresh import; pasture cache recompute after each commit; random-agent end-to-end smoke across 10 seeds with both `fencing` and `farm_redevelopment` in `IMPLEMENTED_NON_ATOMIC_SPACES`.

### `tests/test_farm_redevelopment.py`

Engine-level integration tests for the Farm Redevelopment action space (TASK_6). 20 tests covering: renovate-only walk; renovate-then-build-fences walk; Build Fences requires `renovate_chosen=True` first; Stop illegal at parent before renovate, legal after; material progression WOOD→CLAY and CLAY→STONE; STONE house blocked (`_legal_farm_redevelopment` returns False); renovation cost on `PendingRenovate` (`Resources(clay=num_rooms, reed=1)` for WOOD→CLAY, `Resources(stone=num_rooms, reed=1)` for CLAY→STONE); inner `PendingBuildFences.initiated_by_id == "farm_redevelopment"` (provenance distinct from Fencing space's `"fencing"`); Build Fences engine reuse — `subdivision_started` ordering rule still works via Farm Redev's entry; `_legal_farm_redevelopment` baseline + missing-reed / missing-clay / missing-stone / STONE-house failure modes; Build Fences not offered post-renovate when no legal pasture commit exists (e.g., player has 0 wood after paying renovate); full-walk stack invariants including provenance at each frame.
