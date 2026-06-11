# NN Model Registry

Authoritative catalog of every trained NN checkpoint under `nn_models/`. One row per checkpoint, sorted oldest → newest.

**Update this file as part of every training run.** Add a new row when a model finishes; flip the Status column of any model the new one supersedes. The model directory itself (`config.json`, `best.meta.json`, `test_metrics.json`) is the source of truth for the numbers; this file is the navigable index.

Version conventions: `ENCODING_VERSION` defined in `agricola/agents/nn/encoder.py` (history in **`FIRST_NN.md`** §10.4); `DATA_VERSION` in `agricola/agents/nn/schema.py`. Models with stale `ENCODING_VERSION` fail to load with `EncodingVersionMismatch` — by design — so this column is the first check before reaching for any checkpoint.

> **`value_scale` halved (2026-06-05).** `nn_evaluator_differential` and `measure_leaf_value_scale` now return the **mean** `(V(s,0) − V(s,1)) / 2` (was the un-halved difference), so the MCTS leaf and the single-pass `nn_evaluator` share one `~1x` margin scale; the MCTS `leaf_differential` flag was removed. Every measured checkpoint's stored `value_scale` was divided by 2 to match (champion `M_82k_warmM62k`/`best`: 23.05 → **11.53**). The per-model `value_scale σ=…` figures in the rows below are the **original** measurements — the checkpoints now store half. `1.0` sentinels (unmeasured) were left unchanged.

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
| `M_62k_warmM55k` | 2026-06-02 | 2 | 1 | **62k** = 5k + S1+S2+S3 + 3 NN-forward blends (`blend_nnforward_10k`, `_10k_b`, `_strict_10k`); no low-T S4/S5. keep_frac 1.0 | `[256, 256]` GELU, dropout=0.2, wd=1e-4; **warm-started (full) from `M_55k_all`**; `--fast-loader` | ~9.07M | 6.099 (62k val/test — not cross-comparable) | **Superseded as champion by `M_82k_warmM62k`** (loses to it 35-65 / −2.44). Was the prior champion. **best epoch 4** (warm-start converged near-instantly on val; MAE≠strength — gameplay kept improving). value_scale σ=21.29. Beats `M_55k_all` 280-118-2 (+3.81, 70.4%) and the ensemble 784-16 = 98.0% (vs M_55k's 771-29 = 96.4%). Build peak RSS only 3.13 GB. See FIRST_NN §11 (C19). |
| `M_82k_warmM62k` | 2026-06-02 | 2 | 1 | **82k = ALL data** (5k + S1–S5 + the three blend dirs); full snapshots. keep_frac 1.0 | `[256, 256]` GELU, dropout=0.2, wd=1e-4; **warm-started (full) from `M_62k_warmM55k`**; `--fast-loader` | ~12.0M | 6.0 (82k val — not cross-comparable) | **CURRENT CHAMPION; `nn_models/best` points here** (the canonical best-NN pointer the web UI loads; promote by overwriting `nn_models/best.{pt,meta.json}`). **best epoch 4** (val plateaued, run killed at epoch 20; MAE≠strength yet again — gameplay improved). value_scale σ=23.05 (backfilled — run was killed pre-finalization). **Beats `M_62k_warmM55k` 65-35-0 (+2.44, 65%, n=100)**. MCTS-300 vs its own 1-turn: 55-45 (+1.30, n.s.). **Caveat (C20–C22):** the experimental self-play fine-tunes below beat it *head-to-head* (e14 +5.07, R_e8 +2.92) but the fixed ensemble panel stays flat/down, i.e. self-play *exploitation*, not objective gain — so M82k remains champion until something wins the objective yardstick. See FIRST_NN §11 (C19). |
| `ftA_plain_M82k_nn70t2` | 2026-06-02 | 2 | 1 | 5k self-play `M82k_nn70_t2_5k` (M82k-vs-t2, 1-turn) | `[256, 256]` GELU, dropout=0.2, wd=0, lr 3e-4; **warm-start from `M_82k_warmM62k`** | 710k | 5.556 (self-play split — not cross-comparable) | **Experimental self-play fine-tune (C20), NOT promoted.** Checkpoint of record = **epoch 14** (`epoch_014.pt` = best.pt; "e14"). Beats M82k **+5.07 head-to-head** (304-95-1, n=400, 76.2%) — but ensemble panel only 94.4% vs M82k 96.4% (head-to-head gain is largely self-play exploitation). value_scale σ=25.14. Parent of the round-2 fine-tunes. |
| `ftB1_l2sp1e3_M82k_nn70t2` | 2026-06-02 | 2 | 1 | 5k self-play `M82k_nn70_t2_5k` | `[256, 256]` GELU, dropout=0.2, wd=0; **L2-SP λ=1e-3 anchored to M82k** | 710k | 5.863 | **Experimental (C20), not used.** Round-1 L2-SP arm. Anchor froze the fit (train MSE ~stuck); **lost to M82k −1.79** (38-61, n=100). Anchoring a *base* model against beneficial self-play drift HURTS. |
| `ftB2_l2sp1e2_M82k_nn70t2` | 2026-06-02 | 2 | 1 | 5k self-play `M82k_nn70_t2_5k` | `[256, 256]` GELU, dropout=0.2, wd=0; **L2-SP λ=1e-2 anchored to M82k** | 710k | 6.074 | **Experimental (C20), not used.** Strongest round-1 anchor; **lost to M82k −3.32** (32-68). More anchor = worse — confirms anchoring hurts when adapting a base model to the self-play distribution. |
| `ft2_plain_e14_hardmix6k` | 2026-06-02 | 2 | 1 | 6k = `e14_hardmix_1k` (hard-opponent mix) + `M82k_nn70_t2_5k` | `[256, 256]` GELU, dropout=0.2, wd=0; **warm-start from `ftA` e14** | 854k | 5.298 (not cross-comparable) | **Experimental round-2 plain fine-tune (C21), not promoted.** Checkpoint of record = **epoch 10** (`epoch_010.pt`); best.pt=e1 by val but e10 strongest by gameplay (MAE≠strength). Beats e14 +2.59; **strongest pure NN-vs-NN player** (wins the 3-model round-robin, 64.8%). But over-specialized: ensemble **regressed to 88.0%** (alphas_gen_1 84→80). value_scale σ=25.71 (best.pt). |
| `ft2_l2sp1e4_e14_hardmix6k` | 2026-06-02 | 2 | 1 | 6k = `e14_hardmix_1k` + `M82k_nn70_t2_5k` | `[256, 256]` GELU, dropout=0.2, wd=0; **L2-SP λ=1e-4 anchored to e14**, warm-start from `ftA` e14 | 854k | 5.281 | **Experimental round-2 L2-SP arm (C21) — best all-rounder, not promoted.** Checkpoint of record = **epoch 8** (`epoch_008.pt`; "R_e8"); best.pt=e24 by val. Beats e14 **+2.92** (most of any candidate) AND holds the ensemble panel **93.7%** (≈e14's 94.4%) AND **patched the weak spots** (alphas_gen_1 84→94, gen_7 90→94). Loses to `ft2_plain` e10 head-to-head (40-58) but is far the better generalist. Gentle anchor when *refining an already-adapted* model helps — opposite of ftB1/ftB2. |
| `sp_v_256x2` | 2026-06-10 | 2 | **3** | **41k MCTS self-play** (`cpp_selfplay_30k`+`_10k`+`cpp_ab_batch`, π+root_value) | `[256,256]` GELU dropout=0.2 wd=1e-4; **warm from `M_82k`**; bs=256 | ~6.8M | 3.693 | **First v3 (PUCT self-play) value nets — the capacity sweep.** epoch 5. **MAE NOT cross-comparable to v1/v2 rows** (self-play states are far lower-variance than the heuristic-ensemble distribution). |
| `sp_v_256x2_bs8192` | 2026-06-10 | 2 | 3 | 41k self-play | `[256,256]`; warm from `M_82k`; **bs=8192 `--fast-loader`** | ~6.8M | 3.687 | Same arch at bs=8192/lr=1e-3 — **validated the fast config holds champion-recipe quality** (3.687 ≈ 3.693 bs=256). epoch 18, value_scale σ=5.77. The apples-to-apples **256×2 sweep reference**. |
| `sp_v_512x2` | 2026-06-10 | 2 | 3 | 41k self-play | `[512,512]`; **from scratch**; bs=8192 | ~6.8M | 3.704 | Capacity sweep — wider trunk (~353k params). epoch 10. |
| `sp_v_384x3` | 2026-06-10 | 2 | 3 | 41k self-play | `[384,384,384]`; from scratch; bs=8192 | ~6.8M | 3.710 | Capacity sweep — deeper trunk. **Weakest on every measure** (ensemble 82.8%; loses both head-to-heads). epoch 10. |
| `joint_taper128` | 2026-06-10 | 2 | 3 | 41k self-play | **shared trunk** `[256,256]→128` + value head + 7 fixed + 2 pointer heads; **soft-π** policy + margin value; warm trunk from `sp_v_256x2_bs8192` | ~6.8M (value rows) | 3.66 (value head) | **Stage-B joint value+policy model (strongest agent to date).** Value held → no negative transfer. **Beats previous-best (champion value + 9 separate unweighted heads) at 800-sim PUCT: Python (won) + C++ 198-2 = 99.0%, +12.95.** Trained to epoch 33 (crash), best epoch 27; value_scale 3.28 (measured post-hoc). Not yet promoted to `nn_models/best` (joint model needs consumer wiring — see SHARED_TRUNK.md). |

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

### `ftA` / `ftB1` / `ftB2` — round-1 self-play fine-tune + L2-SP A/B (C20)

- **Purpose**: test whether fine-tuning the champion (`M_82k_warmM62k`) on its *own* 1-turn self-play data (`M82k_nn70_t2_5k`, M82k-vs-t2) yields a stronger model, and whether an L2-SP anchor (penalize `λ·‖θ−θ₀‖²` toward the warm-start weights) helps or hurts. Three arms: plain (`ftA`), λ=1e-3 (`ftB1`), λ=1e-2 (`ftB2`).
- **Hyperparameters delta**: warm-start from M82k; lr 3e-4, dropout 0.2, wd 0, `--save-all-epochs` (so checkpoints are selected by gameplay, not val MSE). Arms differ only in `--l2sp`.
- **Outcome**: **plain wins big** — `ftA` e14 beats M82k +5.07 (304-95-1, n=400). Inverted-U over epochs (e4 +3.63 → e14 +5.32 → e25 +2.74). **Both anchored arms LOSE to M82k** (ftB1 −1.79, ftB2 −3.32; more anchor → worse): the anchor suppresses drift that is *beneficial adaptation* toward the deployment (NN-vs-NN) distribution. Retention probe (broad-distribution MAE, `scripts/nn/retention_eval.py`): plain forgets progressively (+0.38→+0.80 over M82k), anchored arms stay flat (~+0.34–0.40) — the anchor measurably limits forgetting, but the forgetting was *good*. `ftA` e14 vs the 8-config ensemble: 94.4% (vs M82k 96.4%), patched nothing (alphas_gen_1 84%, gen_7 90%).
- **Status**: experimental, **not promoted**. `ftA` e14 is the parent of the round-2 runs. Full analysis: **`FIRST_NN.md`** §11 (C20).

### `ft2_plain` / `ft2_l2sp1e4` — round-2 hard-mix fine-tune (C21)

- **Purpose**: from `ftA` e14, fine-tune on a *hard-opponent-mined* dataset (`e14_hardmix_1k`: e14 in seat 0, seat-1 opponents weighted by their win-rate **against** the NN — alphas_gen_1 heaviest, the two 0%-win configs excluded) + the original 5k self-play. Goal: patch e14's ensemble weakness (alphas_gen_1 84%) while keeping its head-to-head strength. Two arms: plain and L2-SP λ=1e-4 (gentle, anchored to e14).
- **Hyperparameters delta**: warm-start from `ftA` e14; data = `e14_hardmix_1k` + `M82k_nn70_t2_5k`; else as C20.
- **Outcome**: **the anchor is the key, and the targeting only works with it.** `ft2_plain` e10 over-specializes — strongest pure NN-vs-NN (wins the e14/R_e8/plain round-robin at 64.8%, beats e14 +2.59, beats R_e8 58-40) but ensemble **regresses to 88.0%** and the target weakness gets *worse* (alphas_gen_1 80%, gen_7 77%). `ft2_l2sp1e4` e8 ("R_e8") beats e14 **+2.92** (most of any candidate), **holds** the ensemble at 93.7%, and **patches** the weaknesses (alphas_gen_1 84→94, gen_7 90→94). The hard-mix improves generalization *only when an anchor prevents over-specialization* — the exact opposite verdict on L2-SP from C20, because here we refine an already-adapted model rather than adapt a base one.
- **Status**: experimental, **not promoted** (see the C22 plateau caveat: head-to-head-vs-parent is contaminated; the objective ensemble panel is flat across the whole chain). `ft2_l2sp1e4` e8 is the best all-rounder; `ft2_plain` e10 is the strongest pure NN-vs-NN. Full analysis: **`FIRST_NN.md`** §11 (C21).

### `sp_v_*` — v3 self-play value-capacity sweep

- **Purpose**: the first value nets trained on the **41k PUCT self-play games** (DATA_VERSION 3; on-policy, with π + root_value) rather than the heuristic-ensemble data — and a capacity sweep to settle the trunk size for the joint model. Four cells: warm-started `256×2` at bs=256 (`sp_v_256x2`) and the validated bs=8192 fast config (`sp_v_256x2_bs8192`), plus from-scratch `512×2` and `384×3`.
- **Findings**: (1) **the bs=8192 `--fast-loader` config holds champion-recipe quality** (test MAE 3.687 ≈ 3.693), validating the big-batch speedup the NN_TRAINING_SPEEDUP doc left open. (2) **MAE is a backwards predictor of strength here** — `512×2` had the *worst* MAE of the warm/big pair yet *beat* `256×2` head-to-head (1-turn), while the ensemble favored `256×2`; the **800-sim PUCT tiebreaker went decisively to `256×2` (67.5%)**. (3) `384×3` is weakest on *every* measure. Net: **capacity didn't help** (the 170-feature count encoder is the binding constraint, not trunk size) → the joint trunk is `256×2`. MAE within this group is comparable (shared v3 split); **not** comparable to the v1/v2 rows above.
- **Status**: sweep artifacts; superseded by the joint model for production. `sp_v_256x2_bs8192` is the value-side warm-start source for `joint_taper128`.

### `joint_taper128` — Stage-B joint shared-trunk value+policy model

- **Purpose**: one network — a shared `170→256→256→128` trunk feeding a value head + 7 fixed policy heads + 2 pointer heads — trained jointly on the 41k self-play data with **cross-entropy against the visit distribution π** (soft targets) for policy and the terminal margin for value. The architecture goal is one trunk forward per MCTS node instead of separate value+policy nets; the strength goal is the soft-π + on-policy upgrade.
- **Hyperparameters**: trunk `[256,256]`, embedding `E=128` (taper), pointer head `[64]` hidden; dropout 0.2, wd 1e-4, bs 2048, `--fast-loader`; **warm-start trunk from `sp_v_256x2_bs8192`**; per-head gradient balancing (equal-frequency task sampling); early-stop on **value val-MSE**, `--save-all-epochs`.
- **Outcome**: **value held at val_mae 3.64–3.66 the whole run — no negative transfer** (sharing the trunk with 9 policy heads didn't degrade the value task). Policy heads converged (placement CE 1.54→1.16; `fence` stayed ~1.6 spatially-blind, `bake` noisy on ~700 examples — uniform-fallback candidate). **Beats the previous-best setup (champion `M_82k` value + the 9 separate unweighted policy heads) at 800-sim PUCT: Python (joint won) + a C++ replication of 198-2 = 99.0%, +12.95 margin** — confirming the thesis that the soft-π/on-policy upgrade (not the shared trunk per se) is the strength gain. Consumed via `make_joint_fns` (Python, one forward/node) and the C++ `shared_trunk_v1` joint-inference path (differential-validated ≤1e-4). 
- **Bugs caught (recorded so they don't recur)**: (1) `shared_dataset` originally accumulated a whole run dir in a float32 list (~4 GB) → OOM; fixed with per-pickle chunk caching. (2) the training crash skipped the post-run `value_scale` measurement, leaving the default `1.0` — caught at C++ export, re-measured to **3.28**. (3) `make_joint_fns` initially didn't short-circuit terminal states (the C++/`nn_evaluator` do); fixed.
- **Status**: **strongest agent to date**, but **not yet `nn_models/best`** — that pointer is a single value net the web UI / consumers load, and the joint model needs consumer wiring (a value-only adapter or shared-trunk awareness) before promotion. Design + eval: **`SHARED_TRUNK.md`**.

---

## Policy models

Supervised behavioral-cloning **policy heads** (POLICY_HEAD.md) — a factored
policy with one head per decision type (`agricola/agents/nn/policy_heads.py`).
Separate from the value models above; the metric is **top-1 / top-3 agreement**
with the recorded moves, not MAE. Two caveats: (1) agreement ≠ playing strength —
the real measure is PUCT lift (separate session); (2) the `awr` variant is
*expected* to roughly match `unweighted` on top-1, since AWR optimizes for
high-advantage moves, not imitation accuracy — its value shows up only under
search. All `[256,256]` GELU / LayerNorm / dropout 0.2 / wd 1e-4,
`ENCODING_VERSION` 2, trunk warm-started from the `unweighted` placement model (head
layer fresh). AWR baseline = the champion value net (`nn_models/best`); `β = std(A)`,
`w_max = 6`.

| Dir (`nn_models/`) | Head (classes) | Data | Loss | Train | best ep | Test top-1 / top-3 | Status |
|---|---|---|---|---|---|---|---|
| `policy_placement_unweighted` | placement (25) | pre-fix 27k¹ | unweighted | ~1.5M | 28 (killed²) | val 51.3% / 78.3% | **superseded** by `policy_placement_v2_unweighted` (unlabelled meta³ + stale data) |
| `policy_placement_v2_unweighted` | placement (25) | `hidden_info_v2_10k` | unweighted | 570k | 29 | **51.2% / 77.3%** (win 55.1%) | active; clean post-fix data + labelled meta |
| `policy_placement_v2_awr` | placement (25) | `hidden_info_v2_10k` | awr | 570k | 32 | 50.5% / 76.6% (win 54.6%) | active |
| `policy_choose_subaction_unweighted` | choose_subaction (8) | `hidden_info_v2_10k` | unweighted | 60.3k | 5 | **80.3% / 100%⁴** | active |
| `policy_choose_subaction_awr` | choose_subaction (8) | `hidden_info_v2_10k` | awr (β=7.3) | 60.3k | 4 | 80.2% / 100% | active |
| `policy_commit_build_major_unweighted` | commit_build_major (14) | `hidden_info_v2_10k` | unweighted | 22.6k | 7 | **67.7% / 95.8%** (win 70.2%) | active |
| `policy_commit_build_major_awr` | commit_build_major (14) | `hidden_info_v2_10k` | awr | 22.6k | 4 | 67.5% / 95.6% (win 70.5%) | active |
| `policy_commit_sow_unweighted` | commit_sow (104) | `hidden_info_v2_10k` | unweighted | 9.4k | — | **58.6% / 95.7%** (win 60.7%) | active; `1≤g+v≤13` vocab (data max g+v=4) |
| `policy_commit_sow_awr` | commit_sow (104) | `hidden_info_v2_10k` | awr | 9.4k | — | 57.4% / 96.3% (win 60.3%) | active |
| `policy_commit_bake_unweighted` | commit_bake (6) | `hidden_info_v2_10k` | unweighted | 754 | — | **72.2% / 97.9%** (win 75.7%) | active; `grain∈1..6` (data max=5); tiny/low-leverage |
| `policy_commit_bake_awr` | commit_bake (6) | `hidden_info_v2_10k` | awr | 754 | — | 71.1% / 100% (win 70.3%) | active |
| `policy_fencing_unweighted` | fencing (110)⁵ | `hidden_info_v2_10k` | unweighted, **full legality** | 33.7k | — | 28.1% / 56.4% (win 27.9%) | active (experiment); spatially-blind — see ⁵ |
| `policy_fencing_awr` | fencing (110)⁵ | `hidden_info_v2_10k` | awr, **full legality** | 33.7k | — | 28.5% / 55.8% (win 28.6%) | active (experiment) |
| `policy_build_stop_unweighted` | build_stop (2)⁶ | `hidden_info_v2_10k` | unweighted, full legality | 9.1k | 4 | **74.3%** (win 74.7%) | active; learned P(stop) for rooms/stables |
| `policy_build_stop_awr` | build_stop (2)⁶ | `hidden_info_v2_10k` | awr (β=9.7) | 9.1k | 3 | 74.2% (win 74.4%) | active |

¹ Trained on `hidden_info_bimodal_20k` + `hidden_info_nnblend_10k`, generated
*before* the `restricted.py` ordering-filter fix, so its trajectory distribution
is stale (placement legality itself is unchanged — still a valid placement policy
and trunk source). **Superseded** by `policy_placement_v2_unweighted`.
² Killed at epoch 28 before convergence / final test metrics; val numbers only.
³ The pre-fix `policy_placement_unweighted` meta has `head=None` (predates head-label
stamping), so `make_policy_fn` rejects it; the v2 retrain stamps the label.
⁴ top-3 = 100% because parent-pending decisions usually have ≤3 legal options, so
top-3 trivially contains the choice; top-1 is the meaningful metric there.
⁵ **Fencing experiment.** Vocab = the 109 RESTRICTED fence-universe shapes + Stop
(110). **Spatially blind**: the output classes are specific cell-sets but the
encoder has no per-cell features, so the head leans on the legal mask + learned
canonical-shape priors — top-1 28% (vs ~10% random) is the evidence that spatial
encoding is fencing's real bottleneck. Trained with FULL legality (no
restricted/strict wrapper); Stop is a class so it learns when to stop.
⁶ 2-class build-vs-stop head for multi-shot Build Rooms / Build Stables
(`num_built ≥ 1`); the combiner expands the `build` class onto the cell-priority
cell → `{cell: P(build), Stop: P(stop)}`. Replaces the crude uniform 50/50 (which
was ~6× too high on Stop for rooms). Fencing is NOT covered (its own head).
top-3 is meaningless for a 2-class head.

**`hidden_info_v2_10k`** = 10k games regenerated under the fixed `restricted.py`
(the three forcing ordering filters dropped — POLICY_HEAD.md), which made
`plow`/`build_rooms` real ChooseSubAction choices (0 → the two most common).

---

## Pointer policy models

Score-the-legal-set **pointer heads** (POLICY_HEAD.md §11) for the
variable-cardinality Pareto-frontier commits. Unlike the fixed heads, the metric
is **within-frontier** top-1/top-3 (the chosen commit's rank among *its own* legal
candidates), and training is a weighted **segment-CE** over ragged candidate
lists. `animal_frontier` owns `CommitBreed` (harvest breeding) + `CommitAccommodate`
(the three animal markets); each candidate's features are `(sheep_kept, boar_kept,
cattle_kept, food_gained)` concatenated onto the shared state encoding. `[256,256]`
GELU / LayerNorm / dropout 0.2 / wd 1e-4, `ENCODING_VERSION` 2. AWR baseline =
`nn_models/best`, `β = std(A)`, `w_max = 6`.

**Data scope differs from the fixed heads:** trained on the **union of all three
hidden-info runs** (`hidden_info_v2_10k` + `hidden_info_bimodal_20k` +
`hidden_info_nnblend_10k`; ~37k games → 154k frontier snapshots, 326k candidates).
Valid here because breed/market labels are wrapper- and forcing-fix-invariant
(`restricted.py` never narrows breed/markets — only `PendingHarvestFeed`), so the
v2-only constraint that applies to the sub-action heads does not apply.

| Dir (`nn_models/`) | Head | Loss | Train (snaps / cand) | best ep | Test top-1 / top-3⁷ | Status |
|---|---|---|---|---|---|---|
| `pointer_animal_frontier_unweighted` | animal_frontier (CommitBreed + CommitAccommodate) | unweighted | 123k / 326k | 12 | **69.8% / 97.9%** (win 70.0%) | active |
| `pointer_animal_frontier_awr` | animal_frontier | awr (β=6.26) | 123k / 326k | 12 | 68.8% / 97.9% (win 69.5%) | active |
| `pointer_harvest_feed_unweighted` | harvest_feed (CommitConvert + CommitHarvestConversion)⁸ | unweighted | 76k / 761k | 18 | **61.8% / 93.5%** (win 59.7%) | active |
| `pointer_harvest_feed_awr` | harvest_feed | awr (β=4.41) | 76k / 761k | 15 | 61.0% / 93.5% (win 58.3%) | active |

AWR ≈ none on top-1, as expected (AWR optimizes high-advantage moves, not
imitation accuracy — its value shows up only under search).

⁷ `animal_frontier` mean frontier K ≈ 2.64 → random ~38% top-1, top-3 near-trivial.
`harvest_feed` is harder: K up to 92 (mean ≈ 10), so its top-1 (62%) is well above
the ~10% floor but lower than the small-K heads. **top-1 is the meaningful metric.**
⁸ `harvest_feed` owns `PendingHarvestFeed` (pre-`conversion_done`); its candidate
set is the **heterogeneous** legal set — the `CommitConvert` Pareto-frontier points
*and* the `CommitHarvestConversion` craft toggles (`use=False` was removed from the
engine, so toggles are fire-only). 10-dim tagged-union Δ: `[is_toggle, joinery,
pottery, basketmaker, consumed(g,v,s,b,c), begging]`. Candidates come from full
`legal_actions` (no min-begging wrapper).

---

## Combined policy functions (`scripts/nn/build_combined_policy.py`)

The two end-to-end `policy_fn(state, legal) -> {action: prior}` MCTS/PUCT consumes,
assembled from the heads above via `agricola.agents.nn.policy.make_policy_fn`:

- **`build("unweighted")`** — the 9 `*_unweighted` heads.
- **`build("awr")`** — the 9 `*_awr` heads.

Each works over the **full** legal set and dispatches by decision type: fixed head
(placement / choose_subaction / commit_build_major / commit_sow / commit_bake /
fencing) → its masked-softmax; pointer head (animal_frontier / harvest_feed) → its
score-the-set softmax; `build_stop` → learned `P(stop)` + cell-priority build cell
for multi-shot rooms/stables; cell commits (plow, first-build rooms/stables) →
uniform over the cell-priority cell. Coverage is complete — no decision type falls
to a naive uniform-over-full-legal. Both load + drive PUCT end-to-end
(`build_combined_policy.py` `__main__` sanity-checks both).

---

## Updating this file

When a training run produces a new checkpoint:

1. Add a row to the summary table — copy the format above, fill in from the checkpoint's `config.json` and `test_metrics.json`.
2. Add a "Per-model details" subsection — include purpose, hyperparameter delta from defaults, headline outcome (test MAE + any match results), and Status.
3. If the new model supersedes an older one for a specific use case, flip the older model's Status column in the summary table to "superseded" with a brief note pointing at the new model.
4. If the model is trained against a new `ENCODING_VERSION` or `DATA_VERSION`, mark older models with the prior version as "incompatible" in their Status.

Keep entries terse — full reasoning lives in **`FIRST_NN.md`**, not here. This file is a navigable catalog, not a research log.
