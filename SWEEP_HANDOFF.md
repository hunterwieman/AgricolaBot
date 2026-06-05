# UCT c_uct sweep — handoff

Goal: find the best `c_uct` for the **UCT** MCTS agent (NN leaf) by sweeping it against the
1-turn NNAgent. This is step 1 of a larger plan (UCT sweep → PUCT sweep → 6-agent matrix). All
code is in place and tested; this doc is just how to run the sweep and read it.

## Environment
- Run everything with `~/miniconda3/bin/python` (base conda env has torch + pytest; system
  python3 lacks them).
- Working dir: `/Users/hunterwieman/Desktop/Agricola/AgricolaBot`. Changes are uncommitted on `main`.

## The UCT agent being swept
- UCT (vanilla, no policy prior), **policy-sampled fence macros** (`--macro-policy combined:awr`:
  fence chains are sampled from the trained policy instead of an expensive value-net greedy rollout),
  **regular** legality, **NN leaf = plain `e(s,0)`** (1 forward pass; `--leaf-differential` is OFF
  by default).
- `leaf_value_scale` is **auto** (= `value_scale/2 = 11.53`); do NOT pass `--leaf-value-scale`.
- Caches (`FENCE_SCAN_CACHE`, `PARETO_OPT_LEVEL`) are **ON by default** now (module defaults) and
  inherited — do NOT pass `--opt-level`/`--fence-cache`. Keep them on (user instruction).

## ONE decision before launching: the 1-turn baseline's eval form
The `nn` opponent is currently `NNAgent(model, differential=True, ...)` in `scripts/play_mcts_match.py`
(`_build_agent`, the `if name == "nn":` branch). The UCT leaf is *plain* `e(s,0)`, so for an
apples-to-apples NN value function on both sides, **change that opponent to `differential=False`**
(one line) so the 1-turn baseline is also plain `e(s,0)`. Recommended. (If the user says leave it
differential, that's fine too — just note the baseline is then marginally stronger / lower-variance.)
Decide this BEFORE the sweep so the sweep and the later matrix use the same baseline.

## Run the sweep (background, ~30–40 min)
```bash
cd /Users/hunterwieman/Desktop/Agricola/AgricolaBot
LOG=/tmp/uct_sweep.log
: > "$LOG"
for c in 0.0608 0.25 0.5 1.0 2.0 4.0; do
  echo "===== c_uct=$c =====" >> "$LOG"
  ~/miniconda3/bin/python scripts/play_mcts_match.py \
    --opponent nn --policy uct --legality regular --fence-mode macro \
    --macro-policy combined:awr --leaf nn \
    --c-uct "$c" --seeds 1000-1049 --jobs 8 >> "$LOG" 2>&1
  echo "" >> "$LOG"
done
echo "SWEEP DONE" >> "$LOG"
```
- 50 games each (seeds 1000–1049, **disjoint** from the matrix's 0–99 so the chosen c isn't
  overfit to matrix seeds).
- Do NOT pipe the python through `grep` in a background job — `grep` block-buffers and the live
  per-game lines won't appear until it exits. Write the raw output to the log (as above) and grep
  the file afterward.

## Read it / pick the winner
```bash
grep -E "c_uct=|^P0 " /tmp/uct_sweep.log
```
Each block's summary line is `P0 W-D-L P1  avg ... margin <m>` from **P0 = the UCT agent's** view.
Pick the c with the best record (most P0 wins / highest positive `margin`). Notes:
- `leaf_value_scale=11.53` (auto) is the *training-distribution* differential-std/2; over actual
  game states the plain leaf is ~σ5.7, so Q is normalized to ~σ0.5 and the optimal c may land on
  the higher side. **If the winner is at a boundary (0.0608 or 4.0), extend the sweep that way**
  (e.g. add 8.0, 16.0).
- Expect noise at n=50; if two c values are within ~1 game/W-D-L, treat them as tied and prefer
  the lower c (less exploration; cheaper) unless margin clearly favors the higher.
- Context: in tiny smokes the UCT agent *lost* to the 1-turn agent at several c values. That may
  be real (the policy-sampled macros use the spatially-blind `fencing` head, top-1 ~28%). If UCT
  loses across the whole sweep, that's a finding, not a bug — report it.

## After the UCT sweep (next steps, for context)
1. **PUCT c sweep** — same structure but the agent is PUCT: replace the UCT flags with
   `--policy combined:awr --legality full` (fence-mode auto-coerces to flatten); sweep `--c-uct`
   over the same range vs `--opponent nn`. (PUCT's exploration formula differs, so its optimum
   differs from UCT's.) The two PUCT matrix agents share this c.
2. **The 6-pairing matrix** — `scripts/run_nn_search_matrix.py --puct-c <best_puct> --uct-c <best_uct>
   --sims 500 --n 100 --jobs 8`. It drives all 6 pairings of {UCT, 1-turn, PUCT-unweighted,
   PUCT-awr} through `play_mcts_match.py`. (It does NOT pass opt flags, so it inherits caches-on.)

## State of the code (all done, uncommitted on `main`)
- `scripts/play_mcts_match.py`: added `nn` opponent (1-turn NNAgent); `_combined_policy` lru_cache
  (loads the 9 policy heads once/worker); `--macro-policy`/`--opp-macro-policy` (policy-sampled
  fence macros); `--leaf-differential/--no-leaf-differential` (default off = plain `e(s,0)`; on =
  the mean `(e(s,0)-e(s,1))/2`, same scale, `leaf_value_scale` auto = `value_scale/2`);
  `--opt-level`/`--fence-cache` are None-sentinels (inherit module default); **`_value_model` now
  calls `.eval()`** (fixes a dropout-active-at-leaf bug that affected mcts-vs-mcts games).
- `agricola/agents/mcts.py`: `MCTSSearch(macro_policy_fn=...)` + `_sample_fence_action`
  (proportional sampling from the policy under the search's legality); macro-greedy agent is now an
  `EvaluatorAgent` built from the search's own evaluator (no hardcoded V3 — fixes a V3 contaminant
  when the leaf is the NN).
- `agricola/agents/restricted.py`: `make_strict_restricted_legal_actions(evaluator=...)` — the
  harvest-feed cap ranks with the provided value fn (NN when leaf=nn), not hardcoded V3.
- `agricola/opt_config.py`: defaults flipped to `PARETO_OPT_LEVEL=3`, `FENCE_SCAN_CACHE=True`
  (caches ON by default; FENCE_SCAN_CACHE is result-identical, PARETO_OPT_LEVEL≥1 is
  reproducible-but-reordered — see memory). Two default-pin tests updated; full suite (1023) green.

## Gotchas
- `NormalizedValueModel.load()` returns the model in **train** mode — any new code that uses it for
  inference must `.eval()` (the source of the bug above).
- The stored `value_scale` (23.05) is the *differential* leaf std over the *training* distribution;
  it over-normalizes ~2× for actual game states. Fine for a sweep (the sweep finds c), but don't
  treat the absolute c value as physically meaningful across distributions.
