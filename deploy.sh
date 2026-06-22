#!/usr/bin/env bash
#
# Deploy the AgricolaBot web UI to Fly.io with the CURRENT champion model.
#
# The deployed bot's weights come from whatever `nn_models/cpp_export_best`
# points at. Docker COPY can't follow that symlink, so this script resolves it
# and passes the concrete dir name to the Dockerfile as the EXPORT_DIR build-arg.
# Promoting a new champion is therefore just:
#
#     ln -sfn <new_cpp_export_dir> nn_models/cpp_export_best
#     ./deploy.sh
#
# No Dockerfile / .dockerignore edit needed. Any extra args are forwarded to
# `fly deploy` (e.g. `./deploy.sh --now`).
set -euo pipefail

cd "$(dirname "$0")"

LINK="nn_models/cpp_export_best"
if [[ ! -L "$LINK" ]]; then
  echo "deploy.sh: $LINK is not a symlink — expected it to point at the champion's C++ export dir." >&2
  exit 1
fi

# readlink gives the symlink's literal target (a bare dir name, since the symlink
# is relative within nn_models/). Strip any trailing slash for a clean build-arg.
EXPORT_DIR="$(readlink "$LINK")"
EXPORT_DIR="${EXPORT_DIR%/}"

if [[ ! -f "nn_models/${EXPORT_DIR}/weights_manifest.json" ]]; then
  echo "deploy.sh: nn_models/${EXPORT_DIR}/weights_manifest.json not found — the symlink target looks wrong." >&2
  exit 1
fi

echo "deploy.sh: deploying champion export '${EXPORT_DIR}'"
exec flyctl deploy --build-arg "EXPORT_DIR=${EXPORT_DIR}" "$@"
