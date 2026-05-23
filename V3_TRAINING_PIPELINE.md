# V3 Training Pipeline & Next Steps

How the V3 heuristic gets tuned. Covers the CMA-ES setup, the per-category tuning script, the orchestrator that chains categories together, the `v3_best.json` convention, and the integration with `play_web.py`. Ends with a summary of the current training state and open next-step questions.

Companion docs: **`V3_DESIGN.md`** (the V3 evaluator's architecture) and **`HEURISTIC_TUNING_PLAN.md`** (older V1-era tuning plan, partially superseded).

## 1. The optimizer: CMA-ES, briefly

CMA-ES = Covariance Matrix Adaptation Evolution Strategy. A black-box continuous optimizer that searches by maintaining a multivariate Gaussian distribution over the parameter space:

- **mean vector** `m` — current best guess
- **step size** `σ` — how far to sample
- **covariance matrix** `C` — which directions in parameter space tend to vary together

Each iteration ("generation"):
1. Sample `popsize` candidates from `N(m, σ²C)`.
2. Evaluate fitness for each (we play matches against a fixed opponent).
3. Update `m` toward the better candidates, update `C` to elongate along directions the good candidates moved, update `σ` based on whether progress is consistent (grow) or oscillating (shrink).

Used here because:
- Game outcomes are noisy and non-differentiable — no gradient descent.
- Handles 10-100+ dimensions comfortably (V3 categories are 18-101 params each).
- The Python `cma` library has a clean ask/tell loop, supports pickle save/resume, and handles bounded box constraints.

Library: `pip install cma`. Already installed.

## 2. The single-category tune script

`scripts/tune_heuristic.py` — runs ONE CMA-ES optimization over one TUNABLE category.

### 2.1 Conceptual model

Each invocation:
1. Loads a **warm-start base config** (`--from`). This config defines all V3 fields; the ones in the active TUNABLE will be overridden by CMA-ES samples, the rest stay frozen.
2. Loads/constructs an **opponent config** (`--baseline`). The candidate plays against this in every fitness evaluation.
3. Picks a TUNABLE list (`--category`) — the subset of config fields CMA-ES will tune.
4. Either constructs a fresh CMA-ES (`x0` from TUNABLE defaults, `σ₀ = 0.3`) or restores a previous one (`--resume <path>.cma.pkl`).
5. Runs `--max-gens` generations. Each generation: sample `--popsize` candidates, evaluate each via 100 games (`--n-seeds 100`) of `candidate vs baseline`, tell CMA-ES the (negative) margins.
6. After the loop, runs a **holdout match** on 100 disjoint seeds (`--holdout-start 1000 --holdout-n 100`) to verify generalization.
7. Writes three files alongside `--output`:
   - `<stem>.json` — best config, training history, holdout result, metadata
   - `<stem>.log` — human-readable mirror of stdout
   - `<stem>.cma.pkl` — full pickled `CMAEvolutionStrategy` for resume
8. Compares holdout to the existing `tuned_configs/<arch>_best.json` and updates it if the new holdout is better.

### 2.2 Key CLI flags

| Flag | Default | Purpose |
|---|---|---|
| `--category` | `v3_resources` | Which TUNABLE list (see §3) |
| `--from <spec>` | `default_v3` | Warm-start base. Either a named config (`default`, `t2`, `default_v3`) or a path to a previous run's JSON (loads its `best_config`). |
| `--baseline <spec>` | `t2` | Opponent config. Same name-or-path semantics. |
| `--resume <path.cma.pkl>` | None | Restore a previous CMA-ES state. `--max-gens` becomes "additional gens" from the resumed countiter. |
| `--n-seeds` | 50 | Training games per evaluation |
| `--max-gens` | 10 | Generations to run (or "additional gens" if resuming) |
| `--popsize` | 12 | CMA-ES population per gen |
| `--sigma0` | 0.3 | Initial step size (fresh runs only; resume ignores) |
| `--cma-seed` | 1 | CMA-ES internal RNG seed |
| `--jobs` | `cpu_count()` | Parallel processes for population evaluation |
| `--holdout-start, --holdout-n` | 1000, 100 | Holdout seed range |
| `--output <path>` | `tuned_configs/<ts>.json` | Output path; `.log` and `.cma.pkl` companion files share the stem |

### 2.3 Fitness convention

CMA-ES minimizes by default. The fitness is `-avg_margin` (negative because we want to MAXIMIZE margin). All logging and JSON output show `+avg_margin` (with sign flipped back for human readability).

### 2.4 The x0 fallback (important)

After the CMA-ES loop, the script compares `es.best.f` (the best candidate seen by CMA-ES) to `sanity_f0` (the fitness of `x0`, evaluated before the loop). If the best is worse than `x0`, the script **falls back to `x0`** as the official "best config":

```
⚠️ CMA-ES best (+12.467) is worse than x0 sanity (+13.010) by 0.543.
   Falling back to x0 (warm-start base unchanged for the 18 tuned fields).
```

**Why this matters:** several categories (notably food) inherit defaults from CONFIG_V1_T2 that are already near-optimal. CMA-ES samples around `x0` with `σ=0.3` perturbations of size ~10-30% on each field; these typically degrade fitness because `x0` is already a local optimum. CMA-ES converges back toward `x0` over many generations, but with only 10 max-gens it may not catch up.

Without the fallback, the chain-forward orchestrator would propagate degraded configs to subsequent categories. With the fallback, the worst case is "no improvement from this category" — never "regression from this category."

The fallback uses `x0` literally (not the warm-start base). For categories where TUNABLE's defaults match the warm-start base's field values (the common case), this is equivalent.

### 2.5 The `<arch>_best.json` auto-update

After holdout completes, the script reads `tuned_configs/<candidate_arch>_best.json` (creating it if absent) and compares its `holdout.avg_margin` to the new run's holdout. If the new is better (or no existing best), the script copies the new JSON to that path. Implementation: `_maybe_update_best_pointer()` in `tune_heuristic.py`.

This keeps `tuned_configs/v3_best.json` always pointing at the strongest V3 config we've ever produced.

## 3. The TUNABLE categories

A TUNABLE is a list of `(name, default, lower, upper, config_path)` tuples. `config_path` is either:
- `("field_name",)` for a scalar field
- `("field_name", idx)` for a tuple field (e.g., `("family_per_round", 0)`)
- `("field_name", outer, inner)` for nested tuples (e.g., `("hubris_food_by_stage", 0, 0)`)

`vector_to_config(x, base, tunable)` takes a CMA-ES sample vector `x`, applies it to `base` via the path specs, and returns a new config (using `dataclasses.replace`).

### Current category registry

Defined in `scripts/tune_heuristic.py`. Each entry maps to `(tunable_list, architecture)`:

| Category | Architecture | Param count | What it tunes |
|---|---|---|---|
| `v1_addonly` | V1 | 12 | Renovation + location + unfenced-stable + 7 major-improvement values. Used in V1's round 3. Kept for historical reference. |
| `v3_fields_crops` | V3 | 60 | Fields/grain/veg value vectors + blend alphas + grain-pair/veg-pair value vectors + weights. |
| `v3_pastures_animals` | V3 | 101 | Pasture (2 vectors + alpha), sheep/boar/cattle value vectors + alphas, fenced stables, 3 breeding-pair values + weights, unfenced stables. |
| `v3_resources` | V3 | 63 | Wood (15+5+1 vector entries + 6 stage weights), reed (6+2+1+6), clay (5+1+1+6), stone (1+1+6). |
| `v3_food` | V3 | 18 | `hubris_food_by_stage` (6 stages × 2 = 12) + `hubris_begging_by_moves` (6). |

### Base configs

`BASE_CONFIGS` maps name to `(config_instance, arch_label)`:

| Name | Config | Arch |
|---|---|---|
| `default` | `DEFAULT_CONFIG` (V1's hand-picked) | v1 |
| `t2` | `CONFIG_V1_T2` (V1's round-2 tuned, +8.85 vs default) | v1 |
| `default_v3` | `DEFAULT_CONFIG_V3` (V3's defaults, with V1_T2 carry-overs) | v3 |

`_resolve_config(spec)` also accepts a JSON file path; it loads the JSON's `best_config` field and constructs the right dataclass based on the JSON's `candidate_arch` field.

## 4. Save/resume

### Save (every generation, automatic)

At the end of each generation, `tune_heuristic.py`:
1. Writes the JSON with the latest `best_x`, history, etc.
2. Calls `pickle.dump(es, <stem>.cma.pkl)` — atomic via temp+rename.

The pickle contains the full `CMAEvolutionStrategy` object: mean, σ, covariance matrix, evolution paths, all counters, hyperparameters. Restoring it gives bit-for-bit continuation.

### Resume (`--resume <path>`)

When `--resume` is set:
1. `es = pickle.load(open(path, 'rb'))` — restore full state.
2. Check `es.N` matches `len(tunable)` (refuses if the category doesn't match).
3. `target_gen = es.countiter + args.max_gens` — `--max-gens` is interpreted as *additional* generations.
4. `es.opts['maxiter'] = target_gen` — bump the saved cap to allow more iterations.
5. Loop until `es.countiter >= target_gen` or other CMA-ES stop conditions trigger (ignoring `'maxiter'` since we just bumped it).

The warm-start base (`--from`) is **independent** of the resume — the CMA-ES state lives in parameter space (which fields to optimize), the base lives in config space (the values of fields NOT being optimized). So you can resume with a different base, letting CMA-ES continue exploring the same parameter directions but in a new context.

### Why CMA-ES state matters for chained runs

When tuning categories in sequence (resources → pastures → food → resources again, etc.), the second run of a category benefits from the first run's learned covariance: CMA-ES already knows which parameter directions tend to move together, and what σ scale is appropriate. Resuming gives a head start.

## 5. The orchestrator: `run_iterative_v3.py`

Chains multiple `tune_heuristic.py` invocations in sequence. One invocation per (pass, category) pair.

### 5.1 The chain

Per pass, categories run in a fixed order:
1. `v3_fields_crops`
2. `v3_food`
3. `v3_resources`
4. `v3_pastures_animals`

Each step's `--from` is the previous step's output JSON (so the chain accumulates tuned values cumulatively within a pass). The very first step's `--from` is whatever was passed via `--start-from` (default: `tuned_configs/v3_best.json`).

On pass 2+, each step also passes `--resume` pointing to *this category's pickle from the previous pass*. So pass 2's `v3_fields_crops` resumes pass 1's fields_crops CMA-ES — with the CHAIN base reflecting all of pass 1's tunings.

The "block-coordinate Gauss-Seidel" interpretation: each pass cycles through 4 blocks; each block's CMA-ES is warm-restarted from where it last left off, but operating against a fitness landscape that has shifted because other blocks moved.

### 5.2 Key flags

| Flag | Purpose |
|---|---|
| `--n-passes N` | How many full cycles to do. Default 3. |
| `--max-gens N` | Per-step generation cap. Default 10. |
| `--n-seeds N` | Per-evaluation game count. Default 100. |
| `--baseline <spec>` | Opponent for ALL steps. Default `t2`. |
| `--start-from <path>` | Initial warm-start base for the first step of pass 1. Default `tuned_configs/v3_best.json`. |
| `--label <str>` | Prefix for output filenames in `tuned_configs/`. Default `iter`. |
| `--start-step N` | Skip the first N-1 steps. For resuming a partially-completed iteration. |
| `--initial-pickles "cat:path,cat:path"` | Pre-populate the per-category pickle map (for resuming specific categories). |
| `--dry-run` | Print the command sequence without executing. |

### 5.3 Output files

For each step, three files are written to `tuned_configs/`:
- `<label>_p<pass>_<category>.json` — best config + history + holdout result
- `<label>_p<pass>_<category>.log` — per-generation log mirror
- `<label>_p<pass>_<category>.cma.pkl` — pickled CMA-ES state

Plus the orchestrator's own log (where you redirect its stdout — typically `tuned_configs/iter_orchestrator.log`).

### 5.4 Compute estimate

Per step wall time (8 cores, `python -O`, n_seeds=100):

| Category | popsize | min/gen | 10-gen step |
|---|---|---|---|
| fields_crops (d=60) | 16 | ~5.3 | ~53 min |
| food (d=18) | 13 | ~4.3 | ~43 min |
| resources (d=63) | 17 | ~5.6 | ~57 min |
| pastures_animals (d=101) | 18 | ~6.0 | ~60 min |
| **Per pass total** | | | **~3.5 hours** |

2 passes ≈ 7 hours. 3 passes ≈ 10.5 hours. Overnight-job territory.

## 6. v3_best.json convention

`tuned_configs/v3_best.json` is the **always-up-to-date pointer to the strongest V3 config we've ever measured**. Bootstrapped manually, updated automatically by every successful tuning run.

### Auto-update logic

At the end of every `tune_heuristic.py` run, `_maybe_update_best_pointer(new_json, arch, new_holdout_margin)`:
1. Reads existing `tuned_configs/<arch>_best.json`'s `holdout.avg_margin`.
2. If new margin > existing (or no existing): `shutil.copy(new_json, best_path)`.
3. Prints either "UPDATED: +X → +Y" or "unchanged; existing +X > new +Y".

Comparison metric: **holdout margin** (more honest than training margin; less prone to overfitting noise).

### Manual bootstrap

`v3_best.json` was initially bootstrapped from the original V3 resources tuning run (which was killed at gen 25, holdout manually computed afterward at +8.72). See the chat history for the bootstrap step.

## 7. Web UI integration

`play_web.py --v3-config <json_path>` loads the JSON's `best_config` and uses it whenever a seat is set to `hubris_v3`. Without the flag, `hubris_v3` falls back to `DEFAULT_CONFIG_V3` (untuned baseline).

**Stable run command for playing against the current strongest V3:**

```bash
python play_web.py --seats human hubris_v3 --v3-config tuned_configs/v3_best.json
```

Since `v3_best.json` is auto-maintained, this command always uses the latest champion config without needing updates after each tuning run.

The frontend dropdown in the "New Game" dialog has been simplified to **human / random / v1 / v3** (with internal translation: `v1` → backend `hubris` (V1+T2), `v3` → backend `hubris_v3` with the loaded config). The CLI's `--seats` flag still uses the full backend names (`hubris`, `hubris_v3`, etc.) for backwards compatibility.

## 8. Current training state

### 8.1 Per-parameter tuning status (cheat sheet)

Quick reference for what's been optimized and what hasn't, as of `CONFIG_V3_T1`'s promotion (the current `tuned_configs/v3_best.json`).

**Headline numbers**: `HeuristicConfigV3` defines ~278 continuous-float parameters. Of these:

| Status | Scalars | Source of values |
|---|---|---|
| Tuned via V3 iterative CMA-ES | **224** | iter1 (this session's runs); chained over multiple steps |
| Inherited from `CONFIG_V1_T2`'s tuning (V3 v3_food fell back to x0) | **18** | V1 round 2 tuned, never improved by V3 v3_food's attempt |
| Inherited from `CONFIG_V1_T2`'s tuning (no V3 TUNABLE includes them) | **13** | V1 round 2 tuned, never re-tuned in V3 |
| Never tuned — V1 carry-overs at hand-picked defaults | **10** | V1 round 3 attempted but did not promote; V1 hand-picked defaults |
| Never tuned — V3-specific, hand-picked defaults | **12** | V3 design (hand-picked) |
| **Total** | **~277** | |

So roughly **84% of V3's parameters are at tuned values** (242 + 13 = 255 tuned vs ~22 untuned). The 22 untuned scalars are spread across:
- 12 in V3's `score_joint_alpha` and `unused_spaces_alpha` curves (per-stage)
- 10 in V1 carry-over scalars that V1 round 3 tried but couldn't improve

### 8.2 Detailed parameter map

The full picture per category. Each row is a group of related fields in `HeuristicConfigV3`; "TUNABLE" column says which TUNABLE list (if any) covers it; "Tuned by" says where the current values came from.

#### V3-specific fields covered by a TUNABLE

| Field group | # scalars | TUNABLE | Current values from |
|---|---|---|---|
| `plowed_field_value` | 7 | `v3_fields_crops` | iter1 pass-2 fields_crops (killed at gen 4/10) |
| `field_blend_alpha_by_stage` | 6 | `v3_fields_crops` | iter1 pass-2 fields_crops |
| `grain_value` | 10 | `v3_fields_crops` | iter1 pass-2 fields_crops |
| `grain_blend_alpha_by_stage` | 6 | `v3_fields_crops` | iter1 pass-2 fields_crops |
| `veg_value` | 5 | `v3_fields_crops` | iter1 pass-2 fields_crops |
| `veg_blend_alpha_by_stage` | 6 | `v3_fields_crops` | iter1 pass-2 fields_crops |
| `grain_pair_value` | 4 | `v3_fields_crops` | iter1 pass-2 fields_crops |
| `grain_pair_weight_by_stage` | 6 | `v3_fields_crops` | iter1 pass-2 fields_crops |
| `veg_pair_value` | 4 | `v3_fields_crops` | iter1 pass-2 fields_crops |
| `veg_pair_weight_by_stage` | 6 | `v3_fields_crops` | iter1 pass-2 fields_crops |
| `pasture_value_all` | 5 | `v3_pastures_animals` | iter1 pass-1 pastures (10/10 gens) |
| `pasture_value_large` | 5 | `v3_pastures_animals` | iter1 pass-1 pastures |
| `pasture_blend_alpha_by_stage` | 6 | `v3_pastures_animals` | iter1 pass-1 pastures |
| `sheep_value` | 9 | `v3_pastures_animals` | iter1 pass-1 pastures |
| `sheep_blend_alpha_by_stage` | 6 | `v3_pastures_animals` | iter1 pass-1 pastures |
| `boar_value` | 8 | `v3_pastures_animals` | iter1 pass-1 pastures |
| `boar_blend_alpha_by_stage` | 6 | `v3_pastures_animals` | iter1 pass-1 pastures |
| `cattle_value` | 7 | `v3_pastures_animals` | iter1 pass-1 pastures |
| `cattle_blend_alpha_by_stage` | 6 | `v3_pastures_animals` | iter1 pass-1 pastures |
| `fenced_stable_value` | 5 | `v3_pastures_animals` | iter1 pass-1 pastures |
| `fenced_stable_blend_alpha_by_stage` | 6 | `v3_pastures_animals` | iter1 pass-1 pastures |
| `cattle_breeding_pair_value` + `_weight_by_stage` | 7 | `v3_pastures_animals` | iter1 pass-1 pastures |
| `boar_breeding_pair_value` + `_weight_by_stage` | 7 | `v3_pastures_animals` | iter1 pass-1 pastures |
| `sheep_breeding_pair_value` + `_weight_by_stage` | 7 | `v3_pastures_animals` | iter1 pass-1 pastures |
| `unfenced_stable_value` | 5 | `v3_pastures_animals` | iter1 pass-1 pastures |
| `unfenced_stable_weight_by_stage` | 6 | `v3_pastures_animals` | iter1 pass-1 pastures |
| `wood_fence_vector` | 15 | `v3_resources` | iter1 pass-1 resources (10/10 gens) |
| `wood_pre_3rd_room_vector` | 5 | `v3_resources` | iter1 pass-1 resources |
| `wood_generic_value` | 1 | `v3_resources` | iter1 pass-1 resources |
| `wood_weight_by_stage` | 6 | `v3_resources` | iter1 pass-1 resources |
| `reed_room_vector` | 6 | `v3_resources` | iter1 pass-1 resources |
| `reed_renovation_vector` | 2 | `v3_resources` | iter1 pass-1 resources |
| `reed_generic_value` | 1 | `v3_resources` | iter1 pass-1 resources |
| `reed_weight_by_stage` | 6 | `v3_resources` | iter1 pass-1 resources |
| `clay_cookware_vector` | 5 | `v3_resources` | iter1 pass-1 resources |
| `clay_renovation_per_room` | 1 | `v3_resources` | iter1 pass-1 resources |
| `clay_generic_value` | 1 | `v3_resources` | iter1 pass-1 resources |
| `clay_weight_by_stage` | 6 | `v3_resources` | iter1 pass-1 resources |
| `stone_renovation_per_room` | 1 | `v3_resources` | iter1 pass-1 resources |
| `stone_generic_value` | 1 | `v3_resources` | iter1 pass-1 resources |
| `stone_weight_by_stage` | 6 | `v3_resources` | iter1 pass-1 resources |
| `hubris_food_by_stage` | 12 | `v3_food` | V1_T2 carry-over (V3 v3_food's CMA-ES fell back to x0 — never beat V1_T2's tuned values) |
| `hubris_begging_by_moves` | 6 | `v3_food` | V1_T2 carry-over (same fallback) |
| **Subtotal** | **242** | | |

#### V1 carry-over fields (in HeuristicConfigV3, NOT in any V3 TUNABLE)

These fields live on `HeuristicConfigV3` so the carry-over V1 helpers (`_hubris_family_value`, `_hubris_major_value`, etc.) can read them via duck typing. They're NOT touched by any V3 TUNABLE.

| Field | # scalars | Tuned by | Notes |
|---|---|---|---|
| `family_per_round` | 3 | V1 round 2 (CONFIG_V1_T2) | |
| `empty_room_rate_pre_basic_wish` | 1 | V1 round 2 | |
| `empty_room_rate_post_basic_wish` | 1 | V1 round 2 | |
| `starting_player_bonus` | 1 | V1 round 2 | |
| `fireplace_value`, `_mid`, `_late` | 3 | V1 round 2 | |
| `hearth_value`, `_mid`, `_late` | 3 | V1 round 2 | |
| `cooking_secondary_vp` | 1 | V1 round 2 | |
| `field_center_bonus` | 1 | **Never tuned** | V1 round 3 attempted, did not promote |
| `pasture_location_bonus` | 1 | **Never tuned** | V1 round 3 attempted, did not promote |
| `renovation_bonus_per_step_early` | 1 | **Never tuned** | V1 round 3 attempted, did not promote. At 0.0 (backwards-compat). |
| `renovation_bonus_per_step_late` | 1 | **Never tuned** | V1 round 3 attempted, did not promote. At 0.0. |
| `well_value` | 1 | **Never tuned** | V1 round 3 attempted, did not promote |
| `well_food_per_future` | 1 | **Never tuned** | V1 round 3 attempted, did not promote |
| `clay_oven_value` | 1 | **Never tuned** | V1 round 3 attempted, did not promote |
| `stone_oven_value` | 1 | **Never tuned** | V1 round 3 attempted, did not promote |
| `joinery_value` | 1 | **Never tuned** | V1 round 3 attempted, did not promote |
| `pottery_value` | 1 | **Never tuned** | V1 round 3 attempted, did not promote |
| `basketmaker_value` | 1 | **Never tuned** | V1 round 3 attempted, did not promote |
| **Subtotal** | **23** | (13 from V1_T2; 10 untuned) | |

#### V3-specific fields with NO TUNABLE coverage

| Field | # scalars | Tuned by | Notes |
|---|---|---|---|
| `score_joint_alpha_by_stage` | 6 | **Never tuned** | Hand-picked `(0.5, 0.6, 0.7, 0.8, 0.9, 1.0)` |
| `unused_spaces_alpha_by_stage` | 6 | **Never tuned** | Hand-picked `(1.0, 0.7, 0.5, 0.3, 0.1, 0.0)` |
| **Subtotal** | **12** | | |

### 8.3 Completed runs (in chronological order)

1. **V1 round 1** — 10 params, training +1.76, holdout +2.28 (68-0-32 vs V1 default). Did not promote.
2. **V1 round 2** — 58 params, training +8.10, holdout **+8.85** (90-1-9 vs V1 default). Promoted as **`CONFIG_V1_T2`**.
3. **V1 round 3 (add-only)** — 12 params, training +0.14, holdout −0.88 (46-0-54 vs V1+T2). Did not promote. Confirmed V1 architecture at local optimum.
4. **V3 resources (initial)** — 63 params, killed at gen 25 of 30 with training +11.82. Manual holdout: +8.72 (82-1-17 vs V1+T2). Bootstrapped initial `v3_best.json`.
5. **iter1** (2-pass iterative) — 4 categories × 2 passes (8 steps), `--baseline t2`. Killed at pass 2 fields_crops gen 4 of 10 when we discovered an x0 bug. The killed-mid-run pass-2 fields_crops config produced **holdout +14.03 (100-0-0 vs V1+T2)** — the strongest V3 result so far. Promoted as **`CONFIG_V3_T1`**.
6. **iter2** (in progress at time of writing) — 2-pass iterative, `--baseline v3_t1` for both training and holdout (per user direction: "I don't care about continuity"). x0 bug fixed. Holdout comparison now measures progress over V3_T1, not over V1+T2.

### 8.4 iter2 setup (currently running)

Started from `v3_best.json` (= CONFIG_V3_T1). Configuration:
- `--n-passes 2`, `--max-gens 10`, `--n-seeds 100`
- `--baseline v3_t1` (training AND holdout opponent = CONFIG_V3_T1)
- Per-category popsize: 16/13/17/18 for fields_crops/food/resources/pastures_animals
- All bug fixes in place: x0 from base_config (not TUNABLE defaults); session-best tracking (not stale es.best); sample-size check in `_maybe_update_best_pointer`.

Step-by-step plan:

| Step | Pass | Category | Notes |
|---|---|---|---|
| 1 | 1 | fields_crops | fresh CMA-ES from V3_T1's fields_crops values |
| 2 | 1 | food | fresh; expected to fall back (food was already V1_T2-tuned via V3_T1) |
| 3 | 1 | resources | fresh CMA-ES; the rich axis where iter1 saw biggest gains |
| 4 | 1 | pastures_animals | fresh CMA-ES |
| 5 | 2 | fields_crops | `--resume` pass 1's pickle (different chain context) |
| 6 | 2 | food | `--resume` (probably falls back again) |
| 7 | 2 | resources | `--resume` |
| 8 | 2 | pastures_animals | `--resume` |

Output files: `tuned_configs/iter2_p{1,2}_<cat>.{json,log,cma.pkl}` + `tuned_configs/iter2_orchestrator.log`.

Expected wall time: ~4-5 hours.

**Auto-update of `v3_best.json`**: each step's holdout is now `vs V3_T1`. The auto-update compares new vs existing (both `vs V3_T1`); v3_best.json updates whenever a step finds something strictly better than V3_T1 with at least as many holdout games as the existing entry.

## 9. Lessons from the iteration so far

### 9.1 Pass-1 fields_crops improved cleanly

+8.72 → +10.16 holdout (vs V1+T2). The fields/crops parameters were genuinely undertuned in V3's defaults; CMA-ES found a meaningfully better point.

### 9.2 Pass-1 food initially regressed

In its first 7 generations (before we caught the bug and added the x0 fallback), food's training best was +12.43 — *worse than* its `x0` sanity of +13.01. This was because food's defaults were already CONFIG_V1_T2's tuned values (carried into V3), and 10 generations weren't enough for CMA-ES to converge back to those values after exploring with σ=0.3.

**Fix:** the x0 fallback (§2.4) ensures that if CMA-ES can't beat x0, the step's output config equals x0 — preventing chain-forward degradation.

### 9.3 Categories with V1_T2-tuned defaults may be near-optimal

Food's near-immediate hitting-of-x0 (without improvement) suggests its V1_T2 values are already excellent for V3 too. The carry-over assumption ("V1_T2's food curve translates well to V3") is empirically supported.

This might also apply to other carry-over categories (cooking-implement values, family rates, etc.) — but those aren't in any current TUNABLE, so we haven't directly tested.

## 10. Next steps

### 10.1 Finish the current 2-pass run

ETA ~3.5 hours from when food (step 2) finishes. Monitor via:
```bash
tail -f tuned_configs/iter_orchestrator.log
grep -E "step .*/.*pass|UPDATED|Falling back" tuned_configs/iter_orchestrator.log
```

### 10.2 Analyze post-run

When done, expected outputs:
- `tuned_configs/iter_p{1,2}_<category>.{json,log,cma.pkl}` × 8 sets (but step 1 skipped this run — its files are from the initial pass-1 fields_crops we already had)
- `tuned_configs/v3_best.json` reflecting the strongest config
- `tuned_configs/iter_orchestrator.log` with the full per-step history

Analysis to do:
- **Which categories improved?** Compare each step's holdout to the previous step's. If multiple steps fall back to x0, those categories might not have tuning room.
- **Is there cross-category synergy?** If pass 2's first run (fields_crops) significantly improves over pass 1's, the food/resources/pastures tunings shifted the fitness landscape in a way that lets fields_crops do more.
- **Is the run still improving?** If pass 2 only adds 1-2 points over pass 1, we're near convergence and further passes have low value.

### 10.3 If still improving substantially, consider another pass

The orchestrator supports `--n-passes N` arbitrarily. If pass 2 added ≥+3 holdout margin over pass 1, run pass 3 by:
```bash
python -u scripts/run_iterative_v3.py \
    --n-passes 1 \
    --start-from tuned_configs/iter_p2_v3_pastures_animals.json \
    --initial-pickles "v3_fields_crops:tuned_configs/iter_p2_v3_fields_crops.cma.pkl,..." \
    --label iter3
```

### 10.4 Promote the best V3 config to a named constant

Once the iteration converges, promote `v3_best.json`'s `best_config` to a Python constant `CONFIG_V3_T1` in `agricola/agents/heuristic.py` (mirroring the `CONFIG_V1_T2` pattern). This makes the strong V3 config importable as a stable named reference rather than a file path.

### 10.4b ✅ Fixed: TUNABLE x0 vs warm-start base mismatch (+ related)

This section originally documented a bug observed during iter1. The bug is now **fixed** as of the iter2 launch. Kept here as historical context plus what the fixes do.

**The bug.** The fresh-CMA-ES code path used `TUNABLE`'s `default` field as `x0`. If a TUNABLE's defaults differed from the warm-start base's current values (which happens whenever a category has already been tuned in a prior chain step), CMA-ES at gen 0 would OVERWRITE the warm-start's tuned values with TUNABLE's hand-picked defaults — regressing the candidate. Observed concretely in iter1 pass-1 resources: warm-start had +10.16-tuned resources from a prior run; TUNABLE defaults were the V3 hand-picked starting points; sanity at gen 0 was -14.30 vs t2.

**Fix #1 — x0 from base_config.** `_x0_from_base(tunable, base_config)` reads each tuned field's value from `base_config` at run-time. So x0 ≡ warm-start base for the tuned fields (the candidate at x0 exactly equals the warm-start config). TUNABLE's `default` field is now informational only.

**Fix #2 — session-best, not es.best.** A subtle related issue: `es.best` is preserved across pickle save/resume, so on `--resume` it carries stale fitness from the prior run's context (different warm-start). The script previously used `es.best.x` directly as the official "best." Replaced with a session-local `session_best` dict that initializes to `(x0, sanity_f0)` and only updates from THIS session's samples — so the official best is never worse than the warm-start, and never stale-from-a-different-context.

**Fix #3 — sample-size guard in auto-update.** A smoke-test run with `--holdout-n 5` got lucky (5-0-0, margin +15.4) and overwrote a 100-game serious result (+14.03). `_maybe_update_best_pointer` now requires `new_n_games >= existing_n_games` before considering the margin comparison.

All three fixes were verified by smoke-tests across multiple `--from` / `--baseline` / `--resume` permutations. See chat history (2026-05-22 evening session) for the discovery + fix timeline.

### 10.5 Address the food double-count

V3 inherited V1's food handling. Once the iteration converges, consider implementing one of the options from `HUBRIS_V1_NOTES.md` §4:
- Convertible-discount-by-stage: add a 6-element array that scales `convertible` in the food shortfall calculation by stage.
- Or revisit V2's joint-frontier approach in V3 context.

### 10.6 ✅ Done: baseline graduated to V3_T1

This section originally speculated about graduating the baseline once V3 saturated vs T2. Done as of iter2: `--baseline v3_t1` controls both the training opponent and the holdout opponent. The auto-update of v3_best.json now compares "vs V3_T1" margins (with v3_best.json's existing holdout reset to +0.77, the V3_T1-vs-V3_T1 seat-asymmetry floor).

If iter2 yields a meaningful improvement, the promoted `CONFIG_V3_T2` will become the next baseline for iter3 (etc.). This is the iterative AlphaZero-style pattern: each tuning round's opponent is the previous round's best.

Available named baselines in `BASE_CONFIGS` (`scripts/tune_heuristic.py`):
- `default` / `t2` (V1 architecture)
- `default_v3` (V3 architecture, hand-picked starting defaults)
- `v3_t1` (V3 architecture, promoted CONFIG_V3_T1 — the iter1 result)
- Any JSON file path (loads `best_config` from a previous run)

### 10.7 Discrete cutoffs

There are several integer cutoffs in V3 helpers (pasture capacity ≥ 4, num_rooms ≤ 2, breeding capacity ≥ 3, empty-room cap at round 12). These aren't tuned by CMA-ES. If we want to test alternative values, the simplest approach is a manual sweep: try K ∈ {2, 3, 4, 5} for the "pasture large" threshold, run a 30-seed match against `t2` for each, pick the winner. See `V3_DESIGN.md` §8.6.

### 10.8 Future architectures: V4?

V3 is a major step up from V1, but several open design questions might motivate a V4:
- Should resource categories have *more* axes (e.g., separate vectors per regime rather than additive overlays)?
- Should the joint-alpha categories be split out into individual per-category alphas?
- Is there a smoother stage-boundary representation (per-round arrays rather than per-stage step functions)?

Defer all of these until V3 tuning has clearly converged.

## 11. Operational quick reference

### Start a fresh single category tuning (V3, against T2)
```bash
python -O scripts/tune_heuristic.py \
    --category v3_fields_crops \
    --from default_v3 \
    --baseline t2 \
    --max-gens 10 --popsize 16 --n-seeds 100
```

### Resume a category from where you left off
```bash
python -O scripts/tune_heuristic.py \
    --category v3_resources \
    --from tuned_configs/v3_best.json \
    --baseline t2 \
    --resume tuned_configs/iter_p1_v3_resources.cma.pkl \
    --max-gens 10
```

### Run the full iterative pipeline (2 passes)
```bash
nohup python -u scripts/run_iterative_v3.py \
    --n-passes 2 --max-gens 10 --n-seeds 100 \
    > tuned_configs/iter_orchestrator.log 2>&1 &
```

### Continue a partially-finished iteration
```bash
nohup python -u scripts/run_iterative_v3.py \
    --n-passes 2 \
    --start-step <N> \
    --start-from tuned_configs/<previous_step>.json \
    --initial-pickles "v3_food:tuned_configs/iter_p1_v3_food.cma.pkl,..." \
    > tuned_configs/iter_orchestrator.log 2>&1 &
```

### Quick V1-vs-V3 comparison match
```bash
python -O scripts/play_match.py --p0 hubris_v3 --p1 hubris --n 100
```
(`hubris_v3` uses DEFAULT_CONFIG_V3; to use the tuned config, use the `play_web.py --v3-config` path or write a one-off snippet that loads `v3_best.json`.)

### Play against the best V3 in the browser
```bash
python play_web.py --seats human hubris_v3 --v3-config tuned_configs/v3_best.json
```

### Monitor a running orchestrator
```bash
tail -f tuned_configs/iter_orchestrator.log
grep -E "step .*/.*pass|UPDATED|Falling back" tuned_configs/iter_orchestrator.log
ps aux | grep -E "tune_heuristic|run_iterative"
```

### Kill a runaway training
```bash
pkill -f "run_iterative_v3"
pkill -f "tune_heuristic.py"
```
