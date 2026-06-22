# Speedups

Performance work for the engine + agent, in two parts:

- **Part 1 — Implemented.** The optimizations actually in the code, with enough
  detail to understand *why* the complexity exists. This is the catalog a reader
  reaches for after hitting a cache or a specialized helper and asking "what is
  this, and why is it here?"
- **Part 2 — Potential next steps.** Sketched-but-not-landed ideas, each with an
  estimate, a difficulty, and a "when to do it" trigger. **Profile before
  applying** — none are commitments.

When a Potential item lands it moves up to Implemented (collapsed to the
essentials). Deep design records live in their own docs (`FRONTIER_OPT_DESIGN.md`,
`CHANGES.md`, `INCREMENTAL_PASTURE_DESIGN.md`); this file points to them rather
than duplicating. Stable identifiers `S1`–`Sn` are kept across the move so
cross-references elsewhere stay valid.

Numbers cite **`PROFILING.md`** — read its current *"Production MCTS-NN PUCT
profile"* first; it is the authoritative picture of where time goes in the code
today. Re-profile after any change.

> **Read the cProfile caveat in `PROFILING.md` before trusting any per-function
> `tottime`.** cProfile's per-call instrumentation overhead massively inflates
> high-call-count tiny functions (e.g. `_can_afford` measured 18 µs/call under
> cProfile vs **0.32 µs** in a clean micro-bench). Confirm with a micro-bench
> before optimizing anything that "looks hot" in cProfile.

---

## Part 1 — Implemented

### State construction & hashing

**`fast_replace`** (`agricola/replace.py`) — a faster drop-in for
`dataclasses.replace`: caches each class's init-field tuple and constructs
positionally, skipping stdlib's per-call introspection. ~2–3× per call; used at
every state-mutation site. Full rationale: `CHANGES.md` Change 9.

**S5 — Cached `__hash__` on the state dataclasses** (`agricola/state.py`).
The MCTS transposition table is a `dict[GameState, MCTSNode]`, so states are
hashed constantly — and a frozen dataclass's default `__hash__` re-hashes the
entire nested tree (`GameState → players → farmyard → grid → cells …`) every
call. In the production profile this was the **#1 self-time** (~1.97M `hash`
calls per slice, ~13% of the run). Fix: each hot dataclass (`GameState`,
`PlayerState`, `BoardState`, `Farmyard`, `ActionSpaceState`) memoizes its hash
lazily in `__dict__["_hash_cache"]` via `object.__setattr__` (no `__slots__`,
not a dataclass field → invisible to `__eq__`/`__repr__`).
- **Why it's safe:** the objects are immutable, so a cached hash can never go
  stale — there is *no* sync invariant (the risk the "derived data, not cached
  data" principle warns about does not apply to a pure function of an immutable).
- **The real win is the sub-objects.** Most transitions change one small field
  and `fast_replace` shares the rest of the tree *by reference*, so a new
  `GameState`'s hash reuses the cached hashes of every unchanged child — only the
  changed top-level fields are re-hashed.
- **Pickle gotcha:** `__getstate__` strips `_hash_cache`. Python's string/enum
  hashing is per-process seed-randomized, so a cached hash must never cross a
  process boundary (training loads pickles from data-gen workers); the loader
  recomputes a fresh, correct hash on first use.
- **Result:** hashing dropped from #1 self-time to negligible (~5× fewer calls).
  *(This is the S5 entry formerly in "Potential"; its trigger — "MCTS adds a
  content-keyed transposition table" — was met.)*

**`Farmyard.pastures` on-object cache** — the one accepted on-object cache with a
caller-discipline contract (pasture-changing resolvers recompute it; everything
else rides it along via `fast_replace`). `CHANGES.md` Change 3 /
`ENGINE_IMPLEMENTATION.md` §4.1.

**`__debug__` gate on `_assert_nonnegative_state`** — the per-`step` safety net is
compiled out under `python -O`. **Run data-gen with `-O`.** `CHANGES.md` Change 9.

**Round-end-reset guard** (`_resolve_return_home`) — skips redundant `fast_replace`
calls for action spaces that are already empty at round end. `CHANGES.md` Change 9.

### Legality enumeration

**`legal_actions_cache()`** (`agricola/legality.py`) — an opt-in identity-keyed
memoizer, dormant outside a `with` block. MCTS instead caches each node's legal
actions on the node (`MCTSNode._legal_actions`), computed once per unique state.

**S7 — Fence-universe scan cache** (`FENCE_SCAN_CACHE`, `agricola/opt_config.py`,
**default on**). Projection-keyed cache over the fence-universe legality scan
(`_legal_pasture_commits_cached`). ~94% hit rate; was the dominant contributor to
the ~9% MCTS win on the *old V3-leaf* workload. Design + proof:
`FRONTIER_OPT_DESIGN.md` §7.

### Frontier / accommodation

**S8 + the Pareto/accommodation fast paths** (`PARETO_OPT_LEVEL` 0–3,
`agricola/opt_config.py`, **default 3**). Rate-descending `food_payment_frontier`,
max-corner animal frontiers, and projection-keyed caches for the
Pareto/accommodation helpers. Set-identical to baseline (cross-level-tested).
Full design + correctness proofs: `FRONTIER_OPT_DESIGN.md`.
- **Note:** these helpers are *cold in production PUCT* — expensive per call but
  rarely called in NN-leaf search (they matter for animal/feeding-heavy contexts
  like heuristic data-gen). See `PROFILING.md`.

### NN inference (the dominant production cost)

Data-gen runs NN-value-leaf + multi-head-policy PUCT, where ~half the wall is NN
inference. The following are all **byte-identical** (golden-tested) unless noted.

**S10 — `stop_is_legal` empty-stack guard** (`agricola/agents/nn/encoder.py`).
The encoder needs one bit — "is `Stop` legal here?" — which it computed via a full
`legal_actions(state)`. At an empty stack that runs the expensive 24-predicate
`legal_placements`; but `Stop` *pops a pending frame*, so it is **never legal at
an empty stack**. Guard: empty stack → `False`; non-empty → the (cheap) top-frame
sub-action enumerator. ~19× on that computation (it was ~35% of `encode_state`),
byte-identical. Bench: `scripts/bench_stop_is_legal.py`.

**S11 — Index-writer `encode_state`** (`encoder.py`). The encoder built 170
`(name, value)` tuples + `own_`/`opp_` prefixing + a dict (mid-action) + an
`np.fromiter` generator. Rewrote the hot path to write floats straight into a
preallocated `np.empty(170)` by index. The original `(name, value)` `_assemble`
is **kept** as the `feature_names()` source and the **golden-test oracle** — a
test asserts `encode_state == _assemble` over a state corpus, so the fast path
can't drift. ~1.3–1.4× faster (≈22–30%), byte-identical (the fast path is a stable
~50 µs; the reference times 63–73 µs depending on machine load).

**S12 — Swap-aware encode memo** (`encode_for_inference` / `swap_perspective` /
`_encode_p0`, `encoder.py`). In MCTS each node is encoded for the value leaf
(always perspective 0) and, if later expanded, for the policy prior (perspective
= decider). `encode_for_inference` memoizes the perspective-0 encoding (an
`lru_cache` keyed on the now-cheaply-hashable `GameState`, see S5) and derives
perspective 1 by a **block-swap + one bit-flip** instead of re-encoding: the
vector is laid out `own(54) | opp(54) | shared(54) | mid(8)`, and
`encode(s,1) == swap(encode(s,0))` exactly — swap the two player blocks and flip
the lone `current_player_is_own` bit (golden-tested; terminal states need no
flip). This folds the value/policy double-encode at decider-0 nodes and makes the
*differential* leaf's second encode ~free if it is ever re-enabled. ~34% of
inference encodes avoided. (`encode_state` itself — the training-data path — is
untouched.)

**S13 — `model_device` cache** (`agricola/agents/nn/model.py`).
`next(model.parameters()).device` walked the whole module tree (`named_modules` /
`_named_members`) on *every* forward just to read a constant (CPU). Now memoized
on the model. ~2.7 µs/call removed; small (~2% of wall) but free.

**Inference `eval()` at policy assembly** (`make_policy_fn`, `agents/nn/policy.py`)
— *correctness + perf.* Head models load in **TRAIN** mode, so dropout fired on
every prior query → PUCT priors were **nondeterministic** (same state → priors
differing ~0.05 per call). `make_policy_fn` now `eval()`s the models at assembly,
making priors deterministic (and a touch faster: eval-mode dropout is a no-op).
*(The value-net leaf is eval'd by its caller — `play_mcts_match` / `NNAgent`.)*

### C++ self-play engine (native MCTS)

The C++ inner loop (engine + MCTS + hand-rolled MLP inference) has its own
optimization history — the authoritative record is **`CPP_ENGINE_PLAN.md`**
("Optimization pass #1/#2/#3"), not duplicated here. The headline of the latest
pass (joint shared-trunk, 800 sims) is **~3.35× over the prior C++ binary** from
four gated changes: **NEON-vectorized linear dot product** (the big one — 2.54×
alone; scalar float reductions serialized the FMA dependency chain *and* weren't
vectorized), a **per-node trunk-embedding cache** on `MCTSNode` (+1.27×; the
joint trunk forward ran twice per node — value then policy — where Python's
`make_joint_fns` already shared one forward via an LRU), plus two small cleanups
(**field-wise pending-frame hashing** replacing a per-frame JSON round-trip in
`state_hash`, and **`thread_local` scratch buffers** in `Mlp::forward`). All gated
green against `tests/test_cpp_*.py` (≤1e-4 NN; the embedding cache is exact). The
C++ MLP forward is plain C++ — the equivalent of "batch the NN" in PyTorch buys
far less here because the per-call framework overhead PyTorch batching amortizes
doesn't exist (see `CPP_ENGINE_PLAN.md` §0.2 / pass #2). Next lever: a
vectorized/polynomial `erf` for GELU (~7%, deferred).

### MCTS search structure

Architectural choices that exist partly for speed (full detail in
`MCTS_IMPLEMENTATION.md`): the **DAG + transposition table** (different action
orders to the same state share statistics), the **per-node legal-action cache**,
**macro-fencing** (collapse a fence layout to one node — UCT), and the
**strict/regular restricted-legality wrappers** (`agents/restricted.py`) which
shrink branching by dropping dominated actions before search sees them.

### Data-gen / trace replay

**S14 — π-presence singleton signal in trace replay**
(`agricola/agents/nn/trace_replay.py`). C++ self-play data-gen is two phases:
phase 1 (native C++) writes a trace; phase 2 (Python `replay_trace`) re-runs the
action list through the engine to rebuild `GameRecord`s. Replay called
`legal_actions` at every step *only* to decide which states are non-singleton
decisions worth snapshotting — never to validate the trace (`step` applies the
recorded actions unconditionally). On animal-heavy late-game farms that re-runs
the `_build_phi` / `PARETO_OPT_LEVEL` Φ build (S8), which is **pathological under
replay's one-touch-per-state access**: the Φ build is a fixed per-farm-shape cost
that amortizes over the many cap-queries MCTS makes on a shape, but replay visits
each state once, so the build never pays back (and is super-linear in farm size →
a multi-second spike on big farms). MCTS self-play traces already carry the
signal — the search records a `visit_distribution` **only** on non-singleton
decisions — so "entry has π" is exactly the singleton test
`len(filter_implemented(legal_actions(state))) > 1` (verified set-identical →
byte-identical `GameRecord`s). Replay uses that instead, skipping `legal_actions`
entirely; value-only traces (no π recorded anywhere) fall back to `legal_actions`.
**Worst-case game 24,119 ms → 5 ms** (a 30k-game phase-2 replay finished in
~3 min), restoring the design's "~10 ms/game" replay assumption
(`CPP_ENGINE_PLAN.md` §1/§2). Note this is *not* in tension with S8's "Φ is cold
in production PUCT": replay is a different workload where the Φ path is hot, and
the fix removes the call rather than the cache.

---

## Part 2 — Potential next steps

Best-first within each area. Re-profile before acting.

### NN forward passes

**Leaf-batching + virtual loss — the high-ceiling NN lever.** Batch-1 forwards
are dispatch-bound, so per-sim NN cost can't be amortized today. Collect *K*
leaves per descent (virtual loss to diversify selection), run **one batched
forward** over all K, then backprop all. Amortizes dispatch (modest on CPU, large
on GPU). For data-gen at scale the production form is a **batched inference server**
across parallel worker games. **Difficulty:** medium-high (a real `_simulate`
change; slightly alters search via virtual loss). **This is the recommended next
NN lever** — it subsumes most of what jit.trace would buy.

**jit.trace + freeze — MEASURED ~6%, NO-GO for now.** Prototyped
(`scripts/proto_jit_trace.py`): swapping each model's inner `net` for a
`jit.trace`+`freeze` graph is **numerically exact** (max|Δ|=0 over a state corpus)
and ~1.9× on the *raw* forward (47→25 µs), but only **~6–10% end-to-end** (the
forward is one part of each call; the range is machine-load-dependent). Integration
is non-trivial: the traced object is a `ScriptModule`, not a `NormalizedValueModel`,
so `predict_margin`/`policy_probs` + the 9 heads + checkpoint plumbing + the
`freeze`-empties-`parameters` wrinkle all need handling. Not worth ~6–10% — and
leaf-batching attacks the same dispatch cost more fundamentally. Recorded so it
isn't re-discovered.

**Encoding-keyed NN-output cache — MEASURED ~0.9% extra, NO-GO.** The encoding is
lossy (aggregated counts, no spatial info), so the hypothesis was that many distinct
`GameState`s collide to one encoding → caching NN *outputs* by encoding-bytes would
skip forwards the `GameState`-keyed memo can't. Measured
(`scripts/bench_encoding_collisions.py`): only **1.1% of encodings** are shared by
>1 distinct `GameState` → **~0.9% of forwards** beyond what the swap-memo (S12) + DAG
already dedup. Not worth it — and you must encode to get the key, so it never saves
the *encode*, only the forward. Recorded so it isn't re-discovered.

**Shared value+policy trunk** — a single forward producing both value and policy.
A model/training change (out of scope for pure perf work), but the largest
structural NN win long-term.

### Engine / search

**The engine remainder is diffuse.** After S5, no single function is a real
hotspot — the remainder is interpreter overhead spread across the per-sim tree
descent (dict lookups, attribute access, small calls, dataclass construction). No
clean lever without a structural change (fewer allocations per `step`, or a
compiled core) — high-effort / low-ROI. See `PROFILING.md`.

**S4 — Per-shape `fast_replace` helpers.** Hand-written single-shape replacers for
the hottest update patterns, skipping all runtime introspection. `fast_replace`
is the largest *single* engine piece (real object-allocation work), but it's a
diffuse few-% and the helpers are maintenance-heavy (every dataclass field change
must update them). Only if `fast_replace` still dominates after bigger wins land.

**`_can_afford` direct-field access** (`legality.py`) — replace the
`getattr`-over-7-fields idiom with direct attribute access: 2.8× on that function,
byte-identical. But it's **~0.4% of wall** (the cProfile overstated it — see the
caveat at top), so low value on its own.

### Pasture decomposition

**S9 — Incremental / memoized flood-fill** (`compute_pastures_from_arrays`).
**NOT relevant to production PUCT** — absent from the production profile's top
200. The old "#1 self-time" diagnosis was **V3-leaf + MACRO fencing**, which did
greedy value-net rollouts exploring huge numbers of fence sequences; FLATTEN PUCT
barely builds fences. The detailed design (the new-vs-subdivision branch, the
byte-identical-output constraint) is preserved in `INCREMENTAL_PASTURE_DESIGN.md`
for that context — don't pursue for NN-leaf PUCT.

### Hashing

**S6 — Zobrist incremental hashing.** Heavy (every state-mutation site maintains a
running hash — exactly the footgun the "derived data" principle warns against).
S5 already removed hashing as a hotspot, so **probably never** for this game's
scale. Listed for completeness.

### Pareto helpers (cold in PUCT)

**S1 / S2 — anchor / geometric Pareto pruning.** Superseded by the max-corner
fast path (S8), and the helpers are cold in PUCT anyway. Skip unless a future
animal/feeding-heavy workload re-surfaces them.

### Rejected

**S3 / R5 — `legal_placements` availability pre-filter.** Rejected (2026-06):
little real saving (`_is_available` already short-circuits inside each predicate)
and conflicts with the card system (cards make occupied spaces legal). Full
rationale in the git history of this file and `PROFILING.md` (R5).

### Ops levers (not code)

- **`python -O` for data-gen** — drops `_assert_nonnegative_state` and any
  `__debug__` work. Free.
- **Process parallelism** — one game per worker, `torch.set_num_threads(1)` per
  process. Multiplies throughput and **compounds with every per-sim win above**;
  the single biggest lever for generating data at scale.

---

## How to use this doc

1. Read `PROFILING.md`'s current production profile first.
2. Pick from Part 2 by what the *current* profile shows is hot (and confirm with a
   micro-bench, not cProfile `tottime` alone).
3. Skeptical default: don't apply unless the estimated win clears the workload's
   measurement-noise floor.
4. When something lands, move it to Part 1 and update `PROFILING.md`.
