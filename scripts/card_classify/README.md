# Card-mechanics classification tooling

Generates and maintains **`CARD_IMPLEMENTATION_PROGRESS.md`** (repo root) — a per-card
classification of every Agricola card (420 minors + 420 occupations) by the engine
mechanics/features it uses, plus its implementation status.

Everything here is **torch-free plain Python**; run from the **repo root** with
`~/miniconda3/bin/python` (needs `agricola` + the card registries importable).

## The taxonomy

The mechanics taxonomy (the code list + definitions + rulings) is the `TAXONOMY` string in
**`gen_classify.py`** — the durable intellectual artifact. Codes span Activation (ONPLAY / HOOK /
ATWILL / PASSIVE / LATCH), hook Timing/Seam/Firing/Actor, Scope caps, Effects (E-*), Legality
/ structure (L-*), and per-card State (ST-*). Key refined definitions baked in: `L-GEOMBOARD`
= *game-variable* board arrangement (card reveal-order or adjacency) — **not** round-space
numbers/timing/scheduling; `L-CARDFIELD` = the card *itself* is a sown field — not a tile-pool
(`ST-STACK`) nor reading field contents; scoring rules never carry `HOOK`; `A-OWN` is the default
actor; etc.

## How the doc was built (pipeline)

1. Two independent low-effort **classification passes** per card type (`gen_classify.py` → Workflow).
2. **Taxonomy tightening** (geometry / LATCH / scoring / CAP definitions) + a cold re-pass.
3. **High-effort adjudication** of the cards where the two passes disagreed (`gen_review.py`).
4. A **geometry-code verification sweep** (`gen_geomreview.py`) — catches shared bias that
   agreement-based flagging misses.
5. **User rulings** on the residual edge cases.
6. A cross-model **Fable cold sweep + Fable adjudication** of existing-vs-Fable disagreements
   (`gen_fable_adj.py`) — *paused pending usage reset* at time of writing.

## Regenerate the doc

```
~/miniconda3/bin/python scripts/card_classify/doc_gen.py
```

`doc_gen.py` compiles everything in `data/` into the doc. Override **precedence** (highest first):
`RESIDUAL_FIX` (user rulings) → `PATCH_MIN`/`PATCH_OCC` (hand-verified) → `FABLE_ADJ` (cross-model
adjudication) → `GEOM_FIX` (geometry sweep) → `ADJUDICATED` (high-effort) → cold-pass label; then
`GROUP_C_STRIP` post-processing. Markers: ✅ implemented · 🚫 wontfix/banned · ⬜ not yet ·
⚖ high-effort adjudicated · 🔶 residual low-confidence.

## `data/` (workflow outputs consumed by `doc_gen.py`)

| file | what |
|---|---|
| `minors_cold.json` / `occ_cold.json` | current cold-pass labels (tightened taxonomy) |
| `minors_prev.json` / `occ_prev.json` | prior pass (the cross-pass comparison baseline) |
| `minors_cards.json` / `occ_cards.json` | per-card metadata (text, cost, prereq, players, impl status) |
| `adjudicated.json` | high-effort adjudication of the disagreement set (step 3) |
| `geom_fixed.json` | geometry-code verification sweep (step 4) |
| `fable_minors.json` / `fable_occ.json` | Fable cold-sweep labels (step 6) |
| `fable_adj.json` | Fable adjudication output — **absent until the paused run completes** |

## Resume the paused Fable adjudication

```
~/miniconda3/bin/python scripts/card_classify/gen_fable_adj.py   # writes ./fable_adj.js (503 cards, 63 batches, model=fable)
```
1. Launch `fable_adj.js` via the Workflow tool (`model: fable`, `effort: high`).
2. Save its `{result:{cards:[...]}}` output as `data/fable_adj.json`.
3. Re-run `doc_gen.py` — the guarded `FABLE_ADJ` override folds the adjudicated tags in automatically.

## Classify a new deck / re-run a pass

```
~/miniconda3/bin/python scripts/card_classify/gen_classify.py --type minor|occupation \
    [--model fable] [--effort low|medium|high] --out <path>.js
```
Emits a self-contained classification Workflow script (inlines the taxonomy + the card batch) and a
`<path>.js.cards.json` metadata sidecar. `gen_review.py` / `gen_geomreview.py` are the historical
phase generators (kept for reference; their inputs were the original session's workflow outputs,
now preserved in `data/`).
