# Possible Next Steps after Task 6

A sketch of directions the project could take next, organized by project phase. Originally written 2026-05-13 after Task 5; revised 2026-05-15 after Task 5C; rewritten 2026-05-19 after Task 6.

520 tests passing. Every non-atomic action space has a working resolution path; the `NotImplementedError` branch in `_apply_place_worker` is now only a defensive guard for unknown space-IDs. Only the harvest phases (HARVEST_FIELD / HARVEST_FEED / HARVEST_BREED) and rounds 5–14 remain as engine-level work for Phase 1 completion.

This is a planning document, not a commitment.

---

## Engine completeness (Phase 1)

Harvest is the only remaining engine-level work for Phase 1 (a fully playable Family game from setup to scoring).

### A. Harvest phases

Three sub-phases at the end of rounds 4, 7, 9, 11, 13, 14: HARVEST_FIELD → HARVEST_FEED → HARVEST_BREED.

- **HARVEST_FIELD** is mechanical — take 1 crop from each planted field. No agent decisions; pure state transformation.

- **HARVEST_FEED** is the most complex of the three. Each adult requires 2 food; newborns from the just-ended round require 1 food. Players can convert grain/veg directly (1:1) or animals/veg via cooking improvements, plus once-per-harvest building-resource conversions via Joinery / Pottery / Basketmaker's Workshop. Shortfall = 1 begging marker (−3 points) per missing food. The decision space — which goods to convert in what order, whether to beg, whether to release animals before breeding — is the first real strategic-choice surface beyond worker placement.

- **HARVEST_BREED** uses the existing `breeding_frontier` helper in `agricola/helpers.py`. Per-type rule: breeds iff player has ≥ 2 of that animal AND has capacity for the newborn. Players can release animals immediately before breeding to make space; the existing `breeding_frontier` returns a Pareto frontier of post-breed configurations.

Implementing the harvest also unblocks rounds 5–14: the engine currently halts in `Phase.BEFORE_SCORING` after round 4's RETURN_HOME because `_resolve_return_home` doesn't know what to do with the harvest trigger. After harvest lands, the round loop extends to round 14.

Probably 1 task of work. End state: a Family game playable from setup to scoring (without cards beyond Potter Ceramics).

---

## Small engine cleanup / hardening

Worth doing before serious MCTS / agent work begins. Each is 1–2 sessions.

### B. `BoardState.action_spaces` hashability

Currently `BoardState.action_spaces` is a `dict[str, ActionSpaceState]`, which makes `BoardState` (and transitively `GameState`) unhashable. State-hashed legal-actions caching and DAG-MCTS both require this — flagged as a known small refactor in FENCE_IDEAS.md Section 5. Replace the dict with a structurally equivalent hashable type (e.g., a `tuple[ActionSpaceState, ...]` indexed by canonical space-id order, plus a name → index lookup at module load). Mechanical refactor; the tricky part is the canonical ordering choice and updating every call site that currently keys by string.

### C. Performance profiling of `legal_actions` and `step`

Nothing is known to be slow, but no one has measured. Useful before MCTS scaling exposes per-call cost as a bottleneck. Easy first pass: profile `random_agent_play` across the 10-seed sweep, broken down by function. Identify hot paths, then decide whether any caching or restructuring is worth doing. The Fencing legality enumerator is the most likely hot spot given its per-call universe walk; the precomputed 1×1 fast path mitigates this but hasn't been measured.

### D. State-independent fence-universe restriction tooling

The `ACTIVE_FENCE_UNIVERSE_*` constants are swappable today. A small experimental tooling layer — a `restrict_to(predicate)` wrapper, a per-experiment-config layer, or shared test fixtures that swap and restore the constants — would make universe-restriction research cleaner once self-play training begins. Currently each test that swaps does so manually with monkey-patching. Defer until there's a concrete restriction experiment to run.

---

## Phase 2 — baseline agents

After the engine is feature-complete (post-harvest). Useful as benchmarks for the trained agent and as scaffolding for MCTS.

### E. Heuristic agent

A hand-written policy implementing reasonable Agricola strategy: prioritize food security, family growth, field-and-pasture balance, build major improvements on schedule, etc. Plays without MCTS — direct action selection from observed state.

Useful as:
- A baseline to compare the trained agent against (Phase 5+).
- A second agent for sanity-checking the engine end-to-end. `random_agent_play` exercises only the simplest paths; a heuristic agent surfaces edge cases that random play rarely hits.

### F. MCTS scaffolding

Pure MCTS (no neural net yet), used initially with random and heuristic agents to validate the tree-search loop. Becomes the substrate for AlphaZero-style training in Phase 5.

Concrete pieces: a `TreeNode` class with edge / node statistics, a `select / expand / simulate / backup` loop, UCB1 selection, terminal-state handling, and an agent wrapper that uses MCTS to pick actions. State-hashed transposition table (depends on B) lets nodes share statistics across reachable-by-different-paths states; without it, the search tree fragments more than necessary on actions like Fencing (where the builds-before-subdivisions ordering rule already cuts some path-level inflation but doesn't eliminate it).

---

## Phase 3 — card system

The largest single piece of remaining work. Several open design questions block large-scale card implementation; resolving them is itself a meaningful task. Each open question is best addressed when the first card needing it actually lands — don't speculate ahead of concrete consumers.

### G. Compound card interactions

The Pan-Baker-plus-Potter-Ceramics example flagged in TASK_5.md and IMPLEMENTATION_CHOICES.md. When checking `PlaceWorker(space)` legality, the system needs to apply all owned cards' on-placement transformations to a hypothetical state, then ask the existing sub-action predicates against that hypothetical. The trigger registry already supports arbitrary event names; the missing piece is the legality-side speculative application.

Probably worth doing before adding many more cards. Without G, the card system can only handle cards of the Potter Ceramics shape (purely-during-resolution triggers, no on-placement effects).

### H. `after_X` trigger event mechanics

The codebase has precedent for `before_X` events on sub-action pendings. `after_X` events have no precedent. Candidate consumers:
- The vegetable-card example mentioned during Fencing design ("each time you build N fences ≥ current round, gain 1 vegetable").
- Cards like Cottager and Hardware Store that attach to atomic spaces with before/after semantics.

Three candidate mechanisms documented in the design conversations: a resolve-on-pop hook on every pending type, an explicit `ApplyAfterTriggers` action, or overloaded `Stop` semantics. Decision deferred until the first such card lands.

### I. Atomic-space trigger hosting

Atomic spaces currently apply their effect immediately on `PlaceWorker`. For cards that attach to specific atomic spaces (Cottager fires before Day Laborer's food, Hardware Store fires after), atomic spaces need to push trigger-host pendings rather than resolve in one step. Two design questions documented in CLAUDE.md "Card implementation status":

- **Phase tracking.** Generic `primary_effect_applied: bool` on every space pending vs. a `phase: Literal["before", "after"]` field.
- **Phase-transition mechanism.** Explicit transition action vs. overloaded `Stop` vs. nested pendings.

Likely addressed alongside G when card work begins in earnest.

### J. Free-fence accounting and cost-modifier extension

Cards modifying per-edge fence cost (material substitution, free perimeter fences, etc.) need an extension mechanism on `compute_new_fence_edges`. The pattern would mirror `BAKE_BREAD_ELIGIBILITY_EXTENSIONS` / `BAKING_SPEC_EXTENSIONS` in `legality.py`. Free-fence counter fields on `PendingBuildFences` may also be needed (currently excluded per the YAGNI-on-pending-fields principle). Defer until the first such card lands.

### K. The remaining ~470 cards

Largest piece of work in the project. Once G–J above are settled, this becomes ongoing card-by-card implementation. Two related action-space paths unblock alongside cards:

- **Minor improvement play paths.** Optional minor-improvement steps at Basic Wish for Children, House Redevelopment, Major Improvement, and Farm Redevelopment all currently dead-end (no path commits a minor in Family scope). Unblocked by minor-card support.

- **The Lessons action space.** Permanently illegal in the Family game today; the legality predicate omits it from `NON_ATOMIC_LEGALITY`. Enabled once occupation cards exist.

---

## Phases 4–6 — training and evaluation

Furthest out. Listed for completeness.

### L. Imitation learning bootstrap

Train a policy on human game data to bootstrap the agent before self-play. Requires a corpus of human Agricola games (e.g., from BGA logs or other online play). Less compute-intensive than self-play; gets the agent to "plays the game competently" before RL refines it. Optional but accelerates phase 5.

### M. AlphaZero-style self-play RL

Self-play with MCTS guided by a neural network. The network outputs `(policy, value)` given state; MCTS uses the policy as priors and the value as rollout estimates. Iterated self-play improves the network over time.

Depends on F (MCTS scaffolding), and ideally on G–J (card system mostly complete; otherwise the agent learns to play a non-Agricola game). L (imitation bootstrap) is helpful but not required.

### N. Evaluation tooling

Elo ratings between agent versions, score distribution analysis, game-length variance, trace replay viewer, head-to-head match infrastructure. Useful throughout training to detect regressions and to compare experimental variants. Some pieces (trace replay, score distribution) become useful right after harvest lands and could ship earlier than the full evaluation pipeline.

---

## My take (advisory, not prescriptive)

**Highest-impact single next task: harvest (A).** Completes Phase 1; turns the engine into a feature-complete Family-game implementation. Without harvest, no agent work makes sense — there's no "game" to play through to a final score.

**After harvest:** the small-hardening items (B and C) before MCTS work begins, then the heuristic agent (E) for a benchmark, then MCTS scaffolding (F).

**Card system as a separate track:** can run in parallel with agent work, but the open design questions (G, H, I, J) should be settled before adding many cards. Resolve each question when the first card needing it lands; let real cards drive the design rather than speculating ahead of consumers.
