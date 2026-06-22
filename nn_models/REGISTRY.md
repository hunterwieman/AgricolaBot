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
| `M_82k_warmM62k` | 2026-06-02 | 2 | 1 | **82k = ALL data** (5k + S1–S5 + the three blend dirs); full snapshots. keep_frac 1.0 | `[256, 256]` GELU, dropout=0.2, wd=1e-4; **warm-started (full) from `M_62k_warmM55k`**; `--fast-loader` | ~12.0M | 6.0 (82k val — not cross-comparable) | **Strongest *separate-net* value model; NO LONGER `nn_models/best`** (replaced by joint `joint_taper128_thin` 2026-06-15 — the `best` pointer now resolves to the joint model via the `model_kind`-aware `load_value_evaluator`). Remains the separate-net fallback for any value-only consumer that wants a pure `NormalizedValueModel`. **best epoch 4** (val plateaued, run killed at epoch 20; MAE≠strength yet again — gameplay improved). value_scale σ=23.05 (backfilled — run was killed pre-finalization). **Beats `M_62k_warmM55k` 65-35-0 (+2.44, 65%, n=100)**. MCTS-300 vs its own 1-turn: 55-45 (+1.30, n.s.). **Caveat (C20–C22):** the experimental self-play fine-tunes below beat it *head-to-head* (e14 +5.07, R_e8 +2.92) but the fixed ensemble panel stays flat/down, i.e. self-play *exploitation*, not objective gain — so M82k remains champion until something wins the objective yardstick. See FIRST_NN §11 (C19). |
| `ftA_plain_M82k_nn70t2` | 2026-06-02 | 2 | 1 | 5k self-play `M82k_nn70_t2_5k` (M82k-vs-t2, 1-turn) | `[256, 256]` GELU, dropout=0.2, wd=0, lr 3e-4; **warm-start from `M_82k_warmM62k`** | 710k | 5.556 (self-play split — not cross-comparable) | **Experimental self-play fine-tune (C20), NOT promoted.** Checkpoint of record = **epoch 14** (`epoch_014.pt` = best.pt; "e14"). Beats M82k **+5.07 head-to-head** (304-95-1, n=400, 76.2%) — but ensemble panel only 94.4% vs M82k 96.4% (head-to-head gain is largely self-play exploitation). value_scale σ=25.14. Parent of the round-2 fine-tunes. |
| `ftB1_l2sp1e3_M82k_nn70t2` | 2026-06-02 | 2 | 1 | 5k self-play `M82k_nn70_t2_5k` | `[256, 256]` GELU, dropout=0.2, wd=0; **L2-SP λ=1e-3 anchored to M82k** | 710k | 5.863 | **Experimental (C20), not used.** Round-1 L2-SP arm. Anchor froze the fit (train MSE ~stuck); **lost to M82k −1.79** (38-61, n=100). Anchoring a *base* model against beneficial self-play drift HURTS. |
| `ftB2_l2sp1e2_M82k_nn70t2` | 2026-06-02 | 2 | 1 | 5k self-play `M82k_nn70_t2_5k` | `[256, 256]` GELU, dropout=0.2, wd=0; **L2-SP λ=1e-2 anchored to M82k** | 710k | 6.074 | **Experimental (C20), not used.** Strongest round-1 anchor; **lost to M82k −3.32** (32-68). More anchor = worse — confirms anchoring hurts when adapting a base model to the self-play distribution. |
| `ft2_plain_e14_hardmix6k` | 2026-06-02 | 2 | 1 | 6k = `e14_hardmix_1k` (hard-opponent mix) + `M82k_nn70_t2_5k` | `[256, 256]` GELU, dropout=0.2, wd=0; **warm-start from `ftA` e14** | 854k | 5.298 (not cross-comparable) | **Experimental round-2 plain fine-tune (C21), not promoted.** Checkpoint of record = **epoch 10** (`epoch_010.pt`); best.pt=e1 by val but e10 strongest by gameplay (MAE≠strength). Beats e14 +2.59; **strongest pure NN-vs-NN player** (wins the 3-model round-robin, 64.8%). But over-specialized: ensemble **regressed to 88.0%** (alphas_gen_1 84→80). value_scale σ=25.71 (best.pt). |
| `ft2_l2sp1e4_e14_hardmix6k` | 2026-06-02 | 2 | 1 | 6k = `e14_hardmix_1k` + `M82k_nn70_t2_5k` | `[256, 256]` GELU, dropout=0.2, wd=0; **L2-SP λ=1e-4 anchored to e14**, warm-start from `ftA` e14 | 854k | 5.281 | **Experimental round-2 L2-SP arm (C21) — best all-rounder, not promoted.** Checkpoint of record = **epoch 8** (`epoch_008.pt`; "R_e8"); best.pt=e24 by val. Beats e14 **+2.92** (most of any candidate) AND holds the ensemble panel **93.7%** (≈e14's 94.4%) AND **patched the weak spots** (alphas_gen_1 84→94, gen_7 90→94). Loses to `ft2_plain` e10 head-to-head (40-58) but is far the better generalist. Gentle anchor when *refining an already-adapted* model helps — opposite of ftB1/ftB2. |
| `sp_v_256x2` | 2026-06-10 | 2 | **3** | **41k MCTS self-play** (`cpp_selfplay_30k`+`_10k`+`cpp_ab_batch`, π+root_value) | `[256,256]` GELU dropout=0.2 wd=1e-4; **warm from `M_82k`**; bs=256 | ~6.8M | 3.693 | **First v3 (PUCT self-play) value nets — the capacity sweep.** epoch 5. **MAE NOT cross-comparable to v1/v2 rows** (self-play states are far lower-variance than the heuristic-ensemble distribution). |
| `sp_v_256x2_bs8192` | 2026-06-10 | 2 | 3 | 41k self-play | `[256,256]`; warm from `M_82k`; **bs=8192 `--fast-loader`** | ~6.8M | 3.687 | Same arch at bs=8192/lr=1e-3 — **validated the fast config holds champion-recipe quality** (3.687 ≈ 3.693 bs=256). epoch 18, value_scale σ=5.77. The apples-to-apples **256×2 sweep reference**. |
| `sp_v_512x2` | 2026-06-10 | 2 | 3 | 41k self-play | `[512,512]`; **from scratch**; bs=8192 | ~6.8M | 3.704 | Capacity sweep — wider trunk (~353k params). epoch 10. |
| `sp_v_384x3` | 2026-06-10 | 2 | 3 | 41k self-play | `[384,384,384]`; from scratch; bs=8192 | ~6.8M | 3.710 | Capacity sweep — deeper trunk. **Weakest on every measure** (ensemble 82.8%; loses both head-to-heads). epoch 10. |
| `joint_taper128` | 2026-06-10 | 2 | 3 | 41k self-play | **shared trunk** `[256,256]→128` + value head + 7 fixed + 2 pointer heads; **soft-π** policy + margin value; warm trunk from `sp_v_256x2_bs8192` | ~6.8M (value rows) | 3.66 (value head) | **Stage-B joint value+policy model.** Value held → no negative transfer. **Beats previous-best (champion value + 9 separate unweighted heads) at 800-sim PUCT: Python (won) + C++ 198-2 = 99.0%, +12.95.** Trained to epoch 33 (crash), best epoch 27; value_scale 3.28 (measured post-hoc). Superseded as strongest by `joint_cand_feat178` (loses temp-0 63-36). Not promoted to `nn_models/best`. |
| `joint_cand_feat178` | 2026-06-11 | 2 (**cand178**) | 3 | 41k self-play | shared trunk `[256,256]→128`, dropout 0.2; **candidate 178-feature encoder** (`encoder_tag` `cand_feat178_v1`: running-score + turns-to-feeding + renovate/grow bits, begging stripped + post-hoc add-back); warm trunk (full) from `joint_taper128` | ~6.8M (value rows) | 3.61 (value head val) | **Feature-engineered encoder experiment (strongest agent to date), NOT promoted.** best **epoch 39**; value_scale 5.78 (measured; the in-loop `epoch_*.pt` carry the stale warm-start 3.28 — use `best.pt`). **Beats `joint_taper128` at 800-sim full-legality PUCT (C++): temp-0 63-36-1 (+2.13, 63%), temp-0.3 52-47-1 (+0.95, 52%).** Encoder is forward-compatible via the C++/Python registry (`encoder_for_tag`). Superseded on data size by `joint_cand_feat178_57k` (the 57k retrain). See SHARED_TRUNK.md. |
| `joint_taper128_57k` | 2026-06-12 | 2 | 3 | **57k self-play** (41k = `cpp_selfplay_30k`+`_10k`+`cpp_ab_batch`, + `joint_selfplay_15k` + `joint_selfplay_5k`) | shared trunk `[256,256]→128`, dropout 0.2, wd 1e-4; **soft-π** policy + margin value; **bs 8192 `--fast-loader`**; warm trunk (full) from `joint_taper128/best` | ~9.7M (value train rows) | 3.637 (value head val) | **57k retrain of `joint_taper128` (v2 encoder).** best **epoch 48** (early-stop, 63 epochs); value_scale 5.707. Improves on parent's val_mae (3.66→3.637) on 1.4× data. Enabled by the streamed-path / direct-to-split `_finalize_payloads` rebuild (build peak 3.14 GB vs the old ~10 GB OOM at 57k — see SHARED_TRUNK.md §3). **800-sim PUCT (C++, c_uct 0.5): beats the 41k `joint_taper128` 91-8-1 (+6.40) t0 / 94-6 (+5.71) t03 — same ~90% +16k-games gain the candidate showed (the big-data win is encoder-independent); and TIES `joint_cand_feat178_57k` 50-49-1 t0 / 47-51-2 t03 (margins ~0)** — v2 and the candidate encoder are equal at 57k (the candidate's 41k edge washed out). Not promoted. |
| `joint_cand_feat178_57k` | 2026-06-12 | 2 (**cand178**) | 3 | **57k self-play** (same five run dirs as `joint_taper128_57k`) | shared trunk `[256,256]→128`, dropout 0.2, wd 1e-4; **candidate 178-feature encoder** (`cand_feat178_v1`); soft-π + margin value; **bs 8192 `--fast-loader`**; warm trunk (full) from `joint_cand_feat178/best` | ~9.7M (value train rows) | 3.604 (value head val) | **57k retrain of `joint_cand_feat178` (candidate encoder) — strongest by val_mae to date.** best **epoch 39** (early-stop, 54 epochs); value_scale 5.735. Improves on parent (3.61→3.604) and beats `joint_taper128_57k` on val (3.604 vs 3.637), mirroring the 41k candidate>v2 edge. **800-sim PUCT (C++, c_uct 0.5): beats the 41k `joint_cand_feat178` 89-11 (t0) / 87-12-1 (t03) — a huge +16k-games gain (despite a near-flat val_mae move, MAE≠strength); but TIES `joint_taper128_57k` 49-50-1 (t0) / 51-47-2 (t03) — the candidate encoder's 41k edge over v2 vanished once both retrained on 57k.** Equivalent strength to the simpler v2 model; not promoted. Superseded as strongest by `joint_taper128_thin`. See SHARED_TRUNK.md §3. |
| `joint_taper128_thin` | 2026-06-15 | 2 | 3 | **117k self-play, snapshot-thinned** (1/6 of the old 57k + 1/2 of the new `joint_taper57k_selfplay_60k`) | shared trunk `[256,256]→128`, dropout 0.2, wd 1e-4; **int8 store + per-dir snapshot-keep** (fits the 8 GB M1, ~80 s/epoch vs 1100 s thrash); bs 8192, all cores; warm trunk (full) from `joint_taper128_117k`/epoch-25 | ~6.8M (value train rows) | 2.726 (value val — **low-variance thin val, not cross-comparable**) | **Superseded by `joint_taper128_thin_sp30k_lr3e4` (loses 75-76%).** Was the first joint model to clear the objective ensemble yardstick. best **epoch 55** (early-stop, 70). **800-sim PUCT (C++): beats `joint_taper128_57k` 84-15-1 (+3.68) t0 / 86-13-1 (+3.65) t03.** vs the 8-config heuristic ensemble: ~100%. `value_scale` caveat: stored 3.019 is a low-variance-val artifact; common-distribution value ≈ 6.25 (used in matches). See SHARED_TRUNK.md. |
| `joint_taper128_thin_sp30k_lr3e4` | 2026-06-15 | 2 | 3 | **60k new self-play** (`joint_taper128_thin_selfplay_60k`), 1/2 snapshot-keep | shared trunk `[256,256]→128`, dropout 0.2, wd 1e-4; bs 8192; **warm from `joint_taper128_thin_sp30k`/epoch-17** (itself warm from `joint_taper128_thin`); lr 3e-4 (reduced from 1e-3 after oscillation); int8 store | ~5.3M (value train rows) | 2.29 val_mae (low-variance self-play val, not cross-comparable) | **Superseded as champion by `exp_visit_combined` (2026-06-18; loses 213-281, −0.50 at 800-sim MCTS, common-state value_scale). Was `nn_models/best` 2026-06-15 → 06-18.** best **epoch 17** (early-stop, patience 8, 25 epochs). **800-sim PUCT (C++, temp=0): beats `joint_taper128_thin` 76-24 (+2.35) t0 / 75-25 (+2.65) t05.** Also beats all earlier joint champions: `joint_taper128_57k` 89%/86%, `joint_cand_feat178_57k` 82%/86%, `joint_cand_feat178` 99%/95%, `joint_taper128` 94%/98%. value_scale stored 4.24 (own self-play val distribution — measure on common state set before mixed matches). See SHARED_TRUNK.md. |
| `exp_visit_combined` | 2026-06-18 | 2 | 3 | **40k diverse visit-selection self-play** (`visit_t07_20k` temp 0.7 + `visit_t10_20k` temp 1.0 — the data-variation experiment's winning data) | shared trunk `[256,256]→128`, dropout 0.2, wd 1e-4; **warm (full) from `joint_taper128_thin_sp30k_lr3e4`**; **L2-SP λ=1e-3**; bs 2048; int8 store | 40k games | 2.343 val_mae (low-variance self-play val, not cross-comparable) | **CURRENT CHAMPION; PROMOTED to `nn_models/best` (2026-06-18).** best **epoch 15** (early-stop). **800-sim MCTS (C++, common-state value_scale): beats prior champion `joint_taper128_thin_sp30k_lr3e4` 281-213-6 = 56.2% (+0.50, 500 games).** From the data-variation experiment: diverse visit-selection data > near-greedy Q-selection data (Q models fell *below* the champion). **40k did NOT beat the best single 10k condition** (ties `exp_visit_t10` 51.5%) — the diverse-data gain *saturates ~10k games*. value_scale: stored 2.776 (biased training-val proxy); **deployed = 4.345** (common-state prediction std; written to `best.meta.json` + the `cpp_export_best` manifest). **NOTE: promoted on a c_uct=0.5 eval; the codebase c_uct default was then changed to 1.0 — deployment now runs at c_uct 1.0, not yet validated for this model.** |
| `pooled_all_thin_p20` | 2026-06-18 | 2 | 3 | **~180k pooled self-play, snapshot-thinned** — ALL v3 self-play except `sp_combined_t2`: `joint_taper128_thin_selfplay_60k` + `joint_taper57k_selfplay_60k` (keep 0.15 each) + `sp_combined_t1_20k` + `visit_t07_20k` (keep 0.28 each) + `visit_t10_20k` (keep 1/3) | shared trunk `[256,256]→128`, dropout 0.2, wd 1e-4; bs 2048; lr 3e-4; **L2-SP λ=1e-3**; int8 store; warm (full) from its own epoch-18 first pass (`pooled_all_thin`), itself warm from `exp_visit_combined`/`best.pt` | 6.41M (value train rows) | 2.50 val_mae (low-variance pooled self-play val, not cross-comparable) | **NOT PROMOTED — pooling everything regressed. Champion `exp_visit_combined` retained.** best **epoch 6** (flat val plateau; patience 20, early-stop 26). **800-sim MCTS (C++, common-state value_scale 3.03 vs champion 2.94, c_uct 1.0, temp 0): LOSES to `exp_visit_combined` 259-328-13 = 43.2% (−0.62, 600 games; 95% CI [39.2, 47.2]); re-run with prior-mix `w`=0.01 both seats also loses 270-324-6 = 45.0% (−0.67, 600 games; 95% CI [41.0, 49.0]).** Confirms the data-variation finding: the diverse-data gain saturates ~10k games, so pooling 180k of mixed-provenance data dilutes the champion's winning 40k diverse subset with ~120k older-/weaker-generator (`joint_taper*`) games → net regression. More data ≠ better past saturation. **CAVEAT: these pooled runs used `dropout=0.0` (the `train_shared.py` CLI default), NOT the champion's `dropout=0.2` — so the loss is partly an under-regularization confound, not purely data dilution.** |
| `pooled_all_thin_outcome` | 2026-06-18 | 2 | 3 | same ~180k pooled snapshot-thinned corpus as `pooled_all_thin_p20` | shared trunk `[256,256]→128`, **dropout 0.2** (champion-matched), wd 1e-4; bs 2048; lr 3e-4; **L2-SP λ=1e-3**; int8 store; **warm (full 40/40) from the champion `exp_visit_combined`/`best.pt`**; **`--value-target outcome`** (value head regresses `sign(margin) ∈ {-1,0,1}`, tiebreaker-blind win/draw/loss; `shared_dataset.py` finalize-time transform of the cached margin, no re-encode) | 6.41M (value train rows) | 0.65 val_mse (normalized {-1,0,1} scale, NOT comparable to margin runs) | **NOT PROMOTED — statistical TIE with champion, not a clear win. Champion `exp_visit_combined` retained.** best epoch (flat val); early-stop 29 (patience 20). **800-sim MCTS (C++, common-state value_scale: outcome 0.55 vs champion 2.94 — different units, each leaf self-normalized; c_uct 1.0, temp 0): vs `exp_visit_combined` 305-286-9 = 50.8% win (95% CI [46.8, 54.8], straddles 50%), score margin −0.77.** Win-rate-tie + negative-margin is the expected signature of an outcome target (optimizes WINNING, not points). Big jump over the margin-pooled 43–45%, BUT **3-way confounded**: this run changed the target AND fixed dropout (0.2) AND warm-started from the champion (the margin runs did none) — so the gain can't be cleanly credited to the outcome target. The `dropout=0.2` margin-pooled control is the disambiguating next experiment. |
| `joint_outcome_44k` | 2026-06-22 | 2 | 3 | **44.6k self-play (1600 sims)** — 40k cloud `selfplay_1600_40k_cloud` (seed 100100000) + 4.6k local `selfplay_1600_40k` (seed 100000000, traces replayed) | shared trunk `[256,256]→128`, dropout 0.2, wd 1e-4; bs 2048; lr 3e-4; **L2-SP λ=1e-3 (excludes the fresh outcome head)**; **warm (full, 42 tensors) from champion `exp_visit_combined`/best.pt**; **NEW joint value+outcome: a separate `outcome_head` (E→1, target sign(margin)∈{-1,0,1}) co-trained in the value batch off the SAME embedding (one trunk forward) — margin head unchanged** | 44,608 games | margin head 2.59 val_mae + **0.69 outcome sign-acc** (low-variance self-play val, not cross-comparable) | **NOT YET EVALUATED — Phase-2 MCTS eval pending (margin vs outcome vs mixture leaf). First GCP cloud-trained model.** best **epoch 12** (early-stop, 20 epochs); value_scale 2.943 (training-val proxy — re-measure on a common state set for matches). Warm-start preserved value/policy (both flat across epochs — expected on on-policy data); this run mainly *adds* the outcome head. Distinct from `pooled_all_thin_outcome` (value head itself regressed outcome, either/or) — this keeps margin AND adds outcome jointly. Outcome-head C++ export/read not yet ported (Phase 2). |

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
- **Status**: superseded as strongest by `joint_cand_feat178`; still **not `nn_models/best`** (needs consumer wiring). Design + eval: **`SHARED_TRUNK.md`**.

### `joint_cand_feat178` — feature-engineered candidate encoder (178-d)

- **Purpose**: test whether hand-engineering the input encoder — giving the model deterministic features instead of making it re-derive them — beats the v2 encoder at equal everything-else. Same joint architecture and data as `joint_taper128`; the **only** change is the encoder.
- **Encoder delta (`cand_feat178_v1`, 170→178 features)**: per player, **add** `running_score_excl_begging`, `turns_until_next_feeding`, `can_renovate_to_clay`, `can_renovate_to_stone`, `can_grow_family`; **remove** the begging-marker count — begging is handled post-hoc on the value margin (`predicted += −3·(own−opp) begging`), so the net never learns the begging formula. Margin-model only. Selected by the manifest `encoder_tag` through the forward-compatible encoder registry (`encoder_for_tag` in both `encoder.py` and the C++ `encoder.cpp`); adding a future encoder is one registry row.
- **Hyperparameters**: identical to `joint_taper128` (trunk `[256,256]` E=128, dropout 0.2, wd 1e-4, bs 2048, soft-π, per-head balance), **warm-started (full transplant) from `joint_taper128/best`** — only the 170→178 input projection is a fresh layer; the whole deep trunk + value + 9 heads transplant. max-epochs 40, no early stop.
- **Outcome**: best **epoch 39** (val_mae 3.61). **value_scale measured 5.78** (the candidate's value distribution is wider than v2's 3.28 — the running-score feature makes sharper, less-regressed predictions); the per-epoch `epoch_*.pt` checkpoints carry the **stale warm-start 3.28** (the measurement runs post-loop on `best.pt` only — use `best.pt`). **Beats `joint_taper128` at 800-sim full-legality PUCT (C++):** temp-0 **63-36-1 (+2.13, 63%)**, temp-0.3 **52-47-1 (+0.95, 52%)** — a real edge, clearest in deterministic play. (A Python partial at 57 games read ~51%, on the low end of the same noise band — the two engines don't play identical games, ≤1e-4 value/policy diffs compound through PUCT.)
- **C++ + validation**: the candidate encoder + begging add-back are ported to C++ and gated permanently by `test_cpp_candidate_encode_matches_python` (encoder float-exact) + `test_cpp_joint_candidate_matches_python` (joint value/policy ≤1e-4, self-contained random model). Differential-validated byte-exact (encoder) / ≤2.1e-5 (value) / ≤2.1e-6 (policy).
- **Status**: superseded on data size by the 57k retrain `joint_cand_feat178_57k`; **experimental, not promoted.** Design: **`SHARED_TRUNK.md`**.

### `joint_taper128_57k` / `joint_cand_feat178_57k` — 57k retrains

- **Purpose**: retrain both joint models (v2 and the candidate encoder) on the full **57k-game** corpus — the 41k (`cpp_selfplay_30k`+`_10k`+`cpp_ab_batch`) plus `joint_selfplay_15k` (15k) and `joint_selfplay_5k` (1098, replayed from orphan traces) — both warm-started (full transplant) from their 41k bests, to confirm the candidate>v2 edge on more data before any promotion decision.
- **The enabling fix (memory)**: the joint dataset builder OOM'd at 57k — `build_shared_datasets` loaded every cached chunk into RAM up front (~6–8 GB) and `_finalize_payloads` materialized a combined `value__X` that doubled when mask-sliced (≈10 GB peak → macOS compressed-memory thrash on the 8 GB M1). Rebuilt to **stream chunk paths lazily from disk** and **assemble the value tensor directly into its per-split arrays** (no combined array). Build peak dropped to **3.14 GB** (`ru_maxrss`); training-loop adds ~1.5 GB. **This memory behavior is untested and load-bearing — see `SHARED_TRUNK.md` §3 ("the two memory lessons") before refactoring `shared_dataset.py`.**
- **Hyperparameters**: identical joint arch (trunk `[256,256]` E=128, dropout 0.2, wd 1e-4, soft-π, per-head balance) at **bs 8192 `--fast-loader`**, max-epochs 100, early-stop-patience 15, `--save-all-epochs`.
- **Outcome**: both improve modestly on their parents' val_mae on 1.4× data. `joint_taper128_57k` (v2): best **epoch 48** (63 total), val_mae **3.637** (parent 3.66), value_scale 5.707. `joint_cand_feat178_57k` (cand178): best **epoch 39** (54 total), val_mae **3.604** (parent 3.61), value_scale 5.735 — strongest by val_mae to date, and still ahead of the v2 retrain (3.604 < 3.637), mirroring the 41k candidate>v2 result. Both `value_scale`s are consistent with the 41k bs-8192 sweep (sp_v 5.77 / candidate 5.78). **MAE≠strength** (the project's standing caveat) — the 800-sim PUCT eval that decides promotion is **still pending**.
- **800-sim PUCT eval (C++ `run_cpp_match.py`, c_uct 0.5, 100 games/temp; cand57k as P0)**:
  - **More data is a big win, and it's encoder-independent** — `joint_cand_feat178_57k` beats the 41k `joint_cand_feat178` **89-11-0 (+5.23) t0 / 87-12-1 (+6.17) t03**, and the v2 pair mirrors it: `joint_taper128_57k` beats the 41k `joint_taper128` **91-8-1 (+6.40) t0 / 94-6 (+5.71) t03**. Both encoders gain ~90% from the same +16k games — so the magnitude is real, not a confound. The val_mae barely moved (3.61→3.604) yet head-to-head is decisive — the project's MAE≠strength lesson at its sharpest.
  - **The candidate encoder's edge over v2 vanished at 57k** — `joint_cand_feat178_57k` vs `joint_taper128_57k` is a **dead tie: 49-50-1 (+0.17) at temp 0, 51-47-2 (+0.36) at temp 0.3** (margins ~0, inside n=100 noise). At 41k the candidate beat taper 63%/52%; retrain *both* on 57k and they're equal. The hand-engineered features bought an early-data head start that the plain v2 encoder closed out with more games.
- **Status**: both **trained + gameplay-eval'd, neither promoted yet.** On strength they're equivalent, so the candidate encoder no longer justifies its extra machinery (begging strip/add-back, encoder-registry dispatch) — **the simpler v2 `joint_taper128_57k` is the cleaner promote** for equal play; decide on grounds other than strength. (Optional confirmation of the striking 89% magnitude: either 57k model vs the *original* 41k `joint_taper128`.) Neither is `nn_models/best` (still the separate-net `M_82k`; promotion needs value-only consumer wiring). Design: **`SHARED_TRUNK.md`**.

### `joint_taper128_thin` — 117k snapshot-thinned (NEW STRONGEST)

- **Purpose**: scale the corpus to 117k (the 57k + a fresh 60k self-play run generated *by* `joint_taper128_57k`) on the 8 GB M1, where the full 117k OOM'd/thrashed (~1100 s/epoch).
- **The fast-training recipe** (the lever that made it tractable): **per-game snapshot-thinning** — keep **1/6** of each old-57k game's snapshots and **1/2** of each new-60k game's (weight toward the on-policy data; cuts rows *and* within-game autocorrelation, per the `snap6th`/`snap_half` findings) → ~6.8M train rows — **plus int8 feature storage** (every encoder feature is integer; pasture_cap>127 capped) → ~3.5 GB resident, and **all CPU cores** (dropping a wrongly-added `OMP_NUM_THREADS=1`). Result: **~80 s/epoch** (vs 1100 s thrash), warm-started from epoch-25 of the (killed) full-117k run.
- **Two real bugs fixed and validated by this run** (they'd silently mis-calibrated *every* warm-started joint model): (1) the warm-start transplanted the source's `target_std` over the new data's → value head trained against one scale but `predict_margin`/val-MAE used another (7.73 vs 5.57 = 1.39× inflation of val_mae_pts; val_mse, being scale-free, was untouched — which is *why* fixing it moved one metric and not the other). (2) a `NameError` (`x.shape[0]`) crashed the post-hoc `value_scale` *measurement* on any run that finished — which is the root of the stale `value_scale`s across the warm-start chain. Both in `shared_training.py`.
- **`value_scale` is distribution-dependent** (the gotcha): the same model measured **3.019** on its low-variance thin val but **6.25** on a common game-state set. Since MCTS divides each leaf value by `value_scale` so a single `c_uct` is comparable across models, **fair matches require measuring both seats' `value_scale` on the SAME distribution** — the stored manifest values aren't comparable. The matches above patched both seats to common-distribution scales (thin 6.25, 57k 6.71).
- **Outcome**: **beats `joint_taper128_57k` 84-15-1 (t0) / 86-13-1 (t03)** at 800-sim PUCT (C++, common-scale, c_uct 0.5), AND **dominates the 8-config heuristic ensemble** (Python PUCT, 200-sim: champion `alphas_gen_7` 30-0 +23.77; `t2` 4-0; ~100% aggregate, ~2.4× the heuristics' points). The **first joint model to clear the objective ensemble yardstick** — so its strength is real, not self-play exploitation (the failure mode that kept `M_82k` champion).
- **Status**: **STRONGEST; PROMOTED to `nn_models/best` (2026-06-15).** The `best.{pt,meta.json}` pair is a copy of this model's checkpoint. The two value-only consumers (the web UI `nn`/`mcts-leaf` seats and the AWR baseline in `train_policy.py`) load it through the new **`model_kind`-aware `load_value_evaluator`** (`agricola/agents/nn/model.py`) — `"value"` → `NormalizedValueModel.load`, `"shared_trunk"` → `SharedTrunkModel.load`; both expose `predict_margin`/`value_scale`, so the joint model is a drop-in value leaf. The MCTS-leaf consumers (`play_mcts_match.py`, `generate_selfplay_data.py`, `bench_shared_tree.py`) detect the joint `best` and wire value+policy off the one trunk via `make_joint_fns`; the UCT-MACRO-archetype scripts that couldn't take a fused policy (`run_search_tournament.py`/`eval_search_vs_ensemble.py`) have since been retired to `archive/scripts/`.
  - **`value_scale` written: 6.25** (the common-distribution value used in the 800-sim matches), NOT the stored thin-val 3.019. `value_scale` is strongly distribution-dependent — measured on this promotion: **2.89** on the model's own pure-self-play distribution (`joint_taper57k_selfplay_60k`), **5.16** on mid-variance C++ self-play (`cpp_selfplay_10k`), **8.92** on the high-variance heuristic-ensemble distribution (`hidden_info_v2_10k`). 6.25 (registry/SHARED_TRUNK common value) sits in that bracket and keeps the default `c_uct≈0.5` calibrated. `value_scale` is meta-only (read into `model.value_scale` at load), not a state_dict buffer, so only `best.meta.json` was patched; `best.pt` is the verbatim checkpoint.
- Design: **`SHARED_TRUNK.md`**.

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

### `joint_taper128_thin_sp30k_lr3e4` — self-play iteration on `joint_taper128_thin` (NEW STRONGEST)

- **Purpose**: one self-play iteration on top of `joint_taper128_thin` — generate fresh data with the current champion and retrain, the core AlphaZero loop.
- **Data**: `joint_taper128_thin_selfplay_60k` — 60k games generated by `joint_taper128_thin` at 600-sim PUCT, c_uct=0.5, T=1.0. Trained with `--snapshot-keep 0.5` → ~30k games worth of decision points (~5.3M value train rows).
- **Hyperparameters**: identical architecture to `joint_taper128_thin` (trunk `[256,256]` E=128, dropout 0.2, wd 1e-4, bs 8192, soft-π, int8 store). Two-stage warm-start: first run at lr=1e-3 warm from `joint_taper128_thin/best` (oscillated around val_mse 0.534, killed at epoch 19); relaunched at **lr=3e-4** warm from that run's epoch-17 checkpoint → converged smoothly, early-stop at epoch 25 (best epoch 17, val_mse 0.5322).
- **Outcome**: best epoch 17, val_mae 2.29, value_scale 4.24 (own-distribution; measure on common state set for fair cross-model matches). **800-sim PUCT (C++, c_uct=0.5):** beats `joint_taper128_thin` **76-24 (+2.35) at T=0 / 75-25 (+2.65) at T=0.5**. Beats all prior joint champions decisively (82–99% across temps). A bug in `shared_training.py` (odd-length val tensor at finalization) was fixed during this run; the checkpoint itself was unaffected.
- **Status**: **STRONGEST; PROMOTED to `nn_models/best` (2026-06-15).** value_scale 4.24 is the own-distribution measurement — re-measure on a common state set before running mixed matches against models from different distributions.

---

## Updating this file

When a training run produces a new checkpoint:

1. Add a row to the summary table — copy the format above, fill in from the checkpoint's `config.json` and `test_metrics.json`.
2. Add a "Per-model details" subsection — include purpose, hyperparameter delta from defaults, headline outcome (test MAE + any match results), and Status.
3. If the new model supersedes an older one for a specific use case, flip the older model's Status column in the summary table to "superseded" with a brief note pointing at the new model.
4. If the model is trained against a new `ENCODING_VERSION` or `DATA_VERSION`, mark older models with the prior version as "incompatible" in their Status.

Keep entries terse — full reasoning lives in **`FIRST_NN.md`**, not here. This file is a navigable catalog, not a research log.
