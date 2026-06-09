# Incremental Pasture Decomposition — Design Doc (jumping-off point)

> **Status: NOT STARTED — design sketch only.** This is the detailed write-up of S9's "option 2
> (incremental update)" in `SPEEDUPS.md`. It captures the idea, the concrete hooks already
> in the code, and the correctness concerns that make it a session of its own rather than a quick
> patch. It is intentionally a starting point, not a finished plan — several pieces are flagged as
> open.
>
> **Read first:** the S9 entry in `SPEEDUPS.md` (motivation + the memoization alternative),
> and `agricola/pasture.py` (`compute_pastures_from_arrays`, the function being replaced/augmented).

---

## 1. Purpose

`compute_pastures_from_arrays` (`agricola/pasture.py`) is a flood-fill BFS that derives the full
pasture decomposition (enclosed connected components + per-pasture stable count + capacity) from a
farmyard's grid and two fence arrays. The **first MCTS cProfile** (PROFILING.md, 2026-06-02) makes
it the **#1 self-time function in MCTS** — ~4.8 s over 222k calls — because MCTS macro-fencing
explores enormously many fence-build sequences and **every fence-build commit re-runs the full BFS
from scratch**. In random play it's negligible (~2 ms, 82 calls); MCTS is what exposes it.

The idea: most commits change the decomposition only *locally*, so we can update the cached
decomposition incrementally instead of re-flooding the whole 3×5 grid.

**Scope.** This doc covers the two — and only two — pasture-changing effect functions in the engine
(grep confirms these are the sole production callers of `compute_pastures_from_arrays`):

- `_execute_build_pasture` (`resolution.py` ~937) — fence builds (Fencing + Farm Redevelopment).
- `_execute_build_stable` (`resolution.py` ~775) — stable builds (Farm Expansion + Side Job).

Every *other* Farmyard mutation already leaves `pastures` untouched (it rides along via
`fast_replace`; see §2). So this work touches exactly those two functions plus the equivalence-test
harness.

---

## 2. Background — how `pastures` is cached today

`Farmyard.pastures` is a cached field on the frozen dataclass (`state.py:44`, default `()`). History
(see the comment there + CHANGES.md):

- **Change 2** auto-filled it in `Farmyard.__post_init__` — every construction recomputed.
- **Change 3 disabled the auto-fill.** Now the existing `pastures` tuple **rides along unchanged**
  through `fast_replace` on every mutation that doesn't touch fence/stable topology (plow, sow,
  build room, place animals, take resources, …). Only the two resolvers in §1 recompute and pass
  `pastures=...` explicitly. This is the project's one accepted **on-object cache with a
  caller-discipline contract** (CLAUDE.md Foundations → "derived data, not cached data";
  ENGINE_IMPLEMENTATION.md §4.1).

So the cost is **call count, not per-call complexity** — the BFS is over 15 cells. That framing
matters for choosing between this approach and memoization (§7).

### The hook already exists

`_execute_build_pasture` already computes the new-vs-subdivision signal (`resolution.py` ~957):

```python
existing_pasture_cells_bm = 0
for P in farmyard.pastures:
    for (r, c) in P.cells:
        existing_pasture_cells_bm |= 1 << (r * NUM_COLS + c)
is_subdivision = bool(cells_bm & existing_pasture_cells_bm)
```

`is_subdivision` is exactly "does the committed pasture overlap any already-enclosed cell." Today
it's used only to set the ordering-rule flag (`subdivision_started`). The incremental design reuses
it to choose the cheap path vs the local-recompute path.

`compute_new_fence_edges(farmyard, cells_bm)` (`fences.py`) returns the new fence edges + wood cost;
it fences **every boundary edge of `cells_bm`** (an in-set cell adjacent to an out-of-set/outside
neighbor). That full-boundary fencing is what makes the merge case a non-issue (§6, C2).

---

## 3. The `Pasture` contract (what any algorithm must reproduce)

```python
@dataclass(frozen=True)
class Pasture:
    cells: frozenset        # (row, col) tuples
    num_stables: int        # stables on cells inside this pasture
    capacity: int           # 2 * len(cells) * (2 ** num_stables)
```

And `compute_pastures_from_arrays` returns the tuple **sorted by `min(p.cells)` lexicographically**
(`pasture.py:140`).

**This ordering + structure is load-bearing — see §5.**

---

## 4. The core idea

Branch on `is_subdivision` (and on which resolver):

### 4a. Fence build, NOT a subdivision ("new pasture in open territory")

The committed cells were previously unenclosed. Intuition: append a new `Pasture(cells_bm, stables
on those cells, capacity)` to the decomposition, mark those cells enclosed, leave all other pastures
alone, re-sort. **But this is not safe as stated — see C1 (incidental pockets).**

### 4b. Fence build, IS a subdivision ("split an existing pasture")

The new internal fences split exactly one existing pasture into 2+ components. **Only that
pasture's cells can change membership** — every other pasture and all outside cells are untouched
(the new edges are internal to the affected region). So:

1. Identify the affected existing pasture(s) (those overlapping `cells_bm`).
2. Flood-fill **only within that pasture's cell set** (a handful of cells), not the whole grid.
3. Replace the one old `Pasture` with the resulting sub-pastures; repartition stables (C3).
4. Re-sort by `min(cells)`.

This is the real win: the BFS shrinks from 15 cells to the size of one pasture.

### 4c. Stable build (`_execute_build_stable`)

A stable build changes **no fences** — it adds a `STABLE` cell to the grid. So topology is
unchanged; at most **one** pasture's `num_stables` (and thus `capacity`) changes — the pasture
containing the stable's cell, if that cell is enclosed. If the stable cell is unenclosed, the
decomposition is byte-identical. This is the simplest incremental case: find the containing pasture
(if any), `+1` its `num_stables`, recompute its `capacity`, leave the rest. No flood-fill at all.

---

## 5. The hard constraint that dominates the design: byte-identical output

`Farmyard.__eq__` and `__hash__` depend on the `pastures` tuple, and the **MCTS transposition
table keys on `GameState`'s hash**. Two farmyards that are logically the same layout MUST produce
the **same `pastures` tuple** — same `Pasture` objects, same canonical `min(cells)` ordering, same
`num_stables`/`capacity`. If the incremental path yields the same decomposition in a different
order, or an off-by-one stable count, two states that should collide in the transposition table
won't — a silent search-correctness bug, not a crash.

So the deliverable is not "compute the pastures" — it's **"reproduce `compute_pastures_from_arrays`'s
exact output for the same `(grid, h_fences, v_fences)`."** Treat the flood-fill as the reference
oracle.

---

## 6. Concerns / gotchas (the reason this is its own session)

**C1 — Incidental pockets (the outside path's trap).** Fencing every boundary edge of `cells_bm`
can *incidentally* trap a neighboring open cell whose only route to "outside" ran through the cells
you just enclosed. Result: an enclosed pocket that is **not** in `cells_bm`. So "new enclosed set ==
committed cells" is **not guaranteed** in general. Two ways out: (a) prove the curated fence
universe (`fences.py`) can never offer a commit that creates a pocket — plausible but owed as a
proof; or (b) keep a small **local reachability check** around the committed region rather than a
blind append. Until (a) is proven, assume (b).

**C2 — Merge is NOT a risk (and why).** Because `compute_new_fence_edges` fences the *full* boundary
of `cells_bm`, a new region adjacent to an existing pasture gets a fence on the shared edge → they
stay separate components. So building a pasture can never merge two pastures. (Merges would only
arise from *removing* fences, which Agricola never does.) This is what lets 4a/4b avoid a
global recompute.

**C3 — Stable repartition + the combined case (subdivision path).** When a pasture splits, its
stables must be reassigned to whichever sub-component each stable's cell lands in (`num_stables`
drives `capacity`). Also, a single commit can **both** extend into open space **and** subdivide an
existing pasture at once — so 4a/4b are not cleanly either/or; the affected-region computation must
handle a `cells_bm` that straddles enclosed and open cells.

**C4 — Determinism of sub-pasture identity.** After a split, the resulting `Pasture` objects must
sort into the exact positions the flood-fill would produce. Since sorting is by `min(cells)` and the
cells are determined, this should fall out — but it's the thing the equivalence test must hammer.

---

## 7. Relationship to memoization (S9 option 1) — do that first

S9's **option 1** is an `lru_cache` on `compute_pastures_from_arrays` keyed on its three array args
(already hashable tuples-of-tuples). It reduces the **call count** (cache hits skip the BFS
entirely); the incremental approach here reduces **per-call cost** (helps the miss path only).

Fence layouts recur heavily across MCTS paths — the S7 fence-scan cache saw ~94% hits — so
memoization likely removes most of the 4.8 s for ~10 lines and **zero correctness surface** (the key
*is* the inputs; a stale entry is impossible). The incremental rewrite only earns its keep on the
residual misses (genuinely-new layouts).

**Recommendation:** land memoization first, re-profile, and pursue this incremental work **only if
the miss-path BFS still dominates** afterward. The two compose cleanly: memoize the hits, run the
incremental algorithm on the misses. Note also S9's standing caveat — `evaluate_hubris_v3` is ~half
of MCTS cumulative time, so the leaf evaluator (or moving to the NN evaluator) is the bigger lever
regardless.

---

## 8. Suggested session plan

1. **Build the equivalence harness first** (§5 is the whole risk). A test that, over randomized
   legal fence/stable-build sequences, asserts the incremental result is `==` to
   `compute_pastures_from_arrays` on the same arrays — tuple order, stables, capacity included.
   Mirror the cross-level pattern in `tests/test_frontier_opt.py`.
2. **Do the stable-build case (4c) first** — it's the simplest (capacity-only, no flood-fill) and
   exercises the harness end-to-end with low risk.
3. **Resolve C1** — either prove no incidental pockets in the active universe, or implement the
   local reachability check.
4. **Implement 4a/4b** behind a toggle (mirror `opt_config.py` so it's A/B-profilable and
   default-off until proven byte-identical — as the frontier opts were during bring-up, before they
   were flipped default-on).
5. **Profile** against the flood-fill + the memoized version on the MCTS workload.

---

## 9. Open questions

- Can the active fence universe (`fences.py` / `fence_universe.py`) ever produce an incidental
  pocket (C1)? If provably not, the outside path simplifies enormously.
- Is incremental worth it *at all* once memoization lands, or does the ~94%-style hit rate make the
  miss path negligible? (Gate decision — measure, don't assume.)
- Should this be a toggle in `opt_config.py` (consistent with the frontier opts) or, once proven,
  replace the flood-fill outright? Leaning toggle-first.

---

## 10. References

- `agricola/pasture.py` — `compute_pastures_from_arrays` (the oracle), `Pasture`.
- `agricola/resolution.py` — `_execute_build_pasture` (~937, the `is_subdivision` hook),
  `_execute_build_stable` (~775).
- `agricola/fences.py` — `compute_new_fence_edges`, the pasture-shape universe.
- `agricola/state.py:44` — the `Farmyard.pastures` cache + caller-discipline comment.
- `SPEEDUPS.md` — S9 (this item) and S7 (the landed fence-scan cache, distinct path).
- `FRONTIER_OPT_DESIGN.md` / `tests/test_frontier_opt.py` — the toggle + cross-level equivalence
  testing pattern to copy.
- `PROFILING.md` — the MCTS profile that ranks this #1 self-time.
