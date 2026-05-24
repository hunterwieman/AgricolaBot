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
| `--restricted` / `--no-restricted` | **ON** | Builds candidate, baseline, and holdout agents with `legal_actions_fn=restricted_legal_actions`. Recorded as `"restricted": bool` in the output JSON. See §11. |

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
| `--restricted` / `--no-restricted` | **ON by default.** Forwarded to every spawned `tune_heuristic.py` subprocess so iter3+ tune inside the action-pruned space. See §11. |
| `--holdout-n N` | Games per category's post-tuning holdout match. Default 100. |

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

`play_web.py --v3-config <json_path>` loads the JSON's `best_config` and uses it whenever a seat is set to `hubris_v3`. Without the flag, `hubris_v3` falls back to `CONFIG_V3_T1` (and to `DEFAULT_CONFIG_V3` if the constant is somehow None).

`play_web.py` also carries a `--restricted` / `--no-restricted` flag (`argparse.BooleanOptionalAction`, default **ON**). When ON, every AI seat is built with `legal_actions_fn=restricted_legal_actions` so browser-UI agents behave the same way they do during training-pipeline fitness evaluation. The startup line prints `AI seats use restricted_legal_actions: ON/OFF` so the state is visible.

**Stable run command for playing against the current strongest V3 (wrapper active):**

```bash
python play_web.py --seats human hubris_v3 --v3-config tuned_configs/v3_best.json
```

(No flag change needed — `--restricted` is ON by default.) Add `--no-restricted` to play against agents that see the full unrestricted action set.

Since `v3_best.json` is auto-maintained, this command always uses the latest champion config without needing updates after each tuning run.

The frontend dropdown in the "New Game" dialog has been simplified to **human / random / v1 / v3** (with internal translation: `v1` → backend `hubris` (V1+T2), `v3` → backend `hubris_v3` with the loaded config). The CLI's `--seats` flag still uses the full backend names (`hubris`, `hubris_v3`, etc.) for backwards compatibility.

## 8. Current training state

### 8.1 Per-parameter tuning status (cheat sheet)

Quick reference for what's been optimized and what hasn't, as of `iter2`'s completion (the current `tuned_configs/v3_best.json` = `iter2_p2_v3_pastures_animals.json`, +26.06 holdout vs CONFIG_V3_T1 on 100 seeds).

**Headline numbers**: `HeuristicConfigV3` defines ~326 dataclass fields, of which 14 are inert legacy major-value scalars kept for JSON backwards-compat. That leaves ~312 actively-read parameters. Of these:

| Status | Scalars | Source of values |
|---|---|---|
| Tuned via V3 iterative CMA-ES (iter1 → iter2) | **224** | latest iter2 tuning |
| Inherited from `CONFIG_V1_T2` (V3 v3_food fell back to x0 across both iter1 and iter2) | **18** | V1 round 2 tuned, never improved by V3 v3_food |
| Inherited from `CONFIG_V1_T2` (no V3 TUNABLE includes them; still actively read) | **6** | V1 round 2 tuned, never re-tuned: `family_per_round`, `empty_room_rate_pre/post_basic_wish`, `starting_player_bonus` |
| Never tuned — V1 carry-overs at hand-picked defaults (actively read) | **4** | `field_center_bonus`, `pasture_location_bonus` (now V3-c≥3), `renovation_bonus_per_step_early/late` |
| Never tuned — V3-specific per-stage major values (new post-iter2) | **48** | 8 majors × 6 stages; cooking defaults derived from V1_T2 |
| Never tuned — V3-specific hand-picked stage curves | **12** | `score_joint_alpha_by_stage` (6) + `unused_spaces_alpha_by_stage` (6) |
| **Subtotal (actively read)** | **312** | |
| Inert legacy major-value scalars (kept for JSON backwards-compat only) | **14** | not read by V3 evaluator post-refactor |
| **Total dataclass fields** | **326** | |

The new 48 per-stage major scalars are the **largest single untuned block** post-iter2 and the natural target for a new TUNABLE (see §10.x).

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

These fields live on `HeuristicConfigV3` so the carry-over V1 helpers (`_hubris_family_value`, etc.) can read them via duck typing. They're NOT touched by any V3 TUNABLE.

| Field | # scalars | Tuned by | Notes |
|---|---|---|---|
| `family_per_round` | 3 | V1 round 2 (CONFIG_V1_T2) | |
| `empty_room_rate_pre_basic_wish` | 1 | V1 round 2 | |
| `empty_room_rate_post_basic_wish` | 1 | V1 round 2 | |
| `starting_player_bonus` | 1 | V1 round 2 | |
| `field_center_bonus` | 1 | **Never tuned** | V1 round 3 attempted, did not promote |
| `pasture_location_bonus` | 1 | **Never tuned** | Shared scalar; V3 helper applies it only to c≥3 cells (V1 applied to c≥2). |
| `renovation_bonus_per_step_early` | 1 | **Never tuned** | V1 round 3 attempted, did not promote. At 0.0 (backwards-compat). |
| `renovation_bonus_per_step_late` | 1 | **Never tuned** | V1 round 3 attempted, did not promote. At 0.0. |
| **Subtotal** | **10** | (6 from V1_T2; 4 untuned) | |

#### V3 per-stage major-improvement values (NOT in any V3 TUNABLE yet)

Introduced post-iter2 to replace V1's `_hubris_major_value`. Each major has a length-6 per-stage tuple read by `_hubris_major_value_v3`. Defaults derived from CONFIG_V1_T2's tuned 3-tier values (cooking: stages 1-4 = "full", stage 5 = "_mid", stage 6 = "_late"). The "extra cooking implement = flat +1" rule is hardcoded — no longer a config field. Well no longer scales with future-food rounds.

| Field | # scalars | Tuned by | Notes |
|---|---|---|---|
| `fireplace_value_by_stage` | 6 | **Never tuned (defaults from V1_T2)** | stages 1-4 = V1_T2's `fireplace_value`, stage 5 = `_mid`, stage 6 = `_late` |
| `hearth_value_by_stage` | 6 | **Never tuned (defaults from V1_T2)** | analogous |
| `well_value_by_stage` | 6 | **Never tuned (V1 default 4.0 flat)** | drops V1's `well_food_per_future` term |
| `clay_oven_value_by_stage` | 6 | **Never tuned** | hand-picked 2.0 flat |
| `stone_oven_value_by_stage` | 6 | **Never tuned** | hand-picked 3.0 flat |
| `joinery_value_by_stage` | 6 | **Never tuned** | hand-picked 2.0 flat |
| `pottery_value_by_stage` | 6 | **Never tuned** | hand-picked 2.0 flat |
| `basketmaker_value_by_stage` | 6 | **Never tuned** | hand-picked 2.0 flat |
| **Subtotal** | **48** | (all untuned) | Target for a new `v3_majors_per_stage` TUNABLE (see §10.x) |

#### Legacy major-improvement scalars (kept for JSON backwards-compat only)

These pre-refactor field names remain on `HeuristicConfigV3` so older `tuned_configs/*.json` files (including the current `v3_best.json`) construct cleanly. They are NOT read by `evaluate_hubris_v3` post-refactor — superseded by the per-stage arrays above.

| Field | # scalars | Status |
|---|---|---|
| `fireplace_value`, `_mid`, `_late`, `hearth_value`, `_mid`, `_late`, `cooking_secondary_vp` | 7 | Inert (legacy) |
| `well_value`, `well_food_per_future`, `clay_oven_value`, `stone_oven_value`, `joinery_value`, `pottery_value`, `basketmaker_value` | 7 | Inert (legacy) |
| **Subtotal** | **14** | Not read by V3 evaluator |

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
6. **iter2** — 2-pass iterative, `--baseline v3_t1` for both training and holdout. x0 bug fixed. Final holdout **+26.06 vs CONFIG_V3_T1 on 100 seeds** (last promotion: pass-2 pastures_animals = 100-0-0). Promoted to `v3_best.json`. Promotion of this config to `CONFIG_V3_T2` is pending.
7. **Major-value refactor (post-iter2)** — replaced V1's `_hubris_major_value` with V3-specific `_hubris_major_value_v3`: 8 majors × 6 stages = 48 new per-stage scalars. Extra cooking implements now contribute a flat +1 each (replacing `cooking_secondary_vp`). Well no longer scales with future-food rounds. Also added `_hubris_pasture_location_bonus_v3` with c≥3 cells (vs V1's c≥2). All defaults derived from V1_T2 where applicable; no new tuning run yet — see §10.

### 8.4 iter2 setup (completed)

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

### 10.0 Tune the new per-stage major-improvement values

The 48 new per-stage scalars (`fireplace_value_by_stage`, `hearth_value_by_stage`, …, `basketmaker_value_by_stage`) are the largest untuned block post-refactor. Defaults are derived from V1_T2 (cooking) or hand-picked (everything else); they've never been tuned in V3's context.

To set up: register a new TUNABLE `v3_majors_per_stage` in `scripts/tune_heuristic.py` with 48 entries (8 majors × 6 stages each). Reasonable bounds: lower=0.0, upper=10.0 for most (hearth/fireplace might want upper=15.0). Run against the current `v3_best.json` (= iter2's pastures_animals output, which is `~+26 vs V3_T1` already).

Expected behavior:
- Cooking implements (`fireplace_*` and `hearth_*`) are V1_T2-derived → may fall back to x0 like food did (defaults are already strong).
- Well / ovens / crafts are hand-picked → high probability of meaningful gains, especially well_value_by_stage (V1's `4.0 + 0.4 * upcoming_food` formula is gone, so the residual flat value may want tuning).

### 10.1 Promote iter2's final config to CONFIG_V3_T2

iter2 left `v3_best.json` at +26.06 holdout vs CONFIG_V3_T1. Promote it to a named constant `CONFIG_V3_T2` in `agricola/agents/heuristic.py` mirroring the `CONFIG_V3_T1` pattern. Note: the refactor changes the evaluator semantics (well-without-future-food + pasture-c≥3), so the +26.06 number was measured under the *old* evaluator. After promotion, re-measure CONFIG_V3_T2 vs CONFIG_V3_T1 under the refactored evaluator to capture the true post-refactor margin.

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

## 11. Restricted action set (`--restricted`, default ON)

As of the doc-update following iter2, the training pipeline runs by default with `restricted_legal_actions` wrapping every agent's legality consultation. Both `scripts/tune_heuristic.py` and `scripts/run_iterative_v3.py` carry a `--restricted` / `--no-restricted` flag (defaults to ON); `scripts/play_match.py` carries per-seat `--p0-restricted` / `--p1-restricted` flags for ad-hoc comparisons. See **`agricola/agents/restricted.py`** for the wrapper, **CLAUDE.md** "Additional Design Principles" → "Action-pruning wrapper" for the convention, and **`CHANGES.md`** Change 11 for the design rationale + empirical validation.

### 11.1 What the wrapper does (one-paragraph summary)

The wrapper filters the engine's `legal_actions(state)` to apply a set of strategic priors: sub-action ordering (Cultivation plow-before-sow; Grain Util sow-before-bake; Farm Expansion rooms-before-stables), cell priorities (`STABLE_PRIORITY = [(0,4), (0,3), (1,4), (1,3)]`, `ROOM_PRIORITY = [(0,0), (2,1), (1,1), (2,2)]`, `PLOW_PRIORITY = [(0,1), (0,2), (1,1), (0,0), (1,2), (2,2), (2,3)]`), first-pasture opener cells `{(0,4), (1,4)}`, a 5-room cap, and min-begging at `CommitConvert`. Each filter routes through `_safe_narrow` so the wrapper never empties a non-empty input.

### 11.2 Mechanical interaction with V3

Two independent layers that compose at one point:

```python
actions = filter_implemented(self.legal_actions_fn(state))   # wrapper runs here
…
scores = [self._lookahead_value(step(state, a), decider) for a in actions]  # V3 runs here
```

V3 (`evaluate_hubris_v3`) scores the same states it would have, just on a smaller candidate set per decision. V3 never calls `legal_actions` itself, and `step()` doesn't know about the wrapper either. Strategic interaction is via *implicit agreement or disagreement*: V3's tuned coefficients may already prefer a cell the wrapper enforces (agreement → wrapper is free), or V3 may prefer a cell the wrapper forbids (disagreement → V3 picks a V3-suboptimal move at that decision).

### 11.3 Empirical baseline: V3_T1 with the wrapper bolted on

A 1000-game paired match (V3_T1 + restricted vs V3_T1 unrestricted, seeds 0..499 with seats swapped for the second 500):

```
Match A (restricted = P0):  n=500  mean=+0.042  SE=0.56   95% CI=[-1.05, +1.13]   t=+0.08
Match B (restricted = P1):  n=500  mean=-2.060  SE=0.51   95% CI=[-3.06, -1.06]   t=-4.03
PAIRED per-seed mean:       n=500  mean=-1.009  SE=0.19   95% CI=[-1.37, -0.64]   t=-5.42

Win record (decisive):      restricted 478 — unrestricted 488    (49.48%, 95% CI [46.3%, 52.6%])
```

**Win rate is indistinguishable from 50%** (z = −0.32). **Avg margin is −1.0 ± 0.19**, statistically significant due to large N but small in magnitude.

### 11.4 Seat asymmetry — open question

Match A (restricted at P0) and Match B (restricted at P1) disagree by ~2 points. This is *not* conventional turn-order seat bias (`setup(seed)` randomizes `starting_player`). What differs between seat 0 and seat 1: the agent's RNG seed (`seed_offset = 0` for P0, `1` for P1) affects argmax tiebreaks, and `player_idx` may propagate through evaluator code paths in a non-symmetric way. The magnitude (~2 pts) is larger than expected from RNG tiebreaks alone, which suggests there's a `player_idx`-conditional code path somewhere in V3's evaluator or one of the carry-over helpers.

**Diagnostic next step:** run 500 games of `hubris_v3 vs hubris_v3` *with both sides unrestricted*. If the per-seat margins also disagree by ~1 pt, the asymmetry is in V3 itself, not the wrapper — a latent bias affecting all asymmetric matchups in tuning.

### 11.5 What re-tuning under the wrapper does mechanically

When `--restricted` is ON (both sides), CMA-ES optimizes V3's coefficients in the smaller action space:

- **Coefficients that duplicate the wrapper's behavior drift toward 0.** If the wrapper enforces a cell preference, V3's matching parameter (e.g. `pasture_location_bonus`, `field_center_bonus`) doesn't need to push as hard in that direction. CMA-ES should find equivalent fitness at lower values.
- **Coefficients that V3_T1 used to "buy" wrapper-forbidden plays settle elsewhere.** Any V3_T1 preference the wrapper now blocks gets re-optimized within the constrained set.
- **Per-evaluation work is slightly cheaper** because the agent's argmax is over a smaller candidate set; effective wall-clock per generation is unchanged or marginally faster.
- **Holdout comparisons stay valid.** `_maybe_update_best_pointer` compares the new run's holdout margin against the existing `v3_best.json`'s. Both are now `restricted: true` matches against the chosen baseline. The auto-update logic doesn't care whether the prior best was wrapped — it just compares margins on whatever opponents the matches used.

**Net expectation:** re-tuned-V3-under-wrapper should perform at least as well as V3_T1 in the wrapper-active matchup. The current −1 pt cost (§11.3) is the price of bolt-on; re-tuning amortizes it away.

### 11.6 Iter3 setup (when launched)

```bash
nohup python -u scripts/run_iterative_v3.py \
    --n-passes 2 --max-gens 10 --n-seeds 100 \
    --baseline v3_t1 --label iter3 \
    > tuned_configs/iter3_orchestrator.log 2>&1 &
```

`--restricted` is ON by default — no flag needed. To opt out (e.g. for an unrestricted control run), add `--no-restricted`. Auto-update of `v3_best.json` proceeds as usual; the resulting champion JSON will carry `"restricted": true` as a record of how it was tuned.
