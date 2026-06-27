#!/bin/bash
# launch_encode.sh SHARD_IDX N_SHARDS [HOME_ZONE]
# Creates one t2a-standard-16 SPOT box to encode shard SHARD_IDX. Tries the home
# zone first, then the rest (spot stockout is per-zone). Self-deletes on success;
# --max-run-duration is the hard backstop.
set -uo pipefail
IDX=$1; NS=$2; HOME_ZONE=${3:-us-central1-a}
NAME=agricola-enc-$IDX
ALL_ZONES=(us-central1-a us-central1-b us-central1-f)
# put home zone first
ZONES=("$HOME_ZONE"); for z in "${ALL_ZONES[@]}"; do [ "$z" != "$HOME_ZONE" ] && ZONES+=("$z"); done

for Z in "${ZONES[@]}"; do
  echo ">>> creating $NAME in $Z (shard $IDX/$NS)"
  if gcloud compute instances create "$NAME" --zone="$Z" \
      --machine-type=t2a-standard-16 \
      --provisioning-model=SPOT --instance-termination-action=DELETE \
      --max-run-duration=3h \
      --image-family=debian-12-arm64 --image-project=debian-cloud \
      --boot-disk-size=40GB --boot-disk-type=pd-ssd \
      --scopes=cloud-platform \
      --metadata=shard-idx=$IDX,n-shards=$NS \
      --metadata-from-file=startup-script=_cloud_spatial/encode_shard.sh \
      --quiet 2>&1; then
    echo ">>> $NAME launched in $Z"
    exit 0
  fi
  echo ">>> $Z failed (stockout?), trying next zone"
done
echo "FATAL: could not launch $NAME in any zone"; exit 1
