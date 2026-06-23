#!/bin/bash
# Runs ON the GCP VM (uploaded in the job tarball). Plays the c_uct sweep as five
# per-sim-level phases — each phase 10k self-play games of the current champion vs
# itself, both seats at that sim level, c_uct drawn log-uniform [0.3,3] per seat,
# mix-leaf alpha=0.9. All cores work each phase; phases run in sequence so each
# level gets exactly 10k games. Writes out/sweep_<S>.csv (one row per game).
set -e
cd "$HOME"
mkdir -p out
# SWEEP_N games per sim level (per VM); SWEEP_BASE_OFFSET keeps each VM's seed
# ranges disjoint so two boxes' games never collide (merge = concat per level).
N="${SWEEP_N:-10000}"
OFF="${SWEEP_BASE_OFFSET:-0}"
i=0
for S in 400 800 1200 1600 2400; do
  base=$((OFF + i * 1000000)); i=$((i + 1))
  echo "=== phase sims=$S base-seed $base n=$N start $(date +%T) ==="
  python3 scripts/nn/run_cpp_sweep.py \
    --p0-dir nn_models/cpp_export_best --p1-dir nn_models/cpp_export_best \
    --n "$N" --jobs "$(nproc)" --temperature 0.0 \
    --sweep-sims "$S" --cuct-lo 0.3 --cuct-hi 3 --cuct-log --mix-alpha 0.9 \
    --base-seed "$base" --out-csv "out/sweep_$S.csv"
  echo "=== phase sims=$S done $(date +%T) rows=$(wc -l < "out/sweep_$S.csv") ==="
done
echo ALL_PHASES_DONE
