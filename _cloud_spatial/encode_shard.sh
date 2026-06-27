#!/bin/bash
# Runs ON a GCP spot box. Encodes ONE shard of the gen300k corpus with the
# spatial encoder into the shared chunk cache, uploads chunks to the bucket,
# and self-deletes on success. Resilient: per-chunk resume (re-downloads any
# already-uploaded chunks first), incremental upload, success-gated self-delete.
#
# Metadata args (read from the metadata server): shard-idx, n-shards.
# Log: /var/log/job.log  (also ~/job.out for non-root tail).
set -uo pipefail
# Runs as root under GCE's startup-script runner → redirect directly (no `sudo
# tee` / process-substitution, which fails in the runner's no-/dev/fd context and
# silently killed the script at line 1 with an empty log). 644 = world-readable.
exec >/var/log/job.log 2>&1
echo "JOB START encode-shard $(date -u)"
export HOME=${HOME:-/root}   # root's GCE startup env has no HOME; set -u would trip on it

BUCKET=gs://agricola-selfplay-252381762565
SRC=$BUCKET/gen300k
OUTROOT=$BUCKET/spatial300k
md() { curl -s -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/$1"; }

SHARD_IDX=$(md attributes/shard-idx); SHARD_IDX=${SHARD_IDX//[^0-9]/}
N_SHARDS=$(md attributes/n-shards);   N_SHARDS=${N_SHARDS//[^0-9]/}
[ -n "$SHARD_IDX" ] && [ -n "$N_SHARDS" ] || { echo "FATAL: bad shard metadata ($SHARD_IDX/$N_SHARDS)"; exit 1; }
echo "shard $SHARD_IDX of $N_SHARDS"

SHARDOUT=$OUTROOT/shard_$SHARD_IDX
RUNDIR=$HOME/AgricolaBot/data/nn_training/runs/shard_$SHARD_IDX
CHUNKS=$RUNDIR/shared_cand_spatial_v1_chunks
N=$(nproc)

# --- success-gated self-delete watcher (Layer 1) -------------------------------
nohup setsid bash -c '
  while ! grep -q "SHARD DONE" /var/log/job.log 2>/dev/null; do sleep 20; done
  Nn=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/name)
  Zz=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/zone | awk -F/ "{print \$NF}")
  gcloud compute instances delete "$Nn" --zone="$Zz" --quiet
' >/dev/null 2>&1 < /dev/null &

# --- deps ----------------------------------------------------------------------
sudo apt-get update -qq
sudo apt-get install -y -qq python3-pip || { echo "FATAL: apt pip"; exit 1; }
python3 -m pip install --break-system-packages -q numpy torch \
  || { echo "FATAL: pip install failed"; exit 1; }
python3 -c "import numpy,torch" || { echo "FATAL: deps import failed"; exit 1; }

# --- code ----------------------------------------------------------------------
mkdir -p "$HOME/AgricolaBot"
gcloud storage cp "$OUTROOT/code.tgz" "$HOME/code.tgz" || { echo "FATAL: fetch code"; exit 1; }
tar xzf "$HOME/code.tgz" -C "$HOME/AgricolaBot"
cd "$HOME/AgricolaBot"

# --- compute this shard's contiguous pickle slice (deterministic global order) -
gcloud storage ls "$SRC/t1/games/worker_*.pkl" "$SRC/t15/games/worker_*.pkl" \
  "$SRC/t2/games/worker_*.pkl" "$SRC/t3/games/worker_*.pkl" 2>/dev/null \
  | sort > /tmp/all_pkls.txt
TOTAL=$(wc -l < /tmp/all_pkls.txt | tr -d ' ')
[ "$TOTAL" -ge 1600 ] || { echo "FATAL: listed only $TOTAL pickles (<1600)"; exit 1; }
# contiguous block: floor split, last shard takes remainder
BASE=$(( TOTAL / N_SHARDS )); REM=$(( TOTAL % N_SHARDS ))
START=$(( SHARD_IDX * BASE + (SHARD_IDX < REM ? SHARD_IDX : REM) ))
CNT=$(( BASE + (SHARD_IDX < REM ? 1 : 0) ))
echo "TOTAL=$TOTAL shard slice: start=$START count=$CNT"
[ "$CNT" -ge 1 ] || { echo "FATAL: empty slice"; exit 1; }
sed -n "$((START+1)),$((START+CNT))p" /tmp/all_pkls.txt > /tmp/my_pkls.txt
MY=$(wc -l < /tmp/my_pkls.txt | tr -d ' ')
[ "$MY" -eq "$CNT" ] || { echo "FATAL: sliced $MY != $CNT"; exit 1; }

# --- download this shard's pickles --------------------------------------------
# A contiguous global slice can span two temp dirs (t1/t15/t2/t3), and those dirs
# REUSE worker basenames (e.g. worker_127_c000.pkl exists in t15 AND t2) — so
# flattening them into one games/ dir would COLLIDE (later overwrites earlier =
# fewer files). Stage per-temp (unique within a temp), then rename into games/ as
# globally-unique sequential worker_NNNNN.pkl (keeps the worker_*.pkl glob; encode
# reads pickle CONTENT, the filename is irrelevant; chunk_i = i-th sorted local).
mkdir -p "$RUNDIR/games" "$CHUNKS"
echo "downloading $MY pickles (per-temp staged to avoid basename collisions)..."
idx=0
for T in t1 t15 t2 t3; do
  grep "/gen300k/$T/games/" /tmp/my_pkls.txt > "/tmp/t_$T.txt" || true
  n=$(wc -l < "/tmp/t_$T.txt" | tr -d ' ')
  [ "$n" -ge 1 ] || continue
  rm -rf "/tmp/stage_$T"; mkdir -p "/tmp/stage_$T"
  gcloud storage cp $(cat "/tmp/t_$T.txt") "/tmp/stage_$T/" || { echo "FATAL: download $T"; exit 1; }
  ns=$(ls "/tmp/stage_$T"/*.pkl 2>/dev/null | wc -l | tr -d ' ')
  [ "$ns" -eq "$n" ] || { echo "FATAL: $T staged $ns/$n"; exit 1; }
  for f in "/tmp/stage_$T"/*.pkl; do
    mv "$f" "$RUNDIR/games/$(printf 'worker_%05d.pkl' "$idx")"; idx=$((idx+1))
  done
  rm -rf "/tmp/stage_$T"
done
NG=$(ls "$RUNDIR/games/"/*.pkl 2>/dev/null | wc -l | tr -d ' ')
[ "$NG" -eq "$CNT" ] || { echo "FATAL: downloaded $NG/$CNT pickles"; exit 1; }
echo "downloaded $NG pickles OK"

# --- resume: pull any chunks already uploaded for this shard -------------------
gcloud storage rsync "$SHARDOUT/shared_cand_spatial_v1_chunks" "$CHUNKS" 2>/dev/null || true

# --- incremental chunk upload while encoding -----------------------------------
( while true; do
    gcloud storage rsync "$CHUNKS" "$SHARDOUT/shared_cand_spatial_v1_chunks" 2>/dev/null
    sleep 45
  done ) &
UP=$!

# --- encode --------------------------------------------------------------------
echo "=== ENCODE shard $SHARD_IDX ($CNT pickles, $N workers) @ $(date -u) ==="
PYTHONPATH=. python3 scripts/nn/encode_shared.py \
  --run-dir "$RUNDIR" --encoder spatial --encode-workers "$N"
RC=$?
kill "$UP" 2>/dev/null
[ "$RC" -eq 0 ] || { echo "FATAL: encode_shared rc=$RC"; exit 1; }

# verify every chunk exists, then final upload + count manifest
NC=$(ls "$CHUNKS"/chunk_*.npz 2>/dev/null | wc -l | tr -d ' ')
[ "$NC" -eq "$CNT" ] || { echo "FATAL: produced $NC/$CNT chunks"; exit 1; }
gcloud storage rsync "$CHUNKS" "$SHARDOUT/shared_cand_spatial_v1_chunks" || { echo "FATAL: final upload"; exit 1; }
echo "$CNT" | gcloud storage cp - "$SHARDOUT/count.txt" || { echo "FATAL: count upload"; exit 1; }

echo "SHARD DONE idx=$SHARD_IDX chunks=$NC $(date -u)"
