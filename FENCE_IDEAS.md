# Fence-Building Design

This doc captures the design thinking for Agricola's Fencing action: the preferred approach, the alternatives we considered (or could have considered) and rejected, and the open sub-questions. It is intended as a reference for future sessions that need to implement, modify, or reconsider the design.

## 1. Context

Fencing is the single most complex decision in Agricola. The player has up to 15 fence pieces, each costing 1 wood; fences are placed on edges between cells of the 3×5 farmyard or on the farmyard boundary; the placed fences must collectively enclose one or more pastures; and only empty or stable-bearing cells may end up enclosed (rooms and fields cannot). Fences are permanent once placed. A Build Fences action can be entered from three places: the standard Fencing action space, Farm Redevelopment's renovate-then-Build-Fences flow, and various card effects.

The hard problem is the size and shape of the legal action space. A naïve enumeration of legal final fence-edge configurations runs into the combinatorics of subsets of 38 fence edges (4×5 horizontal + 3×6 vertical), most of which are illegal. The legal subset is plausibly in the hundreds to low thousands for a typical mid-game farmyard, though this is an estimate that hasn't been measured. The space does not factor cleanly along a single semantic axis: capacity is multi-dimensional (one type per pasture, capacity formula combines cells and stables, total capacity vs. per-type capacity vs. pasture count all matter independently), and spatial position interacts with future fencing legality (the pasture-adjacency rule) and future room and field placement on the same 3×5 grid. Spatial Pareto dominance is genuinely hard to define — unlike the animal-accommodation case where configurations live in ℕ³ with a clean dominance order, pasture configurations are spatial layouts whose value depends on future board state and positional interaction with rooms, fields, and stables. There is no obvious one-axis collapse.

The decision is also load-bearing for AI training. The action representation we pick here is what the policy network learns over and what MCTS branches on. Switching representations later would invalidate trained models and tooling. This is why the design gets a dedicated doc rather than being decided inline during implementation.

## 2. Goals and features for the solution

Each goal below names a property a candidate design should have, explains why it matters in our setting, and rates how flexible it is — whether we would consider abandoning it under pressure.

**Enumerable legal actions per state.** The engine produces a finite list of legal actions at every decision point. This is foundational to MCTS, which expands children from an enumerated set; to action masking, which needs a well-defined set to mask over; and to the existing `legal_actions()` API, which is the engine's single legality entry point. *Importance: hard requirement.* *Flexibility: very low.* Abandoning this would mean rebuilding the engine API. Even a 5000-action enumeration is preferred to a non-enumerable space.

**Fixed-shape policy head compatibility.** The policy network outputs a distribution over actions. This is cleanest when the action space has a fixed enumerable structure (variable-size lists of cell-sets with per-item embeddings are fine, but free-form generation is not). *Importance: high; closely tied to the previous goal.* *Flexibility: moderate.* Autoregressive heads (AlphaStar-style) are possible if needed, but they add complexity and we'd want a clear motivation.

**Semantically meaningful units.** Actions operate on rules-meaningful concepts (pastures and cells) rather than mechanical primitives (individual fence edges). This matters for two reasons: NNs learn faster when the action representation matches the underlying domain, and card effects almost always reference pastures, not edges. *Importance: moderate-to-high.* *Flexibility: moderate.* The engine could in principle use fence-edge primitives and let the NN learn the abstraction, but this throws away free structure.

**Collapsibility / researcher-applied restriction.** A researcher can mask or remove a subset of legal pasture-commits without breaking the API or the policy head shape. This is more valuable than a generic restrictability feature: many candidate pastures are likely never optimal in any reachable game state (extremely small or pathologically-shaped pastures, configurations that strand cells, fencings that obviously waste wood), and a much smaller knowledge-driven subset plausibly spans every optimal action. Training over a curated restricted set should converge faster, and the restriction can be loosened or tightened across experiments. *Importance: likely a major productivity win for training, not just an experimental nicety.* *Flexibility: high in implementation, low in spirit.* The cost is one-sided — restricting incorrectly silently removes optimal moves from training — so the restriction set must be picked with care. The unified pasture-commit design (Section 4) supports this directly: the legal action set is a list of cell-sets, and a researcher-supplied predicate over cell-sets filters straightforwardly. Section 3 covers a related axis (fixed-list vs on-the-fly enumeration) that makes hand-curated restriction even easier.

**Card-extensibility.** Future cards interact with fencing in several patterns: modifying per-fence cost (passive discounts, material substitutions, free boundary edges), granting free fences with various scoping (single free pasture, per-edge predicates), granting additional Build Fences actions from non-Fencing entry points, firing triggers before or after a Build Fences action, and at least one case of razing and rebuilding. The design should accommodate these patterns without structural rewrites. *Importance: high.* *Flexibility: low.* Card support is the long-term home of fencing complexity; building in extensibility now is much cheaper than retrofitting.

**Consistency with existing engine patterns.** The codebase has settled on multi-shot pendings (Farm Expansion's room and stable builds), choose-time flag-setting on parent pendings, the `*_chosen` boolean field convention, the `PENDING_ID` / `initiated_by_id` provenance scheme, and the `auto_pop=False` mechanism for multi-step commits. Reusing these patterns reduces cognitive load for future sessions and reuses tested machinery. *Importance: medium-to-high.* *Flexibility: medium.* Could deviate with strong justification but the burden of proof is on the deviation.

**MCTS-friendly branching.** Per-step branching factor is manageable — hundreds, not tens of thousands. Higher branching means more compute per node expansion and shallower effective search depth at fixed budget. *Importance: medium-to-high.* *Flexibility: depends on alternative.* Would accept higher branching for a flat single-step action if multi-step inflation became prohibitive.

**Avoidance of single-axis Pareto pruning.** Do not prune the choice space by claiming spatial dominance. Two pastures with the same capacity and stable count are not interchangeable — one may be in a strategic corner, the other in the middle blocking future room placement. *Importance: high (this is the user's explicit framing).* *Flexibility: low.* This is a design principle; the cost of violating it is silently bad training because the pruning happens before the agent ever sees the dominated option.

**Implementation complexity.** Lower complexity is better, all else equal. Simpler engine code is easier to debug, easier to extend, and easier for future sessions to read. *Importance: nice-to-have.* *Flexibility: high.* Would accept significant complexity for a major benefit on a higher-priority goal.

## 3. Enumeration strategy: fixed-list filtering vs on-the-fly construction

Independent of which action representation we pick (Section 4 onward), every implementation has to answer one question: how does `legal_actions` produce its output at each call? Two approaches:

**On-the-fly construction.** At each `legal_actions` call, the enumerator traverses current state and generates legal action objects from scratch. The output is freshly constructed each call.

**Fixed-list filtering.** Precompute a "universe" of candidate action objects once at module load. At each call, iterate the universe and check each entry for current-state legality. Return the entries that pass.

**Critical caveat: universe size depends on the action representation.** In the preferred design (Section 4), one commit names one pasture, so the universe is the set of all connected cell-sets in the 3×5 grid — bounded by the grid geometry, plausibly 1000–5000 entries (unmeasured). In flat alternatives that commit a full fencing configuration in one action (Section 7 alternatives B, C, D), the universe is the set of full configurations, which is combinatorially much larger — combinations over the per-pasture universe. Fixed-list filtering is tractable for single-pasture universes and impractical for full-configuration universes. This is a major reason the multi-shot pasture-commit design composes well with the fixed-list approach, and it is the single biggest practical advantage of the preferred design over the flat alternatives.

### Features we want, and how each approach stacks up

| Feature | Fixed-list filtering | On-the-fly construction |
|---|---|---|
| Predictable per-call cost | Always O(\|universe\| × per-entry-check) | Varies with state; harder to bound |
| Engine-side implementation simplicity | Universe is built once at module load (slow is fine); per-call is just iterate-and-filter | Requires a correct enumeration algorithm at runtime (e.g., connected-subgraph enumeration) |
| Researcher restriction by predicate | Apply predicate at check time | Apply predicate after construction (wastes construction work for rejected candidates) |
| Researcher restriction by hand-curated set | Trivial — drop the entries from the universe at build time | Requires a post-filter; the dropped candidates are still constructed each call |
| Canonical action identity | Each action object exists once in memory; `legal_actions` returns references; equality and hashing are free | Fresh objects per call; equality must compare contents |
| Precomputed per-entry metadata | Easy to attach (boundary edges, bitmaps, size, etc.) | Would have to recompute each call |
| Memory cost | Modest — universe materialized | Minimal — no precomputed storage |
| Wasted iteration | Yes — most entries are illegal in any reachable state | No — only constructs legal items |
| Suitability for huge universes | Poor — universe may not fit or take too long to enumerate | Better — generates only what's needed |

**Recommendation for the preferred design: fixed-list filtering with bitmap-encoded entries.** The combination of (a) small bounded universe, (b) bitmap representation making per-entry checks effectively O(1), (c) trivial hand-curation by editing the universe, and (d) a clean subdivision-canonicalization story via universe-membership lookup (see below) tips fixed-list clearly into the recommended position. On-the-fly construction is kept as the alternative, available as a fallback if universe-materialization assumptions ever break down (e.g., a future ruleset adds a much larger action space).

### Per-call check shape (fixed-list with bitmap)

Represent each universe entry as a 15-bit integer (one bit per grid cell). Precompute alongside each entry the boundary fence-edge bitmaps (`h_boundary`, `v_boundary` — the horizontal and vertical fence-edge indices the entry's boundary touches) and the cell-adjacency bitmap (cells one step orthogonally outside the entry, used for the adjacency-to-existing-pasture check). Per state, precompute bitmaps for: enclosable cells, each existing pasture, frontier cells (unenclosed cells adjacent to existing pastures), current fences (`h_fences`, `v_fences`), and the wood/fence-supply scalars.

Per entry, the legality check is a sequence of O(1) bitwise operations:

- **Enclosable cells only:** `cells_bm & ~enclosable_bm == 0`.
- **Within a single existing pasture P (subdivision case):** `cells_bm & pasture_bm[P] == cells_bm` for some P; OR
- **In unenclosed area (new-pasture case):** `cells_bm & unenclosed_bm == cells_bm`.
- **Adjacency** (for new-pasture case): `adjacency_bm & existing_pasture_cells_bm != 0`, OR no existing pastures yet (first-pasture rule).
- **Affordability:** `new_h = h_boundary & ~h_fences`, `new_v = v_boundary & ~v_fences`, `new_count = popcount(new_h) + popcount(new_v)`. Check `new_count <= fences_in_supply` and `cost(new_h, new_v, state) <= wood` (default cost is `new_count * 1 wood`; cost-modifier predicates layer over this when cards land).

Each entry: a handful of bitwise ops plus two popcounts. Total per call for a ~5000-entry universe: low milliseconds.

For on-the-fly, the enumerator constructs candidates by traversal (find connected subsets of unenclosed cells, enumerate subdivisions per pasture); the conditions are implicit in the traversal logic.

### Subdivision canonicalization via universe-membership lookup

For each candidate C entirely within some existing pasture P, the complement `C' = P\C` represents the same physical subdivision (cuts P into the same two parts) when C' is itself connected. To avoid emitting both, the enumerator does an O(1) lookup:

1. Compute `complement_bm = pasture_bm & ~cells_bm`.
2. Check `complement_bm in universe`. Because the universe contains exactly the connected cell-sets, this lookup also answers "is the complement connected?" — no separate connectivity check needed.
3. If found in the universe: emit C only if it's the canonical side, e.g., `lowest_set_bit(cells_bm) < lowest_set_bit(complement_bm)`.
4. If not found: the complement is disconnected, so it isn't a legal single commit on its own and no duplicate exists. Emit C unconditionally.

This avoids any explicit flood-fill or graph-traversal on the complement — the universe's structure performs the connectivity check by construction. Implementation requirement: the universe must support fast membership lookup. With bitmap representation this is free (bitmaps are hashable ints), so store the universe as a frozenset or dict keyed by bitmap alongside the iteration-order tuple.

### Universe construction options (if we go fixed-list)

Several axes a future implementer should decide; none are blocking, but pinning them down early avoids rework.

- **Eager vs lazy construction.** Eager: build the universe at module import. Lazy: defer until the first `legal_actions` call. Eager is probably fine for our case because the engine is always used (no point deferring); lazy with a module-level cache is a reasonable fallback if import-time cost becomes a concern.

- **Storage shape.** A tuple of frozen action objects gives ordered iteration, immutability, and hash-friendliness. A frozenset deduplicates but loses iteration order. A list works but is mutable and offers nothing tuple doesn't. Tuple is the obvious default; the iteration-order determinism is useful for debugging and trace reproducibility.

- **Per-entry metadata.** Useful candidates: precomputed boundary fence-edge indices (for fast cost derivation), cell count, bounding box, bitmap representation of cells (for fast subset/intersection checks against current state). Compute these at universe construction time when possible — construction can afford to be slow; per-call iteration cannot.

- **State independence.** The universe is a pure function of grid geometry (3×5). It does not depend on game state, player identity, or anything dynamic. A single module-level universe object can be shared across every `legal_actions` call in every game. This is structurally what makes the fixed-list approach cheap; it would not work for engines whose action universe varies with state (e.g., card-drafting games where the relevant card pool changes).

- **Layered universes for restriction experiments.** The shipped "full" universe and an experiment-specific "restricted" universe can be separate objects. The full universe is built once and never modified; an experiment constructs its restricted subset at setup time, and the enumerator is parameterized by which universe to iterate. This composes cleanly with the Section 2 collapsibility goal — different experiments use different restricted universes without changing the engine.

## 4. Preferred design: unified pasture-commit, multi-shot

**Pending.** `PlaceWorker("fencing")` pushes `PendingBuildFences`. Farm Redevelopment pushes the same pending after its renovation phase completes (the Build Fences half of renovate-then-Build-Fences). Card effects that grant an out-of-band Build Fences action push the same pending. The pending follows the multi-shot pattern established by Farm Expansion's room and stable builds and carries:
- `player_idx: int` — whose decision this is.
- `initiated_by_id: str` — provenance for cards that gate on entry point.
- `triggers_resolved: frozenset` — for card-trigger scoping.
- `num_built: int = 0` — multi-shot commit counter, incremented per commit.
- Additional fields are likely to be useful when cards are implemented (per-action commit caps, free-fence counters, per-edge cost-modifier predicates, etc.). Their exact shape is deferred to the card-system task; the pending can grow as needed.

**Sub-action type.** `CommitBuildPasture(cells: frozenset[tuple[int, int]])`. Frozenset gives content-based equality and hashing automatically — two action objects with the same cells are structurally equal regardless of construction order. By convention, whenever cells are iterated for display, logging, or canonical-form computation, sort by `(row, col)` lexicographic order; this keeps human-readable output deterministic.

**Effect.** The named cell-set becomes a new pasture in the resulting state. When the cells lie inside an existing pasture P, the cells of P not in the named set form the rest of the new decomposition — a single second pasture when the complement is connected, or more when it is disconnected. The resulting pasture set is recomputed by `compute_pastures_from_arrays` from the new fence-edge state, so the engine handles either case uniformly. The player names one cell-set per commit; multi-way subdivisions involving multiple deliberate cuts can also be expressed as multiple commits.

**Unified candidate rule.** A candidate cell-set is legal iff:
- All cells are enclosable (empty or stable; rooms and fields cannot be enclosed).
- The cell-set is connected.
- The cells are either entirely within a single existing pasture (a subdivision) or entirely in currently-unenclosed area (a new pasture from open ground). Mixing enclosed and unenclosed cells would require removing an existing fence, which is illegal.
- The cell-set is *attached to or within* an existing pasture, OR the player has no existing pastures (the first-pasture rule). "Within" handles subdivisions trivially; "attached to" handles new pastures via orthogonal adjacency. Treating these symmetrically keeps the new-pasture and subdivision cases under one rule.
- The implied new fence edges are affordable (wood for non-free fences; fences-in-supply for total fence count).

**Canonicalization.** For subdivisions specifically, the named cell-set and its complement-within-P produce identical post-state when the complement is connected. The enumerator detects this via an O(1) universe-membership lookup on the complement (Section 3 spells out the mechanism) and emits only the canonical side — e.g., the one with the lexicographically smaller min-cell. The policy never sees both representations, so no equivalence-learning happens and visit-count signal is not split between functionally identical actions. When the complement is disconnected the lookup fails, no duplicate exists, and the entry is emitted unconditionally.

**Cost handling.** Cost is fully derived per commit from `(state, commit.cells)`: new edges are the boundary of `cells` minus currently-fenced edges, and each edge's cost defaults to 1 wood, modified by any active cost-predicates. This doesn't fit either of CLAUDE.md's existing sub-action cost buckets (it isn't fixed at push time, and it isn't a const-table lookup keyed on commit parameters); it's a fourth pattern — cost is a pure function of state plus commit parameters, computed by the effect function. Worth documenting alongside the existing buckets when this is implemented.

**Stop.** Ends the action; legal once `num_built >= 1`. The "at least one new fence placed" rule is enforced automatically — every legal commit requires at least one new fence edge, so `num_built >= 1` implies the rule is satisfied.

**Why this design.** Maps to Section 2's goals: legal actions are enumerable (cell-sets per step), policy head sees a variable-size list of canonical cell-sets, units are pasture-level, researcher restriction is a one-line predicate filter (or hand-edited universe per Section 3), the multi-shot pattern matches Farm Expansion exactly, and card extensibility plugs into the cost and trigger registries without changing the action shape. The two soft costs are higher branching at the first commit step (estimated 50–300 candidate cell-sets in mid-game, unmeasured) and path-level inflation from commit-order ambiguity (Section 5).

## 5. MCTS interaction

Two distinct redundancy problems show up:

**Action-level redundancy from subdivision naming.** `CommitBuildPasture(cells=A)` and `CommitBuildPasture(cells=P\A)` produce identical post-state for a subdivision of P. The fix is enumerator-level canonicalization (Section 4): emit only the side with the lexicographically smaller min-cell. The policy never sees the duplicate, no equivalence-learning happens, and visit-count signal is not split between equivalent actions. This is strictly cleaner than masking at inference, which would force the policy to learn equal probabilities for equivalent actions and then override at inference — a training/inference mismatch.

**Path-level redundancy from commit order.** Build pasture A then pasture B reaches the same final state as build B then A. For a K-commit fencing action, up to K! orderings reach the same end state — fewer when commits chain (a subdivision of a just-built pasture can only happen after the parent build). In tree-search MCTS, these become distinct subtrees, inflating the tree and wasting expansion compute. For typical fencing actions (1–3 commits), worst-case inflation is 1–6×. The codebase already accepts this inflation for Farm Expansion's multi-shot builds, so accepting it for Fencing is consistent.

Three mitigation paths, none required at the engine layer, all kept open by the frozen-dataclass invariant:
- Accept inflation (no code change; consistent with Farm Expansion).
- Cache network evaluations by state hash (cheap; recovers most of the win by avoiding duplicate network calls without changing the search structure).
- Full DAG MCTS with state-hashed node sharing (clean and well-understood; moderate implementation cost). Edge statistics stay per-`(parent_state, action)`; node-level statistics (visit count, cached value) deduplicate across paths reaching the same state. The main implementation choice is the backup policy when a node has multiple parents (typically: back up only along the traversed path). DAG MCTS is a positive option, not a scary one — flagged here so a future session evaluating performance options doesn't dismiss it.

The choice among these is deferred to the agent-loop implementation phase. The engine commits to nothing here. (Minor aside: the two state-hashing paths above would require reworking `BoardState.action_spaces` from a dict to a hashable equivalent — straightforward but not zero-cost.)

## 6. Open sub-questions within the preferred design

Things to revisit during implementation, not blockers now.

- **Canonicalization rule for subdivisions.** Lex-smallest min-cell is the obvious choice for the canonical-side selection. Alternatives (smaller side by cell count, side with more stables, etc.) would also work; the choice biases what features the policy attends to but does not change correctness. Worth a brief experiment if the policy struggles with subdivision-heavy positions.

- **Researcher-applied masking.** Section 2's "collapsibility" goal made concrete. Likely a runtime predicate accepted by the enumerator (or a wrapper around it). Compile-time masking is also possible but less flexible. Worth picking once we have a concrete experimental need; the unified pasture-commit design supports either approach.

- **Free-fence accounting shape.** The preferred design anticipates a free-fence field on `PendingBuildFences`. A simple integer counter handles some card patterns; others need per-edge predicates or per-action cost overrides. Defer the exact shape to the card-system task; the placeholder field can grow as needed.

- **Cost-modifier registry shape.** Section 4 notes that Fencing's cost-handling pattern doesn't match either of CLAUDE.md's existing buckets. Worth designing the registry alongside the first card that exercises it, and documenting as a fourth cost-handling bucket once stable.

- **Richer pasture-data caching.** `Farmyard.pastures` currently caches the pasture decomposition. The fencing enumerator could benefit from additional cached structures: a per-cell pasture-membership grid (3×5 array mapping each cell to its pasture index or -1 for unenclosed), a frontier-cells set (unenclosed cells orthogonally adjacent to existing pastures, for the adjacency check), or precomputed subdivision options per pasture. Each addition extends the sync invariant on `Farmyard` mutations. Worth profiling before extending the cache — flag here for future thought. The existing single cached value is sufficient for correctness; richer caches are pure perf optimization.

- **Where the "at least one fence placed" rule formally lives.** Implicit in the preferred design (every legal commit places ≥1 fence, and Stop requires `num_built ≥ 1`), but worth documenting in the enumerator so the rule isn't lost if commit semantics change.

## 7. Alternative approaches considered or worth considering

If a future session hits friction with the preferred design — enumeration too slow, card extensions awkward, policy fails to learn, training unstable — the right move is to re-read this section and ask whether one of these alternatives addresses the specific friction better. Tunnel vision on the preferred design is the failure mode to avoid. Some alternatives are listed explicitly so we don't accidentally re-propose them later under different names.

Each entry: what it is, tradeoffs against Section 2, why we didn't pick it, what kind of friction would make it look better, and any commentary.

**A. Flat enumeration of full fence-edge configurations.** A single `CommitFencing(fence_edges)` action; the engine enumerates every legal final edge configuration. *Tradeoffs:* satisfies enumerability but with massive redundancy (many edge configurations produce the same pasture decomposition; redundant fences not part of any pasture boundary are illegal but the enumerator has to filter them). Semantic units are wrong (edge-level, not pasture-level). *Why not:* same decomposition appears multiple times with redundant-fence variations, all dominated by the minimal version; collapses cleanly to alternative B below by canonicalizing to minimal edge sets. *Revisit if:* never; B is strictly better.

**B. Flat enumeration of pasture decompositions (single commit).** A single `CommitFencing(decomposition)` action where the decomposition is a tuple of cell-set pastures; engine derives fence delta. *Tradeoffs:* satisfies enumerability cleanly, single commit per Fencing visit (no path-level inflation, no multi-shot pending machinery). Larger single-step branching than the preferred design — probably 10³–10⁴ at peak because it's combinations over the preferred design's per-step set. Worse trigger granularity if cards need to inspect per-pasture outputs of one action — possible but less natural than the multi-shot version where each pasture-commit is its own engine step. *Why not:* the bigger branching and the worse fit for per-pasture inspection outweigh the avoided path-level inflation. Decomposition-level enumeration also has a one-to-many issue where multiple semantic intents (build new vs subdivide existing) collapse to the same target decomposition, which adds confusion. *Revisit if:* multi-step trace lengths become a serious training problem, OR if the per-step enumeration in the preferred design proves slow and a single-step canonicalized enumeration is more cacheable.

**C. Goal-state specification.** Agent submits a target `Farmyard.pastures` (post-action decomposition); engine derives fence delta and validates. *Tradeoffs:* functionally equivalent to B in expressiveness, but the action object is invariant to the path that produced existing fences (depends only on the resulting state, not the diff). Easier to compare across states for value learning. *Why not:* the path-invariance benefit is small; the engine still has to derive and validate the fence delta; and "target state" is awkward to enumerate or restrict at the granularity a researcher might want. *Revisit if:* value learning across different fencing-history paths becomes unstable, or if a UI/replay tool wants to express fencing actions in absolute rather than relative form.

**D. Differential / incremental fence-edge specification.** Agent submits only the new fence edges (delta arrays); engine validates union-with-existing. *Tradeoffs:* compact action representation; clean if future cards pre-place fences for free (the delta naturally represents the player's contribution separate from card-injected edges). Edge-level units (rather than pasture-level) is the main downside. *Why not:* same semantic-unit problem as A; no advantage over the preferred design unless pre-placed fences become common. *Revisit if:* cards that pre-place fences become a dominant pattern and edge-delta representation simplifies their interaction.

**E. Multi-step one-fence-at-a-time.** Each sub-action commits exactly one fence edge; Stop validates the cumulative result. *Tradeoffs:* very small per-step branching (≤38 edges, much less at peak); deep traces; intermediate states are illegal (dangling fences violate connectivity); the agent has to plan the whole thing in advance anyway because legality is only checked at Stop. *Why not:* depth and the illegal-intermediate-states problem make this much worse than the preferred design. *Revisit if:* per-pasture branching at the first commit exceeds policy-head capacity (very unlikely for our 15-cell farmyard).

**F. Multi-step with new/subdivide as distinct action types.** Two-option choose at the parent (`ChooseSubAction("new_pasture")` vs `ChooseSubAction("subdivide")`), then enumerated cell-set per option. The version we considered before unifying. *Tradeoffs:* explicit intent; smaller per-step enumeration when split; matches Farm Expansion's two-option pattern. Adds a `ChooseSubAction` step to the trace; introduces an artificial distinction (the rules don't really distinguish new from subdivision, they distinguish "what's the resulting pasture set"). *Why not:* the rules don't require the distinction, the unified design has a uniform policy-head shape, and per-action card triggers can derive intent from state if needed. *Revisit if:* a future card explicitly distinguishes "new pasture" from "subdivision" in a way that's hard to derive from state, or if the policy struggles to learn the unified action shape.

**G. Multi-step with completability gating.** Each commit must leave the partial configuration completable to a legal endpoint. *Tradeoffs:* avoids "trapped" intermediate states where the player has placed some fences but cannot legally Stop. Completability-checking is itself a search problem, potentially expensive. *Why not:* in our design, every commit produces a complete pasture (or a complete 2-way subdivision via canonicalization), so every state after a commit is a legal Stop state. The completability problem doesn't arise. *Revisit if:* we ever move to a per-fence-edge multi-step (alternative E) where intermediate states can be illegal.

**H. Verify-only / try-and-reject.** Engine doesn't enumerate; agent proposes an action; engine validates and accepts or rejects. *Tradeoffs:* no enumeration cost; agent must generate legal actions. *Why not:* MCTS fundamentally needs enumerable children at every node; this defeats the engine's `legal_actions()` contract and would require rebuilding the agent loop. The reference e2crawfo/agricola repo uses this approach but never wired up an AI agent against it, which is informative. *Revisit if:* we shift away from MCTS to a generation-style architecture (autoregressive policy that produces actions token by token without explicit enumeration). Significant architectural pivot.

**I. Two-stage budget envelope.** First commit picks a budget (total fence count or pasture count); second commit picks the concrete configuration within that envelope. *Tradeoffs:* spreads branching across two engine steps; the first decision is small (≤16 options); the second is over a constrained subset. *Why not:* the budget envelope is artificial (the rules don't expose this choice as a separate decision); the second step still needs enumeration; adds a `ChooseSubAction` for no semantic benefit. *Revisit if:* enumeration in one step proves intractable but a two-level enumeration is more tractable.

**J. Engine-curated opinionated menu.** Engine emits a heuristically-pruned set of strategically-distinct options (e.g., Pareto-optimal by some heuristic over capacity, wood-spent, cells-used). *Tradeoffs:* smaller branching; pruning is heuristic-driven rather than rule-derived. Lossy for future-adjacency planning since two configurations with the same heuristic score may differ in location. *Why not:* directly violates the "avoid single-axis Pareto pruning" goal from Section 2. The whole point of that goal is that spatial dominance is hard to define correctly. *Revisit if:* someone produces a convincing spatial-aware dominance heuristic that doesn't lose information needed for future fencing or room/field placement.

**K. Hybrid shape-signature.** Engine enumerates a small shape signature (e.g., "one 2×2 pasture", "two 2×1 sharing an edge"); agent's commit specifies the placement of that signature on the grid. *Tradeoffs:* branching factor splits between shape enumeration (~tens of shapes) and per-shape parameter choice (~tens of placements). Clean factorization. *Why not:* the shape signature is artificial — the player doesn't really decide "what shape" separately from "where"; a cell-set commit captures both in one step. The factorization doesn't reduce total branching, just spreads it across two steps. *Revisit if:* we want autoregressive policy heads and need an explicit factorization to plug into them.

**L. Single-pasture-per-Fencing-visit (no multi-shot at all).** Each Fencing action commits exactly one pasture delta; players use multiple Fencing actions across turns to build multiple pastures. *Tradeoffs:* drastically simplifies the engine (no multi-shot pending, no Stop, no inflation); forces multi-turn pacing for what's logically one action. *Why not:* violates the rules — a Build Fences action explicitly allows enclosing "one or more pastures" — and forces the player to spend multiple worker placements on what should be one. *Revisit if:* multi-shot causes serious MCTS inflation issues that none of the Section 5 mitigations resolve, and we're willing to accept the rules deviation as the cost.

**M. Capacity-frontier Pareto.** Reuse the animal-accommodation Pareto frontier pattern: enumerate raw configurations, collapse to capacity-equivalent representatives, agent picks (capacities, cost), engine uses canonical tiebreaker to choose location. *Tradeoffs:* exactly the dominance pruning the design rejects. Collapses spatial information that matters for future fencing legality. *Why not:* explicit rejection — included here so we don't re-propose it later. *Revisit if:* never, unless we figure out a spatial dominance metric that's actually correct, which seems unlikely.

## 8. Cross-cutting axes

A short reference table of dimensions for comparing designs in Section 7. Meant as an evaluation tool, not a recommendation in itself.

| Axis | What it measures |
|---|---|
| MCTS fit | Does the design produce a finite state-determined legal set per node? |
| Policy-head shape | Variable-size list vs. fixed enumeration vs. generative head |
| Card extensibility | How narrow is the surface for cards to modify behavior? |
| Trace / replay consistency | How do actions map back to human game logs? |
| Transposition behavior | How much path-level redundancy does the design create? |
| Implementation complexity | How much new engine machinery is required? |
| Where legality computation lives | Engine (preferred) vs. agent (verify-only) |
| Determinism observable to agent | Is the legal action set state-deterministic? |

## 9. Known open problems

- **Compound card interactions for fencing.** Analogous to the Pan Baker + Potter Ceramics problem flagged in TASK_5.md: one card's effect may enable another card's eligibility under combinations the simple per-edge predicate model doesn't capture. Deferred to the broader card-system task.

- **Per-edge cost-paid metadata on `Farmyard`.** Some card mechanics (e.g., end-game scoring on edges paid via material-substitution variants) may require tracking what was paid per edge, not just edge-presence. Currently `Farmyard` stores only fence booleans. Either expand the dataclass or recompute from a purchase log at scoring time. Decide when the first card needing this is implemented.

- **Richer pasture-data caching.** Flagged in Section 6. The current single cached value (`Farmyard.pastures`) is sufficient for correctness, but the fencing enumerator may benefit from additional cached structures (per-cell pasture-membership grid, frontier-cells set, precomputed subdivision options). Each addition extends the sync invariant on `Farmyard` mutations. Worth profiling before extending.

- **Trigger-event mechanics for "after-action" events.** The codebase has precedent for `before_X` events on sub-action pendings but no precedent for `after_X` events. Cards that fire at the end of a Build Fences action need an `after_build_fences` mechanism. The exact mechanism (resolve at Stop time before popping, push a wrapper pending, etc.) is a card-system task concern but is worth flagging here so the choice is made deliberately.
