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

### F. Heuristic agent — **landed 2026-05-22**

Hand-written policies implementing reasonable Agricola strategy. Two agents shipped:

- **`SimpleHeuristic`** — MVP. `score(state)` + linear resource bonuses + food/begging term.
- **`HubrisHeuristic`** — full-spec. ~50 coefficients in `HeuristicConfig` covering family-future, empty rooms, breeding opportunities, location bonuses, context-aware resources, majors with cooking-primary + round-decay, stage-1×1.5 multiplier, etc. Two evaluator versions: V1 (current default; iterated through user feedback) and V2 (uses `harvest_feed_frontier` for joint goods-or-food optimization — theoretically more correct but loses head-to-head to V1).

Shared infrastructure (`agricola/agents/base.py`) provides the `Agent` protocol, the generic `HeuristicAgent` class with configurable lookahead horizon (1-action or 1-turn, always with singleton-skip), softmax-with-temperature action selection, and a `play_game` driver. The web UI (`play_web.py`) supports any combination of human / random / simple / hubris / hubris_v1 / hubris_v2 in either seat, with manual step-through for AI-vs-AI watching (Enter or "Advance" button).

Bench (20 seeds, default `HeuristicConfig`): V1 beats Random 20-0-0 (+32 vs −4); V1 beats Simple 20-0-0 (+29 vs +16); V1 vs V2 is effectively tied at 7-10-3.

**Next sessions** on this thread are scoped in **`HEURISTIC_TUNING_PLAN.md`**: a self-play tuning harness for the ~50-parameter `HeuristicConfig`, time-varying parameters with monotonic constraints, and stage-dependent score-leaf reweighting to address remaining early-game biases.

### G. MCTS scaffolding

Pure MCTS (no neural net yet), used initially with random and heuristic agents to validate the tree-search loop. Becomes the substrate for AlphaZero-style training in Phase 5.

Concrete pieces: a `TreeNode` class with edge / node statistics, a `select / expand / simulate / backup` loop, UCB1 selection, terminal-state handling, and an agent wrapper that uses MCTS to pick actions.

Now fully unblocked on both fronts:
- **Hashability** (Change 8) — `GameState` can key a transposition table once one is wanted.
- **Within-search memoization** (Change 9) — `legal_actions_cache()` provides an opt-in identity-keyed cache; MCTS wraps its search loop in `with legal_actions_cache(): ...` to take the ~370× cache-hit speedup at zero plumbing cost.

If MCTS performance becomes the bottleneck, POSSIBLE_SPEEDUPS.md S1 (anchor Pareto pruning) and S5 (cached `__hash__` for transposition tables) are the natural targets — but profile first.

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

---

## My take (advisory, not prescriptive)

**F (heuristic agent) landed.** SimpleHeuristic and HubrisHeuristic V1/V2 ship as of 2026-05-22 — see HEURISTIC_TUNING_PLAN.md for the queue of work to improve them via self-play tuning and time-varying parameters.

**Two natural next directions, in parallel:**

1. **Tune the heuristic** (HEURISTIC_TUNING_PLAN.md). Build a self-play tuning harness, extend the parameter space to allow time variation, and reweight score-leaves. This gives the agent its first principled tuning rather than hand-picked coefficients.
2. **MCTS scaffolding (G)** — fully unblocked by Changes 8 and 9. Pure MCTS first, with HubrisHeuristic as the rollout policy. If MCTS rollout cost becomes a problem, POSSIBLE_SPEEDUPS.md S1 (anchor Pareto pruning) is the highest-ROI remaining optimization based on current profiles.

Both compound: a tuned heuristic makes MCTS rollouts cheaper / better, and MCTS-driven self-play could itself be a source of tuning signal for the heuristic.

**Card system as a separate track:** can run in parallel with agent work, but the open design questions (H, I, J, K) should be settled before adding many cards. Resolve each question when the first card needing it lands; let real cards drive the design rather than speculating ahead of consumers.
