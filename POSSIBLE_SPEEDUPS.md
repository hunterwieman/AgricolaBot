# Possible Speedups

A living catalog of optimizations to existing or future code. Each entry has a difficulty estimate, an implementation sketch, and a *guess* at the speedup — uncertainty is called out throughout. **Profile before applying.** None of these are commitments.

Originally written 2026-05-21 after item C's profiling pass landed the first wave of optimizations (`fast_replace`, `legal_actions_cache`, the `__debug__` assertion gate, and the round-end-reset guard — see CHANGES.md Change 9). Sibling document to POSSIBLE_NEXT_STEPS.md, which tracks project-level direction; this one is scoped to performance specifically.

## Reading this doc

Each entry follows the same shape:

- **Target** — what existing cost the change attacks, with numbers if available.
- **Implementation sketch** — enough to start coding without further design.
- **Estimated speedup** — best guess with explicit uncertainty.
- **Difficulty** — low / medium / high, plus what makes it that way.
- **When to do it** — dependencies, evidence triggers, ordering with other items.

Numbers cited are from the Workload A/B/C profiling baseline in PROFILING.md unless stated otherwise. After any non-trivial change, re-run `scripts/profile_engine.py` and update the numbers.

---

## Pareto frontier helpers

### S1. Anchor pruning on `pareto_frontier` and `breeding_frontier`

> **Partially superseded (2026-06).** The broader `pareto_frontier` / `breeding_frontier`
> optimization landed — a max-corner fast path + Level-2/3 projection caches
> (`FRONTIER_OPT_DESIGN.md` §5.2 / §6). Anchor pruning *specifically* was **not** implemented: the
> max-corner short-circuit captured the win, and these helpers turned out to be cold in MCTS anyway
> (PROFILING.md "MCTS profile"), so the anchor sketch below is unlikely to be worth pursuing.

**Target.** `can_accommodate` + Pareto inner generators are now the dominant cost cluster after Change 9 — ~9 ms self-time per Workload-A run, ~22 ms per Workload-B run (mid/late game). `pareto_frontier` is called on every animal-market resolution; `breeding_frontier` fires every harvest. Each call enumerates a (possibly large) candidate set and runs an O(n²) Pareto filter over it.

**Implementation sketch.** When a player gains animals through an action space, the pre-gain animal arrangement is feasible by definition — the player was already accommodating it. The "release all gained" option always lands at exactly the pre-gain state, so it's a frontier candidate. Any post-gain config `(s', b', c')` with `s' ≤ s_current AND b' ≤ b_current AND c' ≤ c_current` (at least one strict inequality) is strictly Pareto-dominated on animal dims; food is excluded from the Pareto check per the "Preserving optionality" Key Design Principle. The entire lower-left rectangular prism in animal-space under the pre-gain anchor can therefore be skipped at enumeration time.

Same argument for `breeding_frontier` with the "no eat, no breed" pre-breed anchor.

Implementation is a few-line dominance check at candidate emit:

```python
# In pareto_frontier, before yielding a candidate (s', b', c'):
if (s_pre is not None
    and s' <= s_pre and b' <= b_pre and c' <= c_pre
    and (s' < s_pre or b' < b_pre or c' < c_pre)):
    continue  # strictly dominated by the pre-gain anchor
```

**Estimated speedup.** Item E's original framing (POSSIBLE_NEXT_STEPS.md, since superseded by this doc) claimed "~2× for small states up to ~30-50× mid-late game, with the O(n²) Pareto-filter step benefiting quadratically." Those are unverified — the lower bound (2×) is plausible from first principles; the upper bound depends heavily on candidate-count growth in late-game states, which we haven't measured. **A safer estimate is 1.5-3× on the Pareto helpers themselves**, which translates to roughly **3-5% wall-clock improvement** on mid/late-game workloads. Uncertain.

**Difficulty.** Low. Few-line change in `agricola/helpers.py`. Risk is also low if the "Preserving optionality" Pareto-dim invariant holds (it does today). Document the assumption in the helper docstring.

**When to do it.** Standalone — no dependencies. The natural follow-on after Change 9.

### S2. Geometric Pareto pruning (extends S1)

**Target.** Same as S1, but more general. Every confirmed-feasible candidate creates its own dominated prism, not just the pre-state anchor.

**Implementation sketch.** Maintain a set of confirmed-feasible anchors. Check candidates in an order that finds high-coordinate candidates early (largest-sum or lexicographic). For each new candidate, test whether it lies inside any anchor's dominated prism; if so, skip without feasibility check. The anchor set is an incremental max-corner Pareto frontier in animal-space.

**Estimated speedup.** Unverified. Most valuable when each feasibility check is expensive (`can_accommodate` enumerates slot assignments — it is). Could double S1's gains in late-game states. Could be much less. **The geometric variant is the kind of optimization that needs measurement before claiming a number.**

**Difficulty.** Medium. Requires picking a candidate-ordering scheme, choosing an anchor-set data structure (small max-Pareto frontier of <10 elements typically), and threading it through `pareto_frontier` + `breeding_frontier`. More code than S1; bigger surface area for subtle bugs around ordering.

**When to do it.** After S1 lands and is measured. If S1 alone delivers most of the win, skip S2 — its added complexity isn't worth small marginal gains. If `can_accommodate` still appears in the top 5 self-time slots after S1, S2 is the right next step.

### Applicability table (S1 + S2)

| Helper | S1 (anchor) | S2 (geometric) |
|---|---|---|
| `pareto_frontier` | ✓ direct fit | ✓ direct fit |
| `breeding_frontier` | ✓ direct fit (pre-breed anchor) | ✓ direct fit |
| `food_payment_frontier` (food_owed > 0) | ✗ — no feasible anchor (player must pay something) | ◐ — once a config X fully pays food_owed, any config Y consuming ≥ on every dim is dominated. Useful but smaller win than for animal frontiers. |
| `harvest_feed_frontier` | ✗ — the do-nothing config is the *worst* on the −begging dim, so it dominates nothing | ✗ — same reason |

**Correctness caveat.** Both forms are valid iff the Pareto dimensions are exactly the upstream-goods counts (animals for `pareto_frontier` / `breeding_frontier`; the 5-tuple remaining-goods vector for `food_payment_frontier`). This holds today per the "Preserving optionality" Key Design Principle. If a future card makes some non-food byproduct into a strategic resource that *should* be a Pareto dim, the invariant must be re-examined.

### S8. Direct-enumeration rewrite of `food_payment_frontier`

> **LANDED (2026-06)**, behind `PARETO_OPT_LEVEL >= 1` (default off). This is the rate-descending
> rewrite specified in `FRONTIER_OPT_DESIGN.md` §5.1, proven sound + complete in its Appendix A.
> Microbench ~53× per call. The sketch below is the original proposal, kept for rationale.

**Target.** `food_payment_frontier` currently enumerates the full 5-D box `[0, grain_cap] × [0, veg_cap] × [0, sheep_cap] × [0, boar_cap] × [0, cattle_cap]` of consumption tuples, filters survivors by `food_produced ≥ food_owed`, then runs an O(n²) Pareto dominance pass on what's left. For typical mid-game inputs the box is small. For late-game inputs (food_owed = 15+, larger supplies, full cooking rates) the box grows polynomially and dominates the helper's wall-clock cost.

`harvest_feed_frontier` wraps `food_payment_frontier` — it calls it once per `paid ∈ [0, food_owed]`. Any speedup to the inner helper transfers proportionally to the outer with zero changes.

**The structural insight.** Sort the goods by conversion rate descending (highest-rate good first; rate-0 goods excluded). Recursive enumeration with a tight per-level upper bound emits exactly the Pareto frontier — no post-hoc dominance pass needed. At level i, the loop runs `x ∈ [0, min(supply_i, ⌈remaining / rate_i⌉)]` where `remaining = food_owed − Σⱼ<ᵢ xⱼ · rateⱼ`. Once `remaining ≤ 0` the algorithm emits immediately (deeper goods stay at zero) and returns without recursing further.

The rate-descending ordering is **correctness-critical, not just an efficiency choice.** With low-rate-first ordering the algorithm over-emits dominated configurations. Concrete counterexample: rates=(1, 3), food_owed=4, supplies=(10, 10):

```
x₁=0: remaining=4; x₂ ∈ [0, ⌈4/3⌉=2]; emit (0, 2) at x₂=2
x₁=1: remaining=3; x₂ ∈ [0, 1];        emit (1, 1) at x₂=1
x₁=2: remaining=2; x₂ ∈ [0, 1];        emit (2, 1) at x₂=1   ← dominated by (1,1)
x₁=3: remaining=1; x₂ ∈ [0, 1];        emit (3, 1) at x₂=1   ← dominated by (1,1)
x₁=4: remaining=0; x₂ ∈ [0, 0];        emit (4, 0) at x₂=0
```

Remainings (cap−consumed): (10, 8), (9, 9), (8, 9), (7, 9), (6, 10). Both (8, 9) and (7, 9) are strictly dominated by (9, 9). Swap to rates=(3, 1) (high first):

```
x₁=0: remaining=4; x₂ ∈ [0, 4]; emit (0, 4)
x₁=1: remaining=1; x₂ ∈ [0, 1]; emit (1, 1)
x₁=2: remaining=-2; early-emit (2, 0)
```

Remainings: (10, 6), (9, 9), (8, 10). All pairwise Pareto-incomparable.

**Why the ordering works (sketch).** With rate descending, incrementing the level-i loop variable by 1 displaces `rate_i` food. Since `rate_i ≥ rate_j` for any inner level j, no inner level can fully compensate by reducing its own consumption by 1 — each inner unit reduction recovers at most `rate_j ≤ rate_i` food. So the emit at x=k+1 trades off against the emit at x=k along the level-i dim (more level-i consumed, less inner consumed) rather than being dominated by it. Case-checked across 2- and 3-good examples with diverse rate ratios; a real proof would tighten "trades off against, not dominated by" into the formal Pareto-incomparable statement and induct over goods.

**Implementation sketch.** A standalone recursive enumerator replaces the existing 5-deep loop:

```python
def food_payment_frontier(player_state, food_owed, rates):
    sR, bR, cR, vR = rates
    grain_max  = player_state.resources.grain
    veg_max    = player_state.resources.veg
    sheep_max  = player_state.animals.sheep
    boar_max   = player_state.animals.boar
    cattle_max = player_state.animals.cattle

    if food_owed == 0:
        return [(grain_max, veg_max, sheep_max, boar_max, cattle_max)]

    # (rate, supply, canonical-dim-index) — canonical dim order is
    # (grain=0, veg=1, sheep=2, boar=3, cattle=4) for the rem-tuple emit.
    goods = [
        (sR, sheep_max,  2),
        (bR, boar_max,   3),
        (cR, cattle_max, 4),
        (vR, veg_max,    1),
        (1,  grain_max,  0),   # grain rate is always 1
    ]
    goods = sorted([g for g in goods if g[0] > 0], key=lambda g: -g[0])

    canonical_max = (grain_max, veg_max, sheep_max, boar_max, cattle_max)
    consumed = [0, 0, 0, 0, 0]
    frontier = []

    def recurse(level, remaining):
        if remaining <= 0:
            frontier.append(tuple(canonical_max[d] - consumed[d] for d in range(5)))
            return
        if level == len(goods):
            return  # remaining > 0 but no more goods → can't fully pay → not emitted
        rate, supply, dim = goods[level]
        upper = min(supply, -(-remaining // rate))  # ceil(remaining / rate)
        for x in range(upper + 1):
            consumed[dim] = x
            recurse(level + 1, remaining - x * rate)
        consumed[dim] = 0   # reset so siblings & parent unwind see 0

    recurse(0, food_owed)
    return frontier
```

Notes:
- `-(-remaining // rate)` is integer ceiling division — faster than `math.ceil(remaining / rate)`.
- The shared mutable `consumed` array with explicit reset after each for-loop is a small perf nit over passing a partial tuple down the recursion. The reset is what keeps deeper dims at 0 when an outer level triggers the early emit.
- Rate-0 goods (animals when the player has no cooking improvement) are excluded from the loop and stay at full supply in the emit — they could never reduce begging anyway.
- The food_owed == 0 short-circuit is preserved.

**What goes away.**
1. The full 5-D box enumeration (replaced by tight recursion: ~|frontier| leaves instead of `∏ caps`).
2. The `food_produced ≥ food_owed` filter inside the inner loop (implicit via the `remaining ≤ 0` emit gate).
3. The O(n²) post-hoc Pareto dominance pass (every emit is on the frontier by construction).

**Estimated speedup.** Per call: **plausibly 10–50×** on typical inputs; more on late-game inputs where the 5-D box gets large. `harvest_feed_frontier` rides on this proportionally — its `paid ∈ [0, food_owed]` outer loop is unchanged but each iteration is correspondingly faster. Wall-clock impact depends on how often these helpers fire in the target workload. From the existing PROFILING.md baseline they aren't in the top 5 self-time slots on random play, but the surface grows in MCTS workloads (every harvest expansion calls them) and in late-game states.

**Caveat: does not apply directly to `harvest_feed_frontier`.** Begging is allowed there, so under-paying configurations (food_produced < food_owed, begging = food_owed − food_produced) are also frontier candidates. The rate-descending tight-bound trick skips exactly those configs (it emits only when remaining ≤ 0). Two paths:

1. *(Recommended.)* Keep the existing wrapper that iterates `food_payment_frontier(paid)` over `paid ∈ [0, food_owed]`. Gets the speedup for free with zero code change to the wrapper. The natural-fit filter and outer Pareto pass stay as-is.
2. Write a direct-enumeration variant that emits under-paying configs too. Possible but the Pareto structure across the begging dim is messier — the elegant "every emit is on the frontier" property doesn't transfer cleanly because under-payment configs change shape on the −begging dim.

Start with (1). Only consider (2) if profiling shows the outer wrapper itself is hot after (1) lands.

**Test discipline.** This change replaces the implementation while preserving the contract (input projection, output set). Land a property-test scaffold during development that runs both the old and new implementations on randomized `(player_state, food_owed, rates)` inputs and asserts equality of the output sets (treating each as a set of tuples, since the emit order may differ). Run it through hundreds of seeds before the swap. Drop the side-by-side and remove the old implementation once the new one is verified. The existing unit tests for `food_payment_frontier` and the downstream `harvest_feed_frontier` tests should continue to pass without modification.

**Difficulty.** Medium. The core algorithm is short, but two pieces need care:
1. The rate-descending correctness argument — should be tightened to a real proof, not just case analysis, before landing.
2. The dim-index bookkeeping in the recursion — getting the goods list and the canonical-dim mapping right under the sort needs a small test exercising at least one input where rates are non-monotonic in canonical-dim order (typical, since animal rates depend on cooking improvements while veg is fixed at vR).

Risk surface is otherwise small: pure function, projection-keyed, output type unchanged.

**When to do it.** Standalone — no dependencies. Complements any caching work (caching reduces miss count; this reduces miss cost). Land before adding LRU caches over the frontier helpers, so the cache is over the fast implementation rather than the slow one.

---

## Legality enumeration

### S3. `legal_placements` short-circuit by availability

**Target.** `legal_placements` iterates all 24 placement predicates per call. Each per-space predicate begins with `_is_available(state, space)` — but Python still pays the function-call overhead (~250-500 ns) for entering and exiting the predicate body just to get a fast "no" via `_is_available`.

`_is_available` runs 216,216 times in Workload C for 48 ms — 24 predicates × 9,009 listcomps. In a typical mid-game state, 8-10 of 24 spaces are occupied by workers; their predicates run, return False at the `_is_available` check, and exit. The function-call overhead for those is wasted.

**Implementation sketch.** Pre-filter by availability at the outer dispatch level:

```python
def legal_placements(state):
    result = []
    for sid in SPACE_IDS:
        if not _is_available(state, sid):
            continue
        if _PLACEMENT_PREDICATES[sid](state):
            result.append(PlaceWorker(space=sid))
    return result
```

The per-space predicates then drop their internal `_is_available` call (it becomes redundant) and become pure can-the-player-actually-do-this checks. This is a coupled change: the predicate body refactor must land at the same time as the outer dispatch refactor.

**Estimated speedup.** Modest. Per-call savings from avoiding 8-10 function-call entries per `legal_placements`: ~2-4 us per call. Across Workload-B's ~5,000 `legal_placements` calls, that's ~10-20 ms saved. Wall-clock: **~2-4% on random-play workloads** — comfortably above noise floor but not transformative.

The uncertainty is around "how much of the predicate body actually runs after the `_is_available` short-circuit" — for predicates that do real work (`_legal_fencing` walks the fence universe; `_legal_major_improvement` enumerates affordability), the avoided cost is much higher than 250 ns. For simple predicates (`_legal_day_laborer`), the avoided cost is just the function-call overhead. I haven't profiled per-predicate body cost.

**Difficulty.** Low-medium. The dispatch rewrite is ~10 lines. The predicate-body refactor (removing redundant `_is_available` calls) is mechanical but touches ~24 functions. Risk: easy to forget to remove the inner `_is_available` from one predicate, leaving it correct but doing redundant work — a regression test that asserts a known-impossible space stays out of `legal_placements` would catch this.

**When to do it.** After S1/S2 if Pareto stops dominating. Or before, if you want a quick easy win — it doesn't depend on anything.

### S7. Project-keyed cache on the fence-universe legality scan

> **LANDED (2026-06)**, behind `FENCE_SCAN_CACHE` (default off). Implemented as
> `legality._legal_pasture_commits_cached` (+ `_legal_pasture_commits_compute`); see
> `FRONTIER_OPT_DESIGN.md` §7. Measured ~94% projection hit rate, and per the MCTS cProfile it is
> the **dominant** contributor to the ~9% MCTS wall-clock win (PROFILING.md). The sketch below is
> the original proposal.

**Target.** `_any_legal_pasture_commit` (placement-time predicate for `_legal_fencing`) and `_enumerate_pending_build_fences` (mid-chain enumerator during a Build Fences action). Both walk the active fence universe — ~109 entries under RESTRICTED, all 1518 under FULL — and apply `_check_entry_legal` per entry (bit-ops over enclosable / pasture / fence / adjacency bitmaps, plus a subdivision-canonicalization step). Per call: estimated ~30–100 μs in late game, scaling with universe size and the number of existing pastures. Fired on every `legal_placements(state)` call where fencing is still available (the placement predicate), and on every `legal_actions(state)` call mid-chain (the enumerator). In MCTS-heavy workloads this is plausibly one of the two or three largest single-call costs inside `legal_actions`.

**Why this is a cache candidate.** The scan reads a small, well-defined projection of state:

| Field | Source | Changed by |
|---|---|---|
| `enclosable_bm` (cell types) | `farmyard.grid` | plow, build-rooms |
| `pasture_bms` (cell-sets only — not `num_stables`) | `farmyard.pastures` | build-fences (creates / subdivides pastures) |
| `h_fences_bm` / `v_fences_bm`, `fences_left` | `farmyard.horizontal_fences` / `vertical_fences` | build-fences |
| `wood` | `p.resources.wood` | any wood gain or spend |
| `subdivision_started` | `PendingBuildFences` (False at placement-time) | build-fences (monotonic False → True) |
| Active universe | `ACTIVE_FENCE_UNIVERSE_*` module constants | effectively immutable in production |

Nothing else is read. Animals, crops, food, non-wood resources, house material, the other player's entire state, board state, phase, current player — all invisible. In MCTS, every path that reaches the same player's fencing decision via a different ordering of irrelevant actions hits the same projection.

Notable consequence: **stable builds don't invalidate the cache.** STABLE cells are still enclosable, and `pasture_bms` reads `.cells` (not `.num_stables`), so a stable build inside an existing pasture leaves the projection untouched. Stable builds invalidate only via the wood-change axis (they spend wood), not via the build itself.

**Implementation sketch.** Refactor the two call sites to share a single LRU-cached helper that returns the full result of the universe scan; the placement predicate gets its bool answer via length check:

```python
@functools.lru_cache(maxsize=50_000)
def _legal_pasture_commits_cached(
    farmyard: Farmyard, wood: int, subdivision_started: bool,
) -> tuple[tuple[PastureCandidate, int, int], ...]:
    """Return tuple of (entry, h_new_bm, v_new_bm) for every legal pasture
    commit under the active universe at this projection.

    Pure function of (farmyard, wood, subdivision_started). Both fencing call
    sites consume this — `_any_legal_pasture_commit` via length check,
    `_enumerate_pending_build_fences` via per-entry action construction.
    """
    enclosable_bm = _enclosable_cells_bm(farmyard)
    pasture_bms = tuple(_cells_bm_of_pasture(P) for P in farmyard.pastures)
    existing_pasture_cells_bm = 0
    for P_bm in pasture_bms:
        existing_pasture_cells_bm |= P_bm
    h_fences_bm = pack_fences_h(farmyard.horizontal_fences)
    v_fences_bm = pack_fences_v(farmyard.vertical_fences)
    fences_left = fences_in_supply(farmyard)
    has_existing_pastures = bool(pasture_bms)

    common = dict(
        enclosable_bm=enclosable_bm,
        pasture_bms=pasture_bms,
        existing_pasture_cells_bm=existing_pasture_cells_bm,
        has_existing_pastures=has_existing_pastures,
        subdivision_started=subdivision_started,
        h_fences_bm=h_fences_bm, v_fences_bm=v_fences_bm,
        wood=wood, fences_left=fences_left,
        universe_set=ACTIVE_FENCE_UNIVERSE_SET,
    )

    out = []
    for entry in ACTIVE_FENCE_UNIVERSE_ENTRIES:
        ok, h_new, v_new = _check_entry_legal(entry, **common)
        if ok:
            out.append((entry, h_new, v_new))
    return tuple(out)


def _any_legal_pasture_commit(state, p):
    return bool(_legal_pasture_commits_cached(p.farmyard, p.resources.wood, False))


def _enumerate_pending_build_fences(state, pending):
    p = state.players[pending.player_idx]
    legal = _legal_pasture_commits_cached(
        p.farmyard, p.resources.wood, pending.subdivision_started,
    )
    return [CommitBuildPasture(cells_bm=e.cells_bm, h_new=h, v_new=v)
            for (e, h, v) in legal]
```

Design choices baked into the sketch:

- **Cache key.** `(Farmyard, int, bool)` — `Farmyard` is already a frozen hashable dataclass; no projection-extraction step at the call site. Two players' fencing queries occupy independent cache entries because each player owns their own `Farmyard` object.
- **Cache value.** Tuple of `(entry, h_new_bm, v_new_bm)` triples, not the final `CommitBuildPasture` list. The h_new / v_new bitmaps are needed by the eventual fence-build commit, so caching them avoids recomputation downstream. The per-call action construction (~100 ns × ~10–50 entries) is cheap enough that storing pre-built action lists is not worth the loss in cache-value abstractness. Tuples (not lists) so the cached value is immutable and safe to share by reference across all callers.
- **No more two-pass iteration.** `_any_legal_pasture_commit`'s precomputed-1×1 fast-path is a short-circuit optimization for the *uncached* bool query (avoid scanning the full universe just to learn "yes, at least one is legal"). With caching, the full scan amortizes over many bool queries, and the fast-path becomes dead code. Remove it in the same patch — keeping it would force the cached helper to also short-circuit, which defeats the cache.
- **No explicit invalidation.** The projection-keyed LRU naturally returns a different entry whenever any input changes. The actions that *do* shift the key are the four invalidators already enumerated: plow, build-rooms, build-fences, any wood change. Everything else (renovate, all non-wood resource changes, animals/crops/food, the other player's turn, stage card reveals, harvest sub-phases) hits the cache.
- **Active-universe caveat.** `ACTIVE_FENCE_UNIVERSE_*` is read inside the function but not part of the key. In production it's set to RESTRICTED at startup and never changes. If `active_universe(...)` is used experimentally, the cache must be cleared on context entry and exit — hook `_legal_pasture_commits_cached.cache_clear()` into the context manager's `__enter__` / `__exit__`. This is one line; including universe identity in the key would also work but is more invasive.

**Test discipline.** `lru_cache` shares state across pytest runs in the same process. Two options:

1. *(Recommended.)* Autouse `conftest.py` fixture calls `_legal_pasture_commits_cached.cache_clear()` between tests. One line. Pure functions of frozen inputs shouldn't cause cross-test pollution in principle, but the fixture is a cheap safety net.
2. Opt-in context manager (matching the existing `legal_actions_cache()` pattern). More invasive — every consumer must wrap calls in a `with` block — but eliminates cache state outside searches. Defer to option 2 only if profiling shows lru_cache lookup overhead is non-trivial on random-play workloads.

**Estimated speedup.** Per cache hit: ~200 ns (tuple hash + dict lookup) vs ~30–100 μs to rescan. **~150–500× per hit on the function call itself.**

Aggregate wall-clock impact depends on hit rate, which is hard to predict pre-measurement. Lower bound: random-play workloads benefit little — there are no transposition-like recurrences to hit. MCTS workloads should benefit substantially: every legal_placements call where fencing is available currently triggers a fresh scan, and most are at the same farm + wood projection as their siblings in the search tree.

Educated guess: **~5–15% wall-clock improvement on MCTS workloads**, weighted toward late game (where the fencing predicate is more often live) and toward higher MCTS budgets (more sims → more hits per unique projection). Random-play workloads probably <1%.

**Difficulty.** Low–medium. The cached helper's body is mostly a refactor of `_any_legal_pasture_commit`'s loop, swapping short-circuit-on-first-legal for collect-all. Two call sites to rewire. One conftest fixture. The risk surface is small — `_check_entry_legal` is already a pure function of explicit arguments, so the refactor doesn't change semantics. The one non-trivial decision is whether to plumb `subdivision_started` correctly into the enumerator's call (it lives on `PendingBuildFences`; a single test exercising a mid-chain subdivision-rejection path is enough to catch a mistake here).

**When to do it.** Standalone — no dependencies on other items in this doc. Independent of S1/S2 (Pareto helpers); landing both in sequence is fine. Probably the highest-ROI non-Pareto item for MCTS workloads. Profile `_enumerate_pending_build_fences` and `_any_legal_pasture_commit` self-time before and after to confirm the predicted gain.

---

## State construction

### S4. Form C — per-shape replacers for the hottest update shapes

**Target.** `fast_replace` (Change 9) saved ~20% per call versus stdlib `dataclasses.replace`. Form C goes further by hand-writing dedicated replacers for the highest-frequency update *shapes*, skipping all runtime introspection.

The hottest shapes from `scripts/count_replaces.py` on Workload B (after the round-end-reset guard):

| Count | % | Shape |
|---:|---:|---|
| 1,851 | 17.4% | `GameState.{pending_stack}` (already specialized via `replace_top` in `pending.py`) |
| 1,406 | 13.2% | `GameState.{players}` |
| 1,006 | 9.5% | `ActionSpaceState.{workers}` |
| 901 | 8.5% | `GameState.{board}` |
| 736 | 6.9% | `PlayerState.{people_home}` |
| 655 | 6.2% | `ActionSpaceState.{accumulated}` |
| 603 | 5.7% | `ActionSpaceState.{accumulated_amount}` |

Top 5 single-field shapes cover ~55% of all replace calls; top 10 cover ~75%.

**Implementation sketch.** In `agricola/replace.py`, alongside `fast_replace`:

```python
def replace_player_people_home(p: PlayerState, new_home: int) -> PlayerState:
    return PlayerState(
        resources=p.resources,
        animals=p.animals,
        farmyard=p.farmyard,
        house_material=p.house_material,
        people_total=p.people_total,
        people_home=new_home,
        newborns=p.newborns,
        begging_markers=p.begging_markers,
        future_resources=p.future_resources,
        minor_improvements=p.minor_improvements,
        occupations=p.occupations,
        harvest_conversions_used=p.harvest_conversions_used,
    )

def replace_space_workers(sp: ActionSpaceState, new_workers: tuple) -> ActionSpaceState:
    return ActionSpaceState(
        workers=new_workers,
        accumulated=sp.accumulated,
        accumulated_amount=sp.accumulated_amount,
        round_revealed=sp.round_revealed,
    )

# ... and so on for the top 5-10 shapes
```

Call sites migrate from `fast_replace(p, people_home=new_home)` to `replace_player_people_home(p, new_home)`.

**Estimated speedup.** Microbenchmark from a typical Form C helper vs `fast_replace`: ~5-10× faster on the targeted shape — no `_FIELDS_CACHE` lookup, no per-field `dict.get`, no generator expression, no `**kwargs` unpacking. So each targeted call drops from ~1-2 us to ~0.2-0.3 us.

Aggregate wall-clock impact depends on call mix. If we hand-write helpers for the top 5 shapes (~55% of calls), savings are ~5 ms across Workload B's 240 ms wall-clock — **~2% on top of Change 9's R3 gains**.

**The cost-benefit ratio of Form C is meaningfully worse than Form A.** Form A was drop-in (one new function, ~89 mechanical call-site edits). Form C requires:
- Hand-writing 5-10 helpers, each touching every field of its dataclass.
- Updating each call site to use the right helper.
- A regression test per helper that compares output against `fast_replace` (otherwise a future field addition silently misses the helper).
- Updating every helper whenever a dataclass gains a field.

**Difficulty.** Medium. Per-helper code is mechanical but the maintenance burden compounds.

**When to do it.** Only if `fast_replace` + its inner generator still appears in the top 3 self-time slots after S1/S2/S3 land. Wait for evidence; do not pre-optimize.

### S5. Cached `__hash__` on hot dataclasses

**Target.** Future MCTS transposition table — `dict[GameState, TreeNode]` content-keyed. Currently `hash(GameState)` measures ~26 us because it recursively hashes thousands of nested fields. A transposition table that pays 26 us per lookup is affordable but not cheap; if MCTS does ~500 transposition lookups per search, that's ~13 ms of pure hashing per search.

**Implementation sketch.** Override `__hash__` on `GameState` (and possibly `BoardState`, `PlayerState`, `Farmyard`) to compute and cache the hash on first access. The challenge: frozen dataclasses can't directly store a cached value, since they reject `__setattr__`. The standard escape hatch is `object.__setattr__`:

```python
# In GameState's __post_init__ (or a custom __hash__):
def __hash__(self):
    h = getattr(self, "_cached_hash", None)
    if h is None:
        h = hash((self.round_number, self.phase, self.current_player, ...))
        object.__setattr__(self, "_cached_hash", h)
    return h
```

The `_cached_hash` attribute must be excluded from `__eq__` and from `__dataclass_fields__`. Easiest: store on `__dict__` directly via `object.__setattr__` and never declare it as a dataclass field at all.

**Estimated speedup.** First access still pays the full 26 us. All subsequent accesses on the same `GameState` object are ~10 ns (read a cached int). For transposition lookups, this matters if the same state is hashed more than once (e.g., the lookup hashes it, then the dict's internal storage hashes it again — though CPython is smart enough to cache that).

**Concrete win:** in a 10k-rollout MCTS search with ~500 unique states discovered, the cache pays the ~26 us once per unique state and then nothing on revisit. Net savings: hard to predict without simulating MCTS workload, but plausibly **~5-15 ms per search**.

This is a transposition-table-enabler, not a within-search optimization (that's R1's job, already done). **It's only worth landing when MCTS implements a content-keyed transposition layer.** Until then, `__hash__` is rarely called.

**Difficulty.** Medium. The `object.__setattr__` trick is well-documented but feels hacky. Care needed to keep `__eq__` correct — the cached hash must not participate in equality (two states with stale caches but equal content should still compare equal). Tests must exercise both first-hash and cached-hash paths.

**When to do it.** When MCTS adds a transposition table and profiling shows `__hash__` in the top 5 self-time slots. Until then, defer.

### S6. Zobrist-style incremental hashing

**Target.** Same as S5, but for the case where even cached `__hash__` is too slow (because we're hashing many distinct new states per second).

**Concept.** Instead of recomputing `hash(new_state) = recursively_hash_everything()`, compute it as `hash(new_state) = hash(old_state) XOR delta(action)`. Each engine action (PlaceWorker, sub-action commit, phase transition) updates the hash incrementally with a precomputed XOR mask.

**Estimated speedup.** Per-hash cost drops from ~26 us → ~10 ns. For workloads dominated by hashing (transposition tables, content-keyed legal-actions caches), this is a 2000× speedup on the hash operation.

**Difficulty.** High. Requires:
- A precomputed random Zobrist table per (field, value) combination — large for `GameState` (thousands of distinct fields × value ranges).
- Engine instrumentation: every `step()` and every sub-action `_execute_*` updates the running hash. Touches every state-mutating site.
- Validation: an "audit" mode that compares the running Zobrist hash against `hash(state)` per step, to catch hash-drift bugs.

The complexity is significant. The CHANGES.md design principle "derived data, not cached data" pushes against this strongly — every state-mutation site becomes responsible for keeping the hash consistent, which is exactly the failure mode that principle was written to prevent.

**When to do it.** Only if S5 lands and `__hash__` is *still* the dominant cost. Probably never for this game — Agricola's state isn't large enough for Zobrist to be necessary at realistic MCTS budgets. Listed for completeness.

---

## Pasture decomposition

### S9. Incremental / memoized `compute_pastures_from_arrays`

**Target.** `agricola/pasture.py:compute_pastures_from_arrays` — the flood-fill BFS that derives the pasture decomposition from the fence arrays. The **first MCTS cProfile** (PROFILING.md "MCTS profile", 2026-06-02) makes it the **#1 self-time function** in MCTS: ~4.8 s self over 222k calls in a 3-game / 120-sim profile, called ~1:1 from `resolution.py:_execute_build_pasture` (every fence-build commit re-runs the full BFS from scratch). Random-play profiling had it at a benign ~2 ms (Workload B, 82 calls) — MCTS exposes it because the search explores enormously many fence-build sequences.

Note this is **distinct from the S7 fence-scan cache**, which already landed: S7 caches the *legality enumeration* (which pasture commits are legal); S9 attacks the *state mutation* (recomputing the decomposition when a fence is actually committed). S7 does not touch this path.

**Implementation sketch.** Two independent options, cheapest first:

1. **Memoize on the fence arrays.** `compute_pastures_from_arrays(grid, h_fences, v_fences)` is a pure function of its three array args. An `lru_cache` keyed on them (they're already tuples of tuples — hashable) collapses the many MCTS paths that reach the same fence layout. The decomposition only depends on `grid` cell types (enclosable vs not) and the two fence arrays, so the key is exact. Hit rate should be high for the same reason S7's was (~94%): fence layouts recur heavily across rollouts. Lowest-effort; reuses the S7-style projection-cache pattern.

2. **Incremental update.** A fence-build commit adds a known set of edges to an existing decomposition. Only the pasture(s) touching those edges can change (split or merge); the rest are unaffected. Recomputing just the affected connected component(s) instead of the whole 3×5 grid avoids the full BFS. More code and more correctness surface (the merge/split logic), but no cache memory and no key-hashing cost.

**Estimated speedup.** `compute_pastures_from_arrays` is ~7% of MCTS self-time in the profile (4.8 s of ~62 s). Memoization (option 1) at a high hit rate could remove most of it → **~3–6% MCTS wall-clock**, comparable to the S7 fence-scan win. Incremental (option 2) could go further on the miss path but with more risk. **Profile-gated** like everything here — verify the hit rate first with a collision-style instrument (cf. `scripts/profile_frontier_helpers.py --mode collision`).

**Difficulty.** Option 1: low (one decorator + a hashable-key check; `pasture.py` is already a clean standalone module). Option 2: medium-high (component-level merge/split logic + tests).

**When to do it.** It's currently the top MCTS self-time entry, so it's the natural next item after the frontier-opt work — but **`evaluate_hubris_v3` (~half of MCTS cumulative) is the bigger lever**; do the leaf-evaluator work (or move to the NN evaluator) first unless the pasture BFS is easier to land. Sequence with the PROFILING.md "Next levers" list.

---

## How to use this doc

1. Re-profile after each landed optimization (`scripts/profile_engine.py --no-profile` for headline numbers; `--workload C` for per-state breakdown; cProfile for hot-path identification).
2. Pick the next item by what's currently the top 1-3 self-time costs in the profile.
3. Sceptical default: don't apply an optimization unless its estimated win is materially above the measurement-noise floor for the workload you care about.
4. Update this file's "Estimated speedup" entries with actual measured numbers as items land — replace guesses with data.

Optimizations not landed will fall out of relevance as the codebase evolves; treat older entries with skepticism if the surrounding code has shifted underneath them.
