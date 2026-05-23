# HubrisHeuristicV3 — Design

V3 is the third architectural iteration of the Hubris heuristic agent. V1 used hand-picked piecewise resource tiers and trusted `score()`'s leaves for most categories; V2 (an opt-in variant) tried to fix V1's "convertible goods double-count" via `harvest_feed_frontier` but lost head-to-head to V1. V3 is a deeper refactor that **replaces the per-category structure of V1** with a uniform "value vector + per-stage modulator" pattern, while preserving V1's strongest hand-picked elements as carry-overs.

This document is the canonical V3 reference. It describes the design decisions, the schema, the combination math per category, and the parts of V1 that V3 deliberately keeps.

For training/tuning workflow see **`V3_TRAINING_PIPELINE.md`**. For per-V1-term rationale see **`HUBRIS_V1_NOTES.md`**.

## File map

| File | Role |
|---|---|
| `agricola/agents/heuristic.py` | All code: `HeuristicConfigV3` dataclass, `evaluate_hubris_v3`, `HubrisHeuristicV3`, per-category helpers, V1 carry-overs. |
| `agricola/agents/__init__.py` | Exports `HubrisHeuristicV3`, `HeuristicConfigV3`, `DEFAULT_CONFIG_V3`, `evaluate_hubris_v3`. |
| `tuned_configs/v3_best.json` | Always-up-to-date "best V3 config" pointer. Auto-updated by tuning runs when a new holdout beats the existing one. |

## 1. Motivation — why V3?

V1's structure was a mix of:

- **`score()` trust** for most leaf categories (fields, pastures, animals, crops, rooms, stables). The mid-game evaluator added small hubris-only "anticipation" terms (breeding-opportunity, crop+field pair, family-future, empty-room) on top.
- **Hand-picked piecewise resource tiers** with branches by regime (no-room-built vs. room-built, no-cookware vs. has-cookware), capped by integer cap parameters (`wood_tier1_cap=6`, etc.).
- **Per-stage food curve** (`hubris_food_by_stage`) — already the right shape.
- **Stage-1 + round-13 + round-14 resource multipliers** as scattered hand-picked "time" parameters.

This worked, and tuning V1 (run 2) achieved a holdout margin of **+8.85** over default V1. But several deeper structural issues showed up in tuning:

- The resource tier caps are integers and not amenable to CMA-ES.
- Regime branches encode "states the agent is in" rather than count-curves; combining them with stage modulators required scattered overlays.
- Categories with hubris-only anticipation terms (e.g. breeding-opportunity) were modeled in ways that didn't compose with score()'s leaves — they were independent additions, not principled time-discounts of leaf value.
- Trusting score() in mid-game implicitly assumes its end-of-game value applies *now*, which is wrong: a pasture in round 4 is worth more than one in round 14 (it compounds via breeding).

V3 reorganizes around two principles:

1. **Every category has explicit `value(count, stage)` semantics.** For categories with a score-leaf, V3 *blends* a parameterized count-curve against the leaf; for categories without (crop-pairs, breeding-pairs, unfenced-stables), V3 contributes additively with a per-stage weight; for categories V3 chooses *not* to explicit-model (clay/stone rooms, people, craft bonuses), V3 applies a single shared `joint_alpha` modulator on the score leaf.
2. **Resources get their own three-component pattern** (per resource): a state-aware vector indexed by the resource's "next-use slot" (next fence to build, next reed-toward-room, etc.), a regime-conditional overlay vector, and a generic per-unit scalar — all gated by a per-stage weight.

The result is more parameters than V1 (~250 vs ~70) but much more expressive, and crucially **every parameter is a continuous float** suitable for CMA-ES.

## 2. The three combination styles

V3 categorizes each scoring-relevant aspect of the player's state and applies one of three combination styles:

### Style A — BLEND (used when `score()` has a leaf for this category)

```
contribution = α[stage] · v3_value(count)  +  (1 − α[stage]) · score_leaf
α ∈ [0, 1]
```

`α = 0` → fully trust `score()`'s leaf (e.g., grain scores -1/+1/+2/+3/+4 by count buckets).
`α = 1` → fully replace with V3's parameterized count-curve.
`α = 0.5` → equal weight blend (the default).

**Used for:** fields, pastures, grain, vegetables, sheep, boar, cattle, fenced stables, unused farmyard spaces.

**Why blend rather than always replace?** Mid-game we don't fully know whether the agent will end up with this count. The score-leaf encodes "if the game ended now you'd score X"; the parameterized vector encodes "in this stage, the agent should value having this many at this rate." Blending captures both: late game, α → 0 and we trust the leaf; early game α → 1 (or higher) and we use anticipation logic.

The unused-spaces variant has a special case: the parameterized side is hard-coded to 0, modeling "empty cells aren't worth penalizing in early game" — `α` ranges from 1 (ignore penalty in stage 1) down to 0 (full penalty in stage 6).

### Style B — ADDITIVE-MULTIPLICATIVE (no score leaf — purely hubris signal)

```
contribution = weight[stage] · v3_value(count)
weight ∈ [0, ∞)
```

`weight = 0` → category contributes zero in this stage.

**Used for:** grain-field pairs, veg-field pairs, breeding pairs (cattle / boar / sheep), unfenced stables.

These don't appear in `score()`'s `ScoreBreakdown` — they're hubris-only anticipatory categories. The "count" is computed from current state (e.g. grain-pair count = `min(supply_grain, empty_plowed_fields)`).

### Style C — JOINT-ALPHA (score leaves V3 doesn't explicitly model)

```
contribution = score_joint_alpha[stage] · score_leaf
```

A single per-stage modulator applied to **clay rooms + stone rooms + people + craft-bonus points**.

**Why?** These categories either:
- Have low time-variance (rooms score the same per-stone-or-clay-room throughout the game), or
- Are already partially modeled elsewhere (V1's `_hubris_family_value` and `_hubris_empty_room_value` cover the "future people" anticipation for the *people* leaf).

A single modulator across these four leaves is enough: it lets the agent value "things already locked in" less early game (when there's still time to acquire more) and more late game. Defaults: `(0.5, 0.6, 0.7, 0.8, 0.9, 1.0)`.

**Begging markers are excluded from joint-alpha** — they always count at full weight (`bd.begging_markers` is added unmodulated). Begging is a permanent strategic penalty; under-weighting it in early game would make the agent take bigger risks.

## 3. Per-category specs

The full `HeuristicConfigV3` schema. For each category: which fields define it, the lengths, and how the contribution is computed.

### A1 — Fields

| Field | Length | Domain |
|---|---|---|
| `plowed_field_value` | 7 | count ∈ {0, 1, ..., 6+} (index 6 = "6 or more") |
| `field_blend_alpha_by_stage` | 6 | one per stage |

**Combination:** Style A blend against `bd.field_tiles`.

### A2 — Pastures (two vectors share one alpha)

| Field | Length | Domain |
|---|---|---|
| `pasture_value_all` | 5 | total pasture count ∈ {0, ..., 4+} |
| `pasture_value_large` | 5 | count of pastures with capacity ≥ 4 ∈ {0, ..., 4+} |
| `pasture_blend_alpha_by_stage` | 6 | shared α for both vectors |

**Combination:** `v1[total] + v2[large_count]` is the parameterized side of a Style A blend against `bd.pastures`.

**Rationale for two vectors:** a 2×1 pasture (capacity 4) is strictly more valuable than two 1×1 pastures (capacity 2 each), even though they count the same in `score()`'s "1 pt per pasture, max 4" formula. The second vector lets the optimizer reward larger pastures separately.

### A3 — Sheep / Boar / Cattle

| Field | Length | Indexing |
|---|---|---|
| `sheep_value` | 9 | counts 0..8+ |
| `boar_value` | 8 | counts 0..7+ |
| `cattle_value` | 7 | counts 0..6+ |
| `<species>_blend_alpha_by_stage` | 6 each | per stage |

Lengths match `score()`'s plateaus (sheep plateau at 8+ score +4, boar at 7+, cattle at 6+).

### A4 — Fenced stables

| Field | Length | Indexing |
|---|---|---|
| `fenced_stable_value` | 5 | count 0..4 (already capped at 4 in `score()`) |
| `fenced_stable_blend_alpha_by_stage` | 6 | per stage |

### A5 — Unused farmyard spaces (special blend)

| Field | Length | Indexing |
|---|---|---|
| `unused_spaces_alpha_by_stage` | 6 | per stage, ∈ [0, 1] |

**Combination:** `(1 - α[stage]) · bd.unused_spaces` (which is already negative).

Parameterized side fixed at 0: "covering empty cells early isn't worth penalty; full penalty by end-of-game."

### B1 — Crop-field pairs

| Field | Length | Indexing |
|---|---|---|
| `grain_pair_value` | 4 | pair count 0..3+ |
| `grain_pair_weight_by_stage` | 6 | per stage, ∈ [0, ∞) |
| `veg_pair_value` | 4 | pair count 0..3+ |
| `veg_pair_weight_by_stage` | 6 | per stage |

**Pair counting (grain priority):**
```
empty_fields = # plowed-empty field tiles
grain_pairs = min(supply_grain, empty_fields)
veg_pairs = min(supply_veg, empty_fields - grain_pairs)
```

Grain gets first dibs on empty fields because grain crops produce more units when sown (3 grain per field vs 2 veg per field).

### B2 — Breeding pairs (cattle/boar/sheep priority allocation)

| Field | Type | Indexing |
|---|---|---|
| `cattle_breeding_pair_value` | scalar | pair count is 0 or 1 |
| `cattle_breeding_pair_weight_by_stage` | 6 | per stage |
| (same trio for boar and sheep) | | |

**Pair counting (cattle > boar > sheep priority):**

A "breeding pair" for type T = (≥2 of type T in supply) AND (a breeding-capacity slot is available). Pasture capacity slots are limited; the priority allocates them top-down.

```python
def _v3_breeding_pair_counts(p):
    cap = _num_breeding_opportunities_from_farm(p)
    cattle = 1 if (cap > 0 and p.animals.cattle >= 2) else 0
    if cattle: cap -= 1
    boar   = 1 if (cap > 0 and p.animals.boar >= 2)   else 0
    if boar: cap -= 1
    sheep  = 1 if (cap > 0 and p.animals.sheep >= 2)  else 0
    return cattle, boar, sheep
```

`_num_breeding_opportunities_from_farm` (already in V1) returns the max number of distinct animal types the farm could host ≥3 of (accounting for pasture capacities, the house pet slot, and standalone stables as flex slots).

**Cattle gets priority** because cattle have the steepest per-unit score-leaf curve (+1 at count=1, vs sheep needing 1 just to break even on the -1 baseline).

### B3 — Unfenced stables

| Field | Length | Indexing |
|---|---|---|
| `unfenced_stable_value` | 5 | count 0..4 |
| `unfenced_stable_weight_by_stage` | 6 | per stage |

No score-leaf. Defaults make this active in stages 1-3 (early game) and zero in stages 4-6 (matching V1's hard `round < 9` cutoff via the natural stage boundary).

### C — Joint-alpha categories

| Field | Length | Indexing |
|---|---|---|
| `score_joint_alpha_by_stage` | 6 | per stage, ∈ [0, 1] |

Applies to `bd.clay_rooms + bd.stone_rooms + bd.people + bd.bonus_points`.

## 4. Resources

V3 uses a **three-component pattern per resource**: a slot-indexed primary vector, an optional regime overlay vector, and a generic per-unit scalar. All three are gated by a per-stage weight.

The "double or triple counting" framing: any individual resource unit contributes through ALL applicable components — the same wood adds to its fence-slot value, the pre-3rd-room bonus (if applicable), and the generic per-unit value. The optimizer can put weight on whichever components matter; tuning typically pushes one component up and the others toward zero, but the architecture doesn't force this.

### Wood (27 params)

| Component | Length | Indexing | Activation |
|---|---|---|---|
| `wood_fence_vector` | 15 | **fence slot** (0 = 1st fence, 14 = 15th) | Always |
| `wood_pre_3rd_room_vector` | 5 | wood count (1st through 5th owned) | Only when `num_rooms ≤ 2` |
| `wood_generic_value` | scalar | n/a | Always (per unit) |
| `wood_weight_by_stage` | 6 | per stage | gates the sum |

**Fence-vector indexing — critical detail:** the player owns N wood, has already built K fences. Wood is "spent" on fences in order: the N pieces of wood map to fence slots K+1 .. K+N. The contribution is `Σ wood_fence_vector[i]` for `i in range(K, min(K+N, 15))`. So **early fences are valued separately from late fences** — V1's "tier 1 at high rate" effect emerges from setting `wood_fence_vector[0..5]` higher than `wood_fence_vector[6..14]`.

**Pre-3rd-room overlay:** activated when the player still has ≤2 rooms (the starting state). Captures V1's hardcoded `wood_first5_no_room = 1.5` bonus for "first 5 wood matter more if you haven't built your 3rd room yet." Length 5, applied to first 5 owned wood. Adds *on top of* the fence-vector contribution.

### Reed (15 params)

| Component | Length | Indexing | Activation |
|---|---|---|---|
| `reed_room_vector` | 6 | reed count in supply (1st through 6th) | Always |
| `reed_renovation_vector` | 2 | renovation step (0 = next, 1 = subsequent) | Only when `house_material != STONE` |
| `reed_generic_value` | scalar | n/a | Always |
| `reed_weight_by_stage` | 6 | per stage | gates the sum |

**Room vector default `(5.0, 1.5, 0.3, 0.3, 0.0, 0.0)`** captures the "1st reed is worth a lot, 2nd reed completes a room cost (+1.5), beyond is low value." The asymmetry models the discreteness of room cost (rooms need exactly 2 reed).

**Renovation vector default `(0.5, 0.3)`** represents "first reed for the next renovation step is worth 0.5, second reed for the renovation step *after that* is worth 0.3" — gated by remaining renovation steps (2 if WOOD house, 1 if CLAY, 0 if STONE).

### Clay (13 params)

| Component | Type | Indexing | Activation |
|---|---|---|---|
| `clay_cookware_vector` | length 5 | clay count (1..5) | Only when `not _has_cooking(state, p_idx)` |
| `clay_renovation_per_room` | scalar | applied to `min(num_clay, num_rooms)` | Only when `house_material == WOOD` |
| `clay_generic_value` | scalar | n/a | Always |
| `clay_weight_by_stage` | 6 | per stage | gates the sum |

**Cookware vector** captures V1's "first 5 clay matter most when you haven't bought cookware yet" (because Fireplace = 2 clay, Cooking Hearth = 4-5 clay).

**Renovation per room** is a scalar by user request (could become a length-5 vector if more granularity is needed). Applied up to the number of rooms the player has — matching the wood→clay renovation cost of 1 clay per room.

### Stone (8 params)

| Component | Type | Indexing | Activation |
|---|---|---|---|
| `stone_renovation_per_room` | scalar | applied to `min(num_stone, num_rooms)` | Only when `house_material == CLAY` (clay→stone renovation) |
| `stone_generic_value` | scalar | n/a | Always |
| `stone_weight_by_stage` | 6 | per stage | gates the sum |

Stone has the simplest structure — no "next slot" indexing. The user opted not to add an explicit major-improvement vector for stone (the per-major values like Well, Stone Oven are handled by the V1 carry-over `_hubris_major_value`).

## 5. V1 carry-overs

V3 doesn't reimplement everything. Several V1 helpers and config fields are carried over unchanged, because they were already principled and well-tuned. The V3 evaluator imports them via the existing V1 helpers — the helpers duck-type on the config object's fields, which `HeuristicConfigV3` exposes with matching names.

### V1 helpers V3 calls

| V1 helper | What it does | Config fields read |
|---|---|---|
| `_hubris_family_value` | Per-future-round value for 3rd/4th/5th family members | `family_per_round` |
| `_hubris_empty_room_value` | Anticipated value of empty rooms (future people) | `empty_room_rate_pre_basic_wish`, `empty_room_rate_post_basic_wish` |
| `_hubris_field_location_bonus` | Per-cell bonus for fields on center 4 cells | `field_center_bonus` |
| `_hubris_pasture_location_bonus` | Per-cell bonus for pasture cells with column ≥2 | `pasture_location_bonus` |
| `_hubris_starting_player_bonus` | Flat bonus when SP token held | `starting_player_bonus` |
| `_hubris_renovation_bonus` | Per-renovation-step bonus | `renovation_bonus_per_step_early/late` |
| `_hubris_major_value` | Replaces score()'s major-improvement leaf with per-major utility values | `fireplace_value*`, `hearth_value*`, `cooking_secondary_vp`, `well_value`, `well_food_per_future`, `clay_oven_value`, `stone_oven_value`, `joinery_value`, `pottery_value`, `basketmaker_value` |
| `_food_term_hubris` | Stage-dependent food + moves-keyed begging penalty | `hubris_food_by_stage`, `hubris_begging_by_moves` |

### Default values copied from CONFIG_V1_T2

`DEFAULT_CONFIG_V3` seeds its carry-over fields with **CONFIG_V1_T2's tuned values** rather than V1's hand-picked defaults. This means a fresh `HubrisHeuristicV3()` starts with the strongest known carry-over parameters. The fields explicitly copied (search for "From V1_T2 tuning" in `heuristic.py`):

- `family_per_round`, `empty_room_rate_pre/post_basic_wish`, `starting_player_bonus`
- All cooking-implement override values (`fireplace_value*`, `hearth_value*`, `cooking_secondary_vp`)
- All food and begging arrays (`hubris_food_by_stage`, `hubris_begging_by_moves`)

Fields NOT tuned in V1_T2 (well, ovens, joinery/pottery/basketmaker) keep V1's hand-picked defaults. The renovation bonus defaults are 0.0/0.0 (renovation was newly-enabled in V1's round 3 and not tuned; setting to 0 preserves backwards compatibility).

### What V3 does NOT carry over

These V1 helpers are **deleted** from V3 because V3's category structure subsumes them:

| V1 helper | V3 replacement |
|---|---|
| `_hubris_resource_value` | V3's three-component resource pattern (§4) |
| `_hubris_breeding_value` | V3's breeding-pair category (§B2) |
| `_hubris_unfenced_stable_value` | V3's unfenced-stables category (§B3) |
| `_hubris_crop_field_pair_bonus` | V3's crop-field-pair categories (§B1) |

V2's joint-frontier food handling (`_food_and_goods_term_v2`) is not in V3 either — V3 inherits V1's food handling unchanged via `_food_term_hubris`.

## 6. The evaluator (top-level orchestration)

`evaluate_hubris_v3(state, player_idx, config)` composes everything into one float:

```python
def evaluate_hubris_v3(state, player_idx, config):
    if state.phase == Phase.BEFORE_SCORING:
        total, _ = score(state, player_idx)
        return float(total)  # End-of-game: just the raw score.

    stage_idx = _stage_of_round(state.round_number) - 1  # 0..5
    p = state.players[player_idx]
    _, bd = score(state, player_idx)

    pts = 0.0
    # BLEND: 9 categories (fields, pastures, grain, veg, sheep, boar, cattle,
    #        fenced stables, unused spaces)
    pts += _v3_blend(...)  # one call per category
    ...

    # ADDITIVE-MULTIPLICATIVE: grain-pair, veg-pair, 3 breeding-pairs, unfenced-stables
    pts += <weight[stage]> * <value vector lookup>
    ...

    # RESOURCES (V3 own pattern): wood, clay, reed, stone
    pts += _v3_resources_contribution(state, p, player_idx, stage_idx, config)

    # JOINT-ALPHA: clay rooms, stone rooms, people, craft bonuses
    j = config.score_joint_alpha_by_stage[stage_idx]
    pts += j * (bd.clay_rooms + bd.stone_rooms + bd.people + bd.bonus_points)

    # Begging at full weight
    pts += bd.begging_markers

    # Major improvement override (V1's hubris helper)
    pts += _hubris_major_value(state, player_idx, config)

    # V1 carry-over additive terms
    pts += _hubris_family_value(state, p, config)
    pts += _hubris_empty_room_value(state, p, config)
    pts += _hubris_field_location_bonus(p, config)
    pts += _hubris_pasture_location_bonus(p, config)
    pts += _hubris_starting_player_bonus(state, player_idx, config)
    pts += _hubris_renovation_bonus(state, p, config)

    # Food / begging penalty (V1 carry-over)
    pts += _food_term_hubris(state, p, player_idx, config)

    return pts
```

Authoritative implementation is in `agricola/agents/heuristic.py`.

## 7. Game-state helpers introduced for V3

Several pure helpers are used by `evaluate_hubris_v3` and the resource/pair logic. They're in the same module as the evaluator:

| Helper | Returns | Purpose |
|---|---|---|
| `_v3_count_field_tiles(p)` | int | # CellType.FIELD cells |
| `_v3_count_plowed_empty_fields(p)` | int | # field cells with no grain or veg (for pair counting) |
| `_v3_total_grain(p)`, `_v3_total_veg(p)` | int | supply + on-field totals |
| `_v3_pasture_counts(p)` | (total, large) | for the two pasture vectors |
| `_v3_fenced_stable_count(p)` | int | sum of `num_stables` across pastures |
| `_v3_crop_field_pair_counts(p)` | (grain, veg) | grain-priority pair allocation |
| `_v3_breeding_pair_counts(p)` | (cattle, boar, sheep) | priority pair allocation |
| `_v3_fences_built(p)` | int | sum of horizontal+vertical fence bitmaps |
| `_v3_clip_index(count, vec_len)` | int | saturating clip for vector lookups |
| `_v3_blend(stage_idx, alpha_arr, parameterized, score_leaf)` | float | the Style A formula |

All take a `PlayerState` (or `GameState`, where needed). Pure functions, no side effects.

## 8. Known limitations / future work

### 8.1 Food double-count (inherited from V1)

V3 uses V1's `_food_term_hubris` unchanged. This means the V1 "convertible goods don't trigger a begging penalty AND still score as goods" double-count is still present. A V3-specific fix (e.g., convertible-discount-by-stage) was discussed but not implemented; see HUBRIS_V1_NOTES.md §4 for the V2 attempt history and why it lost head-to-head.

### 8.2 Stone has no slot-indexed vector

The other three resources have a primary slot-indexed vector (wood: fence slot, reed: room slot, clay: cookware slot). Stone has only the `stone_renovation_per_room` scalar + generic value. The major-improvement use of stone (Well, Stone Oven, etc.) is captured via the V1 `_hubris_major_value` carry-over rather than a stone-major-vector. Could be added if tuning suggests stone is undervalued in mid-game.

### 8.3 Single shared α for pasture vectors

`pasture_value_all` and `pasture_value_large` share one `pasture_blend_alpha_by_stage`. Per-vector alphas would be more expressive — flagged for future expansion if tuning suggests the two vectors want different time profiles.

### 8.4 Empty rooms still use V1's hardcoded constants

`_hubris_empty_room_value` has hardcoded values (the "+3 per assumed future person", the "+2 rounds to fill" delay, the `min(12, ...)` cap). These could be parameterized in V3 but weren't — kept as V1 carry-over to limit V3's parameter explosion.

### 8.5 Joint-alpha lumps 4 disparate categories

`score_joint_alpha_by_stage` modulates clay rooms, stone rooms, people, AND craft bonuses with one curve. These categories have different time-variance profiles. Splitting into per-category alphas would add 24 params (4 × 6) — flagged for future expansion if tuning suggests the lump is too coarse.

### 8.6 Discrete cutoffs in helpers

A handful of integer cutoffs are hardcoded:
- "pasture capacity ≥ 4" → `pasture_value_large` activation
- "≤ 2 rooms" → `wood_pre_3rd_room_vector` activation
- "≥ 3 capacity per pasture" → breeding-capable threshold
- "round 12 cap" in empty-room helper

CMA-ES doesn't handle integers naturally. These are not in `HeuristicConfigV3` and aren't tuned by the current pipeline. If we want to vary them, the simplest path is a manual sweep (try K ∈ {3, 4, 5} and compare margins).

### 8.7 Parameter count vs CMA-ES tractability

V3 has ~250 continuous parameters. The category-by-category tuning approach (see `V3_TRAINING_PIPELINE.md`) keeps any single CMA-ES run to ≤ 101 dimensions, well within the algorithm's comfortable range. Tuning all 250 at once would be much harder (popsize ≈ 30+, generations ≈ 100+ for adequate convergence).
