# Engine Profiling — Findings and Recommendations

Item C from POSSIBLE_NEXT_STEPS.md. Profiles `legal_actions` and `step` across three workloads to identify hot paths before MCTS scaling exposes them as bottlenecks. Date: 2026-05-21.

**No engine code was modified.** This document is observations and recommendations.

For the methodology and prefab states, see `scripts/profile_engine.py` and `scripts/profile_states.py`. Re-run with `python scripts/profile_engine.py` (full) or `--no-profile` (wall-clock only).

---

## Headline numbers (no-profile, 3-run average)

| Workload | Per-action | Per-game | Note |
|---|---:|---:|---|
| A — `random_agent_play` from `setup()`, seeds 0–9 | ~64 us | ~10 ms | Baseline; mirrors the test suite |
| B — `random_agent_play` from `early_round_3_wealthy` | ~80 us | ~14 ms | 25% slower per action; richer action surface |
| C — micro-bench `legal_actions(state)` over 9 prefabs | 30–69 us | n/a | Range across game positions |
| C — micro-bench `step(state, action)` over 9 prefabs | 18–88 us | n/a | Range across game positions |

Implications for MCTS scaling:
- At 64 us/action, a 150-action rollout costs ~10 ms. One thread → **~100 rollouts/sec**.
- An MCTS budget of 1k rollouts/move ≈ 10 seconds/move. 10k rollouts ≈ 100 seconds/move.
- Per-move budgets in the 1–5 second range are reachable with current performance plus modest parallelism (4–8 threads) and no optimizations. **Nothing is on fire.**

---

## Hot paths (cProfile)

Top 5 by self time across workloads, with frequency context:

### 1. `dataclasses.replace` — 16–30 % of self time

- **Workload A:** 27 ms total / 13,752 calls / ~2.0 us per call
- **Workload C:** 119 ms total / 65,267 calls / ~1.8 us per call
- **Where it's used:** every state-update site in resolution and engine code (`_update_player`, `_update_space`, `replace_top`, every `dataclasses.replace(state, ...)` chain in a handler)

The stdlib `dataclasses.replace` does `getattr`-per-field to build a kwargs dict, then calls the class constructor. With `PlayerState` (9 fields), `Farmyard` (5 fields), and `GameState` (7 fields), single-attribute updates pay 7–9 attribute reads regardless of what changed.

### 2. `legal_placements` listcomp — calls all 24 predicates on every `legal_actions()`

- **Workload C:** 68 ms / 9,009 calls of `legal_placements` → ~7.5 us per call
- Each call evaluates 24 predicates whether or not their space could plausibly be legal in the current position
- `_is_available` alone is called 216,216 times in Workload C (24 predicates × 9,009 listcomps) for 48 ms / ~220 ns per call
- Many predicates internally re-derive shared facts: `_num_rooms`, `_can_renovate`, plowed-field counts, etc.

### 3. `can_accommodate` + `pareto_frontier` — scales hard with animal state

- **Workload A:** 4 ms / 2,141 calls
- **Workload B:** 22 ms / 3,531 calls (5.5× the work) — same call count growth, but each call has more candidates to filter
- Inner generator `helpers.py:128` fires 130k times in Workload B (vs 24k in A)
- `dominates` helper: 63k calls in Workload B (Pareto's O(n²) filter)

This is item E (Pareto frontier pruning) being empirically confirmed as a hot path in mid-late game.

### 4. `_any_legal_pasture_commit` + `_check_entry_legal` — Fencing universe walk

- **Workload A:** 6 ms self + 8 ms via `_check_entry_legal` (14,497 calls)
- Per call: ~50 us for the full universe walk
- The 1×1 fast-path is doing its job — without it, this would be much higher
- Not currently the bottleneck, but the largest per-call cost in the legality layer

### 5. `_assert_nonnegative_state` — engine safety-net, every `step()`

- **Workload A:** 4 ms / 1,613 calls / 2.5 us per call
- 1% of step time
- Pure safety net, not a correctness mechanism

---

## What's *not* a hot path

These are worth calling out because they were suspected but turned out fine:

- **`compute_pastures_from_arrays`** — 2 ms total in Workload B (82 calls × ~24 us). The BFS on 3×5 is genuinely cheap. The CHANGES.md Change 3 design (recompute only on pasture-changing effects) keeps it that way.
- **`get_space`** — 309k calls in Workload C for 25 ms total. ~80 ns per call. The tuple+index lookup added by Change 8 is functionally free.
- **`cooking_rates`** — does not appear in the top 25 anywhere.
- **`compute_new_fence_edges`** — appears only deep in the Fencing path, not a hot path.

---

## Recommendations (for your decision)

Listed in order of expected ROI / ease ratio. **No code changes have been made.** Each is a proposal.

### R1. `legal_actions(state)` cache — `dict[GameState, list[Action]]`

**What:** Wrap `legal_actions` with a memoization layer keyed by the (now-hashable) `GameState`. Bounded LRU or a per-MCTS-search cache that's cleared between searches.

**Why:** MCTS calls `legal_actions` once per node-expansion AND once per child-selection at the same node. Workload C shows ~50 us per call. A repeat-call hit ratio of even 50% halves legal-action enumeration cost.

**Cost:** ~20 lines of code. Pure addition; no engine semantics change. Doesn't help random-play workloads (where each state is unique), but those aren't the target consumer.

**Risk:** Low. Memoization is purely additive. The `GameState` hash already works (Change 8). One thing to verify: memory growth — a self-play game generates ~150 unique states, so unbounded growth across thousands of games is the only thing to watch.

### R2. Toggle `_assert_nonnegative_state` via a module flag

**What:** Add `__debug__` gating or a module-level `ASSERTIONS_ENABLED` flag around the assertion in `step()`.

**Why:** 2.5 us × millions of MCTS rollouts adds up. Saves ~4% of total step time. Tests / development / CI keep assertions on; production / training disables them.

**Cost:** ~5 lines. The cleanest form is `if __debug__: _assert_nonnegative_state(...)`, which Python compiles out entirely under `python -O`.

**Risk:** Very low. The assertion has caught one bug (Task 7's Cooking Hearth gate) and that bug is now fixed. The assertion remains a safety net but doesn't need to fire every step in a self-play loop.

### R3. Fast-path `_replace_player` / `_replace_space` / `_replace_farmyard` constructors

**What:** Replace `dataclasses.replace(player, resources=new_res)` (and similar single-field updates on hot dataclasses) with explicit construction:
```python
def _replace_player_resources(p, new_res):
    return PlayerState(
        resources=new_res,
        animals=p.animals,
        farmyard=p.farmyard,
        ...
    )
```

**Why:** `dataclasses.replace` is the #1 self-time cost. The stdlib version does field introspection per call; an explicit constructor skips that. Likely 5–10× speedup on the specific call site (sub-microsecond → 100s of nanoseconds).

**Cost:** Per-shape helper, maybe 5–10 helpers covering the most-frequent update patterns (player resources, player+farmyard, space workers, etc.). ~50–100 lines.

**Risk:** Medium. The helpers couple to dataclass field lists; a future field addition to PlayerState / Farmyard / GameState requires updating every helper that touches that class. Mitigation: make a generic `fast_replace(obj, **kwargs)` that caches the field tuple per class, gaining most of the speedup without per-class code.

I'd recommend trying the **generic `fast_replace`** first, measuring, then deciding whether per-field helpers add enough on top.

### R4. Implement item E's anchor pruning for `pareto_frontier` and `breeding_frontier`

**What:** Item E from POSSIBLE_NEXT_STEPS.md. Anchor-on-pre-state pruning (the easy half) first; geometric pruning later if profiling still shows the helpers as a hot path after anchor pruning.

**Why:** Workload B confirms `can_accommodate` + Pareto-inner generators are the second-largest cost center in mid/late game. The anchor approach is described in detail in item E and should be ~2× speedup for small states, much larger for late-game.

**Cost:** Few-line dominance check per candidate emit in each frontier helper.

**Risk:** Low if the "Preserving optionality" Key Design Principle's Pareto-dim invariant holds (it does today). Document the assumption in the helper docstring.

### R5. Short-circuit `legal_placements` predicates that depend on visible accumulation

**What:** Currently `legal_placements` evaluates all 24 predicates regardless of state. Many predicates short-circuit cheaply (e.g., `_legal_meeting_place` is just `_is_available`), but some do real work (`_legal_fencing` walks the universe). A pre-filter that skips predicates whose space is currently occupied (workers != (0,0)) would cut average cost.

**Why:** In a typical mid-game state, 5–10 of the 24 spaces are occupied by workers. Each occupied space could short-circuit at the `_is_available` check inside its predicate — but the predicate is still being called. A `legal_placements` rewrite that filters by availability first would skip the predicate body entirely.

**Cost:** ~10 lines. Replace the listcomp with a loop that calls `_is_available` once per space and only calls the predicate body if available.

**Risk:** Low. Pure refactor of the dispatch shape.

I'm less sure of the magnitude here — `_is_available` is already inside each predicate, so this is just avoiding the function-call overhead for the *body* of each predicate. Maybe 10–20 % of `legal_placements` time, less in early game.

### R6. (Defer) Geometric Pareto pruning, methodical-agent coverage

**Geometric pruning:** Item E's "incremental geometric pruning" — defer until R4 numbers are in. Likely a separate task once anchor pruning lands.

**Methodical agent:** Item C originally suggested a brute-force agent for coverage. The 9 prefab states already give us coverage of all 24 legal spaces (Workload C); a methodical agent is a bigger build than it's worth right now. Defer.

---

## Suggested order of work

If you want to act on these, the cheapest wins first:

1. **R2** (assertion toggle) — 5 lines, ~4 % win on step cost
2. **R1** (legal_actions cache) — 20 lines, big MCTS win when it lands
3. **R3** (`fast_replace`) — biggest single-function self-time saving; try the generic version
4. **R4** (anchor pruning) — confirmed hot path, moderate scope
5. **R5** (`legal_placements` short-circuit) — optional, less certain win

After R1–R4 land, re-run the profiler from this same harness (`scripts/profile_engine.py`) to measure actual impact.

---

## Re-running

```
python scripts/profile_engine.py                  # all three workloads + cProfile
python scripts/profile_engine.py --no-profile     # wall-clock only (cleaner numbers)
python scripts/profile_engine.py --workload C     # just micro-bench
python scripts/profile_states.py                  # validate prefab states + coverage
```

Workload definitions, prefab states, and the cProfile invocation are all in `scripts/`. Nothing under `agricola/` or `tests/` was modified.
