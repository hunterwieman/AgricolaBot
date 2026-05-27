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
| `--category` | `v3_resources` | Which TUNABLE list (see §3). `v3_all` tunes all 312 V3 params in one call. |
| `--from <spec>` | `default_v3` | Warm-start base. Either a named config (`default`, `t2`, `default_v3`) or a path to a previous run's JSON (loads its `best_config`). |
| `--baselines <spec> [<spec> ...]` | `["t2"]` | Opponent configs for the fitness function. Fitness = mean margin across all listed baselines (each evaluated on the same seed set). Multiple baselines prevent overfitting to a single opponent — see §2.5. Same name-or-path semantics as `--from`. |
| `--baseline <spec>` | — | Backwards-compat alias for `--baselines <spec>` (single-element). Don't use both. |
| `--regression-baseline <spec>` | `t2` | Fixed reference opponent measured per-generation on session-best (NOT in fitness aggregate). Drift detector: trajectory recorded in `regression_history`. Set to `''` to disable. See §2.5. |
| `--resume <path.cma.pkl>` | None | Restore a previous CMA-ES state. `--max-gens` becomes "additional gens" from the resumed countiter. |
| `--n-seeds` | 50 | Training games per evaluation (per baseline) |
| `--max-gens` | 10 | Generations to run (or "additional gens" if resuming) |
| `--popsize` | 12 | CMA-ES population per gen |
| `--sigma0` | 0.3 | Initial step size (fresh runs only; resume ignores) |
| `--cma-seed` | 1 | CMA-ES internal RNG seed |
| `--jobs` | `cpu_count()` | Parallel processes for population evaluation |
| `--holdout-start, --holdout-n` | 1000, 100 | Holdout seed range |
| `--output <path>` | `tuned_configs/<ts>.json` | Output path; `.log` and `.cma.pkl` companion files share the stem |
| `--restricted` / `--no-restricted` | **ON** | Builds candidate, baseline, and holdout agents with `legal_actions_fn=restricted_legal_actions`. Recorded as `"restricted": bool` in the output JSON. |
| `--reset-floor-after-promote` / `--no-reset-floor-after-promote` | **OFF** | Legacy flag — after a fresh promotion of `<arch>_best.json`, re-measure the new champion's self-match floor on the holdout seeds and overwrite the stored `holdout.avg_margin`. Largely subsumed by the multi-baseline + regression-detector approach in §2.5 but kept for runs using a single chained baseline. |

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

### 2.6 Multi-baseline tuning + regression detector

`--baselines` and `--regression-baseline` together address a real failure mode the project hit historically: **silent drift away from a fixed strong reference**.

**Why it matters.** The original setup tuned against ONE baseline (often the current `v3_best.json`, chained across iterations). Each tuning run measured "improvement vs the previous champion." This is a moving target: a candidate that wins by +5 against last iteration's champion may simultaneously LOSE by +10 against a fixed strong reference (like V1+T2) — and the loop would never notice. Empirically, V3 went through iterations claiming "+14 holdout" etc. while concurrently degrading from "beats V1+T2 by 12" → "loses to V1+T2 by 11" — a 22-point drift in absolute strength, invisible to the training loop because V1+T2 was never measured against the candidates.

**The two-part fix:**

1. **`--baselines PATH1 PATH2 ...`** — fitness aggregates margin across multiple opponents. With `--baselines t2 v3_t1`, every candidate plays both opponents on the same seed set, and fitness is the mean margin. A candidate that crushes one opponent while regressing against another doesn't beat one that improves moderately against both. The cost is linear in the number of baselines (2 baselines = 2× compute per candidate eval).

2. **`--regression-baseline PATH`** — measured per generation on the session-best candidate (NOT in fitness aggregate). Trajectory appears in the output JSON's `regression_history` field: `[{generation: N, regression_margin: X}, ...]`. If `regression_margin` trends DOWN while `best_margin_so_far` trends UP, the tuning is overfitting to the baselines — kill the run.

The regression detector adds one extra evaluation per generation, against the session-best (not every candidate). Cheap.

**Recommended setup** for any new run:
- `--baselines t2 v3_best` (or include 2-3 representative opponents)
- `--regression-baseline t2` (V1+T2 is the universal reference; always-strong)

**The older `--reset-floor-after-promote` fix** addressed a related but narrower symptom (the auto-update mechanism's stored-holdout-margin becoming stale across chained iterations). The multi-baseline + regression-detector approach is more general — it catches drift DURING tuning, not just at promotion. Keep `--reset-floor-after-promote` for single-baseline chained-champion runs; reach for `--baselines` + `--regression-baseline` for anything new.

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
| `v3_majors_per_stage` | V3 | 48 | 8 majors × 6 per-stage values (`fireplace_value_by_stage`, ..., `basketmaker_value_by_stage`). Added 2026-05-23 after the major-value refactor. |
| `v3_alphas_and_carryovers` | V3 | 22 | `score_joint_alpha_by_stage` (6) + `unused_spaces_alpha_by_stage` (6) + `family_per_round` (3) + `empty_room_rate_pre/post_basic_wish` (2) + `starting_player_bonus` (1) + `field_center_bonus` (1) + `pasture_location_bonus` (1) + `renovation_bonus_per_step_early/late` (2). Joint TUNABLE covering all otherwise-uncovered actively-read fields. |
| `v3_all` | V3 | 312 | Union of all 6 V3 categories above. For single-call CMA-ES of the entire V3 parameter space. Recommended `--popsize 30` for d=312 (≈ 4+3·ln(d)). The historical split into smaller categories was partly to avoid the "chained baseline drift" failure mode now addressed by `--baselines` + `--regression-baseline`; with the new tooling, all-at-once tuning is viable. |

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

`tuned_configs/v3_best.json` is the **pointer to the current V3 baseline**.

**Current contents:** the `iter1_v3_ported_to_refactor.json` config — iter1's strongest V3 manually ported into the post-refactor schema via `scripts/port_pre_refactor_v3.py`. Beats `CONFIG_V1_T2` by ~12 margin in a 40-game heuristic match (the strongest V3 in the project's tuning history).

The old `v3_best.json` (post-iter4 alphas tune) was preserved as `v3_best_OLD_BROKEN_iter4_alphas.json`. That config LOST to V1+T2 by ~11 — a regression caused by chained-baseline drift across iter2-iter4 that the project's pre-multi-baseline tooling didn't catch. Section 2.5 has the details.

### Auto-update logic

At the end of every `tune_heuristic.py` run, `_maybe_update_best_pointer(new_json, arch, new_holdout_margin)`:
1. Reads existing `tuned_configs/<arch>_best.json`'s `holdout.avg_margin`.
2. If new margin > existing (or no existing): `shutil.copy(new_json, best_path)`.
3. Prints either "UPDATED: +X → +Y" or "unchanged; existing +X > new +Y".

Comparison metric: **holdout margin against the primary (first-listed) baseline**. The new multi-baseline / regression-detector data in the output JSON (`holdout.by_baseline`, `holdout.regression`) is informational — useful for inspecting drift after the fact, but the auto-update gate is the single primary-baseline holdout for backwards compatibility with older runs' JSONs.

**Recommendation for new tuning runs:** use `--baselines t2 v3_best` (or similar diversified set) and `--regression-baseline t2`. After each run, manually inspect the JSON's `regression_history` and `holdout.regression` fields before trusting the auto-update outcome.

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

## 8. Current state

`tuned_configs/v3_best.json` currently points at the **ported iter1 V3 config** (see §6). Beats `CONFIG_V1_T2` by ~12 margin in heuristic head-to-head — the strongest V3 in the project's tuning history. The post-iter4 alphas config that previously held this slot LOST to V1+T2 by ~11 (chained-baseline drift, see §2.5), and is preserved as `v3_best_OLD_BROKEN_iter4_alphas.json` for reference.

**Parameter coverage:** `HeuristicConfigV3` has ~312 actively-read scalars (plus 14 inert legacy major-value scalars kept for JSON backwards-compat). All 312 are tuned in the current `v3_best.json` (carrying iter1's CMA-ES values; the post-refactor per-stage major arrays carry V1_T2-derived defaults via the port).

**Tunable categories** (`scripts/tune_heuristic.py --category`):
- `v3_fields_crops` (60) / `v3_food` (18) / `v3_resources` (63) / `v3_pastures_animals` (101) / `v3_majors_per_stage` (48) / `v3_alphas_and_carryovers` (22)
- `v3_all` (312) — single-call combined tune, recommended `--popsize 30`

**Empirical context for any new V3 tuning:**
- V1+T2 (`hubris` agent / `HubrisHeuristicV1` + `CONFIG_V1_T2`) is the project's strongest standalone heuristic.
- MCTS at 200-500 sims with vanilla UCT loses 3-5 points vs both V1-heuristic and V3-ported-heuristic — current MCTS implementation does not lift over strong heuristics.
- These two facts mean: (a) `t2` (V1+T2) is the universal regression target — set as `--regression-baseline` default; (b) any new V3 tune should aim to beat V1+T2 by MORE than the current ~12 margin to be a real improvement.

**Recommended setup for a new V3 retune:**

```bash
python -O scripts/tune_heuristic.py \
  --category v3_all \
  --from tuned_configs/v3_best.json \
  --baselines t2 v3_best \
  --regression-baseline t2 \
  --popsize 30 --max-gens 30 --n-seeds 50 --jobs 8
```

After the run, inspect the output JSON's `regression_history` field — if `regression_margin` trends down while `best_margin_so_far` trends up, the tune is drifting; abort and investigate.

For more concrete forward-looking work items (NN-based evaluators, MCTS asymptote experiments, V3 weight audits), see **POSSIBLE_NEXT_STEPS.md**.


## 9. Operational quick reference

### Start a fresh V3 retune (recommended setup)
```bash
python -O scripts/tune_heuristic.py \
    --category v3_all \
    --from tuned_configs/v3_best.json \
    --baselines t2 v3_best \
    --regression-baseline t2 \
    --max-gens 30 --popsize 30 --n-seeds 50
```

### Start a fresh single-category tuning (multi-baseline)
```bash
python -O scripts/tune_heuristic.py \
    --category v3_fields_crops \
    --from default_v3 \
    --baselines t2 default_v3 \
    --regression-baseline t2 \
    --max-gens 10 --popsize 16 --n-seeds 100
```

### Resume a category from where you left off
```bash
python -O scripts/tune_heuristic.py \
    --category v3_resources \
    --from tuned_configs/v3_best.json \
    --baselines t2 v3_best \
    --regression-baseline t2 \
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

## 10. Restricted action set (`--restricted`, default ON)

The training pipeline runs by default with `restricted_legal_actions` wrapping every agent's legality consultation. `scripts/tune_heuristic.py` and `scripts/run_iterative_v3.py` carry a `--restricted` / `--no-restricted` flag (defaults to ON); `scripts/play_match.py` carries per-seat `--p0-restricted` / `--p1-restricted` flags for ad-hoc comparisons. See **`agricola/agents/restricted.py`** for the wrapper, **CLAUDE.md** "Additional Design Principles" → "Action-pruning wrapper" for the convention.

### 10.1 What the wrapper does

The wrapper filters the engine's `legal_actions(state)` to apply a set of strategic priors: sub-action ordering (Cultivation plow-before-sow; Grain Util sow-before-bake; Farm Expansion rooms-before-stables), cell priorities (`STABLE_PRIORITY = [(0,4), (0,3), (1,4), (1,3)]`, `ROOM_PRIORITY = [(0,0), (2,1), (1,1), (2,2)]`, `PLOW_PRIORITY = [(0,1), (0,2), (1,1), (0,0), (1,2), (2,2), (2,3)]`), first-pasture opener cells `{(0,4)}` (originally `{(0,4), (1,4)}`; tightened after observing V3 reliably opens at (1,4)), a 5-room cap, and min-begging at `CommitConvert`. Each filter routes through `_safe_narrow` so the wrapper never empties a non-empty input.

### 10.2 Mechanical interaction with V3

Two independent layers compose at one point:

```python
actions = filter_implemented(self.legal_actions_fn(state))   # wrapper runs here
…
scores = [self._lookahead_value(step(state, a), decider) for a in actions]  # V3 runs here
```

V3 (`evaluate_hubris_v3`) scores the same states it would have, just on a smaller candidate set per decision. V3 never calls `legal_actions` itself, and `step()` doesn't know about the wrapper either. Strategic interaction is via *implicit agreement or disagreement*: V3's tuned coefficients may already prefer a cell the wrapper enforces (agreement → wrapper is free), or V3 may prefer a cell the wrapper forbids (disagreement → V3 picks a V3-suboptimal move at that decision).

### 10.3 Seat asymmetry — open question

In matches where the same agent plays both seats with different RNG seeds, per-seat margins disagree by ~1-2 points. This is NOT conventional turn-order seat bias (`setup(seed)` randomizes `starting_player`). The agent's RNG seed (`seed_offset = 0` for P0, `1` for P1) affects argmax tiebreaks, and `player_idx` may propagate through evaluator code paths in a non-symmetric way. The magnitude is larger than expected from RNG tiebreaks alone, suggesting there's a `player_idx`-conditional code path somewhere in V3's evaluator or one of the carry-over helpers.

**Diagnostic next step:** run 500 games of `hubris_v3 vs hubris_v3` *with both sides unrestricted*. If the per-seat margins still disagree by ~1 pt, the asymmetry is in V3 itself, not the wrapper.

### 10.4 What re-tuning under the wrapper does mechanically

When `--restricted` is ON (both sides), CMA-ES optimizes V3's coefficients in the smaller action space:

- **Coefficients that duplicate the wrapper's behavior drift toward 0.** If the wrapper enforces a cell preference, V3's matching parameter (e.g. `pasture_location_bonus`, `field_center_bonus`) doesn't need to push as hard in that direction. CMA-ES should find equivalent fitness at lower values.
- **Coefficients that the warm-start used to "buy" wrapper-forbidden plays settle elsewhere.** Any warm-start preference the wrapper now blocks gets re-optimized within the constrained set.
- **Per-evaluation work is slightly cheaper** because the agent's argmax is over a smaller candidate set; effective wall-clock per generation is unchanged or marginally faster.
- **Holdout comparisons stay valid.** `_maybe_update_best_pointer` compares the new run's holdout margin against the existing `v3_best.json`'s. The auto-update logic doesn't care whether the prior best was wrapped — it just compares margins on whatever opponents the matches used.
