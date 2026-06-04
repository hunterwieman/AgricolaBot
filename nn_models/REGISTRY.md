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
| `M_62k_warmM55k` | 2026-06-02 | 2 | 1 | **62k** = 5k + S1+S2+S3 + 3 NN-forward blends (`blend_nnforward_10k`, `_10k_b`, `_strict_10k`); no low-T S4/S5. keep_frac 1.0 | `[256, 256]` GELU, dropout=0.2, wd=1e-4; **warm-started (full) from `M_55k_all`**; `--fast-loader` | ~9.07M | 6.099 (62k val/test — not cross-comparable) | **Superseded as champion by `M_82k_warmM62k`** (loses to it 35-65 / −2.44). Was the prior champion. **best epoch 4** (warm-start converged near-instantly on val; MAE≠strength — gameplay kept improving). value_scale σ=21.29. Beats `M_55k_all` 280-118-2 (+3.81, 70.4%) and the ensemble 784-16 = 98.0% (vs M_55k's 771-29 = 96.4%). Build peak RSS only 3.13 GB. See FIRST_NN §11 (C19). |
| `M_82k_warmM62k` | 2026-06-02 | 2 | 1 | **82k = ALL data** (5k + S1–S5 + the three blend dirs); full snapshots. keep_frac 1.0 | `[256, 256]` GELU, dropout=0.2, wd=1e-4; **warm-started (full) from `M_62k_warmM55k`**; `--fast-loader` | ~12.0M | 6.0 (82k val — not cross-comparable) | **CURRENT CHAMPION; `nn_models/best` points here** (the canonical best-NN pointer the web UI loads; promote by overwriting `nn_models/best.{pt,meta.json}`). **best epoch 4** (val plateaued, run killed at epoch 20; MAE≠strength yet again — gameplay improved). value_scale σ=23.05 (backfilled — run was killed pre-finalization). **Beats `M_62k_warmM55k` 65-35-0 (+2.44, 65%, n=100)**. MCTS-300 vs its own 1-turn: 55-45 (+1.30, n.s.). **Caveat (C20–C22):** the experimental self-play fine-tunes below beat it *head-to-head* (e14 +5.07, R_e8 +2.92) but the fixed ensemble panel stays flat/down, i.e. self-play *exploitation*, not objective gain — so M82k remains champion until something wins the objective yardstick. See FIRST_NN §11 (C19). |
| `ftA_plain_M82k_nn70t2` | 2026-06-02 | 2 | 1 | 5k self-play `M82k_nn70_t2_5k` (M82k-vs-t2, 1-turn) | `[256, 256]` GELU, dropout=0.2, wd=0, lr 3e-4; **warm-start from `M_82k_warmM62k`** | 710k | 5.556 (self-play split — not cross-comparable) | **Experimental self-play fine-tune (C20), NOT promoted.** Checkpoint of record = **epoch 14** (`epoch_014.pt` = best.pt; "e14"). Beats M82k **+5.07 head-to-head** (304-95-1, n=400, 76.2%) — but ensemble panel only 94.4% vs M82k 96.4% (head-to-head gain is largely self-play exploitation). value_scale σ=25.14. Parent of the round-2 fine-tunes. |
| `ftB1_l2sp1e3_M82k_nn70t2` | 2026-06-02 | 2 | 1 | 5k self-play `M82k_nn70_t2_5k` | `[256, 256]` GELU, dropout=0.2, wd=0; **L2-SP λ=1e-3 anchored to M82k** | 710k | 5.863 | **Experimental (C20), not used.** Round-1 L2-SP arm. Anchor froze the fit (train MSE ~stuck); **lost to M82k −1.79** (38-61, n=100). Anchoring a *base* model against beneficial self-play drift HURTS. |
| `ftB2_l2sp1e2_M82k_nn70t2` | 2026-06-02 | 2 | 1 | 5k self-play `M82k_nn70_t2_5k` | `[256, 256]` GELU, dropout=0.2, wd=0; **L2-SP λ=1e-2 anchored to M82k** | 710k | 6.074 | **Experimental (C20), not used.** Strongest round-1 anchor; **lost to M82k −3.32** (32-68). More anchor = worse — confirms anchoring hurts when adapting a base model to the self-play distribution. |
| `ft2_plain_e14_hardmix6k` | 2026-06-02 | 2 | 1 | 6k = `e14_hardmix_1k` (hard-opponent mix) + `M82k_nn70_t2_5k` | `[256, 256]` GELU, dropout=0.2, wd=0; **warm-start from `ftA` e14** | 854k | 5.298 (not cross-comparable) | **Experimental round-2 plain fine-tune (C21), not promoted.** Checkpoint of record = **epoch 10** (`epoch_010.pt`); best.pt=e1 by val but e10 strongest by gameplay (MAE≠strength). Beats e14 +2.59; **strongest pure NN-vs-NN player** (wins the 3-model round-robin, 64.8%). But over-specialized: ensemble **regressed to 88.0%** (alphas_gen_1 84→80). value_scale σ=25.71 (best.pt). |
| `ft2_l2sp1e4_e14_hardmix6k` | 2026-06-02 | 2 | 1 | 6k = `e14_hardmix_1k` + `M82k_nn70_t2_5k` | `[256, 256]` GELU, dropout=0.2, wd=0; **L2-SP λ=1e-4 anchored to e14**, warm-start from `ftA` e14 | 854k | 5.281 | **Experimental round-2 L2-SP arm (C21) — best all-rounder, not promoted.** Checkpoint of record = **epoch 8** (`epoch_008.pt`; "R_e8"); best.pt=e24 by val. Beats e14 **+2.92** (most of any candidate) AND holds the ensemble panel **93.7%** (≈e14's 94.4%) AND **patched the weak spots** (alphas_gen_1 84→94, gen_7 90→94). Loses to `ft2_plain` e10 head-to-head (40-58) but is far the better generalist. Gentle anchor when *refining an already-adapted* model helps — opposite of ftB1/ftB2. |

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

---

## Policy models

Supervised behavioral-cloning **policy heads** (POLICY_HEAD.md) — a factored
policy with one head per decision type (`agricola/agents/nn/policy_heads.py`).
Separate from the value models above; the metric is **top-1 / top-3 agreement**
with the recorded moves, not MAE. Two caveats: (1) agreement ≠ playing strength —
the real measure is PUCT lift (separate session); (2) the `awr` variant is
*expected* to roughly match `none` on top-1, since AWR optimizes for
high-advantage moves, not imitation accuracy — its value shows up only under
search. All `[256,256]` GELU / LayerNorm / dropout 0.2 / wd 1e-4,
`ENCODING_VERSION` 2, trunk warm-started from the `none` placement model (head
layer fresh). AWR baseline = the champion value net (`nn_models/best`); `β = std(A)`,
`w_max = 6`.

| Dir (`nn_models/`) | Head (classes) | Data | Loss | Train | best ep | Test top-1 / top-3 | Status |
|---|---|---|---|---|---|---|---|
| `policy_placement_none` | placement (25) | pre-fix 27k¹ | none | ~1.5M | 28 (killed²) | val 51.3% / 78.3% | warm-start trunk source; **stale data** |
| `policy_choose_subaction_none` | choose_subaction (8) | `hidden_info_v2_10k` | none | 60.3k | 5 | **80.3% / 100%³** | active |
| `policy_choose_subaction_awr` | choose_subaction (8) | `hidden_info_v2_10k` | awr (β=7.3) | 60.3k | 4 | 80.2% / 100% | active |
| `policy_commit_build_major_none` | commit_build_major (14) | `hidden_info_v2_10k` | none | 22.6k | 7 | **67.7% / 95.8%** (win 70.2%) | active |
| `policy_commit_build_major_awr` | commit_build_major (14) | `hidden_info_v2_10k` | awr | 22.6k | 4 | 67.5% / 95.6% (win 70.5%) | active |

¹ Trained on `hidden_info_bimodal_20k` + `hidden_info_nnblend_10k`, generated
*before* the `restricted.py` ordering-filter fix, so its trajectory distribution
is stale (placement legality itself is unchanged — still a valid placement policy
and trunk source). Worth retraining on `hidden_info_v2_10k`.
² Killed at epoch 28 before convergence / final test metrics; val numbers only.
³ top-3 = 100% because parent-pending decisions usually have ≤3 legal options, so
top-3 trivially contains the choice; top-1 is the meaningful metric there.

**`hidden_info_v2_10k`** = 10k games regenerated under the fixed `restricted.py`
(the three forcing ordering filters dropped — POLICY_HEAD.md), which made
`plow`/`build_rooms` real ChooseSubAction choices (0 → the two most common).

---

## Updating this file

When a training run produces a new checkpoint:

1. Add a row to the summary table — copy the format above, fill in from the checkpoint's `config.json` and `test_metrics.json`.
2. Add a "Per-model details" subsection — include purpose, hyperparameter delta from defaults, headline outcome (test MAE + any match results), and Status.
3. If the new model supersedes an older one for a specific use case, flip the older model's Status column in the summary table to "superseded" with a brief note pointing at the new model.
4. If the model is trained against a new `ENCODING_VERSION` or `DATA_VERSION`, mark older models with the prior version as "incompatible" in their Status.

Keep entries terse — full reasoning lives in **`FIRST_NN.md`**, not here. This file is a navigable catalog, not a research log.
