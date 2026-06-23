#!/bin/bash
# LOCAL driver: stands up one t2a-standard-48, builds the selfplay binary, runs the
# 5-phase c_uct sweep detached on the VM, polls until done, pulls results to
# sweep_out/, and DELETES the VM (trap on EXIT + a 2h hard backstop at create time).
# Run from the repo root, backgrounded; tail its log for progress.
set -uo pipefail
# Args: NAME (VM/output id), SWEEP_N (games/level on THIS box), BASE_OFFSET (seed
# offset so two boxes stay disjoint). Defaults = a single 10k/level box.
NAME="${1:-agricola-cuct-sweep}"
SWEEP_N="${2:-10000}"
BASE_OFFSET="${3:-0}"
ZONE=us-central1-a
MACHINE=t2a-standard-48
REPO="$(pwd)"
JOB_TGZ="/tmp/sweep_job_${NAME}.tgz"
OUT_TGZ="/tmp/sweep_out_${NAME}.tgz"

log() { echo "[driver $(date +%H:%M:%S)] $*"; }

cleanup() {
  log "deleting VM $NAME (this is the money-stopper)"
  gcloud compute instances delete "$NAME" --zone="$ZONE" --quiet 2>&1 || log "delete failed / already gone"
  log "instances now:"; gcloud compute instances list 2>&1 | head -3
}
trap cleanup EXIT

ssh_vm() { gcloud compute ssh "$NAME" --zone="$ZONE" --quiet --command="$1" 2>&1; }

log "creating $NAME ($MACHINE, 2h auto-DELETE backstop)"
gcloud compute instances create "$NAME" --zone="$ZONE" \
  --machine-type="$MACHINE" \
  --image-family=debian-12-arm64 --image-project=debian-cloud \
  --boot-disk-size=20GB --scopes=cloud-platform \
  --max-run-duration=2h --instance-termination-action=DELETE 2>&1 || { log "create FAILED"; exit 1; }

log "waiting for ssh (first connect generates a key, ~60s)"
ready=0
for i in $(seq 1 30); do
  if ssh_vm "echo ssh-ok" | grep -q ssh-ok; then ready=1; break; fi
  sleep 10
done
[ "$ready" = 1 ] || { log "ssh never came up"; exit 1; }

log "packaging + uploading (deref cpp_export_best symlink)"
tar czhf "$JOB_TGZ" --exclude='cpp/build' \
  cpp nn_models/cpp_export_best scripts/nn/run_cpp_sweep.py scripts/cloud_remote_sweep.sh 2>&1
gcloud compute scp "$JOB_TGZ" "$NAME":~/sweep_job.tgz --zone="$ZONE" --quiet 2>&1 || { log "scp FAILED"; exit 1; }

log "building selfplay on VM"
ssh_vm '
  set -e
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq build-essential cmake python3-pybind11 python3 >/dev/null
  tar xzf sweep_job.tgz
  cmake -S cpp -B cpp/build -DCMAKE_BUILD_TYPE=Release \
    -Dpybind11_DIR=/usr/lib/python3/dist-packages/pybind11/share/cmake/pybind11 >/dev/null 2>&1
  cmake --build cpp/build --target selfplay -j"$(nproc)" >/dev/null 2>&1
  test -x cpp/build/selfplay && echo BUILD_OK
' | tee /tmp/build.out
grep -q BUILD_OK /tmp/build.out || { log "build FAILED (see above)"; exit 1; }

log "launching detached sweep (n=$SWEEP_N/level, base-offset $BASE_OFFSET)"
ssh_vm "SWEEP_N=$SWEEP_N SWEEP_BASE_OFFSET=$BASE_OFFSET nohup bash scripts/cloud_remote_sweep.sh > run.log 2>&1 & echo launched pid \$!"

log "polling run.log until ALL_PHASES_DONE (up to ~90 min)"
done=0
for i in $(seq 1 90); do
  sleep 60
  out=$(ssh_vm 'tail -1 run.log; echo "  files: $(ls out 2>/dev/null | tr "\n" " ")"')
  log "poll $i | $out"
  echo "$out" | grep -q ALL_PHASES_DONE && { done=1; break; }
done
[ "$done" = 1 ] || log "WARNING: did not see ALL_PHASES_DONE; collecting whatever exists"

log "collecting results"
ssh_vm 'cd ~ && tar czf sweep_out.tgz out run.log 2>/dev/null && echo collected'
mkdir -p "$REPO/sweep_out/$NAME"
gcloud compute scp "$NAME":~/sweep_out.tgz "$OUT_TGZ" --zone="$ZONE" --quiet 2>&1 \
  && tar xzf "$OUT_TGZ" -C "$REPO/sweep_out/$NAME" 2>&1
log "results:"; wc -l "$REPO/sweep_out/$NAME"/out/*.csv 2>&1 || log "no CSVs pulled"
log "driver finished; cleanup (VM delete) runs next"
