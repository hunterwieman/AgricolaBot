# Heuristic Tuning & Time-Varying Parameters — Plan

> **⚠️ Partially superseded.** This doc was written 2026-05-22 at the end of the
> V1 heuristic-agents arc, before V3 existed. Thread A (self-play tuning harness)
> has been implemented — see **`scripts/tune_heuristic.py`** + **`scripts/run_iterative_v3.py`**
> with operational details in **`V3_TRAINING_PIPELINE.md`**. The V1 round-2 tuning
> Thread A enabled produced **`CONFIG_V1_T2`** (+8.85 holdout vs V1 default).
>
> Threads B (time-varying parameters) and C (score-leaf reweighting) are
> implicitly addressed by V3's architecture: per-stage modulators give every
> category time variation, and the BLEND/ADDITIVE/JOINT-ALPHA combination
> styles handle the score-leaf-trust concern explicitly. See **`V3_DESIGN.md`**.
>
> This doc remains useful for understanding the original V1-era motivation
> for the tuning effort, and the design considerations that led to V3.
>
> **Status:** planning doc written 2026-05-22 at the end of the
> heuristic-agents arc. Captures the next sessions' agenda: systematic
> self-play tuning, extending the parameter space to allow time variation,
> and reweighting score-leaf contributions to discourage over-aggressive
> early-stage score-leaf grabs.
>
> **Companion doc:** **`HUBRIS_V1_NOTES.md`** — design reference for
> V1's term-by-term reasoning. Read that first to understand *what*
> we're tuning before reading *how* to tune it.

The HubrisHeuristic numerical values landed so far are hand-picked from
intuition. They aren't tuned. This plan covers turning the heuristic into
a tunable artifact and finding better values via self-play.

---

## Where we are at the end of the heuristic-agents arc

- `SimpleHeuristic` (MVP) and `HubrisHeuristic` (full-spec) implemented as
  callable agent classes; both reuse `HeuristicAgent` infrastructure
  (1-turn lookahead with singleton-skip + softmax-with-temperature).
- Two Hubris versions:
  - **`HubrisHeuristicV1`** (current default; `HubrisHeuristic` alias):
    the version we iterated on through Round 4. Has a known imprecision
    in convertible-goods accounting that empirically aligns with
    end-game stockpiling behavior.
  - **`HubrisHeuristicV2`** (opt-in): uses `harvest_feed_frontier` for
    joint goods-or-food optimization. More theoretically correct but
    plays slightly worse head-to-head against V1 (the missing piece is
    weighting "I won't actually convert if game ends first").
- `HeuristicConfig` (frozen dataclass) holds ~50 coefficients. All
  values today are scalars.
- Bench (20 seeds, default config):
  - V1 vs Random: 20-0-0, +32 vs −4
  - V1 vs Simple: 20-0-0, +29 vs +16
  - V1 vs V2: 7-10-3 (basically tied)

---

## The three threads for the next sessions

### Thread A — Self-play tuning harness

**Goal.** Given `HeuristicConfig`, find values that maximize a fitness
function (e.g., score vs. a fixed baseline). The harness should:

- Construct a `HubrisHeuristic` from a candidate `HeuristicConfig`.
- Play N games against a fixed baseline opponent on a fixed seed set.
- Return an aggregate fitness (avg score, win rate, or combined).
- Plug into an outer optimization loop.

**Optimization-algorithm shortlist:**

1. **CMA-ES** (`pip install cma`). Gradient-free, well-suited to ~30-50
   parameter problems, handles bounded boxes via input scaling. The
   default recommendation.
2. **Bayesian optimization** (e.g. `scikit-optimize`). Better for very
   expensive evaluations and low-dim spaces. Probably overkill here.
3. **Random search**. Cheap baseline; sometimes competitive with grid
   search. Worth running once for comparison.
4. **Tournament / evolutionary**. Multiple agents play round-robin;
   promote winners; mutate. More expressive but more complex.

**My recommendation:** start with CMA-ES, fall back to random search for
sanity check.

**Fitness function — three candidates:**

| Option | Pros | Cons |
|---|---|---|
| Avg score vs `HubrisHeuristicV1(default_config)` baseline | Stable, reproducible; smooth fitness landscape | Can overfit to the specific baseline's weaknesses |
| Avg score vs `SimpleHeuristic` baseline | Cheaper (Simple is faster); harder baseline to beat with margin | Might saturate (everyone wins by similar margin) |
| Round-robin tournament among the CMA-ES population + a few fixed anchors | Self-balancing; resists overfitting | More expensive; tournament outcomes are noisier |

Likely **start with V1-default as baseline** because it's the natural
"can we tune better than the hand-picked values" question. Later, add
tournament for robustness.

**Compute budget (rough):**

- 1 Hubris game ≈ 0.6-0.8s (1-turn lookahead).
- 30 seeds per evaluation → ~25s per evaluation.
- CMA-ES typical: 20-50 generations × 15-30 population = 300-1500 evals.
- Single-threaded total: 2-10 hours. Parallel (8 cores via `multiprocessing`): 15-90 min.

**Deliverables:**

- `scripts/tune_heuristic.py` — outer optimization loop.
- `scripts/play_match.py` — single matchup runner (factor out from the
  inline bench scripts we've been using).
- `tuned_configs/<timestamp>.json` — persisted best configs.
- A short results writeup comparing tuned vs default.

**Open questions:**

- Library choice: `cma` package vs. roll our own CMA-ES? `cma` is
  standard.
- Reproducibility: should evaluation seeds be fixed across all evaluations
  in a run (yes, lower variance) or resampled (more robust)?
- Bounded vs unbounded parameters: many config fields have natural
  bounds (positive, monotonic). Use CMA-ES's box constraints.
- How to handle the V1/V2 split: tune V1's config; V2 can be tuned
  separately later.

### Thread B — Time-varying parameter space

Many config fields are conceptually time-dependent. For example:

- Wood is more valuable in stage 1 (already partly captured by the
  `stage1_resource_mult` we just added) — but reed and clay probably
  have different stage-curves than wood.
- Family-member rates plausibly decay non-uniformly: 3rd member's
  per-round value should fall faster as the game ends than the 5th's.
- Begging penalty is already time-varying (by moves-remaining bucket).
- Empty-room anticipation has a hardcoded `min(12, ...)` cap that
  models "rooms filled past round 12 score nothing."

**Two ways to parameterize:**

| Form | Description |
|---|---|
| Per-stage tuple | `wood_per_fence_owed: tuple[float, ...] = (0.8, 0.8, 0.8, 0.8, 0.8, 0.8)` — one value per stage (1-6). Step function. |
| Spline / interpolation | A few anchor points; linear-interpolate between them at runtime. Smoother but more code. |

Per-stage tuple is simpler and gives the optimizer enough degrees of
freedom. Spline is overengineering for now.

**Monotonicity constraints.** Some parameters should be non-monotonic
without external constraints (the optimizer might find local minima that
violate strategic priors). For each parameter, mark its desired shape:

- **Monotonic decreasing over stages** (typical for "future-value" terms):
  family rates, empty-room rates, food-conversion utility.
- **Monotonic increasing over stages** (rare; can't think of a strict
  example).
- **Bell-curve / unconstrained** (typical for "current-state" terms):
  food values at stage transitions, fence cost rates.

Enforce via reparameterization: store `(base, delta_1, delta_2, ...)` with
`delta_i > 0` constraints; reconstruct as `base + cumsum(deltas)` for
increasing or `base - cumsum(positive_deltas)` for decreasing.

**Decisions:**

- Which fields get per-stage variation? My instinct: family rates, all
  resource-tier rates, food values, breeding-value rates, empty-room
  rates. Fields like `field_center_bonus` stay scalar (intrinsically
  static).
- How many stages? Six (matching the game's stage card progression) is
  the natural choice. Or fewer (3-4 buckets) for fewer parameters.

### Thread C — Score-leaf reweighting

**The early-grain failure mode.** Today, `score()`'s 0→1 jump for grain
(−1 → +1 = +2 delta) drives the agent to grab Grain Seeds early. The
score-leaf is treated as if it's the *final* count, but in stage 1 the
player will plausibly acquire grain organically before scoring; the
score-leaf bonus is *anticipated*, not earned.

**Two implementations:**

1. **Stage-dependent score-leaf multiplier.** Add
   `score_leaf_mult_by_stage: tuple[float, ...]` (one per stage). In
   `evaluate_hubris_v1`, multiply score()'s grain/veg/sheep/boar/cattle/
   field/pasture contributions by this multiplier. Reduces stage-1
   weight on the 0→1 jumps. Simple but coarse.
2. **Anticipation-based.** Assume by-end-of-game the player will have
   ≥ N of each leaf even with no specific action. Compute leaf score as
   the marginal contribution above the anticipated baseline. More
   principled but more code (need per-leaf anticipation estimates).

My recommendation: start with (1) — it's a one-line change in the
evaluator plus N config fields. Tune the per-stage multipliers via the
self-play harness from Thread A.

**Decisions:**

- Per-category or global multiplier? Different leaves probably need
  different rates: animals genuinely have +2 score jump immediately
  exploitable; grain you'll get later. **Per-category likely.**
- Apply to all score-leaves (including fields, pastures) or just the
  crops/animals? Fields/pastures aren't acquired-by-default; they need
  explicit action. Suggest only crops + animals.

---

## Suggested order

1. **Thread A first** (tuning harness). Build the infrastructure even
   if we don't fully tune yet — every subsequent change becomes
   testable. Probably 1-2 sessions of work.
2. **Thread C second**. Add the score-leaf multipliers. Cheap to
   implement (~30 lines + config). Now the harness has a more
   interesting parameter space to explore.
3. **Thread B third**. Extend to time-varying parameters once we have
   a baseline tuning result and we know which scalars are doing the
   most work.

Each thread is roughly independent — they can be reordered if priorities
shift.

---

## Open items / known unknowns

- **V1 vs V2.** V1 plays better today. After tuning, V2 might catch up
  (the joint-frontier model has more room to express strategy). Worth
  re-benching after tuning lands.
- **Stability across seeds.** Some configs may have high variance
  outcomes. Consider Wilcoxon rank-sum or similar for "is config A
  reliably better than config B?" Currently we just look at average
  scores.
- **Overfitting to baseline.** A tuned config that beats
  `V1(default_config)` may not beat other agents. Hold out a tournament
  set or rotate baselines periodically.
- **Compute distribution.** Self-play tuning is embarrassingly parallel
  (each game independent). On a multi-core box, easy speedup; on a
  GPU/cluster, more involved.
- **When does this stop being useful?** At some point tuning produces
  diminishing returns, and the right next step is MCTS (item G in
  POSSIBLE_NEXT_STEPS.md) which makes the heuristic into a rollout
  policy rather than the decision-maker.

---

## Pointers for the next session

- Engine is unchanged; agents/ is the only new code area.
- All current bench numbers are with `HubrisHeuristicV1` and default
  `HeuristicConfig`. The hand-picked values are documented in
  `HeuristicConfig`'s docstrings and via comments throughout
  `agricola/agents/heuristic.py`.
- The full change-log for HubrisHeuristic since launch is in the
  conversation transcript (Rounds 1-4 plus the final stage-1 + reed
  update). If preserved as a separate doc later, link here.
- `play_heuristic_game.py` and the web UI (`play_web.py --seats AGENT
  AGENT`) are both useful for spot-checking tuned configs by eye.
