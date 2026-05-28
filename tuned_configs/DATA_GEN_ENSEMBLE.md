# Data-Generation Ensemble

8 configs used for self-play data generation toward NN training (Phase 5).
Selected to span a wide strength range (from ~30% to ~86% aggregate win rate
in the 8-config V3 round-robin at 40 games/pair) plus one V1-architecture
agent (`t2`) for state-distribution diversity beyond V3's style.

Round-robin win rate is the fraction of round-robin games each config won
against the other V3 configs (out of 280 games each, against 7 V3 opponents
at 40 games per pair). `t2` was not in the V3 round-robin — separate
architecture, characterized by ~5-15% wins against any of the V3 configs.

| Config | File | Round-robin win rate | Description |
|---|---|---|---|
| **t2** | _alias_ (name resolves to `HubrisHeuristicV1(config=CONFIG_V1_T2)`) | n/a (V1 arch; ~5-15% vs V3 configs) | V1+T2: round-2-tuned V1 heuristic, weakest agent in the ensemble but provides cross-architecture state-distribution coverage. |
| **alphas_gen_7** | [`tuned_configs/alphas_gen_7.json`](alphas_gen_7.json) (also `v3_best.json`) | **86.4%** (rank 1) | Final session-best of the 6-category wood_r1 rotation; r1_force_forest_bonus=1000 baked in; current champion. |
| **alphas_gen_1** | [`tuned_configs/alphas_gen_1.json`](alphas_gen_1.json) | 81.1% (rank 2) | First session-best of the alphas category in the rotation; nearly as strong as gen_7 but plays slightly differently (62.5% gen_7 vs gen_1 H2H). |
| **panel_wood_r1** | [`tuned_configs/panel_wood_r1.json`](panel_wood_r1.json) | 61.1% (rank 3) | Pre-rotation wood-tuned V3: gen_16 retuned on v3_resources only with R1-force-forest applied (60 gens). |
| **panel_gen16** | [`tuned_configs/panel_gen16.json`](panel_gen16.json) | 58.2% (rank 4) | Former v3_best: food-tune output (gen_16) before alphas_gen_7's promotion; reed-first R1 opener, the canonical reed-tuned V3 lineage. |
| **panel_gen47_wood020** | [`tuned_configs/panel_gen47_wood020.json`](panel_gen47_wood020.json) | 40.0% (rank 5) | Adversarial probe: panel_gen47 + wood_flat_bonus=0.2; explicit wood-hoarder, designed as an exploit baseline; provides state-distribution coverage of overcommitted-to-wood mistakes. |
| **panel_gen_25** | [`tuned_configs/panel_gen_25.json`](panel_gen_25.json) | 38.9% (rank 6) | Strong V3 alternative born during the original resources tune; different stylistic emphasis than gen_47/gen_16. |
| **panel_gen47** | [`tuned_configs/panel_gen47.json`](panel_gen47.json) | 30.4% (rank 7) | Earlier V3 champion (resources-tune output); weaker than gen_16 in head-to-head but has different play patterns. |

## Notes

- All 7 V3 configs are `HubrisHeuristicV3(config=...)` agents with their respective JSON best_config loaded. Construct via `_make_agent("v3", cfg, seed, restricted=True)` or directly: `HubrisHeuristicV3(seed=seed, config=cfg, lookahead="turn", legal_actions_fn=restricted_legal_actions)`.
- `t2` is `HubrisHeuristicV1(config=CONFIG_V1_T2, lookahead="turn", legal_actions_fn=restricted_legal_actions)`.
- Configs with `r1_force_forest_bonus > 0` (alphas_gen_7, alphas_gen_1, panel_wood_r1) deterministically open with Forest at round 1. The bonus is baked into the config field so loading the JSON is enough — no external evaluator composition needed.
- `panel_gen16` is identical to whatever `v3_best.json` was prior to the alphas_gen_7 promotion. Preserved here as a stable reference.
- `round1_resources_start.json` is the oldest V3 lineage we have and was excluded from this ensemble per the user (round-robin: 8/280 = 2.9% wins — too weak to contribute meaningful trajectory data).

## Round-robin context

The round-robin data this file references: 8 V3 configs (the 7 above plus
`round1_resources_start`), C(8,2) = 28 pairs, 40 games per pair (20 seeds ×
2 colorings, seeds 700000-700019). Run via `/tmp/round_robin_v3.py`.
Aggregate win rates and the W-L grid are in `/tmp/round_robin_v3.out`.
