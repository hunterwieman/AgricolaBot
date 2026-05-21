# Possible Next Steps after Task 6

A sketch of directions the project could take next, organized by project phase. Originally written 2026-05-13 after Task 5; revised 2026-05-15 after Task 5C; rewritten 2026-05-19 after Task 6.

520 tests passing. Every non-atomic action space has a working resolution path; the `NotImplementedError` branch in `_apply_place_worker` is now only a defensive guard for unknown space-IDs. Only the harvest phases (HARVEST_FIELD / HARVEST_FEED / HARVEST_BREED) and rounds 5–14 remain as engine-level work for Phase 1 completion.

This is a planning document, not a commitment.

---

## Engine completeness (Phase 1)

Harvest is the only remaining engine-level work for Phase 1 (a fully playable Family game from setup to scoring).

### A. Harvest phases (completed)

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

One concern is that `random_agent_play` will not go on some of the more complicated action spaces that require care to set up (e.g. Farm Redevelopment after aquiring the required resources and a large amount of wood). This can be partially mitigated by a prefabricated starting state where each player starts with a very large amount of resources. Then a random agent or a methodical agent that checks every action combination will come across a wider array of legal actions.

### D. State-independent fence-universe restriction tooling (completed)

The `ACTIVE_FENCE_UNIVERSE_*` constants are swappable today. A small experimental tooling layer — a `restrict_to(predicate)` wrapper, a per-experiment-config layer, or shared test fixtures that swap and restore the constants — would make universe-restriction research cleaner once self-play training begins. Currently each test that swaps does so manually with monkey-patching. Defer until there's a concrete restriction experiment to run.

**Landed in `agricola/fence_universe.py`:** the `active_universe(spec)` context manager (named universes or explicit triples; nests; restores on exception), `restrict_to(predicate, base=...)` builder for derived universes, `NAMED_UNIVERSES` registry, and `current_universe()` accessor. A prerequisite footgun-fix in `legality.py` changed the universe-aware enumerator defaults from definition-time-bound constants to `None` sentinels with call-time lookup, so `with active_universe(...):` blocks affect every default-kwarg call site (including all production paths). The pytest-fixture variant mentioned above was deliberately omitted — the context manager covers the use case, and a fixture is a one-liner if one is later wanted. Test coverage: +10 cases in `tests/test_fencing.py` covering swap-via-context-manager, exception restoration, nesting, explicit-triple acceptance, error handling, `restrict_to` filtering / default-base / composition, `current_universe()`, and `NAMED_UNIVERSES` keys.

### E. Pareto frontier pruning optimizations

Two related optimizations to `pareto_frontier` (animal market gain) and `breeding_frontier` (post-breed) in `agricola/helpers.py`. Both exploit the same observation: confirming feasibility of one candidate rules out a whole rectangular prism of other candidates without further checks.

**Anchor pruning.** When a player gains animals through an action space, breeding, or a card effect, the pre-gain animal arrangement is feasible by definition — the player was already accommodating it. The "release all gained" option always lands at exactly the pre-gain state, so it's a frontier candidate. Any post-gain config `(s', b', c')` with `s' ≤ s_current AND b' ≤ b_current AND c' ≤ c_current` (at least one strict inequality) is strictly Pareto-dominated on animal dims; food is excluded from the Pareto check per the **"Preserving optionality"** Key Design Principle. The entire lower-left rectangular prism in animal-space under the pre-gain anchor can therefore be skipped at enumeration time. Same argument for `breeding_frontier` with the "no eat, no breed" pre-breed anchor. Implementation: a few-line dominance check at candidate emit. Speedup range: ~2× for small states up to ~30–50× mid-late game, with the O(n²) Pareto-filter step benefiting quadratically from the candidate-count reduction.

**Incremental geometric pruning.** Generalizes the anchor idea: *every* confirmed-feasible candidate X creates its own dominated prism `{(s, b, c) : s ≤ X.s, b ≤ X.b, c ≤ X.c, with at least one strict inequality}`, not just the pre-state anchor. If candidates are checked in an order that finds high-coordinate feasible candidates early (largest-sum or lexicographically-greedy first, etc.), each confirmed feasible candidate invalidates many remaining candidates before they're enumerated or feasibility-checked. Maintain a set of confirmed-feasible anchors; for each new candidate, test whether it lies inside any anchor's dominated prism; if so, skip without checking feasibility. The anchor set is an incremental max-corner Pareto frontier in animal-space. Most valuable when each feasibility check is expensive (it is, for pareto_frontier — `can_accommodate` enumerates slot assignments).

**Applicability.**
- `pareto_frontier` and `breeding_frontier`: both forms apply cleanly.
- `food_payment_frontier` (food_owed > 0): partially. The simple pre-state anchor is infeasible (player must pay something), so the anchor variant doesn't apply directly. But the broader geometric form *does* apply — once a config X that fully pays food_owed is confirmed, any config Y consuming at least as much of every good (= `Y.remaining ≤ X.remaining` on every dim) is dominated by X. This prunes the lower-left REMAINING prism, equivalently the upper-right CONSUMPTION prism. The existing per-good consumption caps in `food_payment_frontier` already provide a related dimension-level form of this pruning; the geometric variant extends it to joint pruning across goods.
- `harvest_feed_frontier`: does NOT apply — the do-nothing config is the *worst* on the −begging dim, so it dominates nothing.

**Correctness check.** The pruning is valid iff the Pareto dimensions are exactly the upstream-goods counts (animals for `pareto_frontier` / `breeding_frontier`; the 5-tuple remaining-goods vector for `food_payment_frontier`). This holds today per the "Preserving optionality" principle, which excludes downstream byproducts (food) from the Pareto check. If a future card makes some non-food byproduct of conversion into a strategic resource that *should* be a Pareto dim, the assumption must be re-examined.

**Why this matters.** Per-call cost is microseconds today — invisible during human-paced play. The reason to do it is MCTS, where these helpers run inside every rollout, potentially millions of times per turn during self-play. The constant-factor improvement compounds. The pre-state-anchor variant is the easy half and can land standalone; the geometric variant is a more substantial refactor (candidate-ordering choice, anchor-set data structure) and is probably worth deferring until profiling (C) identifies one of these helpers as a hot path.

---

## Phase 2 — baseline agents

After the engine is feature-complete (post-harvest). Useful as benchmarks for the trained agent and as scaffolding for MCTS.

### F. Heuristic agent

A hand-written policy implementing reasonable Agricola strategy: prioritize food security, family growth, field-and-pasture balance, build major improvements on schedule, etc. Plays without MCTS — direct action selection from observed state.

Useful as:
- A baseline to compare the trained agent against (Phase 5+).
- A second agent for sanity-checking the engine end-to-end. `random_agent_play` exercises only the simplest paths; a heuristic agent surfaces edge cases that random play rarely hits.

### G. MCTS scaffolding

Pure MCTS (no neural net yet), used initially with random and heuristic agents to validate the tree-search loop. Becomes the substrate for AlphaZero-style training in Phase 5.

Concrete pieces: a `TreeNode` class with edge / node statistics, a `select / expand / simulate / backup` loop, UCB1 selection, terminal-state handling, and an agent wrapper that uses MCTS to pick actions. State-hashed transposition table (depends on B) lets nodes share statistics across reachable-by-different-paths states; without it, the search tree fragments more than necessary on actions like Fencing (where the builds-before-subdivisions ordering rule already cuts some path-level inflation but doesn't eliminate it).

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

Elo ratings between agent versions, score distribution analysis, game-length variance, trace replay viewer, head-to-head match infrastructure. Useful throughout training to detect regressions and to compare experimental variants. Some pieces (trace replay, score distribution) become useful right after harvest lands and could ship earlier than the full evaluation pipeline.

---

## My take (advisory, not prescriptive)

**Highest-impact single next task: harvest (A).** Completes Phase 1; turns the engine into a feature-complete Family-game implementation. Without harvest, no agent work makes sense — there's no "game" to play through to a final score.

**After harvest:** the small-hardening items (B and C) before MCTS work begins, then the heuristic agent (F) for a benchmark, then MCTS scaffolding (G).

**Card system as a separate track:** can run in parallel with agent work, but the open design questions (H, I, J, K) should be settled before adding many cards. Resolve each question when the first card needing it lands; let real cards drive the design rather than speculating ahead of consumers.
