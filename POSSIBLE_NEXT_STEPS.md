# Possible Next Steps

A sketch of directions the project could take next, organized by project phase. Originally written 2026-05-13 after Task 5; revised after Task 5C, Task 6, the harvest implementation, and the Change-8 hashability work; restructured 2026-05-21 to fold performance work (formerly items C and E) into a single pointer to POSSIBLE_SPEEDUPS.md.

636 tests passing. The engine is feature-complete for the Family game (all 14 rounds, all 6 harvests, Potter Ceramics as the one card). `GameState` is hashable. The engine has been profiled and a first wave of optimizations has landed (Change 9). Letter labels are preserved across removals so cross-references in CHANGES.md / SESSION_HISTORY.md to historical items remain valid.

This is a planning document, not a commitment.

---

## Engine performance

### C. Performance work (catalog in POSSIBLE_SPEEDUPS.md)

Performance work has its own living document — **`POSSIBLE_SPEEDUPS.md`** — which catalogs specific optimization ideas, organized by what they target. The split is intentional: this file is about project *direction* (what to build next); POSSIBLE_SPEEDUPS.md is about *making existing code faster*, with the bias toward measure-before-acting.

**What's already landed (Change 9, 2026-05-21):**

- A profiling harness (`scripts/profile_engine.py`, `scripts/profile_states.py`, plus the counter and microbench scripts) producing reproducible numbers across three workloads.
- `fast_replace` — drop-in faster equivalent of `dataclasses.replace` (~20% per-call speedup, microbenched).
- `legal_actions_cache()` — opt-in identity-keyed memoizer in `agricola/legality.py`, dormant outside a `with` block; parked for MCTS to be the first consumer.
- `__debug__` gate on `_assert_nonnegative_state` — production runs under `python -O` skip the safety net.
- Round-end-reset guard in `_resolve_return_home` — skips redundant `replace` calls for already-empty action spaces.

See **PROFILING.md** for the methodology and headline numbers, and **CHANGES.md Change 9** for the full breakdown.

**What's catalogued for future work (POSSIBLE_SPEEDUPS.md):**

- **S1 — Anchor Pareto pruning** on `pareto_frontier` / `breeding_frontier`. The highest-ROI remaining optimization based on current profiles: `can_accommodate` + Pareto inner generators are now the dominant cost cluster (~22 ms / Workload-B run in mid/late game). Low-difficulty, few-line change.
- **S2 — Geometric Pareto pruning.** Extends S1; defer until S1 is measured.
- **S3 — `legal_placements` short-circuit by availability.** Avoids per-predicate function-call overhead for spaces with workers already on them. Independent quick win, ~2-4% expected.
- **S4 — Form C per-shape replacers.** Continuation of the Change-9 `fast_replace` work — hand-written single-shape helpers for the hottest update patterns. Reach for only if `fast_replace` still dominates after S1-S3.
- **S5 — Cached `__hash__` on hot dataclasses.** Transposition-table enabler; only worth doing once MCTS adds a content-keyed transposition layer.
- **S6 — Zobrist-style incremental hashing.** Heavy alternative to S5; listed for completeness, probably never needed for this game's scale.

Each entry in POSSIBLE_SPEEDUPS.md has an estimated speedup (with uncertainty called out), a difficulty rating, an implementation sketch, and a "when to do it" trigger. The catalog is updated as items land or as new profiling exposes new hot paths.

**When to consult POSSIBLE_SPEEDUPS.md:**

- When profiling identifies a hot path that one of the catalogued items targets.
- When MCTS scales up rollouts and per-action cost becomes the dominant cost.
- When considering a structural change (e.g., adding a transposition table) and you want to know what optimizations are pre-thought-through.

When *not* to consult it:

- Speculatively, ahead of evidence. Every entry has a "profile first" disclaimer; the catalog is reference material, not a TODO list to walk top-down.

---

## Phase 2 — baseline agents

Useful as benchmarks for the trained agent and as scaffolding for MCTS.

### F. Heuristic agent — **landed 2026-05-22 (V1) and 2026-05-22 evening (V3)**

Hand-written policies implementing reasonable Agricola strategy. Three Hubris versions ship plus Simple/Random infrastructure:

- **`SimpleHeuristic`** — MVP. `score(state)` + linear resource bonuses + food/begging term.
- **`HubrisHeuristicV1`** — original V1 architecture. ~70 coefficients in `HeuristicConfig` covering family-future, empty rooms, breeding opportunities, location bonuses, context-aware resources, majors with cooking-primary + round-decay, stage-1×1.5 multiplier, etc. **`CONFIG_V1_T2`** is the round-2-tuned constant (58 params tuned; +8.85 holdout vs default; 90-1-9 record). Wired as the `hubris` seat alias.
- **`HubrisHeuristicV2`** — V1 with `harvest_feed_frontier` for joint goods-or-food optimization. Theoretically more correct but loses head-to-head to V1.
- **`HubrisHeuristicV3`** — current main heuristic. ~250 parameters across blend / additive / joint-alpha categories + three-component resources. Carries over V1's family-future, empty-room, location bonuses, SP, renovation, major-override, and food/begging helpers via duck typing. `tuned_configs/v3_best.json` auto-maintained pointer to the strongest V3 config. See **`V3_DESIGN.md`** for the architecture.

**CMA-ES tuning pipeline** (`scripts/tune_heuristic.py` + `scripts/run_iterative_v3.py`) implements Thread A from HEURISTIC_TUNING_PLAN.md. Per-category tuning with save/resume via pickle, x0 fallback to prevent chain-forward regression, automatic `<arch>_best.json` updates, parallel CMA-ES population evaluation. See **`V3_TRAINING_PIPELINE.md`** for operational guide.

Web UI: `python play_web.py --seats human hubris_v3 --v3-config tuned_configs/v3_best.json` plays you against the current champion. New-game dropdown simplified to human/random/v1/v3.

**Current state:** V1+T2 (= `CONFIG_V1_T2`, the round-2-tuned V1) is the project's strongest standalone heuristic. The current `v3_best.json` is the iter1 V3 manually ported into the post-refactor schema — beats V1+T2 by ~12 margin (the strongest V3 we have). The previous v3_best (post-iter4 alphas) lost to V1+T2 by ~11 (chained-baseline drift, now caught by the multi-baseline + regression-detector tooling). See V3_TRAINING_PIPELINE.md §2.5, §6, §8.

**Open V3 next steps:**

- **F1.** ~~Finish the current iterative run~~ — superseded by the V3 retune planned in F12.
- **F2.** Promote `v3_best.json` to a Python constant `CONFIG_V3_T1` once tuning converges (mirror the `CONFIG_V1_T2` pattern). Document in CHANGES.md.
- **F3.** Address V1's food double-count in V3. Options: convertible-discount-by-stage (add 6-element array scaling `convertible` in the food shortfall calculation by stage); V2-style joint frontier with "will I actually convert?" weighting. See HUBRIS_V1_NOTES.md §4 for the V2 history.
- **F4.** Discrete-cutoff sweep — manual sweep, not CMA-ES. Test alternative values for: pasture "capacity ≥ 4" threshold (currently K=4 for `pasture_value_large`), "≤2 rooms" threshold for `wood_pre_3rd_room_vector` activation, "≥3 capacity per pasture" threshold for breeding-capable, "round 12 cap" in empty-room helper, stage boundaries in `_stage_of_round`. See V3_DESIGN.md §8.6.
- **F5.** Per-stage joint-alpha split. `score_joint_alpha_by_stage` currently modulates clay_rooms + stone_rooms + people + bonus_points with ONE curve. Could split into 4 separate curves (24 params) if tuning suggests the lump is too coarse.
- **F6.** Slot-indexed stone-major vector. Stone currently has only renovation + generic; could add a `stone_major_vector` indexed by stone count, analogous to `wood_fence_vector`. Defer until tuning suggests stone is under-modeled.
- **F7.** Per-vector pasture alphas. `pasture_value_all` and `pasture_value_large` share one blend α; per-vector alphas would let the optimizer give the "large pasture bonus" a different time profile.
- **F8.** ~~Baseline graduation~~ — **OBSOLETE**. The chained-baseline approach this proposed is exactly what caused the iter2 drift. Use `--baselines` (mix of references) + `--regression-baseline t2` instead. See V3_TRAINING_PIPELINE.md §2.5.
- **F9.** Seed-rotation during training. Currently all candidates in all generations play games against the same fixed seeds 0-99. Could rotate per-gen to broaden environmental coverage and reduce overfitting. Lower priority now that multi-baseline addresses overfitting from a different angle.
- **F10.** V4 architectural ideas (defer until V3 has clearly converged). Possible directions: per-round arrays instead of per-stage step functions; explicit regime-conditional vectors instead of additive overlays; an explicit "moves remaining" axis on every category.
- **F11.** ~~x0 from warm-start base bug~~ — **FIXED** in earlier session (`_x0_from_base` extracts at run-time).
- **F12. V3 retune from the recovered ported baseline using the new multi-baseline + regression-detector tooling.** Run `python -O scripts/tune_heuristic.py --category v3_all --from tuned_configs/v3_best.json --baselines t2 v3_best --regression-baseline t2 --popsize 30 --max-gens 30 --n-seeds 50`. Inspect output JSON's `regression_history`. Should improve over the current `+12 vs V1+T2`. If it doesn't, the V3 architecture may be near its ceiling and the next leverage is structural (F10/V4) rather than parameter tuning.
- **F13. Reed weight audit.** Hypothesis (raised this session): V3 over-values reed because of implicit "reed denial" dynamics from V3-vs-V3 self-tuning. Inspect `v3_best.json`'s reed-related fields vs V1's structure to test this; no compute needed. May explain why V3 lost ground to V1 during iter2's drift.

### G. MCTS scaffolding — **landed**

`agricola/agents/mcts.py` ships `MCTSAgent` / `MCTSSearch` / `MCTSNode` / `MacroFencingAction`. Vanilla UCT + FPU + DAG-with-transpositions + leaf-evaluation (no rollouts) + macro-enumeration for Fencing + strict-restricted legality. See **`MCTS_DESIGN.md`** for the full design and **`agricola/agents/mcts.py`** for the implementation.

`MCTSSearch` accepts `evaluator_fn`, `heuristic`, and `leaf_differential` parameters so the same scaffold can run with V1 or V3 as the leaf evaluator, and with single-player vs differential leaf semantics.

**Current empirical finding:** at 200-500 sims with vanilla UCT and the project's V1 / V3 heuristics as leaf evaluators, MCTS **loses 3-5 points** vs the same heuristic used standalone (e.g. MCTS-V1 vs V1-heuristic = −3.88 at 500 sims; MCTS-V3-ported vs V3-ported-heuristic = −5.58 at 200 sims). The +2.5-3 lift seen against the old (drifted) v3_best was MCTS partially compensating for V3's weakness, not absolute value.

**MCTS remains the project's long-term direction** (Phase 5 AlphaZero-style self-play): the current finding scopes what UCT-with-1-turn-leaf-eval does NOW with the CURRENT evaluators at modest sim budgets, not whether MCTS will eventually pay off. PUCT priors + a learned-value NN + higher sim budgets are the natural follow-ups (see N below).

### G2. MCTS asymptote study

Does MCTS-V1 vs V1-heuristic margin cross 0 at high sim budgets (1000, 2000, 5000), or saturate negative? Trend so far: 200 sims = −5.43, 500 sims = −3.88 (small improvement with more sims). Settles whether MCTS at the current scaffolding is just under-budgeted or fundamentally not pulling weight against strong heuristics in this game. Compute: ~30-90 min depending on top budget. Useful before investing more in MCTS scaffold improvements vs jumping to learned evaluators (P).

---

## Phase 3 — card system

The largest single piece of remaining work. Several open design questions block large-scale card implementation; resolving them is itself a meaningful task. Each open question is best addressed when the first card needing it actually lands — don't speculate ahead of concrete consumers.

### H. Compound card interactions

The Pan-Baker-plus-Potter-Ceramics example flagged in TASK_5.md and IMPLEMENTATION_CHOICES.md. When checking `PlaceWorker(space)` legality, the system needs to apply all owned cards' on-placement transformations to a hypothetical state, then ask the existing sub-action predicates against that hypothetical. The trigger registry already supports arbitrary event names; the missing piece is the legality-side speculative application.

Probably worth doing before adding many more cards. Without H, the card system can only handle cards of the Potter Ceramics shape (purely-during-resolution triggers, no on-placement effects).

### I. `after_X` trigger event mechanics

The codebase has precedent for `before_X` events on sub-action pendings. `after_X` events have no precedent. Candidate consumers:
- The vegetable-card example mentioned during Fencing design ("each time you build N fences ≥ current round, gain 1 vegetable").
- Cards like Cottager and Hardware Store that attach to atomic spaces with before/after semantics.

Three candidate mechanisms documented in the design conversations: a resolve-on-pop hook on every pending type, an explicit `ApplyAfterTriggers` action, or overloaded `Stop` semantics. Decision deferred until the first such card lands.

### J. Atomic-space trigger hosting

Atomic spaces currently apply their effect immediately on `PlaceWorker`. For cards that attach to specific atomic spaces (Cottager fires before Day Laborer's food, Hardware Store fires after), atomic spaces need to push trigger-host pendings rather than resolve in one step. Two design questions documented in CLAUDE.md "Card implementation status":

- **Phase tracking.** Generic `primary_effect_applied: bool` on every space pending vs. a `phase: Literal["before", "after"]` field.
- **Phase-transition mechanism.** Explicit transition action vs. overloaded `Stop` vs. nested pendings.

Likely addressed alongside H when card work begins in earnest.

### K. Free-fence accounting and cost-modifier extension

Cards modifying per-edge fence cost (material substitution, free perimeter fences, etc.) need an extension mechanism on `compute_new_fence_edges`. The pattern would mirror `BAKE_BREAD_ELIGIBILITY_EXTENSIONS` / `BAKING_SPEC_EXTENSIONS` in `legality.py`. Free-fence counter fields on `PendingBuildFences` may also be needed (currently excluded per the YAGNI-on-pending-fields principle). Defer until the first such card lands.

### L. The remaining ~470 cards

Largest piece of work in the project. Once H–K above are settled, this becomes ongoing card-by-card implementation. Two related action-space paths unblock alongside cards:

- **Minor improvement play paths.** Optional minor-improvement steps at Basic Wish for Children, House Redevelopment, Major Improvement, and Farm Redevelopment all currently dead-end (no path commits a minor in Family scope). Unblocked by minor-card support.

- **The Lessons action space.** Permanently illegal in the Family game today; the legality predicate omits it from `NON_ATOMIC_LEGALITY`. Enabled once occupation cards exist.

---

## Phases 4–6 — training and evaluation

Furthest out. Listed for completeness.

### M. Imitation learning bootstrap

Train a policy on human game data to bootstrap the agent before self-play. Requires a corpus of human Agricola games (e.g., from BGA logs or other online play). Less compute-intensive than self-play; gets the agent to "plays the game competently" before RL refines it. Optional but accelerates phase 5.

### N. AlphaZero-style self-play RL

Self-play with MCTS guided by a neural network. The network outputs `(policy, value)` given state; MCTS uses the policy as priors and the value as rollout estimates. Iterated self-play improves the network over time.

Depends on G (MCTS scaffolding), and ideally on H–K (card system mostly complete; otherwise the agent learns to play a non-Agricola game). M (imitation bootstrap) is helpful but not required.

### O. Evaluation tooling

Elo ratings between agent versions, score distribution analysis, game-length variance, trace replay viewer, head-to-head match infrastructure. Useful throughout training to detect regressions and to compare experimental variants. Some pieces (trace replay, score distribution) are useful immediately for the existing engine and could ship ahead of the full evaluation pipeline.

### P. NN value-function training

Train a neural network value function that takes a `GameState` (or a featurized view of it) and predicts the expected score margin from that player's perspective. Replaces V1/V3 as the leaf evaluator inside MCTS — and potentially as a standalone agent via 1-turn lookahead.

Why this matters: the empirical bottleneck for agent strength is the EVALUATOR, not the search algorithm. V1/V3 are hand-designed feature combinations with finite expressiveness; a NN can learn arbitrary nonlinear interactions. If a learned value function beats V1 as a standalone evaluator (1-ply margin), it can then be dropped into MCTS as a leaf — and the AlphaZero-style training loop (G → P → better G → ...) becomes available.

**Minimum viable approach:**

1. **Feature extractor:** `GameState → fixed-size float vector` (or sparse representation). Should capture resources, animals, farmyard cells, pending stack, current player, round number, etc. Design choice between raw features and hand-engineered features (mimicking V3's structure) — start with both available and let training preference settle it.
2. **Generate self-play training data:** ~10K-50K games of `V1-heuristic` self-play (with temperature > 0 for diversity), recording (state, final-margin) pairs. ~3-10 hours compute on 8 cores.
3. **Train a value-only NN** (~50K-500K params, hidden dim 64-256). PyTorch. Target: predict final margin from each state.
4. **Evaluate as standalone agent** (1-ply argmax over NN scores) vs V1-heuristic. If NN beats V1, the AlphaZero loop unlocks.

If NN beats V1 by ANY margin, use it as the MCTS leaf evaluator and re-test G (MCTS vs heuristic). MCTS with a stronger leaf should perform better than the current MCTS-with-V1.

**Setup work before any results:** feature extractor, data-generation harness with diversity (temperature + random openings, possibly your exogenous-randomization ideas), PyTorch training script, evaluation framework. Probably 1-2 sessions of pure infrastructure before training data hits the network.

**Uncertainty:** I'd give roughly equal probability (~33% each) to "NN beats V1 by a meaningful margin," "NN ≈ V1 (no improvement)," and "NN clearly worse than V1." No specific prior for Agricola here.

---

## My take (advisory, not prescriptive)

**Current strongest agent: V1+T2** (`HubrisHeuristicV1` + `CONFIG_V1_T2`). The V3 architecture exists and the strongest historical V3 (now in `v3_best.json` via the iter1 port) beats V1 by ~12 in heuristic head-to-head — but the V3 tuning pipeline previously drifted via chained-baseline overfitting (caught by new multi-baseline + regression-detector tooling). MCTS as currently configured doesn't lift over strong heuristics at 200-500 sims.

**Three natural next directions, in priority order:**

1. **V3 retune (F12)** — exercise the new multi-baseline + regression-detector tooling on a real run from the recovered V3 baseline. Goal: V3 that beats V1+T2 by MORE than +12 without drifting. ~2-3 hours. Validates whether the V3 architecture has more headroom than the broken tuning suggested, or whether it's near its real ceiling.

2. **NN value function (P)** — the most likely path to a meaningfully stronger agent. The MCTS finding shows search isn't the bottleneck at current evaluator quality; better evaluators is the leverage point. Setup-heavy (1-2 sessions of infrastructure work before any results), but the strategic payoff is large if it works.

3. **MCTS asymptote (G2)** — settles whether MCTS is "just under-budgeted" or "fundamentally not pulling weight" at the current scaffolding level. Quick to run (~1 hour), tells us whether to invest in MCTS scaffold improvements (PUCT, better priors, more sims) or jump straight to learned evaluators (P).

Smaller items: **F13 (reed weight audit)** is free (no compute) and could clarify why V3 drifted. **F3 (V3 food double-count)** is a meaningful but bounded improvement. F4-F7 are architectural V3 expansions, defer until F12 settles V3's headroom.

**Card system (H-L)** still a separate track that can run in parallel. Open design questions (H, I, J, K) should be settled when the first card needing each lands.
