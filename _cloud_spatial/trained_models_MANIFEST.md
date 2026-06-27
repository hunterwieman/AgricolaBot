# trained_models/ — durable archive (gs://agricola-selfplay-252381762565/trained_models/)

Four 300k-corpus joint shared-trunk value+policy models. Each dir has `best.pt` +
`best.meta.json` + `config.json`. The `gen300k` corpus = 300k self-play games @
1600 sims, snapshot-keep 0.5.

| Dir | Arch | Encoder | Converged val_mse | Role |
|---|---|---|---|---|
| `joint_a256_300k_CHAMPION` | trunk [256,256]→128 | v2 (170-d) | 0.5452 | **Deployed champion** (= A_baseline of the 300k 6-arch sweep). Keep. |
| `joint_b512_300k_bwide` | trunk [512,512]→256 | v2 (170-d) | 0.5376 | B_wide candidate (wider; ~1.76× cost/forward; held, not deployed). |
| `spatial_a256_300k` | trunk [256,256]→128 | spatial (274-d, `cand_spatial_v1`) | 0.5479 | Spatial-encoder experiment arm (256). |
| `spatial_b512_300k` | trunk [512,512]→256 | spatial (274-d, `cand_spatial_v1`) | 0.5405 | Spatial-encoder experiment arm (512). |

## Spatial-encoder experiment verdict (2026-06-26)

The `cand_spatial_v1` encoder adds four 13-cell geometry masks per player
(room/stable/field/enclosed-in-pasture) on top of v2 → 274-d. Tested whether
per-cell farm geometry helps. **It does not — mild regression on both architectures
at both search depths** (C++ MCTS, mix leaf α=0.9, scales re-measured on a common
6k-state set so both seats are calibrated identically):

| Match (spatial = P0) | 800 sims | 1600 sims |
|---|---|---|
| spatial_a256 vs champion (5000 games/cond) | 48.2% | 45.4% |
| spatial_b512 vs B_wide (2000 games/cond) | 45.9% | 47.1% |

The spatial encoder was independently verified correct (masks exactly match
farmyard geometry); the null is real, not a bug. Conclusion: v2's aggregate
features (counts/capacities/fences) already capture the geometrically-relevant
signal; exact cell layout adds little and the 104 sparse extra features dilute the
input. **Spatial encoding retired as a dead end. Champion unchanged.**
