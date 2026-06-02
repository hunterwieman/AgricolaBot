# NN Model Registry

Authoritative catalog of every trained NN checkpoint under `nn_models/`. One row per checkpoint, sorted oldest → newest.

**Update this file as part of every training run.** Add a new row when a model finishes; flip the Status column of any model the new one supersedes. The model directory itself (`config.json`, `best.meta.json`, `test_metrics.json`) is the source of truth for the numbers; this file is the navigable index.

Version conventions: `ENCODING_VERSION` defined in `agricola/agents/nn/encoder.py` (history in **`FIRST_NN.md`** §10.4); `DATA_VERSION` in `agricola/agents/nn/schema.py`. Models with stale `ENCODING_VERSION` fail to load with `EncodingVersionMismatch` — by design — so this column is the first check before reaching for any checkpoint.

---

## Summary table

| Id | Trained | Enc. v | Data v | Data source | Arch / regularization | Train size | Test MAE | Status |
|---|---|---|---|---|---|---|---|---|
| `20260529-153224-acb2` | 2026-05-29 | 1 | 1 | 5k-game run `standard_bimodal_5k` | `[256, 256]` GELU, dropout=0, wd=0 | 50k (sub-sample) | 7.214 | **incompatible** (v1 encoder) |
| `20260529-162301-04fe` | 2026-05-29 | 1 | 1 | 5k-game run `standard_bimodal_5k` | `[256, 256]` GELU, dropout=0, wd=0 | 727k (full) | 6.867 | **incompatible** (v1 encoder); first full-data NN; §11.3 MCTS-lift +3.54 measured against this |
| `20260530-012100-v2wd` | 2026-05-30 | 2 | 1 | 5k-game run `standard_bimodal_5k` | `[256, 256]` GELU, dropout=0, wd=1e-4 | 727k | 6.866 | superseded (lost 436-560 head-to-head vs `v2dropout02`'s peer with same data; see §11) |
| `20260530-013000-v2dropout02` | 2026-05-30 | 2 | 1 | 5k-game run `standard_bimodal_5k` | `[256, 256]` GELU, **dropout=0.2**, wd=1e-4 | 727k | **6.731** | **current best NN** for MCTS leaf; better-calibrated than v2wd, +5.58 MCTS-lift over its own 1-turn (§11.3) |
| `M_10k_standard_bimodal` | 2026-05-30 | 2 | 1 | S1: 10k games, all-8 configs, bimodal T | `[256, 256]` GELU, dropout=0.2, wd=1e-4 | ~1.45M | 6.473 | P1 ablation; S1 arm + P2 margin baseline. Beat S2/S3/S4 (C11-C13); value_scale σ=22.87; tied outcome/winprob standalone (C14) + fair MCTS (C15). MAE not comparable across sections. |
| `M_10k_all_lowT` | 2026-05-30 | 2 | 1 | S4: 10k games, all-8 configs, fixed T=0.3 | `[256, 256]` GELU, dropout=0.2, wd=1e-4 | ~1.45M | 4.870 | P1 ablation; S4 arm. **Low MAE is mostly the easier (low-variance) test distribution, not a better model** — lost 264-735 to S1 (Experiment C11). |
| `M_10k_no_v1_bimodal` | 2026-05-30 | 2 | 1 | S2: 10k games, 7 V3 configs (no t2), bimodal T | `[256, 256]` GELU, dropout=0.2, wd=1e-4 | ~1.45M | 6.323 | P1 ablation; S2 arm (drops the lone V1 config). Lost 404-596 to S1 (Experiment C12) — including t2 in the mix helps. |
| `M_10k_strong3_bimodal` | 2026-05-30 | 2 | 1 | S3: 10k games, top-3 V3 configs, bimodal T | `[256, 256]` GELU, dropout=0.2, wd=1e-4 | ~1.45M | 6.343 | P1 ablation; S3 arm (only the 3 strongest V3 configs). Lost 324-669 to S1 (Experiment C13) — config breadth beats strength-concentration. |
| `M_10k_S1_outcome` | 2026-05-31 | 2 | 1 | S1 (10k, all-8, bimodal) | `[256, 256]` GELU, dropout=0.2, wd=1e-4, **tanh head** | ~1.45M | 0.562 (outcome units) | P2 supervision-target: ±1/0 outcome, MSE. MAE in [-1,1] units — not comparable to margin/winprob. value_scale σ=1.32 (MCTS leaf norm). Standalone (C14) and fair-MCTS (C15) both null — target doesn't measurably matter. |
| `M_10k_S1_winprob` | 2026-05-31 | 2 | 1 | S1 (10k, all-8, bimodal) | `[256, 256]` GELU, dropout=0.2, wd=1e-4, **sigmoid head** | ~1.45M | 0.278 (prob units) | P2 supervision-target: 1/0.5/0 win-prob, BCE. MAE in probability units. value_scale σ=0.66. Tied all matchups standalone (C14) + fair MCTS (C15); faint non-sig edge. |
| `M_55k_all` | 2026-05-31 | 2 | 1 | 55k games = 5k + S1…S5 (everything; chunked builder) | `[256, 256]` GELU, dropout=0.2, wd=1e-4 | ~8M | n/a (see note) | **Superseded as champion by `M_62k_warmM55k`** (loses to it 118-280 / −3.81; ensemble 96.4% vs its 98.0%, both single-seat). Was the prior strongest. Checkpoint of record = **epoch 47** (`best.pt`; the val-MSE-best epoch 68 preserved as `epoch_68_valbest.pt` — epoch 47 beat it 226-170 at n=400, the flat-plateau checkpoint-selection finding). Beats 5k (67-33), 15k (73-27), and the full 8-config ensemble 96.4% (Experiment C16). value_scale σ=22.72 (measured over 5k states). No clean test MAE: the post-rename global-index split shift means the training held-out set isn't reproducible (see FIRST_NN §10.5 live example). Built via `build_datasets_chunked` (8.6 GB RAM — all-in-memory build is impossible at 55k). |
| `M_55k_snap6th` | 2026-06-01 | 2 | 1 | 55k games, **1/6 of snapshots per game** (`--train-keep-frac 0.16667`; seed-hash split, cache) | `[256, 256]` GELU, dropout=0.2, wd=1e-4 | ~1.34M | 5.717 | Data-efficiency experiment (C17), snapshot-thinning arm. epoch 31 (run killed at the val plateau; `best.pt` salvaged + finalized post-hoc). value_scale σ=20.23. **Beats `game6th` 145-55 (+3.96)** at matched 1/6 budget, but **loses to `M_55k_all` 49-149 (+4.30)**. Test MAE comparable to `game6th` only (shared seed-hash split), not to `M_55k_all`/permutation models. |
| `M_55k_game6th` | 2026-06-01 | 2 | 1 | 55k games, **1/6 of games whole** (`--train-game-frac 0.16667`; seed-hash split, cache) | `[256, 256]` GELU, dropout=0.2, wd=1e-4 | ~1.36M | 5.919 | Data-efficiency experiment (C17), game-subset control arm. epoch 6. value_scale σ=19.79. **Loses to `snap6th` 55-145 (−3.96)** and to `M_55k_all` 20-80 (−6.25). Confirms within-game snapshot redundancy: at matched budget, dropping games is worse than thinning snapshots. |
| `M_55k_snap_half` | 2026-06-01 | 2 | 1 | 55k games, **1/2 of snapshots per game** (`--train-keep-frac 0.5`; seed-hash split, cache) | `[256, 256]` GELU, dropout=0.2, wd=1e-4 | ~4.0M | 5.641 | Snapshot-scaling follow-up (C18). **epoch 95** (ran full patience to convergence). value_scale σ=20.41. vs `M_55k_all`: **160-237 (+2.24, 40.3%)** at n=400 — much closer to full than `snap6th` (1/6, 24.7%), so more snapshots help once converged. **Cautionary note:** an early checkpoint (`epoch_22.pt`, kept on disk) lost 23-77 (+4.05) — the undertrained read badly understated it; smaller-data models converge later, so fixed-checkpoint comparisons mislead. Test MAE comparable to snap6th/game6th (shared seed-hash split). |
| `M_62k_warmM55k` | 2026-06-02 | 2 | 1 | **62k** = 5k + S1+S2+S3 + 3 NN-forward blends (`blend_nnforward_10k`, `_10k_b`, `_strict_10k`); no low-T S4/S5. keep_frac 1.0 | `[256, 256]` GELU, dropout=0.2, wd=1e-4; **warm-started (full) from `M_55k_all`**; `--fast-loader` | ~9.07M | 6.099 (62k val/test — not cross-comparable) | **NEW CHAMPION — strongest model in the pipeline.** **best epoch 4** (warm-start converged near-instantly on val; MAE≠strength — gameplay kept improving). value_scale σ=21.29. **Beats `M_55k_all` head-to-head 280-118-2 (+3.81, 70.4%, n=400)** and **the 8-config ensemble 784-16 = 98.0%** (+15.39; single-seat, vs M_55k's re-baselined 771-29 = 96.4%). Confounded (warm-start + blend + S4/S5-drop), but the process beats M_55k. Build peak RSS only **3.13 GB** (full 82k would fit). See FIRST_NN §11 (C19). |

---

## Per-model details

### `20260529-153224-acb2` — first end-to-end smoke test

- **Purpose**: validate the training pipeline end-to-end on a small slice. Not a research result.
- **Hyperparameters**: lr=1e-3, weight_decay=0, batch_size=512, max_epochs=50, early_stop_patience=10. `train_sample_size=50000` (paired snapshots), all else default.
- **Outcome**: pipeline confirmed working. Best epoch 7, test MAE 7.214. Used only as the predecessor to the full-data run.
- **Status**: **incompatible** with current code (`ENCODING_VERSION` = 1; current code is 2). Kept for archaeology; do not attempt to load.

### `20260529-162301-04fe` — first full-data NN

- **Purpose**: full-data baseline trained on all 727k descriptors at the default architecture. Used in all initial gameplay experiments (NNAgent vs 8-config ensemble at ~60% aggregate; MCTS-NN-500 vs NNAgent-1-turn at 68-32, +3.54 margin per **`FIRST_NN.md`** §11.3).
- **Hyperparameters**: lr=1e-3, weight_decay=0, batch_size=512, max_epochs=50, early_stop_patience=10. No subsampling.
- **Outcome**: best epoch 1 (val MSE plateaued immediately), test MAE 6.867. Used as the foundation for the v2 encoder's gameplay-comparison baseline.
- **Status**: **incompatible** with current code (`ENCODING_VERSION` = 1; current code is 2). Retained on disk for reproducing prior match results before the encoder fix, but `NormalizedValueModel.load` will raise `EncodingVersionMismatch`. To re-evaluate matches against this checkpoint, temporarily downgrade `ENCODING_VERSION` and revert the encoder change.

### `20260530-012100-v2wd` — v2 retrain with weight decay

- **Purpose**: first retrain after the encoder fix (`current_player_is_own` decider-aware, §10.4 changelog). Added `weight_decay=1e-4` as a small regularization probe.
- **Hyperparameters**: lr=1e-3, **weight_decay=1e-4**, batch_size=512, max_epochs=50, early_stop_patience=10. No subsampling.
- **Outcome**: essentially identical to the v1 baseline — best epoch 1, test MAE 6.866. Confirms (a) the encoder fix doesn't materially change aggregate MSE because most non-harvest snapshots were already correct, (b) weight_decay=1e-4 is too weak to flatten the val curve. **Lost** standalone gameplay head-to-head against `v2dropout02` (436-560, avg margin -0.62 over 1000 games; see **`FIRST_NN.md`** §11).
- **Status**: superseded by `v2dropout02` for both standalone and MCTS use. Kept as the no-dropout reference point.

### `20260530-013000-v2dropout02` — v2 with dropout=0.2 (current best)

- **Purpose**: probe whether stronger regularization extends the useful training window and improves generalization.
- **Hyperparameters**: lr=1e-3, weight_decay=1e-4, **dropout=0.2**, batch_size=512, **max_epochs=100, early_stop_patience=20**. No subsampling.
- **Outcome**: real improvement on test MAE (6.731 vs 6.866 for v2wd; ~2% relative reduction). Best epoch 3 (vs 1 for unregularized runs). Val curve drops for 3 epochs then plateaus broadly. **Lost** head-to-head NNAgent-vs-NNAgent (436-560 vs `v2wd`), but as an MCTS leaf evaluator beats its own 1-turn lookahead at +5.58 margin (80-19 in 100 games at 500 sims) — a larger MCTS lift than the v2wd model would extract per the indirect chaining estimate. Detailed analysis in **`FIRST_NN.md`** §11.3-11.4.
- **Status**: **current best NN for MCTS leaf evaluation.** Better-calibrated than `v2wd` despite worse standalone argmax. The default model to reach for unless a newer entry below supersedes it.

### `M_55k_snap6th` / `M_55k_game6th` — data-efficiency experiment (C17)

- **Purpose**: at a matched ~1/6 training-descriptor budget, compare two ways to subsample the 55k-game data — thin snapshots across *all* games (`snap6th`, `--train-keep-frac 0.16667`) vs keep *all* snapshots of 1/6 of the games (`game6th`, `--train-game-frac 0.16667`). Tests the FIRST_NN §13.1 within-game-label-redundancy question. Both use the seed-hash split + warm encoded cache; identical architecture; identical (shared) val/test sets.
- **Hyperparameters**: identical to `M_55k_all` (lr=1e-3, wd=1e-4, dropout=0.2, batch=512, max_epochs=100, patience=20, margin/linear). Only the train-subsample flag differs.
- **Outcome** (NNAgent 1-turn, strict legality): `snap6th` **beats `game6th` 145-55 (+3.96)** — thinning snapshots ≫ dropping games at matched budget. Both lose to full `M_55k_all` (`snap6th` 49-149 / +4.30; `game6th` 20-80 / +6.25). Shared-test MAE agrees: snap6th 5.717 < game6th 5.919. So within-game snapshots are substantially (not totally) redundant: spend a fixed budget across all games' labels, not on fewer games — but 1/6 still trails full data.
- **Status**: experiment artifacts; not production models. `M_55k_all` remains the strongest. Full analysis in **`FIRST_NN.md`** §11 (C17).

---

## Updating this file

When a training run produces a new checkpoint:

1. Add a row to the summary table — copy the format above, fill in from the checkpoint's `config.json` and `test_metrics.json`.
2. Add a "Per-model details" subsection — include purpose, hyperparameter delta from defaults, headline outcome (test MAE + any match results), and Status.
3. If the new model supersedes an older one for a specific use case, flip the older model's Status column in the summary table to "superseded" with a brief note pointing at the new model.
4. If the model is trained against a new `ENCODING_VERSION` or `DATA_VERSION`, mark older models with the prior version as "incompatible" in their Status.

Keep entries terse — full reasoning lives in **`FIRST_NN.md`**, not here. This file is a navigable catalog, not a research log.
