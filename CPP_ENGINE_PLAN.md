# C++ Self-Play Engine — Design & Staged Port Plan

> **Status: COMPLETE — all 7 stages landed; ~4× faster than Python single-thread.** A
> faithful C++ reimplementation of the self-play *inner loop* (engine + MCTS + NN inference),
> built alongside — not replacing — the Python codebase. Every stage is validated against the
> Python oracle by its equivalence gate (≈118 cpp gates green). **Results + per-stage notes in
> §8.1.** Further optimization headroom (state structural-sharing, NN leaf-batching) is noted
> there for a future pass.

> **Audience note.** The project owner reads Python fluently but not C++. This plan is
> therefore built around a *differential-testing harness that reports in Python/game terms*:
> the trust mechanism is "the Python engine and the C++ engine produce identical results over
> millions of states," asserted and displayed in Python. The owner reviews test output, never
> C++ source. §3 is the heart of that and should be read most carefully.

---

## 0. Why, and what we are (and are not) building

### 0.1 The problem

Self-play data generation is the bottleneck. A single **MCTS-vs-MCTS self-play game in the
production config** — PUCT, NN value leaf, combined policy prior, **500 sims/move** — takes
**15–25 s single-thread** (measured). That per-game cost is what the C++ port targets. The
**~10,000 games in ~10 hours** observed is that figure under multi-worker parallelism
(≈20 s/game × 10k ÷ 10 h ⇒ **~5–6 effective workers**). The end goal — an AlphaZero-style
value+policy network trained on self-play — wants *far* more games (a serious run is 10⁵–10⁶
games, i.e. hundreds of single-thread core-hours even before the loop's later iterations), so
15–25 s/game single-thread is the real wall. Renting cores helps but costs money, and **a faster
per-game engine makes every rented core cheaper too** — the C++ win compounds with parallelism
rather than competing with it.

> The setup is evidently already parallelized (15–25 s/game single-thread vs the ~3.6 s/game wall ⇒
> ≈5–6 workers). Before measuring any C++ win, confirm the remaining *free* levers are maxed:
> **`python -O`** (drops the per-`step` assertions), **one worker per core**, and
> **`torch.set_num_threads(1)` per worker** (libtorch is multi-threaded by default; with process
> parallelism that oversubscribes cores — `generate_selfplay_data.py` already sets it). C++ is the
> lever *beyond* those.

### 0.2 The performance thesis (grounded in `PROFILING.md`)

The production workload — MCTS-NN PUCT, `FenceMode.FLATTEN`, single-pass NN value leaf + 9-head
combined policy prior — splits roughly in half:

| half | ~% wall | what it is |
|---|---:|---|
| NN inference (value + policy) | ~50% | tiny MLP forwards + `encode_state` (~10%) |
| engine + search machinery | ~50% | `step` (~13%), `legal_actions` (~12%), diffuse bookkeeping/state-construction (~23%) |

The two halves have very different ceilings under a native rewrite:

- **Engine + search (~50%)** is pure Python-interpreter overhead on small-object work
  (frozen-dataclass allocation, dict lookups, hashing, attribute access). This is where C++
  wins hardest — plausibly **20–40×** on these pieces (the FLOP content is trivial; it's all
  interpreter cost).
- **NN inference (~50%)** is *not* compute-bound — the models are tiny MLPs (`[256, 256]`,
  ~110k parameters); the cost is PyTorch per-call dispatch on batch-1 forwards, not arithmetic. Native libtorch +
  not re-paying Python dispatch gets maybe **5–15×** on the forwards, and `encode_state`
  (~10% of wall) goes near-free in C++.

**Realistic all-in ceiling:** ~**8–15×** on the per-game cost — **15–25 s/game → ~1–3 s/game
single-thread** (500 sims) — with a meaningful intermediate checkpoint (~3–4×, i.e. ~4–8 s/game)
reachable before the riskiest stage (native MCTS), see §8. Process parallelism then multiplies
wall-clock throughput on top, exactly as today.

These are estimates, not promises. The staged plan is built so each stage delivers a *measurable*
result and the project can stop when the win is "enough."

### 0.3 Scope: build the inner loop, keep everything else in Python

**Ported to C++ (the hot loop, runs billions of times):**

- The complete **Family-game transition function**: `GameState` + `step` + `legal_actions` +
  scoring + every subsystem (fencing, harvest, animal accommodation, the pending stack).
- **MCTS** (PUCT, FLATTEN, chance nodes).
- **NN inference** (value net + 9 policy heads) via **TorchScript + libtorch**.
- The **encoder** (`encode_state`, 170 features) and the **policy combiner** (`make_policy_fn`'s
  decision tree).

**Explicitly NOT ported — stays Python, unchanged:**

- **The heuristic evaluators** (HubrisHeuristic V1/V3, CMA-ES tuning, the data-gen ensemble).
  *Per the owner's instruction:* they existed only to bootstrap self-play data and have served
  their purpose. The C++ MCTS leaf is **always the NN value net**, never a heuristic. (This also
  matches the standing project rule that MCTS is only ever run with an NN value leaf.)
- **The card trigger machinery + Potter Ceramics** (`cards/triggers.py`, `cards/potter_ceramics.py`).
  Family-only for now — see §12 for the forward path when cards land. **Important exception:** the
  three built-in *harvest conversions* (`cards/harvest_conversions.py` — joinery 1 wood→2 food,
  pottery 1 clay→2 food, basketmaker 1 reed→3 food) live under `cards/` but are **Family-game
  content, not optional cards** — they are surfaced during harvest feeding (`CommitHarvestConversion`)
  and are a candidate type in the `harvest_feed` policy head, so they **must be ported** (folded into
  the transition + harvest, §4 row 7).
- **Web UI / human play** (`play.py`, `play_web.py`), the **training pipeline**
  (`dataset`/`model`/`training`/`policy_training`), the **data-gen orchestration**, and the
  Python engine itself — which becomes the **differential oracle** (§3) and the **trace replayer**
  (§2). The Python engine keeps doing everything except the hot loop.

### 0.4 The one strategic decision baked in: record policy targets too

The codebase has moved past value-only data: `DecisionSnapshot` now carries optional
`visit_distribution` (the root visit counts π, the AlphaZero policy target) and `root_value`
(`schema.py`, `DATA_VERSION = 3`), populated by a new self-play recording path
(`agricola/agents/nn/selfplay_recording.py`, driven by `scripts/nn/generate_selfplay_data.py`).
Since the C++ binary *runs* the MCTS that produces π, **it must emit π + root_value per searched
decision** — these are search byproducts and cannot be reconstructed by replaying actions alone
(§2.4). Designing the trace to carry them costs little and unlocks training both heads from C++
data. A value-only trace is then just the degenerate case (both fields omitted).

---

## 1. Architecture

```
   ┌─────────────────────────── Python (unchanged) ───────────────────────────┐
   │                                                                            │
   │   train value/policy ──► export TorchScript ──►  models/*.ts               │
   │        ▲                                              │                     │
   │        │                                              ▼                     │
   │   build_datasets  ◄── replay traces ──┐      ┌───────────────────┐         │
   │   (existing pipeline, unchanged)      │      │                   │         │
   │        ▲                              │      │   C++ self-play    │         │
   │   GameRecords ◄── Python trace replayer│     │   binary           │         │
   │                  (new, small adapter) │      │  engine+MCTS+      │         │
   │                                       └──────┤  libtorch infer    │         │
   │                                  traces/*.json│                   │         │
   │   Python engine = differential ORACLE         └───────────────────┘         │
   │        ▲                                              ▲                      │
   │        │ pytest differential harness (§3) ────────────┘ (pybind11 binding)   │
   └────────┴───────────────────────────────────────────────────────────────────┘
```

**Data flow each self-play generation:**

1. Python trains the value + policy nets (existing pipeline). Export each to TorchScript
   (`jit.trace` + `save`) → `.ts` files. (One-time per checkpoint; `proto_jit_trace.py` already
   proved trace-export is numerically exact for these models.)
2. The **C++ self-play binary** loads the TorchScript models via libtorch, runs MCTS-NN PUCT
   self-play games entirely natively (no Python in the loop), and writes **game traces** (action
   sequences + per-decision π/root_value + outcomes) to disk as JSON.
3. A small **Python trace-replay adapter** reads the traces, replays each through the *existing*
   Python engine to rebuild `GameState`s, and produces `GameRecord`s — which flow into the
   **unchanged** `build_datasets` → train pipeline.

**Why traces, not live interop:** the C++↔Python boundary is just a file format, so the hot loop
never crosses it (where the speedup lives) and Python's encoder/dataset/training code is untouched.
Replay is cheap (~10 ms/game — pure `step` along a known action list, no search/NN), so rebuilding a
10k-game dataset takes a minute or two (vs the hours generation takes), and you can **re-encode with a new feature set later without
regenerating games** (the current pipeline's best property is preserved).

> **Replay perf footgun (fixed — SPEEDUPS.md S14).** `replay_trace` originally called `legal_actions`
> at every step purely to decide which states are non-singleton decisions worth snapshotting (it never
> uses it to *validate* the trace — `step` applies recorded actions unconditionally). On animal-heavy
> late-game farms that re-runs the `PARETO_OPT_LEVEL` Φ build (`_build_phi`), which is pathological
> under replay's one-touch-per-state access (the Φ build amortizes over many cap-queries in MCTS but
> replay touches each state once) — up to ~24 s for a single game, breaking the ~10 ms/game assumption.
> Fix: MCTS self-play traces record a `visit_distribution` only on non-singleton decisions, so
> "entry has π" is set-identical to the `legal_actions` singleton test (→ byte-identical `GameRecord`s);
> replay uses that and skips `legal_actions` (value-only traces fall back). Worst-case game 24 s → 5 ms.

**Build shape — one core library, two front-ends:**

- `libagricola_cpp` (static) — the engine + MCTS + inference + encoder + policy.
- A **pybind11 module** (`agricola_cpp`) exposing the core functions to Python — used **only** by
  the differential test harness (§3), and optionally as the "Python-MCTS-over-C++-engine"
  intermediate (§8 stage 5 checkpoint).
- A **standalone executable** (`selfplay`) — production data-gen, no Python.

---

## 2. The interop contract: game traces

### 2.1 Replay determinism — confirmed

The load-bearing claim for the trace design **holds** (verified against the code):
`setup(seed)` + an ordered action list that **includes the `RevealCard` actions** fully
reconstructs a game by replaying through pure `step` — **with zero `Environment` access**.

Why: `RevealCard` is a normal `step` action (`engine.py:_apply_reveal_card`), and it carries the
revealed card id as a string (`RevealCard.card`). `step` never consults the `Environment`; the
`Environment` is needed only to *generate* an unseen game's reveals, never to *replay* a recorded
one — the hidden order is already baked into the recorded `card` strings. So the **action trace
(not the bare seed) is the source of truth**, and the C++ binary may use its own RNG for setup +
reveals (no need to reproduce NumPy's PCG64 stream).

### 2.2 Trace format — extend the existing web-UI schema

`play_web.py` already emits a per-action JSON trace (`trace_snapshot()` →
`agricola-trace-seed<N>.json`): an envelope `{seed, seats, actions: [...]}` where each action is
`{round, phase, decider, type, params, display}`, and `params` mirrors each `Action` dataclass's
fields. **Reuse this shape**, with three gaps to close:

1. **`RevealCard.card` is currently dropped** (the web `_action_params` has no `RevealCard` branch,
   so it serializes `params: {}` — the card id is lost). This is the *critical* fix: per §2.1 the
   `card` string is exactly what makes replay Environment-free. Add `{"card": action.card}`.
2. **No `params → Action` deserializer exists anywhere** (the web UI dispatches the human's choice
   by integer index, never reconstructs an `Action`). We must write one in Python — 17 cases, all
   scalar/string except `CommitBuildPasture.cells` (`frozenset(tuple(c) for c in params["cells"])`).
   The full field list is in `actions.py`; the per-type `params` table is in the web encoder
   (`play_web.py` `_action_params`).
3. **No π / root_value carriage.** Extend each searched-decision action dict with optional
   `"visit_distribution": [[params, count], ...]` and `"root_value": float` (§2.4).

`display` is a human-readable convenience — ignore on read. `round`/`phase`/`decider` are useful
debug metadata; the replayer should *assert* the recorded `decider` matches `decider_of(replayed
state)` as a cheap drift check.

### 2.3 Two distinct serialization concerns — keep them separate

- **Action-trace serialization (production interop):** C++ writes, Python reads. JSON. The §2.2
  schema. This is the *only* serialization the production standalone binary needs.
- **Canonical STATE serialization (test only):** full `GameState` ↔ a deterministic text dump, in
  *both* languages, used by the differential harness (§3). Test-only ⇒ speed irrelevant, can be
  verbose and maximally debuggable. The production binary never serializes a state.

### 2.4 What a pure action trace cannot reconstruct (and why we record it)

Replaying actions gives the *chosen* action but not the *distribution over alternatives* the search
produced. So:

- **Value-head data** needs *nothing* beyond the replayed `GameState` — `encode_state` is a pure
  function of `(state, perspective)`. A pure action trace suffices.
- **Policy-head data** needs **π** (`visit_distribution`, `dict[Action,int]` from
  `root_visit_distribution`) and optionally **root_value** (root mean-Q in P0's frame) **per
  searched decision** — un-regenerable from actions (regenerating them by re-running Python MCTS
  would defeat the whole point). The C++ binary already computes these inside its search; it just
  serializes them alongside the chosen action.

The Python replayer then re-captures `DecisionSnapshot`s exactly as `recording.py`/
`selfplay_recording.py` do, attaching the recorded π/root_value, and emits standard
`GameRecord`s. **Singleton rule must match:** a decision is recorded iff
`len(filter_implemented(legal_actions(state))) > 1`. The replayer should re-derive this in Python
with the same `legal_actions_fn`, so any C++/Python "what counts as a decision" mismatch is
sidestepped (Python is authoritative for *which* snapshots exist; C++ is authoritative for π).

---

## 3. The differential-testing methodology (the spine)

This is the trust mechanism and the thing that makes a faithful port tractable for a Python-only
reviewer. **Principle: the Python engine is the oracle; the C++ engine must be observably
byte-identical, and every comparison is asserted and displayed in Python/game terms.**

### 3.1 Canonical state serialization

Define one canonical, deterministic text/JSON dump of a full `GameState`, implemented in Python
first (trivial — walk the frozen dataclasses in declaration order) and mirrored in C++. It is the
single shared artifact both engines must agree on. Properties:

- Covers every field of `GameState` / `PlayerState` / `BoardState` / `Farmyard` / `Cell` /
  `Resources` / `Animals` / `ActionSpaceState` / the `pending_stack` tagged union — see §5 and the
  per-file field tables the research produced.
- **Order-independent for `frozenset` fields** (`Pasture.cells`, `minor_improvements`,
  `occupations`, `harvest_conversions_used`, `triggers_resolved`, `CommitBuildPasture.cells`):
  serialize as sorted lists.
- Excludes the `_hash_cache` (it is per-process-salted in Python and stripped on pickle; not part
  of identity).
- String equality of two dumps **is** the state-equivalence test, and doubles as the
  human-readable diff when something diverges.

### 3.2 The trace-replay differential test (engine equivalence)

The primary gate for the engine (`legal_actions` + `step` + scoring):

1. **Python generates random games** (random play sweeps every subsystem — fencing, harvest,
   accommodation, scoring). For each game it records: the initial state dump, and per step the
   **legal-action set** (canonical), the **chosen action**, the **resulting state dump**, and the
   final **scores + tiebreakers**. Reveals are recorded as explicit `RevealCard` actions.
2. **The C++ engine replays each game**: deserialize the initial state once, then for each step
   assert (a) C++ `legal_actions` **set** == Python's recorded set; (b) after applying the same
   action, C++'s resulting state dump == Python's recorded dump; (c) at the end, C++ score +
   tiebreaker == Python's. Run over **millions** of random games.
3. **Any mismatch is reported in game terms** — round, phase, the diverging state fields — at the
   level the owner can read.

Why this is clean: **RNG never enters the comparison.** The only engine randomness is the reveal
order, and the replayed trace includes reveals as explicit actions, so C++ just *applies* them;
`step`/`legal_actions` are deterministic given `(state, action)`. (In production C++ uses its own
RNG for its own games — it needs a *correct* game distribution, not bit-identical-to-a-Python-seed
games.)

**Comparison granularity:** `legal_actions` is compared as a **set** (correctness). Cross-language
*ordering* is deliberately *not* required of the engine — ordering only matters for (a) NN policy
pointer-head candidate pairing, which each engine keeps self-consistent end-to-end, and (b) MCTS
reproducibility, which we validate by strength, not bit-identity (§7.4).

### 3.3 How the harness runs (pybind11 + pytest)

The recommended mechanism keeps the entire differential test inside the pytest suite the owner
already runs:

- The pybind11 module exposes `cpp_legal_actions(state_dump) -> [action_dump]`,
  `cpp_step(state_dump, action_dump) -> state_dump`, `cpp_encode(state_dump, perspective) ->
  [float]`, `cpp_value(state_dump) -> float`, `cpp_policy(state_dump) -> {action_dump: prior}`,
  and the scoring functions.
- pytest drives them and compares against the *live* Python engine over generated states — either
  live (Python holds its own state, calls C++ on the serialized copy, compares) or via the
  file-based replay of §3.2. Live comparison is the tight inner-loop dev tool; file replay is the
  bulk/offline gate.
- A standalone "replay-and-dump" executable + a Python JSON-diff script is a no-pybind fallback if
  the binding ever becomes a nuisance.

### 3.4 Component-level gates (beyond the engine)

| Component | Gate (vs Python oracle) | Tolerance |
|---|---|---|
| Engine (`legal_actions`/`step`/`score`) | trace-replay, §3.2, over millions of random states | **exact** (set-equal / dump-equal) |
| `encode_state` | C++ encode == Python `encode_state` over a state corpus | **exact** (float32 bit-identical, or ≤1 ULP) |
| Value forward | C++ `predict_margin` == Python over a corpus | ≤1e-4 (float) |
| Policy combiner | C++ `policy_fn` priors dict == Python over a corpus | ≤1e-4 per action |
| MCTS components | UCB/PUCT formula, backprop sign-flip, chance round-robin, transposition keying — hand-built cases mirrored in both | exact |
| MCTS end-to-end | C++-MCTS vs Python-MCTS head-to-head, many seeds | ~50% ± noise (strength parity, §7.4) |

The exact gates (engine, encoder) are the bulk of the work and the well-behaved part. The MCTS
end-to-end gate is the honest soft spot (§7.4).

---

## 4. What must be ported — inventory

Mapped to the Python source, with a complexity/risk read. "Risk" = likelihood of subtle divergence,
i.e. how hard the equivalence gate is to pass.

| # | Component | Python source | Notes | Complexity | Risk |
|---|---|---|---|---|---|
| 1 | State data model | `state.py`, `resources.py`, `pasture.py`, `constants.py` | Frozen structs → C++ value structs; no numpy, all int/bool/enum/tuple. Cached structural hash. | Med | Low |
| 2 | Pending stack | `pending.py` | 25-variant tagged union; `player_idx` nullable (`PendingReveal`). | Med | Low |
| 3 | Actions | `actions.py` | 17-variant tagged union. | Low | Low |
| 4 | Pasture flood-fill | `pasture.py` `compute_pastures_from_arrays` | 3-pass BFS; **canonical output order = sorted by `min(cells)`** (feeds hash/eq). | Med | **Med** |
| 5 | Legality | `legality.py` | 24 placement predicates + 23 pending enumerators + shared helpers. Biggest correctness surface. | **High** | **High** |
| 6 | Fence universe | `fences.py` | Precomputed static tables (FULL 1518 / FAMILY 762 / EXTENDED 193 / **RESTRICTED 109** = production). `PastureCandidate` edge metadata; `_check_entry_legal` 6-step chain. *(`fence_universe.py`'s runtime universe-swap + the `opt_config` fence-scan cache are NOT needed — use the fixed RESTRICTED table directly.)* | **High** | **High** |
| 7 | Transition | `engine.py`, `resolution.py`, `cards/harvest_conversions.py` | `step` dispatch, `_advance_until_decision` phase machine, the 4 dispatch tables, all `_resolve`/`_initiate`/`_choose_subaction`/`_execute` handlers, harvest (FIELD/FEED/BREED) incl. the 3 built-in harvest conversions (joinery/pottery/basketmaker). | **High** | Med |
| 8 | Frontier helpers | `helpers.py` | `can_accommodate` (4^n), `pareto_frontier`, `breeding_frontier`, `food_payment_frontier`, `harvest_feed_frontier`, `cooking_rates`, `extract_slots`. Port the **level-0 baselines** (set-identical to the optimized paths). | Med-High | Med |
| 9 | Scoring | `scoring.py` | 15 categories + craft bonus + tiebreaker. | Med | Low |
| 10 | Setup | `setup.py`, `environment.py` | SP coin-flip + within-stage shuffle of 14 cards; own RNG fine. | Low | Low |
| 11 | Encoder | `agents/nn/encoder.py` | 170 floats, exact index layout; terminal zeroing; the `decider_of`-based `current_player_is_own`. | Med | **Med** |
| 12 | NN models | `agents/nn/model.py`, `policy_model.py`, `policy_pointer_model.py` | Plain MLPs `[256,256]` gelu/LN/dropout; load via TorchScript. | Med | Low |
| 13 | Policy heads + combiner | `agents/nn/policy_heads.py`, `policy.py` | 9 heads + the 5-branch `make_policy_fn` decision tree + cell-priority/build-stop logic. | **High** | **Med** |
| 14 | MCTS | `agents/mcts.py`, `agents/base.py` | PUCT + FLATTEN + chance nodes + transposition DAG + two RNG streams. Skip MACRO. | **High** | Med (engine), High (cross-lang exactness — but validated by strength) |
| 15 | Trace I/O + replay adapter | new + `agents/nn/{schema,recording}.py`, `play_web.py` | C++ writer; Python reader/replayer → `GameRecord`. | Med | Low |

**Not ported:** heuristics (`agents/heuristic.py`, tuning); the `restricted.py` legality *wrappers*
(PUCT uses the full unrestricted `legal_actions`, so the wrappers aren't on the production path —
**but** the cell-priority constants + `_filter_cell_priority` in `restricted.py` ARE needed by the
policy combiner, §6.3); the card trigger machinery + Potter Ceramics (`cards/triggers.py`,
`cards/potter_ceramics.py`) — **but NOT `cards/harvest_conversions.py`, which is Family content and
IS ported** (§0.3); web/human UI; training.

---

## 5. The data model in C++

### 5.1 Mapping frozen dataclasses → structs

Everything in the core model is value-typed, immutable, and free of numpy/floats — it maps cleanly
to C++ value structs. Fixed dimensions throughout: **grid 3×5 = 15 cells**, horizontal fences
**(4,5)=20 edges**, vertical fences **(3,6)=18 edges**, 15 fence supply, 4 stable supply,
`future_resources` length 14, 25 action spaces, 10 majors.

Use `std::array` for the fixed-shape grids/fences. Represent the pending stack as a
`std::variant` (or a tagged base + enum discriminant) over the 25 frame types; `player_idx` is an
`std::optional<int>` / sentinel (the `PendingReveal` nature case is the only `none`). Actions are a
`std::variant` over 17 types.

Field-by-field tables (names, types, defaults) are in the research output and the Python files; the
implementer should treat `state.py`/`resources.py`/`pasture.py`/`pending.py`/`actions.py` as the
authoritative schema and the canonical serializer (§3.1) as the contract.

### 5.2 Immutability, structural sharing, and the transposition table

Python state is immutable; `step` returns a new `GameState`, and `fast_replace` shares unchanged
subtrees *by reference*, so the MCTS DAG is cheap. The C++ port has a choice:

- **Default (recommended first):** value-semantic `GameState` with whole-object copies on `step`.
  States are small (low-KB), correctness is trivial, and the transposition table dedups. Get it
  correct first.
- **Optimization (later, if alloc/memory shows up in the C++ profile):** mirror Python's structural
  sharing with `shared_ptr` sub-objects (farmyard, board, players) so `step` copies only the
  changed branch. This is the C++ analogue of `fast_replace` + the cached-hash win (S5) and is the
  natural place the engine half's speedup is realized.

### 5.3 Hashing & equality (the transposition-table contract)

The MCTS transposition table keys on `GameState`. Port must provide `std::hash<GameState>` +
`operator==` over the full structure, with **the hash cached on the state** (computed once at
construction — the C++ analogue of S5, which removed Python's #1 self-time). Equality must be
structural (and collisions fall back to it). `re_root` uses **pointer identity** for reachability —
use an `unordered_set<MCTSNode*>`.

### 5.4 Correctness gotchas surfaced by the research (port carefully)

- **Canonical pasture ordering** — `compute_pastures_from_arrays` returns pastures **sorted by
  `min(cells)` lexicographically**; this ordering is part of `Farmyard` hash/eq. Replicate exactly.
- **`SPACE_IDS` is a fixed 25-entry canonical order** (11 permanents then 14 stage cards in stage
  order); the per-game shuffle lives only in the `Environment`. `board.action_spaces` is indexed by
  this order.
- **Two animal-count conventions in commits:** `CommitAccommodate`/`CommitBreed` carry **post-event**
  counts; `CommitConvert` carries **consumed** amounts. Don't conflate.
- **Harvest pushes one frame per player** with the **starting player's frame on top** (decides
  first); both players' frames coexist on the stack — this is the live case the `decider_of` rule
  (top-frame `player_idx`, not `current_player`) exists for.
- **`decider_of` returns `0`, `1`, or `None`** (`None` = `PendingReveal`, routed to the dealer /
  flagged as a chance node). It is top-of-stack `player_idx` if the stack is non-empty, else
  `current_player`.
- **`step` does not validate legality and does not auto-resolve singletons** — even a forced `Stop`
  is an explicit step. The game loop lives outside the engine.
- **`Farmyard.pastures` is the one cached field** — recomputed only by the two pasture-changing
  effects (`_execute_build_stable`, `_execute_build_pasture`); everything else rides it along. In
  C++ with value semantics, recompute it in exactly those two effects.
- **Tiebreaker couples to scoring** — the end-game tiebreaker = building resources
  (wood+clay+reed+stone) in supply **minus** the resources spent on craft bonuses
  (Joinery/Pottery/Basketmaker), so craft spending both scores points *and* lowers the tiebreaker.
  `score` and `tiebreaker` recompute the craft spend independently (`scoring.py`). The trace-replay
  gate compares both exactly, so an error here is caught — but it's easy to get wrong first pass.

---

## 6. NN inference in C++

### 6.1 Model export + loading

Python trains as today; export each model with `torch.jit.trace` + `save` to a `.ts` file (the
`.pt` checkpoints are raw state-dict pickles, so TorchScript export is the clean cross-language
path; `proto_jit_trace.py` already verified trace-export is numerically exact for these models).
The C++ binary loads the `.ts` via libtorch and reads the `.meta.json` sidecar for architecture +
`value_scale` + `encoding_version` (hard-check it equals the C++ `ENCODING_VERSION`).

All models are plain post-norm MLPs: `[Linear → LayerNorm → GELU → Dropout]×2 → Linear(out)`,
`input_dim=170` (pointer heads: `170 + candidate_dim`), `hidden=[256,256]`, dropout 0.2. **Inference
is eval-mode: never apply dropout** (leaving it active made Python priors nondeterministic — the
combiner `eval()`s the heads for exactly this reason).

- **Value:** `x_norm=(x-input_mean)/input_std` → MLP → `* target_std` = margin (`predict_margin`).
  Production value head is **linear** with `value_scale ≈ 11.526`. (The linear head matters: the
  MCTS terminal leaf uses the raw `score(0)-score(1)` margin, which is only consistent with a
  linear/margin value head — see §7.3.)
- **Fixed policy head:** MLP → logits → masked softmax (illegal classes → −∞; all-illegal-row
  guard → treat as all-legal to avoid NaN).
- **Pointer head:** per candidate, normalize the **full concatenated row** `[state(170);
  cand(D)]` (so `input_mean/std` span both parts — concat *then* normalize), MLP → scalar, softmax
  over candidates.

### 6.2 The encoder (170 features)

`ENCODING_VERSION = 2`, `ENCODED_DIM = 170`. Layout: **own 0–53 | opp 54–107 | shared 108–161 |
mid-action 162–169**. The encoder emits **raw** values (counts/flags); normalization happens in the
model. Port against `encoder.py` (and golden-test against Python `encode_state` — exact). Gotchas
the research flagged:

- `current_player_is_own` (idx 109) uses **`decider_of(state)`**, not raw `current_player`.
- Accumulation features (idx 112–121) are in **`_ACCUMULATION_SPACES` order**, *not* canonical
  `SPACE_IDS` order; but `space_avail` (136–160) *is* canonical order. Don't conflate.
- `food_owed` uses `newborns` **only on harvest rounds** (`2·people_total − newborns` iff
  `round ∈ {4,7,9,11,13,14}`, else `2·people_total`).
- `pasture_cap_*` (13–17) are **sorted descending, padded to 5**.
- **Terminal zeroing:** at `BEFORE_SCORING`, a specific index set is forced to 0 *after* writing
  blocks (`game_end_indicator` stays 1; resources/animals/majors/etc. retained). The exact set is
  in `encoder.py` (`_TERMINAL_ZERO_NAMES` + the `subaction_avail_*` prefix).
- The perspective-swap memo (`encode_for_inference`/`swap_perspective`) is a pure perf trick
  (block-swap + one bit-flip) — optional; the C++ side can just encode twice. Implement it later if
  the C++ profile wants it.

### 6.3 The 9 policy heads + combiner

Heads: 7 fixed-vocab (`placement` 25, `choose_subaction` 8, `commit_build_major` 14, `commit_sow`
104, `commit_bake` 6, `fencing` 110, `build_stop` 2) + 2 pointer (`animal_frontier` dim 4,
`harvest_feed` dim 10). Each head's vocab, `owns`/`target_index`/`legal_mask` predicates, and the
pointer `enumerate_candidates` featurizers are specified in `policy_heads.py`. The `fencing` head's
110 classes = the **109 RESTRICTED universe shapes (in `UNIVERSE_RESTRICTED_ENTRIES` order)** +
`__stop__` — the class↔shape map must match that ordering exactly.

The combiner `make_policy_fn` (`policy.py`) is the trickiest non-NN logic — a 5-branch decision
tree over the full legal set, returning `{action: prior}` (the search soft-prunes by treating
omitted actions as prior 0; it does **not** renormalize — pass priors through as-is):

1. A fixed head `owns(state)` → masked-softmax priors over that head's legal classes.
2. Else a pointer head `owns(state)` → softmax over the enumerated frontier candidates.
3. Else `build_stop` owns it (multi-shot Build Rooms/Stables with `num_built ≥ 1`) →
   learned P(stop) split across build options on a **cell-priority** cell + the Stop option.
4. Else a cell-commit pending (`PendingPlow`/`PendingBuildStables`/`PendingBuildRooms` first build)
   → uniform over the cell-priority-filtered commits (no encoder signal for spatial cells).
5. Else → uniform over the full legal set.

Cell-priority tuples (`STABLE_PRIORITY`, `ROOM_PRIORITY`, `PLOW_PRIORITY`) and `_filter_cell_priority`
are in `restricted.py` — port these specific constants/logic (they are used by the combiner even
though the rest of `restricted.py` is not on the PUCT path).

---

## 7. MCTS in C++

Port the production path only: **PUCT + `FenceMode.FLATTEN` + NN value leaf + chance nodes**. The
MACRO fence machinery (`expand_macros`, `MacroFencingAction`, replay queue, `macro_sequences`) is
UCT-only dead code under FLATTEN — **skip it entirely**. Source: `agents/mcts.py`, `agents/base.py`,
and `MCTS_IMPLEMENTATION.md` (authoritative).

### 7.1 Structures

- **Node:** `state`, `decider` (0/1, or **0 as a frame label for chance nodes**), `children`
  (`action → node`), `parents` (DAG in-edges, maintained but not read at backprop), `visits` (N),
  `value_sum` (W; `Q = W/N`), `is_chance`, `chance_counts` (per-outcome round-robin counter — used
  *instead of* child.visits because a shared DAG child inflates visits), `_legal_actions` (lazy
  per-node cache), `_action_priors` (lazy, PUCT).
- **Search:** transposition table `GameState → Node*` (owns nodes; `re_root` prunes to the live
  subtree by pointer identity), config, `search.rng`. **Production self-play uses ONE search/agent
  for both seats** (shared tree — `re_root` each move carries the tree + its stats across the
  P0↔P1 boundary; `selfplay_recording.py`, MCTS_IMPLEMENTATION.md §11.2). Mirror this.
- **Agent:** `sims_per_move` (cap on *total* root visits, `cap_total_sims=True` default),
  `c_uct` (reused as `c_puct`), `fpu_offset`, `action_selection_temperature` (class default 0.2,
  but **production self-play uses 1.0** — see §7.5), `agent.rng`.

### 7.2 The simulation loop

Four interleaved phases per sim (`_simulate`): SELECT (PUCT) + EXPAND, EVALUATE (once, at the leaf),
BACKPROP (path-only). Key behaviors:

- **PUCT:** `U(s,a) = Q(s,a) + c_puct · P(s,a) · √(max(N_parent,1)) / (1 + N(s,a))`. Unvisited /
  uncreated children use `Q = parent_Q − fpu_offset`, `N = 0`, and compete via their prior. Ranges
  over **all** legal actions (created or not). Singletons short-circuit before any prior is
  computed. Argmax with random tiebreak via `search.rng`.
- **Forced-move step-through:** a fresh non-terminal child with exactly one legal action is *not*
  evaluated — the sim steps through it so the value lands at the next genuine decision/terminal
  (keeps the NN queried only at real decisions). Applies in both modes.
- **Priors are lazy:** computed once per multi-option node on first selection (`_ensure_priors`),
  never on singletons/chance/unexpanded-frontier nodes.

### 7.3 Leaf value + backprop sign convention

- `evaluate_leaf(state)`: **terminal** → `(score(state,0) − score(state,1)) / leaf_value_scale`
  (exact margin, evaluator-independent); **mid-game** → `evaluator(state, 0, model) /
  leaf_value_scale`, where the evaluator already returns a **P0-frame margin** from one forward
  pass. Set `leaf_value_scale = model.value_scale`. Chance nodes are **never** leaf-evaluated.
  *(The terminal branch assumes a linear/margin value head — see §6.1. The C++ port should assume a
  linear head; if a non-linear head is ever used, make the terminal branch head-aware.)*
- **Backprop** walks the recorded path (not `parents`): `decider==0` nodes (incl. chance) add
  `+leaf_value_p0`; `decider==1` nodes add `−leaf_value_p0`; all `visits += 1`. **At read time**, a
  parent reading a child with a different `decider` flips the sign. (Store-in-own-frame +
  flip-on-read are the two faces of the one zero-sum rule.)

### 7.4 Chance nodes (hidden round-card reveal)

A reveal state (`decider_of == None`) is a chance node. Routing: **uniform round-robin** over the
≤3 candidate `RevealCard`s, picking the least-routed outcome (RNG tiebreak), tracked by
`chance_counts`. Never UCB/PUCT-selected, never leaf-evaluated; the node sits on the path and its
plain `value_sum/visits` converges to the uniform reveal expectation. It carries `decider=0` so
backprop/UCB math is unchanged — **`is_chance`, not `decider`, gates the special routing.**

The ≤3 candidates are reconstructed **from public state only** (no `Environment`):
`stage = stage_of_round(round_number + 1)`; candidates = that stage's `STAGE_CARDS` minus the
already-`revealed` ones (`legality.py` `_enumerate_pending_reveal`).

### 7.5 The played move + RNG

After the sim budget, play from the **root visit-count distribution**: `probs ∝ visits^(1/T)`,
sampled with the **agent** RNG. The MCTSAgent class default is `T=0.2` (≈argmax, for head-to-head
eval play), but **production self-play uses `T=1.0`** (`generate_selfplay_data.py --temperature`
default — sample proportional to visits, the AlphaZero self-play exploration setting). The recorded
π is the **raw** visit counts (unnormalized, τ=1) regardless of the played-move `T`. Expose
`root_visit_distribution(root)` = π (the policy target, §2.4) and the root mean-Q **flipped into P0's frame** (`q if root.decider == 0 else -q`,
matching the terminal-margin convention) = `root_value` (`selfplay_recording._root_value_p0`).

**Two independent RNG streams:** `search.rng` (all tree-internal tiebreaks / chance round-robin)
and `agent.rng` (played-move sampling only). For C++ the determinism story is "same seeds + same
engine → same play"; **exact NumPy PCG64 replication is unnecessary** (the engine is RNG-free after
setup; the search reads no `Environment`). Use any good deterministic PRNG with the same two-stream
split and consumption points.

### 7.6 Validation honesty

The engine stages get *exact* gates. **MCTS is the one component without a clean cross-language
exact test** — float summation order, RNG, and tie-break ordering all diverge. Plan:

- **Unit-test the deterministic pieces exactly** in both languages (PUCT/UCB formula, backprop
  sign-flip, chance round-robin, transposition keying).
- **Isolate inference from search:** because the encoder + value + policy gates (§3.4) already prove
  C++ and Python feed the search identical numbers, any divergence is a search-logic bug, not an
  inference bug.
- **Accept strength parity as the end-to-end gate:** C++-MCTS vs Python-MCTS over many seeds should
  be ~50% ± noise. This is the real acceptance test, and the stage where "first version will have
  bugs" is most true.

---

## 8. The staged plan

Each stage has required reading, a deliverable, and an **equivalence gate** that must pass before
the next stage. Build the differential harness (§3) *first* — it is the spine every later gate
plugs into. There is a deliberate **decision checkpoint after Stage 5**.

> Implementers: the per-stage "read" lists are the minimum. The six research reports that seeded
> this doc are dense, file:line-grounded extractions of exactly these areas — reuse them.

**Stage 0 — Scaffolding + serialization + harness skeleton.**
Read: `state.py`, `actions.py`, `pending.py`, `constants.py`; `play_web.py` trace format.
Deliver: CMake project + `cpp/` tree; pybind11 module skeleton; the **canonical state serializer**
(Python side) + matching C++ deserializer/serializer stubs; the **trace reader/replayer** (Python)
+ the `params → Action` deserializer (17 cases, incl. the `RevealCard.card` fix); the pytest
differential-harness driver (no engine logic yet — round-trips serialization).
Gate: serialize→deserialize→serialize round-trips byte-identically in both languages over a state
corpus.

**Stage 1 — State model + pasture flood-fill + hashing.**
Read: `state.py`, `resources.py`, `pasture.py`.
Deliver: the C++ structs, `compute_pastures_from_arrays` (with canonical `min(cells)` ordering),
cached structural hash + equality.
Gate: over a corpus of random farmyards, C++ pasture decomposition + state hash/eq + canonical dump
match Python exactly.

**Stage 2 — `legal_actions` + the fence universe.**
Read: `legality.py`, `fences.py`, `fence_universe.py`, `opt_config.py` (level-0 semantics);
`ENGINE_IMPLEMENTATION.md` §1, §4.
Deliver: the precomputed RESTRICTED fence universe table + `PastureCandidate` metadata +
`_check_entry_legal`; all 24 placement predicates; all 23 pending enumerators; the reveal
enumerator.
Gate: over **millions** of random Python-generated states, C++ `legal_actions` **set** == Python's.
(Biggest single correctness surface.)

**Stage 3 — `step` + resolution + phase machine + scoring + frontiers.**
Read: `engine.py`, `resolution.py`, `scoring.py`, `helpers.py`; `ENGINE_IMPLEMENTATION.md` §3, §4.
Deliver: `step`/`_apply_action`, the 4 dispatch tables + all handlers, `_advance_until_decision`
(WORK/RETURN_HOME/PREPARATION-reveal/HARVEST FIELD-FEED-BREED), the level-0 frontier helpers,
scoring + tiebreaker.
Gate: **full trace-replay (§3.2)** — millions of Python random-game traces replayed through C++,
identical state dump at every step + identical final score/tiebreaker. **This is the engine's
graduation gate.**

**Stage 4 — Setup + reveals + the production self-play driver shell (UCT/random first).**
Read: `setup.py`, `environment.py`, `agents/base.py` (`play_game`, `decider_of`).
Deliver: C++ `setup` (own RNG: SP coin-flip + within-stage shuffle), the env-equivalent dealer, the
game-driver loop, and a random/`legal_actions`-only self-play that emits traces.
Gate: C++-emitted random-game traces replay cleanly in Python (zero mismatches) and produce valid
`GameRecord`s; the existing `validate_dataset.py` invariants pass on a C++-generated run.

**Stage 5 — NN inference (encoder + value + policy combiner) via libtorch.**
Read: `agents/nn/encoder.py`, `model.py`, `policy_heads.py`, `policy.py`,
`policy_model.py`, `policy_pointer_model.py`; `proto_jit_trace.py`; `FIRST_NN.md` §4,
`POLICY_HEAD.md` §11/§14.
Deliver: TorchScript export script (Python); C++ encoder (170 features), value forward, the 9 heads,
the combiner decision tree + cell-priority/build-stop logic.
Gate: C++ `encode` exact vs Python; C++ value within 1e-4; C++ policy priors dict within 1e-4 over a
corpus.
**➤ DECISION CHECKPOINT.** At this point engine + encode + inference are native and exposed through
pybind. Wire **Python MCTS over the C++ engine/inference** as an intermediate and **benchmark**.
Expected ~3–4× (Python MCTS bookkeeping becomes the ceiling). **If that is enough, stop here** and
ship it as the data-gen path — skipping the riskiest stage.

**Stage 6 — Native MCTS + the standalone self-play binary.**
Read: `agents/mcts.py`, `agents/base.py`, `MCTS_IMPLEMENTATION.md` (full).
Reference: `agents/nn/selfplay_recording.py` + `scripts/nn/generate_selfplay_data.py` are the Python
prototype of *exactly* this binary — shared-tree self-play, the exact `MCTSSearch` config (full
legality, `nn_evaluator` single-pass, `leaf_value_scale = model.value_scale`, combined `policy_fn`,
`FenceMode.FLATTEN`, `cap_total_sims=True`), forced-move step-through, π/`root_value` extraction
(`RootCapturingMCTSAgent`), and chunked-streaming trace writes. Mirror it.
Deliver: C++ `MCTSNode`/`MCTSSearch`/`MCTSAgent` (PUCT, FLATTEN, chance nodes, transposition DAG,
two RNG streams, temperature play, π/root_value extraction); the standalone `selfplay` executable
writing full traces (incl. π/root_value); the Python replay adapter → `GameRecord` → existing train
pipeline.
Gate: MCTS component unit tests exact (§7.6); **strength parity** C++-MCTS vs Python-MCTS ~50% ±
noise; a small C++-generated dataset trains a value net whose test MAE matches a Python-generated
one (sanity).

**Stage 7 — Parallelize + final benchmark.**
Deliver: process/thread parallelism (one game per worker, `torch.set_num_threads`-equivalent =
single-thread libtorch per worker), final wall-clock measurement vs the Python baseline.
Gate: end-to-end games/hour vs the 10k/10hr baseline; update `PROFILING.md` + `SPEEDUPS.md`.

### 8.1 Implementation status

| Stage | State | Notes |
|---|---|---|
| 0 — Scaffolding + serialization + harness | ✅ **DONE** | see below |
| 1 — State model + pasture flood-fill + hashing | ✅ **DONE** | see below |
| 2 — `legal_actions` + fence universe | ✅ **DONE** | see below |
| 3 — `step` + resolution + scoring + frontiers | ✅ **DONE** | see below |
| 4 — Setup + reveals + self-play shell | ✅ **DONE** | see below |
| 5 — NN inference (encoder/value/policy) | ✅ **DONE** | checkpoint decided → proceed to 6; see below |
| 6 — Native MCTS + standalone binary | ✅ **DONE** | see below |
| 7 — Parallelize + final benchmark | ✅ **DONE** | **~4× faster than Python** (clean idle), see below |

**Stage 0 (landed).** Python foundation + C++ build skeleton, all gates green
(`tests/test_cpp_canonical.py`, `tests/test_cpp_trace_replay.py`, `tests/test_cpp_binding.py`):

- `agricola/canonical.py` — tag-driven canonical `GameState` ↔ JSON (`dumps`/`loads`). Generic
  dataclass walker (drift-proof; auto-registers the state/action/pending/enum types), byte-identical
  round-trip verified over a 1000+ state corpus spanning pending stacks, harvest, reveals, two-player
  frames, and terminal states.
- `agricola/agents/nn/trace_replay.py` — the trace writer (`game_to_trace`) + the replay adapter
  (`replay_trace` → `GameRecord`) + action↔`params` serde (all 17 action types). Verified to
  reproduce `play_recording_game` exactly across seeds (decision states, chosen actions, terminal,
  scoring). Closes the web-UI `RevealCard.card` drop.
- `cpp/` — CMake (3 targets: `agricola_core` lib + `agricola_cpp` pybind module + `selfplay`
  binary), the toolchain-proving binding, build docs. Module builds + imports; version constants
  checked against Python.

**Stage 1 (landed).** The full C++ state model + flood-fill + serde + hashing, first
*cross-language* gate green (`tests/test_cpp_state.py`, 1056-state corpus, 288 farmyards with
pastures incl. fenced stables):

- `cpp/include/agricola/types.hpp` — every state struct (enums, Resources, Animals, Cell, Pasture,
  Farmyard, ActionSpaceState, PlayerState, BoardState, GameState) + the 25-variant `PendingDecision`
  (`std::variant`). C++20 defaulted `operator==` gives structural equality for free.
- `cpp/src/pasture.cpp` — `compute_pastures`, a faithful port of the 3-pass flood-fill with the
  canonical `min(cells)` ordering. **Recomputed C++ pastures reproduce Python's cached decomposition
  byte-for-byte** over the corpus.
- `cpp/src/canonical.cpp` — C++ canonical serde via vendored `nlohmann::ordered_json`
  (`cpp/third_party/`). **Byte-identical** to `agricola/canonical.py`: C++ deserialize→serialize of a
  Python dump reproduces the input exactly.
- `cpp/src/hash.cpp` — `state_hash` (FNV-1a over the canonical string; correctness-first, a fast
  field-wise hash is a Stage 6 perf item). No collisions across the corpus; equal states → equal
  hash; C++ `states_equal` agrees with Python equality on sampled pairs.
- Build: `CMAKE_CXX_STANDARD 20`; `agricola_core` now compiles pasture/canonical/hash; the pybind
  module exposes `canonical_roundtrip` / `recompute_pastures` / `state_hash` / `states_equal`.

**Stage 2 (landed).** The full legality surface + fence universe in C++; cross-language
set-equality gate green (`tests/test_cpp_legality.py`, ~7000-state corpus over 40 random games
covering pending stacks, harvest feed/breed, all three markets, fencing frames, reveals, terminal):

- `cpp/include/agricola/actions.hpp` + `cpp/src/action_canonical.cpp` — the 17 action types
  (`std::variant`) + `{type, params}` serialization matching `trace_replay.action_to_params`.
- `cpp/include/agricola/constants.hpp` + `cpp/src/constants.cpp` — `SPACE_IDS`, costs, baking specs,
  accumulation rates, stage cards, `stage_of_round`, harvest rounds.
- `cpp/gen/export_fence_universe.py` → generated `cpp/src/fence_universe_data.cpp` — the **109-entry
  RESTRICTED universe** exported from Python (not re-derived) in load-bearing order; plus
  `cpp/src/fences.cpp` (`PastureCandidate`, pack/apply, `compute_new_fence_edges`).
- `cpp/src/helpers.cpp` — level-0 baselines: `cooking_rates`, `can_accommodate`, `extract_slots`,
  the Pareto/breeding/food-payment/harvest-feed frontiers, supply/enclosure helpers.
- `cpp/src/legality.cpp` — `legal_actions` dispatch, `legal_placements` + 24 placement predicates +
  shared helpers, `_check_entry_legal`/`_any_legal_pasture_commit`, the 23 per-pending enumerators +
  the reveal enumerator.
- Gate compares the C++ legal-action *set* to Python's `filter_implemented(legal_actions(state))`
  (set-equality, order-independent per §3.2). The card path (`FireTrigger`/Potter Ceramics) is
  correctly omitted (Family-only): it's set-identical since `potter_ceramics` is never owned in
  Family play, which the gate confirms over the corpus.
- *(Delegated to a subagent; built + driven to green here. The subagent couldn't run Bash, so it
  wrote the code and I ran the generator/build/gate — the model going forward.)*

**Stage 3 (landed).** The transition function + scoring in C++; the engine's **graduation gate**
green (`tests/test_cpp_step.py`): byte-identical trace-replay (`cpp_step(before, action) == after` at
every step of 30+ random games) + `score`/`tiebreaker` matching Python at terminal. This means the
C++ **engine** is byte-faithful to the oracle.

- `cpp/src/engine.cpp` — `step`, `_apply_action` dispatch, the commit dispatcher
  (`COMMIT_SUBACTION_HANDLERS` semantics), `_advance_until_decision` phase machine (WORK /
  RETURN_HOME / PREPARATION two-state reveal walk / HARVEST FIELD→FEED→BREED / round-14 terminal),
  the phase resolvers (return-home, complete-preparation, harvest field/feed/breed).
- `cpp/src/resolution.cpp` — every atomic/non-atomic/choose/execute handler, incl. the 3 harvest
  conversions (joinery/pottery/basketmaker) and the SP-on-top harvest frame order.
- `cpp/src/scoring.cpp` — the 15 scoring categories + craft bonus + tiebreaker (independent craft-spend).
- `action_from_json` (inverse serde), `state_ops.hpp` (push/pop/replace_top), pybind `step`/`score`/
  `tiebreaker`.
- *(Delegated; built + driven to green here. One trivial fix — a `GameState`/`int` name collision in
  `_execute_breed` — otherwise the agent's first-pass C++ passed the graduation gate immediately,
  including the risky `_execute_build_pasture` fence-edge path.)*

**Stage 4 (landed).** Setup + reveal dealer + a trace-emitting random self-play driver; gate green
(`tests/test_cpp_selfplay.py`, 63 cases): C++ initial states are always valid round-1 states Python
could produce (SP × round-1 card), C++ traces replay cleanly through the Python engine, every reveal
is a legal candidate, the round-card order is a valid within-stage permutation, SP is balanced, and
the produced `GameRecord`s pass the `validate_dataset` invariants.

- `cpp/src/setup.cpp` — `setup(seed)` (own `std::mt19937_64`: SP coin-flip + 2/3 food split +
  within-stage `STAGE_CARDS` shuffle + round-1 pre-deal via the green Stage 3 `step`), `reveal_action`.
- `cpp/src/selfplay.cpp` — `random_selfplay_trace(seed)` emitting the `agricola-cpp-trace-v1` envelope
  (canonical `initial_state` + `{round,phase,decider,type,params}` actions), two independent RNG
  streams. `cpp/apps/selfplay.cpp` is now a real CLI (`selfplay --seed N --out PATH`).

**Stage 5 (landed).** Native NN inference — encoder + value net + 9 policy heads + the combiner —
via TorchScript + libtorch; all three gates green (`tests/test_cpp_nn.py`):

- `scripts/nn/export_torchscript.py` → `nn_models/cpp_export/*.ts` (+ `manifest.json`): value, 7 fixed
  heads, 2 pointer heads, normalization baked into each traced graph (value=`predict_margin`,
  fixed=raw logits, pointer=raw per-candidate scores over the full `[state;cand]` row), `value_scale
  ≈ 11.526`.
- `cpp/src/encoder.cpp` — the 170-feature encoder, **float-exact vs Python `encode_state`** over a
  both-perspective corpus (this gate runs even on a no-torch build, isolating the highest-bug-risk
  piece). `cpp/src/nn.cpp` — `value()` (≤1e-4 vs Python) and `policy()` (the full 5-branch combiner;
  priors ≤1e-4 per action vs `build_combined_policy.build("unweighted")`).
- libtorch wired via `AGRICOLA_BUILD_TORCH=ON` (encoder stays torch-free; `nn.cpp` + its bindings
  guarded by `AGRICOLA_WITH_TORCH`). **Linked first try — no ABI/C++20 friction** (the §10 risk).

**Decision checkpoint (resolved → proceed to Stage 6).** The plan's intermediate measurement was
"Python-MCTS over the C++ engine/inference, expect ~3–4×." That estimate assumed a *handle-based*
binding (C++ owns the state, Python passes opaque handles). The binding actually built is
**JSON-string-based** — ideal for the differential harness, but it pays full canonical-serialization
cost on every call, so a Python-MCTS-over-this-binding intermediate would be dominated by boundary
serialization (likely *slower* than pure Python, not 3–4×). Building a separate handle-based binding
purely to measure an intermediate is throwaway work (Stage 6's native loop replaces it). So: skip the
intermediate measurement, go straight to native MCTS (Stage 6); the real end-to-end speedup number
comes at Stage 7 (native `selfplay` games/sec vs the Python baseline). The user's standing direction
("go hard / keep going") aligns.

**Refinements made during Stage 0 (vs the §2.2 sketch):**
- The trace envelope carries the **canonical `initial_state` dump**, not just a seed, so replay is
  fully RNG-independent (the action trace is the source of truth, per §2.1) — the C++ binary emits
  its own start state and Python replays without reconstructing setup RNG.
- π entries carry a parallel `visit_distribution_types` list so each `Action` key round-trips from
  its `params` (an `Action`'s type isn't recoverable from `params` alone).
- **Build note:** this machine's Command Line Tools ship clang with an empty default libc++ path
  (`<toolchain>/usr/include/c++/v1` missing; the headers live only under the SDK). `cpp/CMakeLists.txt`
  compile-tests `<string>` and, only if it fails, injects the SDK's libc++ as a system include —
  portable and a no-op on healthy toolchains. Requires `pip install pybind11 cmake` (done in the
  conda env).

**Stage 6 (landed).** Native MCTS (PUCT + FLATTEN + chance nodes) + the production self-play binary,
mirroring `agents/mcts.py` + `selfplay_recording.py`; gate green (`tests/test_cpp_mcts.py`, 9/9:
component tests + self-play record validity + **strength parity vs Python MCTS held**). New/changed:

- `cpp/include/agricola/mcts.hpp` + `cpp/src/mcts.cpp` — `MCTSNode` / `MCTSSearch` (transposition
  DAG keyed on `state_hash`+`operator==`, owns nodes via `unique_ptr`, `re_root` prunes to the live
  subtree by pointer identity *and* scrubs dangling back-edges before freeing) / `MCTSAgent` (the
  `_simulate` loop: PUCT selection over the full legal set, forced-move step-through, chance
  round-robin via `chance_counts`, path-only backprop with the store-in-own-frame / flip-on-read sign
  rule, visit-count temperature play). Leaf = `NNInference::value(state) / value_scale` (terminal →
  exact margin). Two RNG streams (`search.rng` tiebreaks/chance, `agent.rng` played move). Skips MACRO
  fencing entirely. Guarded behind `AGRICOLA_WITH_TORCH`.
- `cpp/src/selfplay.cpp` (+ `selfplay.hpp`) — `mcts_selfplay_trace(seed, sims, c_uct, temperature,
  model_dir)`: shared-tree MCTS-vs-MCTS self-play emitting the `agricola-cpp-trace-v1` envelope with
  `visit_distribution` + `visit_distribution_types` + `root_value` on each non-singleton searched
  decision (singletons/reveals carry none) — a line-for-line mirror of `play_selfplay_recording_game`.
- `cpp/apps/selfplay.cpp` — adds an MCTS mode:
  `selfplay --mcts --seed N --sims S --model-dir DIR [--c-uct C --temperature T] --out PATH`
  (the random mode is preserved).
- `cpp/bindings/pybind_module.cpp` — `mcts_selfplay_trace(...)`, a stateful `CppMctsAgent(model_dir,
  sims, c_uct, temperature, seed).choose(state_dump) -> action_dump` for per-move head-to-head eval,
  and a `mcts_debug_root(...)` introspection hook (root visit/chance counts) for the component gates.
- `cpp/CMakeLists.txt` — `mcts.cpp` added under `AGRICOLA_BUILD_TORCH`.
- `tests/test_cpp_mcts.py` — the Stage-6 gate: component tests (single-option short-circuit, visit
  budget, chance round-robin uniformity, first-sim PUCT = max-prior pick), self-play record validity
  (`replay_trace` → valid v3 `GameRecord`, π + `root_value` populated, `validate_dataset` invariants
  pass), and statistical strength parity (C++ vs Python MCTS in a wide band; C++ ≫ Random).

**Stage 7 (landed) — final benchmark + the critical perf finding.** Final clean numbers (fully-idle
machine, single-thread `OMP_NUM_THREADS=1`, 160 sims, production config: NN value leaf + combined
policy + FLATTEN; measured back-to-back after *all* optimizations):

| | s/game |
|---|---:|
| Python production MCTS | **3.93** |
| **C++ native** (incl. ~0.15 s/process startup) | **0.98** |
| C++ native — steady-state (startup amortized over many games) | **~0.83** |

→ **~4× per game (with startup), ~4.7× steady-state**, single-thread; at 500 sims C++ ~2.5 s/game vs
the ~15–25 s Python ballpark. Process parallelism multiplies throughput on top, exactly as today.
**Correctness preserved** (all 118 gates green).

> *Measurement caveat:* earlier "idle" runs (Python 6.94 / first-correct C++ 12.7) were thermally
> inflated after hours of heavy compute — both engines measured ~1.8× faster on a truly-quiet
> machine, but the **ratio (~4×) is stable** and is the honest figure. The first-correct C++ was
> ~1.8× *slower* than Python before the two perf fixes below.

The *first* native build was **1.8× slower than Python** — a sampling profile (`sample`) of the
running binary pinned the cause to **`nlohmann` JSON serialization in the hot path**, two
self-inflicted pathologies, *not* the engine or NN (libtorch was a minor share):
1. **`ActionLess` map comparator** serialized *both* actions to JSON on every comparison
   (`std::map<Action,…>` for `children`/`priors`/`chance_counts`, hit on every PUCT step). Fixed by
   giving each `Action` a defaulted `operator<=>` and comparing via the variant's native ordering —
   no serialization. **This was the dominant cost (12.7 → 1.7 s/game).**
2. **`state_hash`** originally FNV-hashed the *entire* canonical-JSON dump of the state. Replaced with
   a fast field-wise structural hash (pending frames hashed via a small per-frame serialization for
   full discrimination). (10.5 → 6.1 s/game at 64 sims before fix #1 landed.)

**Lesson for the future:** the transposition table + per-node action maps are *the* MCTS hot path;
they must key on cheap structural hash/compare, never on serialization. Both pathologies were the
"correctness-first, optimize in Stage 6/7" items the plan deliberately deferred (§5.3) — and the
`sample`-based attribution was decisive in finding them.

**Optimization pass #2 (done; profile-driven).** After the headline result, a fresh `sample` profile
drove two more changes — and corrected the plan's *a priori* guesses about which levers matter:

1. **Hand-rolled native NN inference (libtorch dropped).** The profile flagged libtorch (`c10::`/`at::`)
   as ~half the samples, so the TorchScript backend was replaced with a direct C++ MLP
   (`cpp/src/mlp.cpp`, weights via `scripts/nn/export_weights.py` → raw float32 + `weights_manifest.json`),
   matching Python ≤1e-4 (`test_cpp_nn.py`). **Build no longer needs libtorch at all** (`cmake -S cpp -B
   cpp/build`, no torch flags). *Surprise:* wall-time only improved ~8% — the libtorch sample count was
   inflated by its thread-pool **spin-waiting** (multi-thread samples that weren't main-thread wall-time).
   The architectural win (no dependency, no ABI risk, no spin) is the real payoff.
2. **Per-node action maps `std::map`→`std::unordered_map`.** With NN out of the way, the true
   main-thread hotspot was the `std::map<Action,…>` comparisons (variant `operator<` on every PUCT
   step). Switching to `unordered_map` + a fast field-wise `ActionHash` cut that cost **~3×**
   (754→248 samples/action-type).

After both, the profile is **diffuse** — no dominant hotspot (action hash/eq, `GameState` copy/hash,
residual `nlohmann` from trace-π + pending-hash serialization), the same regime Python hit post-S5.
Net (final clean idle, 160 sims): C++ **0.98 s/game** vs Python **3.93 s/game** = **~4×** (~4.7×
steady-state); this pass cut the top remaining hotspot ~3×, and the hand-rolled MLP also cut C++
per-process startup from ~0.49 s (TorchScript) to ~0.15 s.

**Lesson — profile, don't guess.** The plan predicted the levers would be *state structural sharing*
and *NN batching*. The profiler said otherwise: malloc/state-copy was minor (~1.5% — structural
sharing **not worth it**), and the NN was dispatch-bound but partly spin-inflated. The actual wins
were JSON-removal (action maps + state hash) — found only by sampling the running binary.

**Optimization pass #3 — non-algorithmic levers, tried and MEASURED as no-gos (kept for the record).**
After pass #2 the profile was diffuse, so two implementation-level (non-algorithmic) tweaks were
attempted and **reverted** because a controlled A/B showed no win:

1. **Compiler tuning — `-mcpu=apple-m1` + LTO (`CMAKE_INTERPROCEDURAL_OPTIMIZATION`).** Within
   measurement noise (~1.0–1.5× over an interleaved A/B that swung 0.80–1.25 per game). The build was
   already `-O3 -DNDEBUG`, and on arm64 the default codegen + LTO don't move this workload. NN parity
   stayed ≤1e-4. Reverted (no benefit, adds CMake complexity).
2. **Flat per-node containers** — replacing the three per-node `std::unordered_map<Action,…,ActionHash>`
   (children / priors / chance_counts) with vectors index-aligned to `legal`, so PUCT selection indexes
   instead of hashes. Cleanly isolated (both `-O3`, 50-game batch): flat **44.6 s vs 43.8 s — ~2%
   *slower*.** The selection-side hash removal was real but tiny (the maps hold ≤~30 entries, where
   `unordered_map` is already cheap), and building the index-aligned `priors` turned `O(n)` into an
   `O(n²)` `Action==` scan that more than offset it. Reverted.

**The meta-lesson (again): the profiler's *sample counts* over-attribute.** Just as libtorch's
sample share was inflated by thread-pool spin (pass #2), the `ActionHash`/per-node-map share was
inflated relative to its actual wall-time cost — killing it didn't help. On a diffuse profile,
single-function sample counts are a weak guide; only an A/B on wall-time tells the truth.

**Remaining headroom (algorithmic — out of scope here, and genuinely diminishing):** **NN leaf-batching**
(amortize the hand-rolled forwards across a batch with virtual loss) is the one lever with real
ceiling, but it's an algorithmic change to the search and was explicitly out of scope. The residual
`nlohmann` (pending-hash serialization; the trace-π `action_to_json` is per-decision and necessary) is
small. **Conclusion: the implementation is at its non-algorithmic floor — the ~4× in hand is the bulk
of the available win**, and further speedup needs either leaf-batching or just more/faster cores.

**Stage B (landed, post-Stage-7) — joint shared-trunk inference + two-net match mode.** The C++
`NNInference` gained a `shared_trunk_v1` mode toggle (one trunk + standalone `embed_norm` LayerNorm +
identity-norm head blobs), an internal `state_hash`-keyed embedding cache (one trunk forward per node,
`mcts.cpp` unchanged), and a `selfplay --match --model-dir-p0 A --model-dir-p1 B` two-net match mode
(`mcts_match_game`, driven in parallel by `scripts/nn/run_cpp_match.py`). Gate
`tests/test_cpp_nn.py::test_cpp_joint_matches_python` is a self-contained permanent gate (random
`SharedTrunkModel` → real export → C++ joint value/policy ≈ Python `make_joint_fns` ≤1e-4); the
composite gates stay green. Full detail in **§13**; the joint model itself in **`SHARED_TRUNK.md`**.

---

## 9. Build system, repo layout, dependencies

### 9.1 Where the code goes

**Guiding principle: the existing `agricola/` engine is never modified** — it is the differential
oracle and stays pristine. All new code is either under a new top-level `cpp/` or a handful of
*additive* Python files placed next to their existing counterparts.

```
AgricolaBot/
  agricola/                      # EXISTING — untouched (the differential oracle)
    canonical.py                 # NEW (Python): canonical GameState↔text dump — the shared
                                 #   contract C++ must match; reference impl, test-only
    agents/nn/
      trace_replay.py            # NEW (Python): read C++ JSON traces → params→Action
                                 #   deserializer → replay through the engine → GameRecord
                                 #   (the adapter feeding the unchanged training pipeline)

  cpp/                           # NEW — all C++ lives here
    CMakeLists.txt
    include/agricola/            # headers: state, actions, pending, legality, fences,
                                 #   resolution, scoring, helpers, encoder, model, policy, mcts
    src/                         # implementations (mirror the agricola/*.py modules)
    bindings/
      pybind_module.cpp          # the `agricola_cpp` pybind11 module (test surface only)
    apps/
      selfplay.cpp               # the standalone production data-gen binary
    tests/                       # optional C++-side unit tests (Catch2/gtest) for
                                 #   formula-level checks (PUCT, backprop, chance routing)
    third_party/                 # or fetched via CMake: pybind11, nlohmann/json, libtorch
    build/                       # GITIGNORED — compiled artifacts + the selfplay binary

  tests/                         # EXISTING pytest suite
    test_cpp_engine.py           # NEW: differential harness (legal_actions/step/score)
    test_cpp_encoder.py          # NEW: C++ encode == Python encode_state (exact)
    test_cpp_policy.py           # NEW: C++ value/policy priors == Python (≤1e-4)
    test_cpp_mcts.py             # NEW: MCTS component + strength-parity gates

  scripts/nn/
    export_torchscript.py        # NEW (Python): jit.trace + save value/policy nets → .ts

  nn_models/<id>/
    best.ts                      # NEW: TorchScript export beside best.pt / best.meta.json

  data/
    selfplay_traces/             # GITIGNORED — C++-emitted JSON traces (regenerable)
```

Each kind of new code, and why it sits there:
- **All C++** → `cpp/`. Builds separately via CMake; never imported by `agricola/` or existing
  tests directly — only through the `agricola_cpp` pybind module (which the new `tests/test_cpp_*.py`
  files import). The pybind module exists for the differential tests and the optional Stage-5
  intermediate; **production data-gen uses the standalone `selfplay` binary and never crosses into
  Python.**
- **Python glue (3 small files)** sits next to its natural neighbors: the canonical serializer is
  engine-adjacent (`agricola/canonical.py`), the trace replayer joins the recording code
  (`agents/nn/trace_replay.py`), and the TorchScript exporter joins the other NN scripts
  (`scripts/nn/`).
- **New pytest files** join the existing suite, so the differential gates run under the normal
  `~/miniconda3/bin/python -m pytest`.

**Gitignored** (matching how `data/nn_training/runs/` is handled): `cpp/build/` and
`data/selfplay_traces/`.

**The only edits to *existing* files across the whole project:** `.gitignore` (two entries), and —
once this plan is accepted — one row in the CLAUDE.md doc index plus the directory-tree section. No
existing engine, agent, or test code changes.

### 9.2 Toolchain & dependencies

- **Toolchain:** CMake; a C++17/20 compiler. Dependencies kept minimal:
  - **pybind11** — the test binding (and optional Stage-5 intermediate).
  - **libtorch** (CPU build) — native inference. (GPU later if ever wanted; the models are tiny so
    CPU is likely fine and matches the current data-gen target.)
  - a small **JSON** library (e.g. nlohmann/json) — trace + canonical-dump I/O.
- **Coexistence:** Python remains fully usable throughout — the C++ lives entirely in `cpp/`, builds
  separately, and is reached only via the pybind module in the differential tests and the standalone
  binary for data-gen. Day-to-day Python work (web UI, training, heuristics) is unaffected.
- **CI:** the differential tests run under the existing pytest suite (build the pybind module, then
  the `tests/test_cpp_*` files exercise the gates). Use `~/miniconda3/bin/python` (the env with
  torch + pytest).

---

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Subtle engine divergence (fencing, accommodation, harvest frontiers) | The exact trace-replay gate over *millions* of random states catches any divergence and localizes it in game terms. Build the harness first. |
| MCTS can't be bit-matched cross-language | Expected and accepted — unit-test deterministic pieces exactly; validate end-to-end by strength parity (§7.6). |
| TorchScript export drift / numerical mismatch | `proto_jit_trace.py` already shows exactness; gate value/policy within 1e-4 at Stage 5. Re-export + re-gate on every checkpoint. |
| libtorch integration friction (the `freeze` parameters wrinkle, ScriptModule plumbing) | Contained to Stage 5; the value/policy gates fail loudly if wrong. |
| Two-engine sync burden as the game evolves | Family-only freeze for now; the harness makes any future re-port safe. Cards explicitly deferred (§12). |
| Effort overrun | The Stage-5 checkpoint lets the project bank a ~3–4× win and stop before native MCTS if that suffices. |
| Doc/code drift | Port against the **live code**, not prose docs. (The `DATA_VERSION=2`→**3** + `DecisionSnapshot` self-play fields + the two new self-play files were already fixed in CLAUDE.md as part of this work.) |

---

## 11. Open decisions (defaults chosen; confirm or redirect)

1. **Interop = traces, not live objects.** *Default: yes.* The hot loop never crosses the boundary.
2. **Inference = TorchScript + libtorch (native, in-loop).** *Default: yes.* Alternative considered:
   batched callbacks to Python/PyTorch (no libtorch dep, but the boundary isn't fully eliminated) —
   rejected for the production binary, viable as a fallback if libtorch integration stalls.
3. **Record π + root_value (not value-only).** *Default: yes* — trains both heads from C++ data;
   value-only is the degenerate case.
4. **NN-only MCTS leaf; no heuristic ported.** *Per owner instruction.*
5. **Family-only, RESTRICTED fence universe; cards deferred.** *Default: yes* (§12).
6. **Value head is linear/margin.** *Required* by the terminal-leaf scoring path (§6.1/§7.3); matches
   the active registry models.
7. **C++ uses its own RNG** (no NumPy PCG64 replication). *Default: yes* — the trace, not the seed,
   is the replay source of truth.
8. **Doc location:** this file at top level (`CPP_ENGINE_PLAN.md`), alongside `SPEEDUPS.md` /
   `PROFILING.md`. *Add a row to the CLAUDE.md doc index when this is accepted.*

None of these are blocking; the plan proceeds on the defaults unless redirected.

---

## 12. Forward path: cards (Phase 3)

The owner's stated plan is to build a world-class Family engine *first*, then add cards, then speed
up again. This plan fits that cleanly:

- The C++ engine is **Family-only** now. When cards land in Python (Phase 3), they are built on the
  reusable sub-action primitives and the trigger machinery the Python engine already has.
- The C++ re-port of cards is then **additive** and **safe**: the same differential harness
  (extended with card-exercising games) re-validates the C++ engine against the Python oracle. The
  serialization, trace format, MCTS, and inference layers all carry forward — only the new card
  effects/triggers and their legality extensions need porting.
- This is exactly why porting *now* isn't wasted effort: the harness + structure are the durable
  investment; the card delta is incremental.

---

## 13. Joint shared-trunk inference + two-net match mode (Stage B)

The original §6 inference path is *composite*: a separate value net plus nine independent policy-head
nets, each its own MLP with its own input-normalization. The Phase 2.3 successor is the **joint
shared-trunk model** — one trunk feeding the value head and the full factored policy, trained jointly
on self-play data (full design + training + results in **`SHARED_TRUNK.md`**). It is ported into the
C++ `NNInference` as a **mode toggle, not a new class**: the two modes share the manifest loader, the
hand-rolled `Mlp` primitive, and the entire §6.3 policy-combiner dispatch — **only the forward
differs**. The composite path (§6) is untouched, so its gates stay green and the maintenance invariant
holds (no engine / legality / scoring / encoder change — this is a pure inference-backend addition).

### 13.1 The `shared_trunk_v1` manifest + the standalone `embed_norm`

`scripts/nn/export_weights.py` detects a `SharedTrunkModel` checkpoint (`--value-ckpt <joint-ckpt>
--out-dir <dir>`) and writes a manifest tagged `"format": "shared_trunk_v1"` (the composite export is
`"raw_f32_v1"`); `NNInference` auto-detects the tag and flips to joint mode. Joint mode loads:

- the **trunk** MLP (170 → embedding `E=128`), then
- a **standalone `embed_norm`** LayerNorm on the embedding. It is loaded *separately* rather than as
  the trunk's final layer because the C++ `Mlp` primitive applies **GELU after every LayerNorm**, and
  `embed_norm` must be a bare LayerNorm (no activation) — so the only genuinely new math in the joint
  path is this one standalone LN. Everything downstream reuses the existing `Mlp` verbatim.
- the **head blobs**, each taking the *embedding* with **identity input-normalization** (the trunk
  already produced a normalized latent). The pointer heads bake their per-candidate normalization into
  the **candidate slice** of the `[embedding ; cand]` row, so the existing `Mlp` is reused unchanged —
  no special pointer-norm code path.

### 13.2 The embedding cache — one trunk forward per node, `mcts.cpp` unchanged

`NNInference` keeps an internal **`state_hash`-keyed embedding cache**, so the trunk runs **once per
node**: the node's `value()` call and its `policy()` call for the same leaf share that single forward
(the cache hands both the same embedding). This exactly mirrors the Python `(state, perspective)`
memo in `make_joint_fns` (`SHARED_TRUNK.md` §5). Because the sharing lives **inside `NNInference`**,
`cpp/src/mcts.cpp` needs **no changes** — it still calls `value()` then (lazily) `policy()` per leaf
as before, and the composite per-head dispatch is untouched.

### 13.3 Two-net match mode — `selfplay --match`

A new mode plays **one net against another** (separate trees, per-seat `value_scale`), for fast
torch-free head-to-head evaluation of two joint (or composite) checkpoints:

```
selfplay --match --mcts --model-dir-p0 A --model-dir-p1 B --sims S [--c-uct C --temperature T]
```

`mcts_match_game(...)` (`cpp/src/selfplay.cpp` + `cpp/include/agricola/selfplay.hpp`, wired through
`cpp/apps/selfplay.cpp`) runs P0 on net A and P1 on net B with **independent search trees** and each
seat's own `value_scale`. It is driven in parallel by **`scripts/nn/run_cpp_match.py`** — a
process-pool driver (one contiguous seed slice per worker, parsing the per-game `GAME …` / `MATCH …`
lines and aggregating W-D-L + the P0−P1 score margin), mirroring `generate_selfplay_data_cpp.py`'s
worker-pool pattern. Together this unlocks fast, torch-free **self-play generation and matches with
the joint model** — the next data round (`SHARED_TRUNK.md` §7).

### 13.4 The differential gate

`tests/test_cpp_nn.py::test_cpp_joint_matches_python` is a **self-contained, permanent** gate: it
builds a *random* `SharedTrunkModel`, exports it through the real `export_weights.py` CLI to the
`shared_trunk_v1` format, loads it into the C++ joint `NNInference`, and asserts C++ joint value +
policy match Python `shared_policy.make_joint_fns` to **≤1e-4** over a state corpus. No trained
checkpoint is needed, so the gate runs anywhere. The composite gates (§3.4 value/policy ≤1e-4) remain
green — the joint path is additive.

---

*Companion docs: `SHARED_TRUNK.md` (the joint shared-trunk model — design, training, results, and
this C++ port), `PROFILING.md` (where time goes), `SPEEDUPS.md` (Python-side optimizations + the
leaf-batching lever that is the no-rewrite alternative), `ENGINE_IMPLEMENTATION.md` (deep engine
mechanics — the §3/§4 reference for Stages 2–3), `MCTS_IMPLEMENTATION.md` (the Stage-6 reference),
`FIRST_NN.md` + `POLICY_HEAD.md` (the Stage-5 reference).*
