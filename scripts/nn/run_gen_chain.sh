#!/bin/bash
# Chained self-play generation:
#   1. Resume the 20k temp=1.0 visit-selection run (original config)
#   2. -> 10k Q-selection @ temp=0.005
#   3. -> 10k Q-selection @ temp=0.01
#   4. -> 10k Q-selection @ temp=0.02
# Each link runs only if the previous succeeded (&&).
set -e
cd "$(dirname "$0")/../.."
PY=python
GEN=scripts/nn/generate_selfplay_data_cpp.py
RUNS=data/nn_training/runs

# Link 1: resume the 20k (visit-selection, temp 1.0)
"$PY" "$GEN" --n-games 20000 --n-workers 8 --sims 800 --c-uct 1.0 \
  --temperature 1.0 --prior-mix 0.1 --model-dir nn_models/cpp_export_best \
  --chunk-size 100 --out-dir "$RUNS/20260616-223628-c379" --resume \
  >> "$RUNS/selfplay_c1_t10_m01_20k.log" 2>&1

# Link 2: 10k Q-selection @ temp 0.005
"$PY" "$GEN" --n-games 10000 --n-workers 8 --sims 800 --c-uct 1.0 \
  --temperature 0.005 --prior-mix 0.1 --select-by q \
  --model-dir nn_models/cpp_export_best --chunk-size 100 \
  --out-dir "$RUNS/selq_t0005_10k" \
  > "$RUNS/selq_t0005_10k.log" 2>&1

# Link 3: 10k Q-selection @ temp 0.01
"$PY" "$GEN" --n-games 10000 --n-workers 8 --sims 800 --c-uct 1.0 \
  --temperature 0.01 --prior-mix 0.1 --select-by q \
  --model-dir nn_models/cpp_export_best --chunk-size 100 \
  --out-dir "$RUNS/selq_t001_10k" \
  > "$RUNS/selq_t001_10k.log" 2>&1

# Link 4: 10k Q-selection @ temp 0.02
"$PY" "$GEN" --n-games 10000 --n-workers 8 --sims 800 --c-uct 1.0 \
  --temperature 0.02 --prior-mix 0.1 --select-by q \
  --model-dir nn_models/cpp_export_best --chunk-size 100 \
  --out-dir "$RUNS/selq_t002_10k" \
  > "$RUNS/selq_t002_10k.log" 2>&1

echo "CHAIN COMPLETE"
