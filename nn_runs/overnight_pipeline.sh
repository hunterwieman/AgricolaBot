#!/usr/bin/env bash
# Overnight data-gen + training pipeline.
# - 5 sections × 10k games each → 5 new run dirs
# - 7 models trained on various combinations → 7 new model dirs
# - Each step gated on the previous's exit code via `set -e -o pipefail`
# - Per-step logs in nn_runs/overnight_*.log

set -e -o pipefail
cd "$(dirname "$0")/.."

# ---- 7 V3-only config paths (drops t2) ----
V3_ONLY=(
    tuned_configs/alphas_gen_7.json
    tuned_configs/alphas_gen_1.json
    tuned_configs/panel_wood_r1.json
    tuned_configs/panel_gen16.json
    tuned_configs/panel_gen_25.json
    tuned_configs/panel_gen47.json
    tuned_configs/panel_gen47_wood020.json
)

# ---- Top-3 V3 by round-robin (alphas_gen_7, alphas_gen_1, panel_wood_r1) ----
STRONG3=(
    tuned_configs/alphas_gen_7.json
    tuned_configs/alphas_gen_1.json
    tuned_configs/panel_wood_r1.json
)

# ---- Shared training hyperparams (v2-dropout architecture) ----
TRAIN_ARGS=(
    --hidden-dims 256,256
    --activation gelu --norm layer --dropout 0.2
    --lr 1e-3 --weight-decay 1e-4
    --batch-size 512
    --max-epochs 100 --early-stop-patience 20
)

EXISTING_5K=data/nn_training/runs/20260528-031528-9d6a

echo "=== Phase 1: Data generation (5 sections × 10k games) ==="
date

# Section 1: standard recipe (all 8, bimodal T)
python -O scripts/nn/generate_training_data.py \
    --n-games 10000 --n-workers 8 --base-seed 5000000 \
    --out-dir data/nn_training/runs/S1_standard_bimodal_10k \
    2>&1 | tee nn_runs/overnight_gen_S1.log

# Section 2: no V1 (7 V3 only, bimodal T)
python -O scripts/nn/generate_training_data.py \
    --n-games 10000 --n-workers 8 --base-seed 6000000 \
    --out-dir data/nn_training/runs/S2_no_v1_bimodal_10k \
    --approved-configs "${V3_ONLY[@]}" \
    2>&1 | tee nn_runs/overnight_gen_S2.log

# Section 3: top-3 V3 only, bimodal T
python -O scripts/nn/generate_training_data.py \
    --n-games 10000 --n-workers 8 --base-seed 7000000 \
    --out-dir data/nn_training/runs/S3_strong3_bimodal_10k \
    --approved-configs "${STRONG3[@]}" \
    2>&1 | tee nn_runs/overnight_gen_S3.log

# Section 4: all 8 configs, T=0.3 fixed
python -O scripts/nn/generate_training_data.py \
    --n-games 10000 --n-workers 8 --base-seed 8000000 \
    --out-dir data/nn_training/runs/S4_all_lowT_10k \
    --fixed-temperature 0.3 \
    2>&1 | tee nn_runs/overnight_gen_S4.log

# Section 5: 7 V3 only, T=0.3 fixed
python -O scripts/nn/generate_training_data.py \
    --n-games 10000 --n-workers 8 --base-seed 9000000 \
    --out-dir data/nn_training/runs/S5_no_v1_lowT_10k \
    --fixed-temperature 0.3 \
    --approved-configs "${V3_ONLY[@]}" \
    2>&1 | tee nn_runs/overnight_gen_S5.log

echo "=== Phase 2: Training (7 models) ==="
date

# M1: 10k standard bimodal (S1 alone)
python -O scripts/nn/train_first.py "${TRAIN_ARGS[@]}" \
    --run-dir data/nn_training/runs/S1_standard_bimodal_10k \
    --out-dir nn_models/M_10k_standard_bimodal \
    2>&1 | tee nn_runs/overnight_train_M_10k_standard_bimodal.log

# M2: 10k no V1 bimodal (S2 alone)
python -O scripts/nn/train_first.py "${TRAIN_ARGS[@]}" \
    --run-dir data/nn_training/runs/S2_no_v1_bimodal_10k \
    --out-dir nn_models/M_10k_no_v1_bimodal \
    2>&1 | tee nn_runs/overnight_train_M_10k_no_v1_bimodal.log

# M3: 10k strong-3 bimodal (S3 alone)
python -O scripts/nn/train_first.py "${TRAIN_ARGS[@]}" \
    --run-dir data/nn_training/runs/S3_strong3_bimodal_10k \
    --out-dir nn_models/M_10k_strong3_bimodal \
    2>&1 | tee nn_runs/overnight_train_M_10k_strong3_bimodal.log

# M4: 10k all-configs lowT (S4 alone)
python -O scripts/nn/train_first.py "${TRAIN_ARGS[@]}" \
    --run-dir data/nn_training/runs/S4_all_lowT_10k \
    --out-dir nn_models/M_10k_all_lowT \
    2>&1 | tee nn_runs/overnight_train_M_10k_all_lowT.log

# M5: 10k no-V1 lowT (S5 alone)
python -O scripts/nn/train_first.py "${TRAIN_ARGS[@]}" \
    --run-dir data/nn_training/runs/S5_no_v1_lowT_10k \
    --out-dir nn_models/M_10k_no_v1_lowT \
    2>&1 | tee nn_runs/overnight_train_M_10k_no_v1_lowT.log

# M6: 15k standard (existing 5k + S1)
python -O scripts/nn/train_first.py "${TRAIN_ARGS[@]}" \
    --run-dir "$EXISTING_5K" data/nn_training/runs/S1_standard_bimodal_10k \
    --out-dir nn_models/M_15k_standard \
    2>&1 | tee nn_runs/overnight_train_M_15k_standard.log

# M7: 55k everything (existing 5k + S1 + S2 + S3 + S4 + S5)
python -O scripts/nn/train_first.py "${TRAIN_ARGS[@]}" \
    --run-dir "$EXISTING_5K" \
              data/nn_training/runs/S1_standard_bimodal_10k \
              data/nn_training/runs/S2_no_v1_bimodal_10k \
              data/nn_training/runs/S3_strong3_bimodal_10k \
              data/nn_training/runs/S4_all_lowT_10k \
              data/nn_training/runs/S5_no_v1_lowT_10k \
    --out-dir nn_models/M_55k_all \
    2>&1 | tee nn_runs/overnight_train_M_55k_all.log

echo "=== All done ==="
date
