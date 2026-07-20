# syntax=docker/dockerfile:1
#
# AgricolaBot web UI — single always-on container for Fly.io.
#
# Two stages:
#   1. build   — compiles the standalone C++ `selfplay` binary for Linux.
#   2. runtime — slim Python image that serves play_web.py and shells out to it.
#
# The C++ binary MUST be compiled inside the image: the local artifact is a
# Mach-O arm64 binary and won't run on Linux. The AI ("mcts") seat in
# play_web.py runs `cpp/build/selfplay --move` as a subprocess and reads the
# weights from nn_models/cpp_export_best — both are baked in below.

# ---------------------------------------------------------------------------
# Stage 1: build the C++ `selfplay` binary
# ---------------------------------------------------------------------------
# CMakeLists.txt calls find_package(pybind11) and defines pybind11_add_module
# unconditionally at *configure* time, so pybind11 + python dev headers must be
# present even though we only build the standalone `selfplay` target (which
# links agricola_core only — no libtorch, no pybind link). nlohmann/json is
# vendored under cpp/third_party, so no extra package is needed for it.
FROM ubuntu:24.04 AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        python3 \
        python3-dev \
        python3-pybind11 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY cpp/ cpp/

# Configure, then build ONLY the standalone selfplay target (skips compiling
# the agricola_cpp pybind module — the differential-test surface we don't ship).
# pybind11_DIR is set explicitly from the installed package so find_package()
# (called unconditionally in CMakeLists.txt at configure time) can't miss it.
RUN cmake -S cpp -B cpp/build -DCMAKE_BUILD_TYPE=Release \
        -Dpybind11_DIR="$(python3 -m pybind11 --cmakedir)" \
    && cmake --build cpp/build --target selfplay -j "$(nproc)" \
    && test -x cpp/build/selfplay

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# numpy is the ONLY third-party Python runtime dependency. The server is
# stdlib-only (http.server + SSE); torch is never imported on the serving path.
RUN pip install --no-cache-dir numpy

WORKDIR /app

# Compiled binary from the build stage, placed at the exact path play_web.py
# expects (cpp/build/selfplay, resolved relative to play_web.py's location).
COPY --from=build /src/cpp/build/selfplay cpp/build/selfplay

# Weights for the C++ inference. nn_models/cpp_export_best is a SYMLINK in the
# repo, and Docker COPY does NOT follow symlinks — so the build can't just copy
# `cpp_export_best`. Instead the concrete target dir is passed in as a build-arg
# (EXPORT_DIR) and copied to the path play_web.py expects. .dockerignore lets the
# whole cpp_export_* family through to the build context; only this one dir lands
# in the image. `./deploy.sh` resolves the symlink and sets the arg automatically,
# so promoting a champion is just re-pointing the symlink — no edit here.
ARG EXPORT_DIR=cpp_export_exp_visit_combined
COPY nn_models/${EXPORT_DIR}/ nn_models/cpp_export_best/

# Python source + web assets.
COPY agricola/ agricola/
# agricola/agents/base.py (+ other agent modules) import `filter_implemented`
# from tests.test_utils at module load, so ship that one util plus the empty
# package marker. The deployed C++ bot never CALLS it — this only satisfies the
# import. test_utils.py itself depends on numpy + agricola only (both present).
COPY tests/__init__.py tests/test_utils.py ./tests/
COPY play.py play_web.py ./
COPY static/ static/
COPY templates/ templates/

# Smoke checks (no fabricated game state): prove the server imports torch-free
# and that the C++ binary is present and executable.
RUN python -c "import play_web" \
    && test -x cpp/build/selfplay

# Provenance stamp: the exact git commit this image was built from, passed in by
# `./deploy.sh` (git rev-parse HEAD) and read by play_web.py into each downloaded
# action trace (the `code_version` field), so a reported game can be reproduced by
# checking out that commit. The container has no .git (.dockerignore excludes it),
# so the value must be baked in here. Placed last so it never invalidates the
# cached layers above — only this cheap layer rebuilds when the commit changes.
ARG GIT_COMMIT=unknown
ENV AGRICOLA_GIT_COMMIT=${GIT_COMMIT}

EXPOSE 8000

CMD ["python", "play_web.py", "--host", "0.0.0.0", "--port", "8000", "--seats", "human", "mcts", "--no-browser"]
