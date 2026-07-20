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

# Provenance: stamp the image with the exact commit it is built from, so every
# downloaded action trace records its code version (play_web.py -> the trace's
# `code_version` field) and a reported game can be reproduced by checking out that
# commit. We only ever deploy committed code, so refuse a dirty tree — that keeps
# the stamp an EXACT description of what runs, not an approximation.
if [[ -n "$(git status --porcelain)" ]]; then
  echo "deploy.sh: working tree is dirty — commit or stash changes before deploying" >&2
  echo "           (the trace's code-version stamp must match the code that runs)." >&2
  exit 1
fi
GIT_COMMIT="$(git rev-parse HEAD)"

echo "deploy.sh: deploying champion export '${EXPORT_DIR}' at commit ${GIT_COMMIT}"
exec flyctl deploy \
  --build-arg "EXPORT_DIR=${EXPORT_DIR}" \
  --build-arg "GIT_COMMIT=${GIT_COMMIT}" \
  "$@"
