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

## How to use this doc

1. Re-profile after each landed optimization (`scripts/profile_engine.py --no-profile` for headline numbers; `--workload C` for per-state breakdown; cProfile for hot-path identification).
2. Pick the next item by what's currently the top 1-3 self-time costs in the profile.
3. Sceptical default: don't apply an optimization unless its estimated win is materially above the measurement-noise floor for the workload you care about.
4. Update this file's "Estimated speedup" entries with actual measured numbers as items land — replace guesses with data.

Optimizations not landed will fall out of relevance as the codebase evolves; treat older entries with skepticism if the surrounding code has shifted underneath them.
