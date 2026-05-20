# Test Reference

170 tests across 6 files.

---

## test_state.py — Setup, initialisation, and Resources (18 tests)

### Setup

**test_setup_starting_food**
Checks that the starting player begins with 2 food and the other player begins with 3 food. Works regardless of which player the RNG picks as starting player.

**test_setup_starting_rooms**
Checks every cell of both players' farmyards. Cells (1,0) and (2,0) must be ROOM with WOOD material; all other 13 cells must be EMPTY. Also checks `house_material == HouseMaterial.WOOD`.

**test_setup_no_fences**
Checks that every value in both players' `horizontal_fences` and `vertical_fences` arrays is False.

**test_fresh_farmyard_has_empty_pastures**
Checks that `farmyard.pastures == ()` for both players at fresh setup — no fences means no enclosed areas.

**test_setup_people**
Checks that each player starts with `people_total=2` and `people_home=2`.

**test_setup_major_improvements_available**
Checks that `major_improvement_owners` has length 10 and every entry is None (all improvements still on the supply board).

**test_setup_round_card_count**
Checks that `round_card_order` has exactly 14 entries and contains each of the 14 stage card IDs exactly once (no duplicates, no missing).

**test_setup_stage_ordering**
Checks that stage 1 cards appear in rounds 1–4, stage 2 in rounds 5–7, stage 3 in rounds 8–9, stage 4 in rounds 10–11, stage 5 in rounds 12–13, and stage 6 in round 14.

**test_setup_deterministic**
Calls `setup(seed=42)` twice and checks the two GameState objects are equal. Ensures the RNG produces identical results for the same seed.

**test_setup_different_seeds**
Calls setup with seed=0 and seed=1 and checks that the two states differ in at least one of: starting player or round card order.

**test_fences_in_supply_derivation**
Derives `fences_in_supply` from the fence arrays of a fresh farmyard and checks it equals 15.

**test_stables_in_supply_derivation**
Counts STABLE cells in a fresh farmyard grid and checks `stables_built == 0`.

### Resources

**test_resources_add**
Checks that `Resources(wood=3) + Resources(wood=2, food=1)` produces `Resources(wood=5, food=1)`.

**test_resources_add_identity**
Checks that `Resources() + r == r` and `r + Resources() == r` (identity element for addition).

**test_resources_add_all_fields**
Checks that addition sums all seven fields correctly.

**test_resources_add_returns_new_instance**
Checks that `a + b` returns a new object distinct from both `a` and `b` (immutability).

**test_resources_bool_true**
Checks that `bool(r)` is True for Resources objects with at least one nonzero field.

**test_resources_bool_false**
Checks that `bool(Resources())` and `bool(Resources(wood=0, ...))` are both False.

---

## test_helpers.py — Pastures, slots, accommodation, Pareto frontier, cooking rates, breeding (37 tests)

### Pasture cache (`farmyard.pastures`)

**test_no_fences_no_pastures**
A farmyard with no fences at all should return an empty tuple — no enclosed areas.

**test_single_1x1_pasture**
Four fences enclosing cell (0,0). Checks: exactly 1 pasture, `cells={(0,0)}`, `num_stables=0`, `capacity=2`.

**test_2x1_pasture**
Fences enclosing cells (0,0) and (0,1) as one unit (no internal fence). Checks: 1 pasture, `cells={(0,0),(0,1)}`, `capacity=4`.

**test_stable_in_pasture**
1×1 pasture at (0,0) with a STABLE tile on that cell. Checks: `num_stables=1`, `capacity=4` (stable doubles capacity).

**test_two_stables_in_2x1**
2-cell pasture where both cells are STABLE. Checks: `num_stables=2`, `capacity=16` (2 × 2 cells × 2² = 16).

**test_two_adjacent_pastures**
A 2-cell area split by an internal fence into two 1×1 pastures. Checks: 2 pastures returned, each with `capacity=2`.

**test_unfenced_cell_not_pasture**
With no fences at all, cell (1,2) must not appear in any pasture's cell set.

### Cache structural-property tests

> The auto-fill `__post_init__` from CHANGES.md Change 2 was disabled in
> CHANGES.md Change 3. Pastures are now populated by the `_make_farmyard`
> test helper (which calls `compute_pastures_from_arrays` explicitly).
> Seven auto-fill-specific tests were deleted as part of Change 3; the
> two tests below survive because they exercise canonical ordering and
> structural equality (which MCTS subtree sharing depends on) via the
> updated helper.

**test_pastures_canonical_order**
Encloses two cells: (0,0) and (1,3). Asserts `pastures[0]` has `min(cells)==(0,0)` and `pastures[1]` has `min(cells)==(1,3)`. Then builds an equivalent farmyard by adding the enclosures in the reverse order, and asserts the two `pastures` tuples compare equal — canonical ordering produces deterministic equality.

**test_equivalent_farmyards_compare_equal_and_hash_equal**
Build the same farmyard two ways: enclose (0,0) then (2,4), versus enclose (2,4) then (0,0). Asserts `farmyard1 == farmyard2` and `hash(farmyard1) == hash(farmyard2)`. Validates the canonical ordering guarantee MCTS subtree sharing depends on.

### `enclosed_cells` helper

**test_enclosed_cells_helper**
Calls `enclosed_cells` on a fresh no-fence farmyard and asserts the result is `frozenset()`. Then adds two single-cell enclosures at (0,0) and (2,4) and asserts the result is `frozenset([(0,0),(2,4)])`.

### `extract_slots`

**test_extract_slots_standalone_stable**
Farmyard with 1 standalone stable (not enclosed by any fence) and no pastures. Checks that `extract_slots` returns `pasture_capacities=[]` and `num_flexible=2` (1 standalone stable + 1 house pet).

### `can_accommodate`

**test_empty_farm_no_animals**
No pastures, 1 flexible slot (house), 0 animals of each type. Must return True.

**test_fits_in_one_pasture**
One pasture of capacity 4. 4 sheep, 0 boar, 0 cattle, 0 flexible slots. Must return True.

**test_overflow_to_flexible**
One pasture of capacity 4, 1 flexible slot. 4 sheep + 1 boar: sheep fill the pasture, boar goes to house. Must return True.

**test_overflow_exceeds_flexible**
One pasture of capacity 4, 1 flexible slot. 4 sheep + 2 boar: sheep fill the pasture, but 2 boar overflow and only 1 flexible slot exists. Must return False.

**test_two_types_two_pastures**
Pastures of capacity 4 and 2, 1 flexible slot. 4 sheep + 3 boar: sheep in big pasture, 2 boar in small pasture, 1 boar in house. Must return True.

### `pareto_frontier` (animal counts only, rates=(0,0,0))

**test_empty_farm**
No fences, no stables — only the house pet slot. Player gains 1 sheep, 1 boar, 1 cattle. Can keep at most 1 animal total. Checks that (1,0,0), (0,1,0), (0,0,1) are all in the frontier and no configuration with 2+ animals is.

**test_worked_example**
Two pastures (cap 4 and cap 2), 1 flexible slot, current animals (0,4,0), gained (4,0,0). Checks that (4,3,0) and (3,4,0) are in the frontier and (4,4,0) is not.

**test_inventory_constraint**
Same setup as worked example. Checks that no returned configuration has boar > 4 (the inventory upper bound), verifying (2,5,0) can never appear.

**test_discard_to_gain**
Player has 4 boar and gains 4 sheep. Checks that (4,3,0) is in the frontier — the player can discard 1 boar in exchange for fitting more sheep — while (4,0,0) is not (dominated by (4,3,0)).

**test_no_gained_no_change**
Player has 1 sheep in a 1×1 pasture and gains nothing. Frontier must contain exactly `Animals(sheep=1)` — no other options exist.

### `cooking_rates`

**test_no_cooking_improvement**
Player owns no major improvements. Checks that `cooking_rates` returns (0, 0, 0).

**test_fireplace_owned**
Player owns Fireplace (index 0). Checks that `cooking_rates` returns (2, 2, 3).

**test_cooking_hearth_owned**
Player owns Cooking Hearth (index 2). Checks that `cooking_rates` returns (2, 3, 4).

**test_hearth_beats_fireplace**
Player owns both Fireplace (index 1) and Cooking Hearth (index 3). Checks that `cooking_rates` returns the Cooking Hearth rates (2, 3, 4), since Hearth is strictly better.

### `pareto_frontier` (with rates, food computation)

**test_pareto_food_no_improvement**
Rates (0,0,0). Player gains 4 sheep in a 1×1 pasture. Checks that food is always 0 in the frontier regardless of what is discarded.

**test_pareto_food_with_fireplace**
Two pastures (cap 4 and cap 2), gained 4 sheep, current 0. Rates (2,2,3). Checks that the frontier contains (4,0,0) and its food is 0 — all sheep kept, none cooked.

**test_pareto_food_partial_keep**
House-only player (1 flexible slot), gains 4 sheep. Rates (2,2,3). Can keep at most 1 sheep. Checks that (1,0,0) is in the frontier with food=6 — (4−1)×2 from cooking 3 sheep.

**test_pareto_food_existing_animals_eaten**
Player has 2 boar in a 1×1 pasture (cap 2), gains 2 sheep. Rates (2,2,3). Checks that (2,1,0) and (1,2,0) are both in the frontier, each with food=2.

### `breeding_frontier`

**test_breeding_no_animals**
Player has no animals and a house-only farm. Frontier must contain exactly `Animals()` with food=0.

**test_breeding_one_of_each**
Player has 1 sheep, 1 boar, 1 cattle (none breeds). House-only farm (1 flexible slot). Frontier contains single-animal configurations only, all with food=0.

**test_breeding_sheep_only_breeds**
s=2, house-only farm (1 flexible). s_desired=3, max fit=1. (1,0,0) dominates (0,0,0). sF=1 < 3 → food=0. Asserts frontier is exactly `{(1,0,0): 0}`.

**test_breeding_sheep_breeds_with_room**
s=2, two-pasture farm (cap 4 + cap 2 + house). s_desired=3, all of 0..3 fit. (3,0,0) dominates all. Asserts frontier is exactly `{(3,0,0): 0}`.

**test_breeding_food_from_excess**
Farm: 2×1 pasture (cap 4) + house. sheep=4, cattle=1. (5,0,0) and (4,0,1) are incomparable. Asserts frontier is exactly `{(5,0,0): 0, (4,0,1): 2}`.

**test_breeding_worked_example**
b=4, two-pasture farm. Rates (2,2,3). b_desired=5; 5 boar fit. Asserts frontier is exactly `{(0,5,0): 0}`.

**test_breeding_formula_sF_ge_3**
s=3, 1×1-pasture farm (cap 2 + house = 3 max). Rates (2,0,0). sF=3, sF≥3 path. food=(3+1−3)×2=2. Asserts frontier is exactly `{(3,0,0): 2}`.

**test_breeding_formula_sF_lt_3**
s=3, house-only farm (1 flexible). Rates (2,0,0). sF=1 < 3 → food=(3−1)×2=4. Asserts frontier is exactly `{(1,0,0): 4}`.

---

## test_scoring.py — End-of-game scoring (8 tests)

**test_score_empty_farm_two_people**
Scores the default starting state: 2 rooms, 13 empty cells, no development. Verifies every scoring category individually: fields=−1, pastures=−1, grain=−1, veg=−1, sheep=−1, boar=−1, cattle=−1, unused=−13, people=+6, total=−14. (Note: `unused` uses -1 per unused tile formula which gives -13 for 13 empty cells.)

**test_field_tile_scoring**
Places 3 FIELD tiles on a player's farmyard and checks that `field_tiles` scores 2 pts (the correct value for exactly 3 fields on the scoring table).

**test_animal_scoring**
Sets a player's animals to sheep=4, boar=3, cattle=2 and checks each animal category scores correctly: sheep=2, boar=2, cattle=2.

**test_begging_markers**
Sets `begging_markers=2` and checks that the begging_markers score is −6 (2 × −3).

**test_fenced_stable_scoring**
Places a STABLE tile inside a 1×1 fenced pasture. Checks that `fenced_stables` scores 1 pt.

**test_craft_building_bonus**
Gives player 0 ownership of Joinery (index 7) and 7 wood in personal supply. Checks that `bonus_points` equals 3 (the maximum tier for Joinery).

**test_tiebreaker**
Sets a player's resources to wood=3, clay=2, reed=1, stone=4, food=10. Checks that `tiebreaker` returns 10 (sum of building resources only; food excluded).

**test_tiebreaker_subtracts_craft_bonus_spending**
Gives player 0 ownership of Joinery (index 7) and resources wood=7, clay=2, reed=1, stone=4. Joinery qualifies for 3 bonus pts, consuming 7 wood. Raw building total=14; after subtracting 7 wood spent=7. Checks that `tiebreaker` returns 7.

---

## test_legality_atomic.py — Atomic action space legality (27 tests)

Uses the unified `legal_placements` function (covers both atomic and non-atomic spaces). Tests in this file target only the 12 atomic spaces.

### Per-space: legal when conditions met

**test_day_laborer_legal_at_setup**
Day Laborer has no accumulation precondition; it is always available from round 1.

**test_fishing_legal_with_accumulation**
At setup, `fishing` already has `accumulated_amount=1` (round-1 pre-load). Checks PlaceWorker("fishing") is legal.

**test_forest_legal_with_accumulation**
At setup, `forest` already has `accumulated=Resources(wood=3)`. Checks PlaceWorker("forest") is legal.

**test_clay_pit_legal_with_accumulation**
At setup, `clay_pit` already has `accumulated=Resources(clay=1)`. Checks PlaceWorker("clay_pit") is legal.

**test_reed_bank_legal_with_accumulation**
At setup, `reed_bank` already has `accumulated=Resources(reed=1)`. Checks PlaceWorker("reed_bank") is legal.

**test_grain_seeds_legal_at_setup**
Grain Seeds has no accumulation precondition; always available from round 1.

**test_meeting_place_legal_at_setup**
Meeting Place is legal even with 0 food — taking the SP token is itself an effect.

**test_meeting_place_legal_with_zero_accumulation**
Meeting Place with `accumulated_amount=0` is still legal. Confirms the zero-food exception.

**test_western_quarry_legal_when_revealed_with_accumulation**
Reveals `western_quarry` at current round with `Resources(stone=1)`. Checks PlaceWorker is legal.

**test_vegetable_seeds_legal_when_revealed**
Reveals `vegetable_seeds` at current round (no accumulation condition). Checks PlaceWorker is legal.

**test_eastern_quarry_legal_when_revealed_with_accumulation**
Reveals `eastern_quarry` at current round with `Resources(stone=1)`. Checks PlaceWorker is legal.

**test_basic_wish_legal_when_revealed_with_room**
Basic Wish requires more rooms than people. Adds 1 extra room to give rooms (3) > people (2). Checks PlaceWorker is legal.

**test_urgent_wish_legal_when_revealed**
Urgent Wish only requires `people_total < 5`. Starting state has 2. Checks PlaceWorker is legal.

### Per-space: illegal when conditions fail

**test_fishing_illegal_with_zero_accumulation**
Sets `accumulated_amount=0` on `fishing`. Must be absent from legal placements.

**test_forest_illegal_with_zero_accumulation**
Sets `accumulated=Resources()` on `forest`. Must be absent.

**test_clay_pit_illegal_with_zero_accumulation**
Sets `accumulated=Resources()` on `clay_pit`. Must be absent.

**test_reed_bank_illegal_with_zero_accumulation**
Sets `accumulated=Resources()` on `reed_bank`. Must be absent.

**test_western_quarry_illegal_with_zero_accumulation**
Reveals `western_quarry` with empty Resources. Confirmed absent despite being revealed.

**test_eastern_quarry_illegal_with_zero_accumulation**
Reveals `eastern_quarry` with empty Resources. Confirmed absent.

**test_basic_wish_illegal_at_max_family**
Sets `people_total=5` (maximum). Basic Wish must be absent even with plenty of rooms.

**test_basic_wish_illegal_without_room**
Starting state: 2 people, 2 rooms — rooms not > people. Basic Wish must be absent.

**test_urgent_wish_illegal_at_max_family**
Sets `people_total=5`. Urgent Wish must be absent.

### Cross-cutting

**test_occupied_space_illegal**
Marks Day Laborer as occupied (`workers=(1,0)`). PlaceWorker("day_laborer") must be absent.

**test_unrevealed_stage_space_illegal**
At round 1, `western_quarry` has `round_revealed > 1`. Even with goods it must be absent.

**test_no_workers_returns_empty**
Sets `people_home=0` for the active player. `legal_placements` must return `[]`.

**test_setup_legal_set**
At fresh setup (round 1), asserts the complete legal set is exactly: `day_laborer`, `grain_seeds`, `meeting_place`, `forest`, `clay_pit`, `reed_bank`, `fishing`, `farmland`. Farm expansion and side_job are absent (no wood/reed/baking improvement). Stage cards are unrevealed. Fencing is deferred; lessons is omitted.

### Per-player

**test_current_player_determines_legality**
Sets `current_player=1`. Player 1 has 2 people and 2 rooms (Basic Wish blocked). Player 0 has a spare room. Confirms Basic Wish is absent — it checks player 1's farm, not player 0's.

---

## test_resolution_atomic.py — Atomic action space resolution (24 tests)

### Per-space happy-path tests

**test_day_laborer_resolution**
Resolves Day Laborer. Checks `food` increases by 2 and all other resources are unchanged.

**test_fishing_resolution**
Resolves Fishing (pre-loaded with 1 food at setup). Checks `food` increases by `accumulated_amount` and `accumulated_amount` is reset to 0. Checks no other resources change.

**test_forest_resolution**
Resolves Forest (pre-loaded with `Resources(wood=3)`). Checks `wood` increases by `accum.wood` and `accumulated` is reset to `Resources()`. Checks no other resources change.

**test_clay_pit_resolution**
Resolves Clay Pit. Checks `clay` increases by accumulated amount and accumulation resets.

**test_reed_bank_resolution**
Resolves Reed Bank. Checks `reed` increases by accumulated amount and accumulation resets.

**test_grain_seeds_resolution**
Resolves Grain Seeds. Checks `grain` increases by 1 and all other resources are unchanged.

**test_meeting_place_resolution**
Resolves Meeting Place. Checks `food` increases by `accumulated_amount`, accumulation resets to 0, and `starting_player` is updated to the active player.

**test_western_quarry_resolution**
Reveals Western Quarry with `Resources(stone=2)`. Resolves it. Checks `stone` increases by 2 and accumulation resets.

**test_vegetable_seeds_resolution**
Reveals Vegetable Seeds. Resolves it. Checks `veg` increases by 1 and all other resources unchanged.

**test_eastern_quarry_resolution**
Reveals Eastern Quarry with `Resources(stone=3)`. Resolves it. Checks `stone` increases by 3 and accumulation resets.

**test_basic_wish_resolution**
Adds 1 extra room, reveals Basic Wish, resolves it. Checks `people_total` increments by 1, `newborns` increments to 1, `people_home` decrements by 1 (parent placed; newborn not added to home), and `workers[ap] == 2` (parent + newborn on space).

**test_urgent_wish_resolution**
Reveals Urgent Wish, resolves it. Same assertions as basic wish: `people_total` +1, `newborns`=1, `people_home` −1, `workers[ap] == 2`.

### Cross-cutting invariants (using Day Laborer as representative)

**test_resolution_marks_space_occupied**
After resolution, `day_laborer.workers[ap] == 1`.

**test_resolution_decrements_people_home**
After resolution, active player's `people_home` is one less than before.

**test_resolution_doesnt_advance_current_player**
`current_player` is unchanged after resolution.

**test_resolution_doesnt_advance_phase**
`phase` is unchanged after resolution.

**test_resolution_other_player_unchanged**
The non-active player's entire `PlayerState` is equal before and after resolution.

**test_resolution_other_spaces_unchanged**
All action spaces other than `day_laborer` have identical `workers`, `accumulated`, and `accumulated_amount` after resolution.

### Edge cases

**test_meeting_place_zero_accumulation**
Sets `accumulated_amount=0` on Meeting Place before resolution. Checks food is unchanged (no food gained) but `starting_player` is still updated.

**test_accumulation_zero_after_take**
Resolves Forest (pre-loaded with wood=3). Checks `accumulated == Resources()` afterward.

**test_resolution_returns_new_state**
Resolves Day Laborer. Checks that `state.players[ap].resources is not new_state.players[ap].resources` — confirms the functional, non-mutating design.

### Wish-specific tests

**test_basic_wish_workers_are_two**
Resolves Basic Wish. Checks `workers[ap] == 2` (parent + newborn both occupy the space).

**test_basic_wish_other_player_workers_zero**
Resolves Basic Wish for player `ap`. Checks `workers[other] == 0` — the other player's worker count on the space is unaffected.

**test_wish_increments_newborns**
Resolves Basic Wish. Checks `newborns == 1` exactly — not 0 or 2.

---

## test_legality_non_atomic.py — Non-atomic space legality and shared helpers (56 tests)

Test helpers: `_set_space`, `_reveal_space`, `_set_player`, `_set_grid`, `_set_resources`, `_set_owner`, `_enclose_cell` (places 4 fences around one cell to form a 1×1 pasture), `_enclose_rect` (places boundary fences around rectangle [r0..r1]×[c0..c1]).

### `_can_bake_bread`

**test_can_bake_bread_with_fireplace_and_grain**
Gives active player Fireplace (index 0) and 1 grain. Asserts `_can_bake_bread` is True.

**test_can_bake_bread_no_improvement**
Gives active player 5 grain but no baking improvement. Asserts `_can_bake_bread` is False.

**test_can_bake_bread_no_grain**
Gives active player Fireplace (index 0) but 0 grain. Asserts `_can_bake_bread` is False.

### `_can_sow`

**test_can_sow_grain_on_empty_field**
Sets cell (0,0) to FIELD and gives 1 grain. Asserts `_can_sow` is True.

**test_can_sow_no_empty_field**
Sets cell (0,0) to FIELD with `grain=2` (planted, not empty). Gives 1 grain in supply. Asserts `_can_sow` is False.

**test_can_sow_no_seeds**
Sets cell (0,0) to FIELD (empty) but 0 grain and 0 veg in supply. Asserts `_can_sow` is False.

### `_can_plow`

**test_can_plow_first_field**
Fresh state: 2 rooms, 13 empty cells, no fields. Asserts `_can_plow` is True (first field can go anywhere non-enclosed).

**test_can_plow_adjacent**
Sets (0,0) to FIELD. Asserts `_can_plow` is True because (0,1) is empty and adjacent.

**test_can_plow_no_adjacent**
Sets (0,0) to FIELD, (0,1) to ROOM. (1,0) is already a ROOM. No adjacent empty cell exists. Asserts `_can_plow` is False.

**test_can_plow_excludes_enclosed_cell**
Fills all non-room cells with FIELDs except (0,4). Encloses (0,4) with a single-cell fence pasture. Without the enclosed filter, _can_plow would return True. With it, asserts False — enclosed empty cells cannot become fields.

**test_can_plow_first_field_excludes_enclosed_cells**
Fills cols 0–2 with ROOMs (9 cells). Encloses cols 3–4 as a 3×2 pasture (6 enclosed EMPTY cells). No FIELDs exist. Without the enclosed filter, the first-field branch would return True. With it, asserts False — every empty cell is enclosed.

### `_has_stable_placement`

**test_has_stable_placement_legal**
Fresh state: 13 empty cells, all 4 stables in supply. Asserts `_has_stable_placement` is True.

**test_has_stable_placement_no_supply**
Converts 4 cells to STABLE so supply reaches 0. Asserts `_has_stable_placement` is False.

**test_has_stable_placement_no_empty_cell**
Fills every non-room cell with FIELD (no empty cells remain). Asserts `_has_stable_placement` is False.

### `_can_afford_room` / `_has_room_placement` / `_can_build_room`

**test_can_afford_room_legal**
Sets resources to wood=5, reed=2 (exact cost for a wood house). Asserts `_can_afford_room` is True.

**test_can_afford_room_insufficient**
Sets resources to wood=4, reed=2 (1 short). Asserts `_can_afford_room` is False.

**test_has_room_placement_legal**
Fresh farmyard: rooms at (1,0) and (2,0); adjacent empty cells (0,0), (1,1), (2,1) are unoccupied and non-enclosed. Asserts `_has_room_placement` is True.

**test_has_room_placement_no_adjacent_empty**
Sets (0,0), (1,1), (2,1) — all room-adjacent cells — to FIELD. No empty cells adjoin any room. Asserts `_has_room_placement` is False.

**test_has_room_placement_excludes_enclosed_cell**
Sets (1,1) and (2,1) to FIELD, encloses (0,0) with a single-cell fence. The only room-adjacent empty cell is enclosed. Asserts `_has_room_placement` is False.

**test_can_build_room_legal**
Sets wood=5, reed=2. Fresh farmyard has valid placement cells. Asserts `_can_build_room` is True.

**test_can_build_room_no_resources**
Sets wood=4, reed=2 (insufficient). Asserts `_can_build_room` is False.

**test_can_build_room_no_adjacent_empty**
Sets wood=5, reed=2 (sufficient). Surrounds rooms with FIELDs. Asserts `_can_build_room` is False (geometry blocked).

### `_can_renovate`

**test_can_renovate_wood_to_clay**
Fresh state: 2-room wood house. Sets clay=2, reed=1 (exact cost). Asserts `_can_renovate` is True.

**test_can_renovate_already_stone**
Sets `house_material=STONE`. Asserts `_can_renovate` is False regardless of resources.

**test_can_renovate_insufficient_resources**
Wood house, 2 rooms; sets clay=1 (< 2 needed). Asserts `_can_renovate` is False.

### `_can_afford_any_major_improvement`

**test_can_afford_major_improvement_basic**
All 10 improvements unowned. Sets clay=2. Can afford index 0 (Fireplace, 2 clay). Asserts True.

**test_can_afford_major_improvement_return_fireplace**
Player owns Fireplace (index 0); 0 clay. Cooking Hearth (index 2) is unowned. Owning Fireplace counts as credit toward Cooking Hearth cost. Asserts True.

**test_can_afford_major_improvement_all_owned**
Marks all 10 improvements as owned (alternating between players). Sets abundant resources. Asserts False — nothing left to buy.

### Per-space: legal when conditions met

**test_farm_expansion_legal_can_build_room**
Sets wood=5, reed=2. Room path is open. Asserts PlaceWorker("farm_expansion") is legal.

**test_farm_expansion_legal_can_build_stable**
Sets wood=2, reed=0. No room (insufficient reed). Empty cell + stables in supply satisfies the stable path. Asserts PlaceWorker("farm_expansion") is legal.

**test_farmland_legal**
Fresh setup: no fields, plenty of empty cells. First plow is always legal. Asserts PlaceWorker("farmland") is legal.

**test_side_job_legal_can_build_stable**
Sets wood=1. Empty cell + stables in supply satisfies stable path. Asserts PlaceWorker("side_job") is legal.

**test_side_job_legal_can_bake_bread**
Sets wood=0. Gives Fireplace (index 0) and grain=1. Bake-bread path is open. Asserts PlaceWorker("side_job") is legal.

**test_grain_utilization_legal_can_sow**
Reveals `grain_utilization`. Sets cell (0,0) to FIELD; gives grain=1. Sow path is open. Asserts legal.

**test_grain_utilization_legal_can_bake_bread**
Reveals `grain_utilization`. Gives Fireplace and grain=1. Bake-bread path is open. Asserts legal.

**test_sheep_market_legal**
Reveals `sheep_market` with `accumulated_amount=1`. Asserts legal.

**test_pig_market_legal**
Reveals `pig_market` with `accumulated_amount=1`. Asserts legal.

**test_cattle_market_legal**
Reveals `cattle_market` with `accumulated_amount=1`. Asserts legal.

**test_major_improvement_legal**
Reveals `major_improvement`. Sets clay=2 (can afford Fireplace at index 0). Asserts legal.

**test_house_redevelopment_legal**
Reveals `house_redevelopment`. Sets clay=2, reed=1 (can renovate 2-room wood house). Asserts legal.

**test_cultivation_legal_can_plow**
Reveals `cultivation`. Fresh state: no fields, can plow first field. Asserts legal.

**test_cultivation_legal_can_sow**
Reveals `cultivation`. Fills all non-room cells with STABLEs except (0,0) which is an empty FIELD. Gives grain=1. Plow is blocked; sow is open. Asserts legal.

**test_farm_redevelopment_legal**
Reveals `farm_redevelopment`. Sets clay=2, reed=1. Asserts legal.

### Per-space: illegal when conditions fail

**test_farm_expansion_illegal_cannot_build_anything**
Sets wood=0, reed=0. Converts 4 cells to STABLE (0 stables left in supply). No room, no stable — asserts absent.

**test_farmland_illegal_no_valid_cell**
Fills all non-room cells with STABLEs (no empty cells). Asserts PlaceWorker("farmland") is absent.

**test_side_job_illegal_neither_option**
Sets wood=0, grain=0 (no baking improvement). Both stable and bake-bread paths blocked. Asserts absent.

**test_grain_utilization_illegal_neither_option**
Reveals `grain_utilization`. Fresh state has no fields and no baking improvement. Neither sow nor bake-bread is possible. Asserts absent.

**test_sheep_market_illegal_zero_accumulation**
Reveals `sheep_market` with `accumulated_amount=0`. Asserts absent.

**test_pig_market_illegal_zero_accumulation**
Reveals `pig_market` with `accumulated_amount=0`. Asserts absent.

**test_cattle_market_illegal_zero_accumulation**
Reveals `cattle_market` with `accumulated_amount=0`. Asserts absent.

**test_major_improvement_illegal_cannot_afford_any**
Reveals `major_improvement`. Fresh player has 0 of every resource and no Fireplace. Cannot afford anything. Asserts absent.

**test_house_redevelopment_illegal_already_stone**
Reveals `house_redevelopment`. Sets `house_material=STONE` and abundant resources. Asserts absent.

**test_farm_redevelopment_illegal_already_stone**
Reveals `farm_redevelopment`. Sets `house_material=STONE` and abundant resources. Asserts absent.

**test_cultivation_illegal_neither_option**
Reveals `cultivation`. Fills all non-room cells with STABLEs (no plow, no sow). Asserts absent.

### Cross-cutting: fencing and lessons never appear

**test_fencing_absent_from_legal_placements**
Reveals `fencing` and gives the player abundant resources. Asserts "fencing" is never in the output of `legal_placements` (deferred implementation).

**test_lessons_absent_from_legal_placements**
Asserts "lessons" is never in the output of `legal_placements` (always illegal in the Family game).
