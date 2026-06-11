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

**Caching + the memory lesson.** It writes **one npz chunk per source pickle**
(`shared_v2_chunks/`), so the encode peak is one pickle (~14 MB), not a whole run
dir. The first version accumulated an entire 30k dir in a float32 Python list
(~4 GB at 6.3M rows) and was jetsam-killed on the 8 GB M1; per-pickle chunking
fixed it (peak ~65 MB) and made it resumable. A cache hit is a pure `np.load`.
(See the project memory note on memory-frugal data code, and mirror
`dataset.build_datasets_chunked`.)

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
