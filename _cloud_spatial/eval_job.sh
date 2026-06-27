#!/bin/bash
# Runs ON a GCP spot box. Builds the C++ selfplay binary, then plays a 1000-game
# 800-sim MCTS match: a256-spatial (P0) vs champion joint_a256_300k (P1), both at
# the mix leaf alpha=0.9, scales pre-measured on a common set. Self-deletes on done.
set -uo pipefail
exec >/var/log/job.log 2>&1
echo "JOB START eval-match $(date -u)"
export HOME=${HOME:-/root}
BUCKET=gs://agricola-selfplay-252381762565/spatial300k
N=$(nproc)
md() { curl -s -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/$1"; }
MN=$(md attributes/match-n);       MN=${MN:-1000}
MSIMS=$(md attributes/match-sims); MSIMS=${MSIMS:-800}
MSEED=$(md attributes/match-seed); MSEED=${MSEED:-0}
MLABEL=$(md attributes/match-label); MLABEL=${MLABEL:-spatial_a256_vs_champion}
MLABEL=${MLABEL//[^a-zA-Z0-9_]/}
P0DIR=$(md attributes/match-p0dir); P0DIR=${P0DIR:-cpp_export_spatial_a256}; P0DIR=${P0DIR//[^a-zA-Z0-9_]/}
P1DIR=$(md attributes/match-p1dir); P1DIR=${P1DIR:-cpp_export_champ}; P1DIR=${P1DIR//[^a-zA-Z0-9_]/}
echo "match params: n=$MN sims=$MSIMS base-seed=$MSEED label=$MLABEL  P0=$P0DIR P1=$P1DIR"

# self-delete on success marker (Layer 1)
nohup setsid bash -c '
  while ! grep -q "MATCH DONE" /var/log/job.log 2>/dev/null; do sleep 20; done
  Nn=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/name)
  Zz=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/zone | awk -F/ "{print \$NF}")
  gcloud compute instances delete "$Nn" --zone="$Zz" --quiet
' >/dev/null 2>&1 < /dev/null &

# --- deps (C++ build is torch-free; run_cpp_match needs only python3) ----------
sudo apt-get update -qq
sudo apt-get install -y -qq build-essential cmake python3-pybind11 python3-numpy \
  || { echo "FATAL: apt deps"; exit 1; }

# --- code + exports -----------------------------------------------------------
mkdir -p "$HOME/AgricolaBot"
gcloud storage cp "$BUCKET/code.tgz" "$HOME/code.tgz" || { echo "FATAL: code"; exit 1; }
tar xzf "$HOME/code.tgz" -C "$HOME/AgricolaBot"
cd "$HOME/AgricolaBot"
mkdir -p nn_models
gcloud storage cp -r "$BUCKET/eval/$P0DIR" "$BUCKET/eval/$P1DIR" nn_models/ \
  || { echo "FATAL: exports"; exit 1; }

# --- build selfplay binary ----------------------------------------------------
echo "=== building selfplay @ $(date -u) ==="
cmake -S cpp -B cpp/build -DCMAKE_BUILD_TYPE=Release \
  -Dpybind11_DIR=/usr/lib/python3/dist-packages/pybind11/share/cmake/pybind11 || { echo "FATAL: cmake"; exit 1; }
cmake --build cpp/build --target selfplay -j"$N" || { echo "FATAL: build"; exit 1; }
[ -x cpp/build/selfplay ] || { echo "FATAL: no selfplay binary"; exit 1; }
echo "selfplay built OK"

# --- run the match (spatial P0 vs champ P1, mix alpha 0.9) ---------------------
RES=$HOME/$MLABEL.log
( while true; do [ -f "$RES" ] && gcloud storage cp "$RES" "$BUCKET/eval/$MLABEL.partial.txt" 2>/dev/null; sleep 30; done ) &
UP=$!
echo "=== MATCH a256-spatial(P0) vs champion(P1), $MSIMS sims, $MN games (seed $MSEED), $N jobs @ $(date -u) ==="
python3 scripts/nn/run_cpp_match.py \
  --p0-dir "nn_models/$P0DIR" \
  --p1-dir "nn_models/$P1DIR" \
  --n "$MN" --base-seed "$MSEED" --jobs "$N" --sims "$MSIMS" --c-uct 1.0 --temperature 0.0 \
  --leaf-mode-p0 mix --leaf-mode-p1 mix --mix-alpha-p0 0.9 --mix-alpha-p1 0.9 \
  --label "$MLABEL" 2>&1 | tee "$RES"
RC=${PIPESTATUS[0]}
kill "$UP" 2>/dev/null
[ "$RC" -eq 0 ] || { echo "FATAL: match rc=$RC"; exit 1; }
gcloud storage cp "$RES" "$BUCKET/eval/$MLABEL.txt" || echo "WARN: final upload"
echo "MATCH DONE $(date -u)"
