# Test Descriptions

Per-file coverage descriptions for each `tests/test_*.py`. Offloaded from CLAUDE.md to reduce session-start context; sessions modifying or adding tests can read this file when needed.

For test infrastructure (`tests/__init__.py`, `tests/factories.py`, `tests/test_utils.py`), see **`FILE_DESCRIPTIONS.md`**.

---

### `tests/test_state.py`

Tests for the state dataclasses and the `setup` function. Covers: correct starting food amounts, correct starting room positions, all fences starting False, fresh farmyards have an empty `pastures` cache, correct people counts, all major improvements starting unowned, correct number of stage cards and their correct stage-ordering, determinism (same seed → identical state), `Resources.__add__` / `Resources.__bool__` behaviour, and the Task 5 state fields (empty `pending_stack`, default-empty `future_resources`, `minor_improvements`, `occupations`).

### `tests/test_helpers.py`

Tests for everything in `helpers.py` and the `Farmyard.pastures` cache. Covers: `fences_in_supply` and `stables_in_supply` on fresh and modified farmyards; the pasture decomposition on a range of fence configurations (single-cell pasture, multi-cell, stables inside, subdivided); canonical pasture ordering and structural equality/hashing of equivalent farmyards (the property MCTS subtree sharing depends on); the `enclosed_cells` helper; `extract_slots` including the standalone stable path; `can_accommodate` for feasible and infeasible configurations; `pareto_frontier` for single and multi-type gains with and without cooking rates; `breeding_frontier` for all the breeding food formula branches; `cooking_rates` 4-tuple `(sheep, boar, cattle, veg)` with the `(0,0,0,1)` no-cooking fallback for veg; the Task-7 food-payment frontiers — `food_payment_frontier` (food_owed=0 shortcut, partial-pay direct enumeration, Pareto excludes over-conversion, infeasibility returns empty) and `harvest_feed_frontier` (food_owed=0 shortcut, partial-pay configs with begging tradeoffs, three-config invariant for 2 grain + food_owed=2, full-feed-never-dominated invariant, food_payment matches begging-zero subset invariant, animal cooking). All frontier tests assert the complete frontier set/dict, not just membership of a specific point.

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
- Round transitions: WORK ends when both players are at 0 workers; RETURN_HOME resets all action-space workers; RETURN_HOME returns people home but does NOT clear newborns; PREPARATION clears newborns, refills revealed accumulation spaces, increments `round_number`, resets `current_player` to `starting_player`; RETURN_HOME on a HARVEST_ROUND (e.g. round 4) transitions to `HARVEST_FIELD`; non-harvest rounds transition to `PREPARATION`.
- Error behaviors: `step` raises on `BEFORE_SCORING`; raises `NotImplementedError` on unknown space-IDs (e.g., `lessons`, which is permanently illegal in the Family game and never surfaces via `legal_placements`).
- End-to-end: random-agent plays the full 14-round game to `BEFORE_SCORING` for 10 different seeds without raising (`test_random_agent_plays_full_game`; renamed post-Task-7 from `test_random_agent_plays_four_rounds`).
- A meta-invariant test confirming the decider rule (`pending_stack[-1].player_idx == state.current_player` when stack non-empty AND phase==WORK) holds throughout a deterministic play-through. The phase qualifier was added in Task 7 — harvest pendings can legitimately have a different `player_idx` than `current_player` because no worker is placed during harvest; the stack alone identifies the decider.
- `legal_actions_cache()` (added in Change 9): 7 tests covering the opt-in identity-keyed memoizer. Outside any `with` block, `legal_actions` is uncached (`test_legal_actions_uncached_by_default`). Inside, repeated calls on the same state return the cached list (`test_legal_actions_cached_inside_context_manager`). Distinct states get distinct entries (`test_legal_actions_cache_distinguishes_states`, `test_legal_actions_cache_size_grows_with_unique_states`). The cache is dropped on `with` exit (`test_legal_actions_cache_cleared_on_exit`). Nesting is supported (`test_legal_actions_cache_nests`). The cache stays consistent as state evolves via `step` inside the block (`test_legal_actions_cache_step_state_evolution`).

### `tests/test_replace.py`

Tests for `agricola.replace.fast_replace`, the Change-9 performance helper. 14 tests verifying behavioral equivalence with stdlib `dataclasses.replace` across every dataclass shape the engine uses (`Resources`, `Animals`, `Cell`, `ActionSpaceState`, `PlayerState`, `Farmyard`, `GameState`, `BoardState`, and `PendingSow` as a stand-in for the Pending hierarchy with ClassVar fields). Each test constructs an object, calls `fast_replace` and `dataclasses.replace` with the same arguments, and asserts the results are equal. Also covers: no-changes returns equal; original object is not mutated; multi-field updates; chained replace operations. Guards the migration's drop-in assumption — if a future field addition breaks `fast_replace`'s positional construction, these tests fail before any production call site does.

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

### `tests/test_harvest_field.py`

Tests for `_resolve_harvest_field` (Task 7). 11 tests covering: single-grain-field yields 1 grain (cell.grain decrements); single-veg-field yields 1 veg; multiple fields per player each yield 1; empty FIELD cell yields nothing and stays unchanged; both players harvest their own fields independently; `harvest_conversions_used` reset to `frozenset()` on both players (overrides a pre-populated stale set); phase transitions to `HARVEST_FEED`; FEED pendings pushed (one per player, SP on top, `len == 2`); pasture cache preserved (fields cannot lie inside pastures); newborns NOT cleared (survive into FEED for the 1-food discount); the pushed FEED pendings carry no `food_owed` field — payment is deferred to `CommitConvert` and each player's food supply is untouched by `_initiate_harvest_feed`.

### `tests/test_harvest_feed.py`

Engine-level integration tests for the HARVEST_FEED resolution (Task 7). 20 tests covering the deferred-payment model: `_initiate_harvest_feed` does NOT debit food (the pending no longer carries `food_owed`); dynamic `food_owed` from live player state drives the legality frontier; full-food → trivial commit pays from supply (1 surplus); short-food → CommitConvert pays what's available + assigns shortfall as begging; newborn discount reduces `need`; trivial FEED gratuitous `CommitConvert(0,0,0,0,0) → Stop` floor; grain 1:1 conversion (3-grain + need=2 yields three CommitConvert options at consume 0/1/2); veg conversion across no-cooking / Fireplace / Cooking-Hearth rates; once-per-harvest craft conversions (Joinery use=True adds 2 food to supply directly and is no longer offered; insufficient wood → only use=False legal; craft still offered when food_owed=0); overpay-and-spill (Joinery fires with need=1 → after CommitConvert, 1 surplus remains in supply); all 3 crafts offered for triple-owner; Stop gating by `conversion_done`; push order (SP on top; non-SP on top after SP Stops); Pareto excludes over-conversion at the engine level.

### `tests/test_harvest_breed.py`

Engine-level integration tests for the HARVEST_BREED resolution (Task 7). 8 tests covering: push order (SP on top); two pendings pushed (one per player); no-animals trivial commit + Stop; single-type breeding (2 sheep + cap-3 → `CommitBreed(3,0,0)`); `breed_chosen` gates Stop; multi-type breeding with the two-1×1-house-pet contention (frontier = `{(3,2,0), (2,3,0)}`); SP Stop brings other player to top; capacity-forced release with Fireplace (3 sheep + cap-3 → `CommitBreed(3,0,0)` and `+2` food).

### `tests/test_harvest_integration.py`

End-to-end multi-round integration tests for the harvest pipeline (Task 7). 28 tests covering: random-agent over 20 seeds reaches `BEFORE_SCORING` with `round_number == 14` and empty stack; harvest phases (FEED + BREED) and harvest pendings (PendingHarvestFeed + PendingHarvestBreed) reached at least once across 10 seeds (HARVEST_FIELD is mechanical and never observed mid-step); round 14's HARVEST_BREED → BEFORE_SCORING transition (via `_advance_until_decision` with empty stack); round 4's HARVEST_BREED → PREPARATION → round 5 transition; `harvest_conversions_used` resets each harvest (used in one harvest, available again at the next); begging markers from `_execute_convert` propagate to `score()` (4 begging → −12 from `breakdown.begging_markers`); pending-stack evolution through both players' FEED (2 frames → SP Stop → 1 frame → other Stop → BREED pendings pushed); newborn discount applied at round-4 FEED (3 people with 1 newborn → need=5 → begging=5 with 0 food and no convertibles); all 6 harvests fire at the expected rounds {4, 7, 9, 11, 13, 14} via deterministic random play.

### `tests/test_agents_heuristic.py`

Smoke tests for `agricola/agents/` — both evaluators, both agents, the lookahead-mode + temperature toggles, and the breeding-opportunity helper. 25 tests covering: both evaluators return finite floats on fresh setup and across multiple seeds; both agents return one of `legal_actions(state)` at decision time; both agents finish a full game over multiple seeds (parametrized [0, 7, 42]) without crashing; Hubris self-play also completes; beat-random thresholds (Simple ≥ 7/10, Hubris ≥ 8/10) and Hubris-beats-Simple threshold (≥ 6/10) over 10-seed matches with average-score assertions; `lookahead="action"` mode runs to completion; `lookahead="bogus"` raises ValueError at construction; temperature > 0 sampling completes a game; the breeding-opportunity helper (`_num_breeding_opportunities_from_farm`) anchored to the user's worked examples (1×1 = 1 breed; two 1×1s = 1 breed; 1×1 + 2×1 = 2; two 2×2 = 2; three 2×1s = 3; no pastures = 0).

### `tests/test_restricted_actions.py`

Tests for `agricola/agents/restricted.py`. 51 tests covering both the regular wrapper (`restricted_legal_actions`) and the strict-mode wrapper (`strict_restricted_legal_actions`) including the `use=False` filter shared by both. Organized into three suites.

**Regular wrapper (23 tests, original suite).** **No-op cases:** PlaceWorker-level decisions (empty stack) pass through unrestricted; empty input (BEFORE_SCORING) propagates as empty. **Sub-action ordering:** Cultivation plow-before-sow (sow drops when plow on offer; survives when plow illegal); Grain Utilization sow-before-bake (analogous); Farm Expansion rooms-before-stables (analogous). **Cell priority:** stable / room / plow priorities pick the top-priority cell from their respective lists; stable priority falls back to next entry when first is occupied (FIELDs, not STABLEs — STABLEs would consume supply); falls back to full action set when no priority cell is legal. **Room cap:** `MAX_TOTAL_ROOMS=5` drops `ChooseSubAction("build_rooms")` at `PendingFarmExpansion` and drops further `CommitBuildRoom` at `PendingBuildRooms` mid-session; inactive below cap. **First-pasture restriction:** at `pastures_built=0` requires `cells ∩ {(0,4), (1,4)}` ≠ ∅; restriction lifts at `pastures_built ≥ 1`. **Min-begging at `PendingHarvestFeed`:** keeps zero-begging configs when any exist; passes through unchanged when only one CommitConvert is enumerated; narrows to the (grain=1) option when partial payment beats no payment. **Cross-cutting:** randomized full-game walk through the wrapper asserts (a) the wrapper never empties a non-empty input and (b) every wrapper-returned action is a member of the unrestricted set.

**`use=False` craft filter (2 tests).** Verifies `CommitHarvestConversion(use=False)` is dropped from `restricted_legal_actions` output when both `use=True` and `use=False` are offered; verifies safe-narrow fallback preserves `use=False`-less output when the engine never offered `use=True` (player owns the craft but can't afford to fire).

**Strict-wrapper additions (26 tests).** **No-op invariants:** strict is identity at PlaceWorker level; strict is a subset of regular; empty input passes through. **Cultivation sow-max (§7.1):** collapse to the (grain+veg)-max commit with grain-priority tiebreak; doesn't fire for `PendingSow` from Grain Utilization. **Grain-Util veggie auto-max (§7.2):** for each `grain_sown` ∈ legal set, the surviving `veg_sown` is `min(veggies_in_supply, empty_fields - grain_sown)`; collapses to veg=0 when no veggies; doesn't fire for `PendingSow` from Cultivation. **Fencing patterns (§7.3):** one test per rule (rules 1-9), plus no-rule-match pass-through, plus rule-7 pasture-identity-required negative test (2x2 split into two 1x2s doesn't match the subdivision rule; cell-set union also doesn't match rules 8/9 since the union is the full 2x2, not {(0,3),(0,4)}). Rule 8 also has a variant that builds two separate 1x1 pastures at (0,3) and (0,4) to demonstrate cell-set-union semantics (vs the pasture-identity semantics of rule 7). **Harvest-feed cap (§7.4):** inactive when ≤7 commits; engages when >7 commits (strict collapses to exactly 7 = top-5 + 2 random); crafts always preserved; deterministic given a fixed-seed RNG via the `make_strict_restricted_legal_actions(rng=...)` factory. **Cross-cutting:** randomized full-game walk through the strict wrapper asserts (a) never empties a non-empty input and (b) every wrapper-returned action is a subset of the unrestricted set.

Helpers shared by the strict suite: `_add_pasture(state, player_idx, cells)` (adds fence-arrays for a cell-set entry, recomputes pasture decomposition; repeated calls produce multiple pastures sharing boundary fences); `_build_fences_pending(...)` (constructs a `PendingBuildFences` frame); `_fencing_test_state(wood, pasture_cell_sets)` (full state setup for fencing-pattern tests).

### `tests/test_v3_majors_and_pasture_bonus.py`

Coverage for the V3-specific major-improvement override and pasture-location bonus introduced when V3 stopped calling V1's `_hubris_major_value` and `_hubris_pasture_location_bonus`. 20 tests across three groups. **Cooking/major value (8 tests):** owner-empty returns 0; hearth-only / fireplace-only use per-stage primary values; hearth+fireplace = hearth + flat +1 (one extra cooking); 2 fireplaces = fireplace + 1; 3 cookings = primary + 2; 2 hearths = hearth + 1; opponent-owned cookings don't count. **Well + singleton majors (3 tests):** well uses per-stage value; well no longer scales with future-food-rounds (drop of `well_food_per_future`); all 6 singleton majors sum at stage 1. **Stage variance (1 test):** pottery owner walked through all 11 round-to-stage transitions, asserting the correct per-stage value at each. **Pasture bonus (4 tests):** V3 cell set = exactly {(r, c) : r ∈ 0..2, c ∈ {3, 4}} (excludes c=2 cells V1 included); c=2-only pasture credits 0; c={2,3,4} pasture credits 2 (not 3); zero bonus param zeros out. **Backwards compat (4 tests):** all 14 legacy major fields still on the dataclass; all 8 new `*_by_stage` arrays have length 6; a synthesized old-shape dict (constructed by stripping the new per-stage major fields from `tuned_configs/v3_best.json`) loads via `HeuristicConfigV3(**cfg_dict)` and fills the missing fields from dataclass defaults — resilient to v3_best.json itself being updated by subsequent tuning runs; the evaluator runs end-to-end on the loaded config (finite float for both players on a fresh state).

### `tests/test_mcts.py`

Tests for `agricola/agents/mcts.py`. 24 tests covering the MCTS data structures, the macro-fencing pipeline, and end-to-end smokes. Uses small `sims_per_move` (typically 5-25) and `n_random_fencing=1` or `2` to keep the suite under a few seconds; the slow tests are the end-to-end smokes.

**`MacroFencingAction` / `MCTSNode` identity (3 tests):** `MacroFencingAction` equality keyed on `label` (same label equal, different label distinct, both hashable for use as dict keys); `MCTSNode` identity equality — two nodes for the same `GameState` compare UNEQUAL when they are different objects (`@dataclass(eq=False)` is the documented semantic); `_legal_actions` lazy cache — populated only after `_compute_legal_actions` is called.

**Transposition table (3 tests):** `find_or_create_node(state)` returns the SAME object on repeated lookups (dedup invariant); the same call with `parent=...` appends the parent to `child.parents`; `add_edge` is idempotent on parent dedup (calling twice doesn't duplicate `parents` entries).

**Re-rooting (2 tests):** `re_root(new_root)` walks the live subtree from `new_root` (via `children` BFS) and drops every transposition entry not in the reachable set — verified by setting `new_root` to a brand-new state not in the previous tree, expecting `len(transpositions) == 1`. `re_root(current_root)` is a no-op (preserves the existing table).

**Leaf evaluation (2 tests):** mid-game leaf eval returns a finite float (`evaluate_hubris_v3(state, 0) - evaluate_hubris_v3(state, 1)`); terminal leaf eval (`Phase.BEFORE_SCORING`) returns the raw score margin from P0's perspective.

**UCB + FPU (3 tests):** after `N` sims, `root.visits == N`; if `sims_per_move >= num_children`, every root child has at least one visit (the FPU validation per MCTS_DESIGN §8 Phase 2 — a broken FPU formulation would leave some children un-visited); `mean_q == 0` for a 0-visit node (the parent-mean-Q fallback used in the UCB formula).

**Action selection (2 tests):** at temperature 0, the picked action is among the argmax children (random tiebreak via the agent's RNG); at temperature > 0 with roughly-balanced visit counts, repeated sampling produces > 1 distinct action across 200 calls (statistical sanity that the softmax distribution is nondegenerate).

**End-to-end smokes (3 tests):** MCTS@5 sims vs `RandomAgent` finishes a full game (`final.phase == BEFORE_SCORING`, trace > 50 actions); same for MCTS@5 vs `HubrisHeuristicV3`; shared-tree self-play with a single `MCTSAgent` instance on both seats also completes.

**Macro-fencing pipeline (4 tests):** `_pbf_on_top(state)` predicate is True iff `PendingBuildFences` is on top (False at empty stack, False at `PendingFencing` wrapper, True at `[PendingFencing, PendingBuildFences]`); `_enter_pbf` auto-steps through the singleton `ChooseSubAction("build_fences")` at `PendingFencing` and lands at PBF on top; `_drain_wrapper` consumes the outer `PendingFencing`'s mandatory `Stop` singleton after PBF pops; `expand_macros` at a `PlaceWorker("fencing")` state produces at least one `MacroFencingAction`, removes the original trigger from the legal-action list, populates `root.macro_sequences` for each macro, and each sequence starts with the trigger + has ≥ 3 actions total (trigger + entry + at least one commit + Stop(PBF) + Stop(wrapper)). A 5th test exercises the macro-commit replay (when MCTS picks a macro at the top level, the agent queues the rest of the sequence in `_pending_macro_actions` and replays it across subsequent calls without re-running MCTS).

**Tree growth sanity (1 test):** after running 20 sims at a fresh state, the transposition table has more than just the root (`len(transpositions) > 1`).

Helpers: `_small_search(rng_seed, n_random_fencing)` (cheap MCTSSearch with small `n_random_fencing` for fast tests); `_small_agent(search, sims, c_uct, temperature, rng_seed)` (cheap MCTSAgent); `_state_at_fencing_placeworker()` (state where `PlaceWorker("fencing")` is one of P0's legal moves, used by the macro tests).
