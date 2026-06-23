# Shared-trunk joint value+policy model (Stage B)

Design + implementation + results record for the **joint shared-trunk network** —
one trunk feeding a value head and the full factored policy, trained jointly on
self-play data, consumed by MCTS through one forward per node, and ported to the
C++ engine. This is the Phase 2.3 successor to the separate value net + nine
independent policy heads.

> **Status (2026-06-23):** current champion is **`joint_outcome_44k`** (§10) — the
> first model with an **outcome head** (a win/draw/loss classifier beside the margin
> value head) and the first **GCP-cloud-trained** model. Trained on 44.6k fresh
> self-play games (40k cloud 1600-sim + 4.6k local), warm-started from the prior
> champion `exp_visit_combined`. It beats that champion modestly in a 1000-game
> seat-balanced head-to-head — 53–55% @800 sims, 56–59% @1600 — and is deployed with
> the new **mix leaf** at **α=0.9** (mostly margin, 10% outcome nudge; §10.5). It is
> the current `nn_models/best` / `cpp_export_best`. The prior champion
> `exp_visit_combined` (§9) trained on 40k diverse visit-selection self-play;
> `joint_taper128_thin_sp30k_lr3e4` before it; the original `joint_taper128` beat the
> previous-best separate-net setup **198-2 = 99.0%, +12.95 margin** at 800-sim PUCT.

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
  outcome head:   MLP(E→1, linear)       → raw win/draw/loss signal  (added 2026-06-23, §10.1)
  7 fixed heads:  Linear(E→K_h)          → masked softmax (placement … fencing, build_stop)
  2 pointer heads: MLP([E ; cand]→64→1)  → per-candidate softmax
```

- **Reuses `ConfigurableMLP`** for the trunk and every head — no new MLP math.
- `predict_margin` / `value_scale` / dual-perspective antisymmetry are preserved
  bit-for-bit, so the value head is a drop-in value evaluator.
- **`outcome_head`** (§10.1) is a second value-style head reading the same embedding,
  predicting the *tiebreaker-blind* game outcome `sign(margin) ∈ {−1, 0, +1}` rather
  than the margin in points. `outcome_from_embedding` / `predict_outcome` are its
  accessors; it is **co-trained in the value task** off the one embedding. `load` is
  backward-compatible — checkpoints predating the head simply leave it fresh.
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
- **Outcome head co-trained in the value batch** (§10.1, added 2026-06-23): `_value_loss`
  runs `embed(x)` **once**, then `value_from_embedding` *and* `outcome_from_embedding`
  off the same embedding, summing the margin-MSE and the outcome loss into one
  forward / one backward. (A separate outcome *task* would re-run the trunk — the
  point of folding it into the value task is to amortize the shared forward.) The
  target is `sign(margin)`, attached by `shared_dataset` as `_y_outcome` on the value
  splits (the per-row `won` field already existed). CLI `--train-outcome` (default ON)
  / `--no-train-outcome` / `--outcome-loss-weight`; eval logs outcome sign-accuracy
  alongside value MAE.
- **Warm-start** the trunk from the value-sweep winner (`sp_v_256x2_bs8192`) or a
  prior champion. **The L2-SP anchor excludes the outcome head** when it is fresh:
  anchoring a randomly-initialized head toward its (random) warm-start weights pulls
  against learning it. (`l2sp` therefore skips the head params absent from the source
  checkpoint.)

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

### 5.1 Three leaf modes + a tunable α (2026-06-23)

With the outcome head landed (§10.1), the MCTS leaf can read **either** head, or a
blend — all off the **one** trunk forward. The mode is a `make_joint_fns(leaf_mode=…,
margin_scale=…, outcome_scale=…)` parameter (Python) / `MCTSSearch::set_leaf_mode` +
`set_mix_alpha` over a `LeafMode` enum (C++), with the scales read from the export
manifest:

- **`margin`** — the historical leaf: P0-frame margin in points, divided by the margin
  `value_scale` so leaves sit at ~unit variance.
- **`outcome`** — the outcome head's win/draw/loss signal (~[−1, 1]), divided by its
  own `outcome_scale`.
- **`mix`** — `α · (margin / margin_scale) + (1−α) · (outcome / outcome_scale)`.
  Crucially, **each Q is normalized first, then averaged** — so both terms enter at
  unit variance and the blend is itself ~unit-variance, used **directly** (effective
  `value_scale` 1.0, no further division). `α=1` reduces to `margin`, `α=0` to
  `outcome`; default `0.5`. The deployed champion runs `mix` at **α=0.9** (§10.5).

Wired end-to-end through the C++ binary: `selfplay --match` / `--move` / `--analyze` /
`--sweep` take `--leaf-mode` + `--mix-alpha`; `run_cpp_match.py` exposes
`--leaf-mode-p0` / `--leaf-mode-p1`; `run_cpp_sweep.py` takes `--sweep-alpha` (each
game draws a per-seat random α, reported back in the `GAME` lines — the basis for the
α-sweep, §10.5).

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
- **Outcome head + leaf modes (2026-06-23).** `export_weights.py` writes the outcome
  head's blob + its `outcome_scale` into the manifest (`outcome: null` when the source
  checkpoint predates the head, so old exports still load). C++ `NNInference` reads
  the blob; `MCTSSearch` exposes `set_leaf_mode`/`set_mix_alpha` (the `margin`/`outcome`/`mix`
  modes of §5.1), with the scales taken from the manifest. A new permanent gate
  `tests/test_cpp_nn.py::test_cpp_outcome_matches_python` checks the C++ outcome output
  against Python `predict_outcome` ≤1e-4.

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

---

## 9. Data-variation experiment + the `exp_visit_combined` champion (2026-06-18)

**Question:** how does the *amount and type of variation* in self-play data affect
the strength of a model trained on it? We generated self-play data from the
`joint_taper128_thin_sp30k_lr3e4` champion under five move-selection regimes, all
else equal (800 sims, c_uct 1.0, prior_mix 0.1):

- **visit-selection** (played move sampled ∝ visits^(1/T)) at T=0.7 and T=1.0 — higher diversity;
- **Q-selection** (played move = argmax / softmax of sign-corrected root-child mean-Q; the new
  `--select-by q`) at T=0.005, 0.01, 0.02 — near-greedy, low diversity.

**Method.** One joint model trained per condition (warm-start from the champion,
L2-SP λ=1e-3, identical recipe, 10k games each — the 20k visit sets capped via the
new `--max-games`). Ranked by **800-sim MCTS round-robin** — the as-used setting.
(A 1-turn value-head proxy was explicitly rejected: it's a different, weaker agent
and ignores the policy head + search. Eval the model the way it's actually played.)

**Result — diversity is the lever:**

| condition | round-robin win% |
|---|---|
| visit T=1.0 | 57.5 |
| visit T=0.7 | 56.0 |
| champion (ref) | 50.7 |
| Q T=0.01 | 46.3 |
| Q T=0.005 | 45.6 |
| Q T=0.02 | 44.0 |

Both visit (diverse) models beat the champion; all three Q (near-greedy) models
fell *below* it. Near-greedy self-play produces a narrow, autocorrelated state
distribution that generalizes worse to real play.

**Saturation.** A 40k retrain combining both visit temps — **`exp_visit_combined`**
— beat the champion (**56.2%, 281-213-6**, 500 games at 800-sim MCTS) but only
**TIED** the best single 10k model `exp_visit_t10` (51.5%). So the diverse-data
gain **saturates ~10k games per generation**; 4× the data from a fixed generator
added nothing. `exp_visit_combined` was `nn_models/best` from 2026-06-18 until
**superseded by `joint_outcome_44k`** (§10) on 2026-06-23. The saturation finding
held up: the next gain came from *fresh* diverse generation off this champion (the
44.6k corpus of §10.3), not more retraining on fixed data.

### 9.1 Common-state `value_scale` normalization (the eval methodology)

`value_scale` is a **calibration constant**, not a strength knob: the MCTS leaf is
`predict_margin(s) / value_scale`, so leaves sit at ~unit variance and a single
c_uct means the same exploration/exploitation balance across models. The *correct*
value for a model is the std of its **own** margin predictions on the states it
searches. The **stored** value (training-data `target_std`) is a **biased proxy**:
the generation policy shapes the data's margin spread (near-greedy → tight margins
→ small `target_std`), so it's correlated with the experimental condition — a
search-calibration error that would masquerade as a data-quality effect.

Fix: measure each model's value_scale as `std(predict_margin)` over a **common**
fixed state set and patch the export manifests. Stored values spanned 2.37–4.01 (a
data artifact); common-state values clustered 4.19–5.33. Skipping this would have
handicapped the low-`target_std` visit models — the eventual winners (e.g.
`exp_visit_t07` stored 2.37 vs true ~4.19 → would have searched far too greedily).
Honest caveat: the purest basis is each model's own visited distribution; a common
fixed set approximates it (fine for these near-identical fine-tunes). The promoted
champion's deployed value_scale is **4.345** (common-state), not its biased 2.776.

### 9.2 Q-based move selection (`--select-by q`)

Selecting the played move by sign-corrected mean-Q instead of visit count (the
PUCT search is unchanged; only the final pick differs; `MCTSAgent::select_action_by_q`
in C++). A/B vs visit-selection: ~tie at 800 sims (51%), worse at 400 (44%) —
neutral-to-worse, because visit count is the lower-variance, more robust statistic.
So it stays **off** for play; in this experiment it was the *data-generation*
variable (its data trained weaker models), not a play-strength win.

### 9.3 c_uct unified to 1.0

The codebase had a 0.5/1.4 mix of c_uct defaults. Unified to **1.0** everywhere
(scripts, the C++ binary, the Python `MCTSAgent`, the web-UI bot + analyze seats).
Validated: combined@1.0 ≈ combined@0.5 (round-robin tie), and combined still beats
the prior champion at c_uct 1.0. The promoting eval (56.2%) ran at c_uct 0.5; the
1.0 default is on-par, not a regression.

---

## 10. The outcome head + `joint_outcome_44k` champion (2026-06-23)

Two threads converged this generation: a new **outcome head** (a win/draw/loss
classifier beside the margin value head) and the first **cloud-generated** self-play
corpus. The result, **`joint_outcome_44k`**, is the new `nn_models/best`, deployed
with the new **mix leaf** at α=0.9.

### 10.1 The outcome head — what and why

The margin value head predicts the terminal score *margin in points*; the outcome
head predicts the **tiebreaker-blind game result** `sign(margin) ∈ {−1, 0, +1}`
(loss / draw / win), a coarser but more directly decision-relevant target — winning
by 1 and winning by 20 are the same outcome. It is a `ConfigurableMLP(E→1, linear)`
reading the **same trunk embedding** as the value head; its target is **not** scaled
by `target_std` (it's a sign, not a magnitude).

The implementation choice that matters is **where it trains**: it is *co-trained in
the value-task batch*, not as its own task. `_value_loss` runs `embed(x)` once, then
both `value_from_embedding` and `outcome_from_embedding` off that one embedding, and
sums the margin-MSE and outcome losses into a single forward/backward (§4). A separate
outcome task would re-run the trunk per step; folding it in amortizes the shared
forward, so the head is nearly free to add. `shared_dataset` attaches `_y_outcome =
sign(margin)` to the value splits (the per-row `won` field already existed), and the
L2-SP warm-start anchor **excludes** the fresh head (anchoring a random head toward
random weights impedes learning it). `SharedTrunkModel.load` is backward-compatible:
checkpoints predating the head leave it fresh. New accessors:
`outcome_from_embedding` / `predict_outcome`; CLI `--train-outcome` (default ON).

### 10.2 Three leaf modes + α

With both heads available, the MCTS leaf can read the margin head, the outcome head,
or a normalized blend of the two — all off the one trunk forward. The full mechanics
(the `margin` / `outcome` / `mix` modes, the normalize-each-Q-then-average rule, the
Python / C++ / CLI wiring) are in **§5.1**; the export + differential-gate side in
**§7**. The deployed mode is **`mix` at α=0.9** — the α-sweep (§10.5) is what set that
value.

### 10.3 The corpus — first cloud-trained model

44,608 fresh self-play games, replayed from C++ traces into the standard `GameRecord`
format:

- **40,000 games on GCP cloud** at 1600 sims/move, seed 100100000 — the first time
  self-play generation ran off the M1 (the cloud-scaling thread; `joint_outcome_44k`
  is the **first GCP-cloud-trained model**).
- **4,608 games locally** at seed 100000000.

Trained warm-started (full 42-tensor transplant) from `exp_visit_combined` with the
champion recipe matched exactly: trunk 256×256 → E=128, dropout 0.2, lr 3e-4, L2-SP
λ=1e-3, bs 2048, value loss-weight 9, v2 encoder, `--save-all-epochs`. Best epoch 12
(early-stop at 20).

**What it learned.** Value and policy were essentially **preserved** — val-MAE flat
across epochs, which is expected for a warm-start on on-policy data drawn from a
sibling of the source model. The generation mainly **adds the outcome head** (outcome
sign-accuracy **0.69**); it is not a from-scratch value improvement.

### 10.4 Eval vs the prior champion

1000-game **seat-balanced** head-to-head against `exp_visit_combined`, common-state
`value_scale`, c_uct 1.0, greedy play, across three sim budgets and all three leaf
modes (joint as the new model):

| sims | margin | outcome | mix |
|---|---|---|---|
| 200  | 51.6% | 50.9% | 50.6% |
| 800  | 53.1% | 54.1% | 55.2% |
| 1600 | 56.1% | 56.4% | **59.0%** |

A **real but modest** improvement: a tie at 200 sims, growing with search depth, with
`mix` strongest at depth. The gain depends on the leaf being given enough search to
exploit.

**Methodology lessons (both bite the same way — small match runs are seed-noisy):**

- A first **400-game** run *overstated* this edge at **59–62%**; a fresh-seed
  **1000-game** re-run corrected it to the table above. Trust the larger, fresh-seed
  number — the same caution `value_scale`-calibration (§9.1) exists to enforce.
- **`value_scale` is distribution-dependent → measure on a COMMON state set** (§9.1).
  The prior champion measured **2.933** on the 1600-sim self-play states here, versus
  its *deployed* 4.345 — using the deployed number would have mis-calibrated its
  search in this match. The joint model's common-state margin scale is **2.966**, its
  outcome scale **0.533**.

### 10.5 The mix-α sweep — margin is the robust leaf

The §10.4 table shows `mix` beating the others *against this one opponent*, but that
could be opponent-specific exploitation rather than a general strength gain. To pin
down the best α as a *general* leaf, a **10,000-game self-play sweep** (5k @ 800 sims +
5k @ 1600, joint vs joint, `mix` leaf): **each player draws α ~ U[0, 1] per game**
(via `run_cpp_sweep.py --sweep-alpha`), and `analyze_alpha_sweep.py` does a Gaussian
Nadaraya-Watson **kernel regression** (bandwidth 0.2, both seats pooled) of win-prob
vs α.

The curve rises ~monotonically in α:

- **peak at α ≈ 0.9–0.93** (margin-heavy);
- **pure outcome (α=0) is *worst*** (~47%);
- the **0.5 mix is mediocre** (~50%);
- **pure margin (α=1) is near-best**.

This **flips the §10.4 ranking** (where mix > outcome > margin vs the champion): the
mix/outcome edge over `exp_visit_combined` is **partly champion-specific exploitation**,
while in general self-play **margin is the robust leaf**. The takeaway — and the
deployed setting — is **α=0.9**: "mostly margin, with a 10% outcome nudge," the small
amount of outcome that the sweep shows is a marginal help without buying into the
pure-outcome leaf's weakness. New tool: `scripts/nn/analyze_alpha_sweep.py`
(pooled-seat kernel regression + plot).

### 10.6 Deploy (see CLAUDE.md §2.6 / DEPLOY.md)

`joint_outcome_44k` was promoted to `nn_models/best` + `cpp_export_best` and deployed
live with the **mix leaf at α=0.9**. The web-UI analysis overlay shows a `mix` badge
with the **raw, un-denormalized Q** (the directly-used unit-variance blend of §5.1).
