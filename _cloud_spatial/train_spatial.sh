#!/bin/bash
# Runs ON a GCP box (spot, on-demand fallback). Downloads the 6-shard spatial
# chunk cache, stubs the game pickles (training only COUNTS them on a cache hit),
# and trains TWO joint shared-trunk models in parallel on the SAME data with
# --snapshot-keep 0.5 ("discard half"):
#   A: trunk 256,256 -> embed 128   (mirrors champion joint_a256_300k)
#   B: trunk 512,512 -> embed 256   (mirrors candidate B_wide)
# Epoch checkpoints upload incrementally. Does NOT self-delete (training needs a
# human convergence call); --max-run-duration is the cost backstop. Resume is
# MANUAL: relaunch with metadata init-a/init-b = gs:// path of the latest epoch
# ckpt and lr-a/lr-b = 3e-4 (warm-resume), per the 6arch-sweep playbook.
set -uo pipefail
exec >/var/log/job.log 2>&1
echo "JOB START train-spatial $(date -u)"
export HOME=${HOME:-/root}
md() { curl -s -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/$1"; }

BUCKET=gs://agricola-selfplay-252381762565
SP=$BUCKET/spatial300k
N_SHARDS=6
INIT_A=$(md attributes/init-a); INIT_B=$(md attributes/init-b)
LR_A=$(md attributes/lr-a); LR_A=${LR_A:-1e-3}
LR_B=$(md attributes/lr-b); LR_B=${LR_B:-1e-3}
MODELS=$(md attributes/models); MODELS=${MODELS:-a256 b512}  # which to train (space/comma list)
MODELS=${MODELS//,/ }
cd /

# --- deps ----------------------------------------------------------------------
sudo apt-get update -qq
sudo apt-get install -y -qq python3-pip || { echo "FATAL: apt pip"; exit 1; }
python3 -m pip install --break-system-packages -q numpy torch \
  || { echo "FATAL: pip install failed"; exit 1; }
python3 -c "import numpy,torch" || { echo "FATAL: deps import failed"; exit 1; }

# --- code ----------------------------------------------------------------------
mkdir -p "$HOME/AgricolaBot"
gcloud storage cp "$SP/code.tgz" "$HOME/code.tgz" || { echo "FATAL: fetch code"; exit 1; }
tar xzf "$HOME/code.tgz" -C "$HOME/AgricolaBot"
cd "$HOME/AgricolaBot"
RUNROOT=$HOME/AgricolaBot/data/nn_training/runs

# --- pull each shard's chunk cache + stub its game pickles ---------------------
RUNDIRS=""
for k in $(seq 0 $((N_SHARDS-1))); do
  RD=$RUNROOT/shard_$k; CD=$RD/shared_cand_spatial_v1_chunks
  mkdir -p "$RD/games" "$CD"
  CNT=$(gcloud storage cat "$SP/shard_$k/count.txt" 2>/dev/null | tr -d '[:space:]')
  CNT=${CNT//[^0-9]/}
  [ -n "$CNT" ] && [ "$CNT" -ge 1 ] || { echo "FATAL: bad count.txt for shard $k ($CNT)"; exit 1; }
  echo "shard $k: expecting $CNT chunks"
  gcloud storage rsync --recursive "$SP/shard_$k/shared_cand_spatial_v1_chunks" "$CD" \
    || { echo "FATAL: chunk download shard $k"; exit 1; }
  NC=$(ls "$CD"/chunk_*.npz 2>/dev/null | wc -l | tr -d ' ')
  [ "$NC" -eq "$CNT" ] || { echo "FATAL: shard $k got $NC/$CNT chunks"; exit 1; }
  # stub one games pickle per chunk (cache-hit only counts them, never reads them)
  for i in $(seq 0 $((CNT-1))); do : > "$RD/games/$(printf 'worker_%05d.pkl' "$i")"; done
  RUNDIRS="$RUNDIRS $RD"
done
echo "all $N_SHARDS shards staged: $RUNDIRS"

# --- common training args (champion recipe; snapshot-keep 0.5 = discard half) --
COMMON="--encoder spatial --run-dir $RUNDIRS --snapshot-keep 0.5 \
  --dropout 0.2 --value-weight 9 --batch-size 2048 \
  --max-epochs 120 --early-stop-patience 12 --save-all-epochs"

# --- one training, with incremental ckpt upload to the bucket ------------------
train_one() {  # $1=label $2=trunk $3=embed $4=lr $5=init(gs:// or empty)
  local LABEL=$1 TRUNK=$2 EMBED=$3 LR=$4 INIT=$5
  local OUT=$HOME/out/$LABEL
  mkdir -p "$OUT"
  local EXTRA=""
  if [ -n "$INIT" ] && [ "$INIT" != "none" ]; then
    # --init-from reads the ckpt's sibling .meta.json, so fetch BOTH.
    gcloud storage cp "$INIT" "$OUT/warm_init.pt" || { echo "FATAL: fetch init $LABEL"; return 1; }
    gcloud storage cp "${INIT%.pt}.meta.json" "$OUT/warm_init.meta.json" || { echo "FATAL: fetch init meta $LABEL"; return 1; }
    EXTRA="--init-from $OUT/warm_init.pt"
    echo "=== $LABEL warm-resume from $INIT (lr $LR) ==="
  else
    echo "=== $LABEL random-init (lr $LR) ==="
  fi
  # incremental epoch-ckpt upload loop
  ( while true; do
      gcloud storage rsync "$OUT" "$SP/ckpts/$LABEL" >/dev/null 2>&1
      sleep 90
    done ) &
  local UP=$!
  # Small-MLP matmuls saturate ~8 threads; more just spin + add BLAS sync cost
  # (observed: OMP=16 → only ~8 cores effective). 8/model is near-optimal; the box
  # is sized by RAM (128GB for 2 parallel loads), not cores. PYTHONUNBUFFERED so
  # per-epoch lines flush to train.out immediately (else block-buffered = blind).
  local TH=8
  PYTHONUNBUFFERED=1 OMP_NUM_THREADS=$TH MKL_NUM_THREADS=$TH OPENBLAS_NUM_THREADS=$TH \
    python3 -u scripts/nn/train_shared.py $COMMON \
      --trunk-hidden-dims "$TRUNK" --embedding-dim "$EMBED" --lr "$LR" \
      $EXTRA --out-dir "$OUT" > "$OUT/train.out" 2>&1
  local RC=$?
  kill "$UP" 2>/dev/null
  gcloud storage rsync "$OUT" "$SP/ckpts/$LABEL" >/dev/null 2>&1
  echo "=== $LABEL FINISHED rc=$RC @ $(date -u) ==="
  return $RC
}

# SEQUENTIAL (not parallel): one model at a time so the single small box has no
# co-tenant memory-bandwidth contention → full-speed epochs on 8 vCPU. Each
# train_shared.py is its own process, so a256's ~33GB dataset is freed before
# b512 builds its own — both fit a 64GB box one-at-a-time. Cheapest finish.
echo "=== training [$MODELS] SEQUENTIALLY (cheap single-box, no contention) @ $(date -u) ==="
for M in $MODELS; do
  case $M in
    a256) train_one a256 "256,256" 128 "$LR_A" "$INIT_A"; echo "a256 exit=$?";;
    b512) train_one b512 "512,512" 256 "$LR_B" "$INIT_B"; echo "b512 exit=$?";;
    *) echo "WARN: unknown model $M, skipping";;
  esac
done
echo "TRAIN DONE $(date -u). Box left alive — inspect, then delete."
