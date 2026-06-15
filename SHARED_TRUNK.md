# Shared-trunk joint value+policy model (Stage B)

Design + implementation + results record for the **joint shared-trunk network** —
one trunk feeding a value head and the full factored policy, trained jointly on
self-play data, consumed by MCTS through one forward per node, and ported to the
C++ engine. This is the Phase 2.3 successor to the separate value net + nine
independent policy heads.

> **Status (2026-06-10):** built, trained (`joint_taper128`), and validated.
> The joint model **beats the previous-best setup** (champion value net + the 9
> separate unweighted policy heads) at 800-sim PUCT — Python (joint won) and a
> C++ replication of **198-2 = 99.0%, +12.95 margin**. The Python *and* C++
> inference paths agree ≤1e-4. Not yet promoted to `nn_models/best` (that pointer
> is a single value net; the joint model needs consumer wiring first).

---

## 1. Why

Two independent upgrades motivated this, and the honest framing (which the
results bear out) is that they're separable:

1. **Data + target upgrade — the real strength gain.** Train on the on-policy
   41k PUCT self-play games (DATA_VERSION 3, with π + root_value), and switch the
   policy from hard behavioral cloning of the played action to **cross-entropy
   against the visit distribution π** (the AlphaZero-correct soft target, only
   possible now that the data carries π). This is where the win comes from.
2. **Shared trunk — an efficiency/parameter-sharing play.** One trunk forward per
   MCTS node feeds both value and policy, instead of a value-net forward *and* a
   policy-net forward. Mostly an inference-cost win; not the strength lever.

The capacity sweep (§6) settled the trunk size first: **256×2** (extra width/depth
didn't help — the 170-feature count encoder is the binding constraint, not trunk
size; MAE was a *backwards* predictor of play strength).

---

## 2. Architecture — `SharedTrunkModel` (`agricola/agents/nn/shared_model.py`)

Fully architecture-agnostic (every width is a constructor arg):

```
input 170 → trunk MLP [256,256] → Linear→ embedding E=128 → LayerNorm(E)   (embed_norm)
  value head:     Linear(E→1)            → × target_std  (margin)
  7 fixed heads:  Linear(E→K_h)          → masked softmax (placement … fencing, build_stop)
  2 pointer heads: MLP([E ; cand]→64→1)  → per-candidate softmax
```

- **Reuses `ConfigurableMLP`** for the trunk and every head — no new MLP math.
- `predict_margin` / `value_scale` / dual-perspective antisymmetry are preserved
  bit-for-bit, so the value head is a drop-in value evaluator.
- **Pointer heads take `[embedding ; candidate]`** (not `[state(170) ; cand]`) —
  the trunk runs once on the state, the candidate features are concatenated to
  the *embedding*. This unifies the pointer heads onto the trunk *and* is cheaper
  than the standalone pointer model (no per-candidate state re-encode). The
  per-head fitted candidate-normalization rides as buffers.
- `config_dict()` + `NET_REGISTRY` registration so `save`/`load` round-trip.

The **taper** (E=128 < trunk width) is dual-purpose: it halves the wide policy
heads' per-leaf cost (fencing 110-way, sow 104-way: cost ∝ E×K) and gives a
compact latent for interpretability. The sweep said capacity doesn't help value,
so the bottleneck costs nothing there.

---

## 3. Data — one-pass, cached, memory-frugal (`shared_dataset.py`)

The joint model needs value + every head's examples from the *same* games with a
*consistent* split. `build_shared_datasets` reads each run dir's pickles **once**
and emits, per game: value rows (both perspectives of every decision state + the
terminal, margin target), fixed-head rows (decider-perspective + legal mask +
soft-π), and pointer-head rows (per-candidate features + soft-π). The
decider-perspective encoding is computed once and shared between a state's value
and policy rows.

**Caching + the two memory lessons.** This builder has **two distinct memory
peaks**, on opposite sides of the cache, and both have bitten on the 8 GB M1.
Treat this whole subsection as load-bearing — see the warning at the end before
touching `shared_dataset.py`.

*Peak 1 — the encode (cache-write) side.* It writes **one npz chunk per source
pickle** (`shared_v{tag}_chunks/`), so the encode peak is one pickle (~14 MB),
not a whole run dir. The first version accumulated an entire 30k dir in a float32
Python list (~4 GB at 6.3M rows) and was jetsam-killed; per-pickle chunking fixed
it (peak ~65 MB) and made it resumable. A cache hit is a pure `np.load`. (Mirror
`dataset.build_datasets_chunked`.)

*Peak 2 — the finalize (cache-read / assembly) side.* This is the one that OOM'd
at **57k games** and was fixed in a later session. Two traps compounded: (a)
`_load_or_encode_run_dir` loaded **every chunk fully into RAM up front** (all 579
chunk dicts ≈ 6–8 GB resident *before* assembly even ran); and (b)
`_finalize_payloads` built a **single combined `value__X`** (~4 GB float16) and
then sliced it into train/val/test with boolean masks — so the combined array and
its ~3.3 GB train-split copy were alive *simultaneously*, a 2× spike on top of (a).
Peak ≈ 10 GB → macOS compressed-memory **thrash** (looks "stuck" at 95% CPU with
tiny RSS and free-mem near 0; it is not stuck, it is crawling). The fix, which
must be preserved:
- `_load_or_encode_run_dir` returns chunk **`Path`s, not loaded dicts**, so the
  whole run dir is never resident; `_finalize_payloads` streams each chunk lazily
  from disk via `_src_load(src, key)` (one chunk's worth at a time).
- The big value tensor is built **directly into its three pre-allocated per-split
  arrays** — pre-scan the tiny `value__seed`s to size each split, then copy each
  chunk's rows into the right split and free the chunk. There is **never a combined
  `value__X`** to double. The small per-head arrays still use a (now lazy, path-
  based) `cat()`; only the value tensor needed the direct-to-split treatment.
- Result: peak **3.14 GB** at 57k (`ru_maxrss`), free-mem steady, no thrash; the
  subsequent training loop fits in ~1.5 GB more.

**Beyond ~117k games: stream, don't materialize (`shared_stream.py`).** The
finalize fix above bounds the *peak during the build*, but the result is still the
**whole dataset resident as torch tensors** for the entire training run — ~8.5 GB
at 117k games (the float32 π/mask/value-y tensors + torch overhead dominate; int8
feature storage only halves the X tensors and still lands at 8.5 GB), which
kernel_task-thrashes the 8 GB M1 (~13 min/epoch). The serious fix is to train
**directly off the on-disk chunk npzs**: `train_shared(..., stream=True)` /
`scripts/nn/train_shared.py --stream` swaps `build_shared_datasets` for
`build_shared_streams` (`shared_stream.py`). The training process RAM is then
bounded to **~2-3 GB regardless of corpus size** (117k, 250k, a million games all
train at the same footprint). The dense value + 7 fixed train tasks become
`_TaskStream`s (a per-task windowed-shuffle buffer of `--buffer-chunks`≈8 chunks,
reading only that task's keys from each chunk and only its train rows); the small
pointer-train + the 10%/10% val/test splits stay materialized (the eval loops
index them directly). The shared input norm + `target_std` are fit on value-train
by the same streaming float64 two-pass scan — never materializing the train value
tensor. The **training-loop body is unchanged**; only the data source differs, and
the in-RAM path remains the default (the tests exercise it). The win is *not
holding the full dataset*, so int8 storage is irrelevant under `--stream`. Measured
on the full 117k corpus (6 cached run dirs): training-process `ru_maxrss` ≈ {{RAM}}
(vs 8.5 GB in-RAM), free memory steady, no kernel_task thrash.

> **⚠ Why this is fragile — read before refactoring `_finalize_payloads`.** The
> memory behavior is **not covered by any test.** `test_nn_shared_dataset.py` runs
> on ~30 tiny games and checks only *correctness* (shapes, splits, π, cache
> round-trip); on data that small the peak is dominated by the torch import, so a
> memory regression is invisible. A future session that "tidies" the streaming
> build back into a load-all-then-`np.concatenate`-then-mask-slice will pass every
> test green **and silently reintroduce the 57k OOM** — which is exactly how the
> joint builder shipped the bug originally (it reused the value builder's interface
> but not its memory discipline). Keep the path-streaming + direct-to-split shape.
> (See also the project memory note on memory-frugal data code.)

---

## 4. Training — `shared_training.py` (CLI `scripts/nn/train_shared.py`)

Interleaves per-task batches through the shared trunk: each step samples a task
(value / a fixed head / a pointer head), draws a batch, backprops its loss into
the trunk + that head. Key choices:

- **Soft-π loss**: cross-entropy against the normalized visit distribution
  (`-(π · log_softmax(masked_logits))`); reduces to one-hot BC when π is absent
  (legacy data). Pointer heads use the segment-softmax analogue.
- **Per-head gradient balancing**: each head is sampled *equally often* regardless
  of row count, so the rare heads (bake ~700 examples vs placement's millions) get
  a real vote in the trunk. Value gets a configurable larger share. Open caveat:
  bake is untrainable/unmeasurable at ~700 examples — the robust answer is to
  uniform-fallback unreliable heads in the combiner, not to over-weight them.
- **Fast loader** (`_CyclicTensor`, batched index over in-memory tensors) + bs 2048
  — skips the per-row DataLoader (the dominant overhead; see NN_TRAINING_SPEEDUP).
- **Early-stop on value val-MSE only** (the most reliable single signal; head CEs
  are logged, not gated). `--save-all-epochs` so the final checkpoint is picked by
  *play*, not val-MSE — important because the warm-started trunk plateaus value
  early while the policy heads keep improving.
- **Warm-start** the trunk from the value-sweep winner (`sp_v_256x2_bs8192`).

### 4.1 Scaling to 117k — thinning + int8, and two warm-start bugs (2026-06-15)

Growing the corpus to **117k games** (the 57k + a 60k self-play run generated *by*
`joint_taper128_57k`) OOM'd/thrashed even with `--stream` (~1100 s/epoch). The
recipe that made it tractable on the 8 GB M1, producing **`joint_taper128_thin`,
the new strongest model** (REGISTRY.md):

- **Per-game snapshot-thinning** (`build_shared_datasets(snapshot_keep=…)` /
  `--snapshot-keep`): a seeded keep-fraction per chunk, **per run dir** (e.g.
  `[1/6]*5 + [1/2]` — keep 1/6 of each old-57k game's snapshots, 1/2 of each
  new-60k game's). Cuts rows *and* within-game autocorrelation (consecutive
  snapshots are near-duplicate with the same value target; the `snap6th`/`snap_half`
  finding). Value + fixed-head rows are thinned; the small pointer heads are kept
  whole. The mask is seeded by `(chunk, n)` so every key of a (chunk, task) is
  thinned identically — rows stay aligned (verified).
- **int8 feature storage** (`--store-dtype int8`): every encoder feature is an
  integer (verified; only ~0.25% of states have `pasture_cap_0 > 127`, capped —
  harmless), so int8 halves the feature tensors losslessly. Batches upcast to f32.
- **All CPU cores**: do NOT set `OMP_NUM_THREADS=1` for a *single* training process
  (that's for parallel self-play workers) — it throttles the matmuls to one core.
- Net: ~6.8 M train rows, ~3.5 GB resident, **~80 s/epoch** (≈13× the thrash).

> **Two load-bearing warm-start bugs fixed here — they had silently mis-calibrated
> *every* warm-started joint model.** Read before touching `init_from`:
> 1. **`target_std` transplant.** The shape-tolerant warm-start copied the source
>    model's *normalization buffers* (`input_mean/std`, `target_std`, pointer cand
>    norms) over the new data's. With a different data distribution that means the
>    value head trains against the new `target_std` (5.57) while `predict_margin`
>    and val-MAE use the source's (7.73) — a **1.39× scale error**. `val_mae_pts`
>    (`× target_std`) inflates; `val_mse` (scale-free) does *not* — which is exactly
>    why a fix can move one and not the other. **Fix:** transplant weights only;
>    keep the new data's norm + `value_scale = float(model.target_std)`.
> 2. **`value_scale`-measurement `NameError`** (`x.shape[0]` → `diff.shape[0]`): the
>    post-hoc measurement crashed on any run that *finished*, so `value_scale` froze
>    at the stale warm-start value — the root of the registry's "stale value_scale"
>    complaints.
> **And `value_scale` is distribution-dependent** — the same model measured 3.02 on
> its low-variance thin val but 6.25 on a common game-state set. MCTS divides each
> leaf value by `value_scale` so one `c_uct` is comparable across models, so **fair
> matches require measuring both seats' `value_scale` on the SAME state set** (the
> stored manifest values aren't comparable); patch the export manifests before a
> match. See `scripts/play_mcts_match.py --leaf-value-scale`.

---

## 5. Inference — `make_joint_fns` (`shared_policy.py`), one forward per node

Returns `(value_fn, policy_fn)` for MCTS. The win: **both are evaluated from the
decider's perspective**, so a single trunk embedding serves both (value is then
sign-flipped into the P0 frame — the leaf contract). The embedding is **memoized
per `(state, perspective)`**, so the value call and the policy call for the same
leaf hit one forward — **`mcts.py` needs no changes** (the memo does the sharing;
no leaf "reorder" required). `policy_fn` mirrors `make_policy_fn`'s dispatch
exactly (fixed head / pointer head / build_stop / cell-priority uniform /
full-legal uniform) — only the forward differs (off the shared embedding). Only
the *one owning* head runs per node (the others' `owns` predicate is false),
plus the value head. Terminal states short-circuit to the exact margin.

Trade-off: sharing the forward means the value is the single-pass decider-frame
estimate (sign-flipped), not the two-pass differential — matching production
self-play's single-pass `nn_evaluator`.

---

## 6. The capacity sweep that set the trunk size

Four value nets on the 41k self-play data (`sp_v_*` in REGISTRY):

| | vs ensemble | 1-turn head-to-head | 800-sim PUCT | test MAE |
|---|---|---|---|---|
| 256×2 | **98.5%** | 512 beats it | **beats 512, 67.5%** | 3.687 |
| 512×2 | 93.5% | beats both | — | 3.704 |
| 384×3 | 82.8% | loses both | — | 3.710 |

Verdict: **256×2** (capacity didn't help; 384-deep clearly worst). And **MAE
ranked them backwards** from play — the standing reminder that MAE ≠ strength.

---

## 7. C++ joint inference (`cpp/`) — CPP_ENGINE_PLAN.md §… 

The joint model is ported into the C++ `NNInference` as a **mode toggle**, not a
new class (the two modes share the manifest loader, the `Mlp` primitive, and the
entire policy dispatch — only the forward differs):

- A `format: "shared_trunk_v1"` manifest (written by `export_weights.py
  --value-ckpt <joint-ckpt>`, auto-detected) flips it to joint mode: load the
  trunk + a **standalone `embed_norm`** LayerNorm (standalone because the C++ MLP
  applies GELU after every LayerNorm, so it can't be a trunk layer) + head blobs
  that take the embedding with **identity input-norm** (pointer heads bake the
  candidate-norm into the cand slice — so the existing `Mlp` is reused verbatim).
- An **internal embedding cache** (`state_hash`-keyed) gives one trunk forward per
  node, so `mcts.cpp` is unchanged — exactly mirroring the Python memo.
- **Two-net match mode**: `selfplay --match --model-dir-p0 A --model-dir-p1 B`
  (`mcts_match_game` in `selfplay.cpp`) plays one net vs another, separate trees,
  per-seat `value_scale`. Driven in parallel by `scripts/nn/run_cpp_match.py`.
- Differential-validated: C++ joint value/policy ≈ Python `make_joint_fns` ≤1e-4
  over 1464 states; the composite path is untouched (gates still green).

This unlocks **C++ self-play generation with the joint model** (the next data
round) at ~4× speed and torch-free (memory-safe).

---

## 8. Results + open items

- **Value held** (val_mae 3.64–3.66) — no negative transfer from sharing the
  trunk with 9 policy heads. The make-or-break check passed.
- **Joint beats previous-best** at 800-sim PUCT: 99.0% (C++ 198-2), confirming the
  soft-π + on-policy upgrade is the strength gain.
- **Open**: (1) promote to `nn_models/best` (needs a value-only adapter or
  shared-trunk-aware consumers); (2) the `fence` head is spatially blind (encoder
  has no per-cell features) and `bake` is under-data — uniform-fallback them in
  the combiner; (3) the flat-256 embedding variant + a re-sweep of E off the
  cache; (4) the next self-play generation *with* the joint model (C++).
- **Bugs caught** (so they don't recur): per-dir-accumulation OOM → per-pickle
  chunking; crash-skipped `value_scale=1.0` → re-measured 3.28; missing terminal
  short-circuit in `make_joint_fns`.
