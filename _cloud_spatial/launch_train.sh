#!/bin/bash
# launch_train.sh [INIT_A] [INIT_B] [LR_A] [LR_B] [HOME_ZONE]
# Creates one t2a-standard-32 SPOT box (128GB RAM = safe for 2 parallel dataset
# loads; 32 vCPU bundled) to train BOTH spatial models. Fresh launch: no args.
# Warm-resume after preemption: pass gs:// paths to the latest epoch ckpts + 3e-4.
# No self-delete (training needs a convergence call); --max-run-duration backstop.
set -uo pipefail
INIT_A=${1:-}; INIT_B=${2:-}; LR_A=${3:-1e-3}; LR_B=${4:-1e-3}; HOME_ZONE=${5:-us-central1-b}; MODELS=${6:-a256,b512}
NAME=agricola-train
# Cost-right-sized: n2-highmem-8 (8 vCPU, 64GB) trains the two models SEQUENTIALLY
# (train_spatial.sh) — 64GB fits one model's ~33GB dataset, 8 vCPU covers the
# ~6-8 effective cores step-bound training can use, and one-at-a-time avoids the
# memory-bandwidth contention that slowed the shared 32-vCPU box. ~1/3 the
# vCPU-hours of n2-standard-32. x86 (oneDNN/AVX). Spot.
ALL_ZONES=(us-central1-b us-central1-a us-central1-c us-central1-f)
ZONES=("$HOME_ZONE"); for z in "${ALL_ZONES[@]}"; do [ "$z" != "$HOME_ZONE" ] && ZONES+=("$z"); done

for Z in "${ZONES[@]}"; do
  echo ">>> creating $NAME in $Z (init-a='$INIT_A' init-b='$INIT_B' lr=$LR_A/$LR_B)"
  if gcloud compute instances create "$NAME" --zone="$Z" \
      --machine-type=n2-highmem-8 \
      --provisioning-model=SPOT --instance-termination-action=DELETE \
      --max-run-duration=24h \
      --image-family=debian-12 --image-project=debian-cloud \
      --boot-disk-size=100GB --boot-disk-type=pd-ssd \
      --scopes=cloud-platform \
      --metadata=init-a="$INIT_A",init-b="$INIT_B",lr-a="$LR_A",lr-b="$LR_B",models="$MODELS" \
      --metadata-from-file=startup-script=_cloud_spatial/train_spatial.sh \
      --quiet 2>&1; then
    echo ">>> $NAME launched in $Z"; exit 0
  fi
  echo ">>> $Z failed (stockout?), trying next"
done
echo "FATAL: could not launch $NAME"; exit 1
