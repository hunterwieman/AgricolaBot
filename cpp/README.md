# `cpp/` — the C++ Agricola engine port

The native self-play inner loop (engine + MCTS + libtorch inference) that the
Python engine is the differential oracle for. See **`../CPP_ENGINE_PLAN.md`** for
the full design and the staged plan; this README is just how to build it.

**Status: Stage 0 (scaffolding).** Only the build skeleton + a toolchain-proving
pybind module exist yet. The engine lands across Stages 1–6.

## Layout

```
cpp/
  CMakeLists.txt            three targets from one core lib
  include/agricola/         public headers (Stage 0: version.hpp)
  src/                      implementations (mirror agricola/*.py modules)
  bindings/pybind_module.cpp  the `agricola_cpp` differential-test module
  apps/selfplay.cpp         the standalone production data-gen binary
  build/                    GITIGNORED — compiled artifacts
```

## Prerequisites

```sh
~/miniconda3/bin/pip install pybind11 cmake     # cmake is pip-installable
```

A C++17 compiler (Apple clang / gcc) is assumed present. libtorch ships with the
conda `torch` install (`python -c "import torch; print(torch.utils.cmake_prefix_path)"`)
and is only needed from Stage 5 (`-DAGRICOLA_BUILD_TORCH=ON`).

## Build

```sh
PYBIND11_DIR=$(~/miniconda3/bin/python -m pybind11 --cmakedir)
~/miniconda3/bin/cmake -S cpp -B cpp/build \
    -Dpybind11_DIR="$PYBIND11_DIR" \
    -DPython_EXECUTABLE="$HOME/miniconda3/bin/python"
~/miniconda3/bin/cmake --build cpp/build -j
```

This produces `cpp/build/agricola_cpp.*.so` (the pybind module) and
`cpp/build/selfplay` (the standalone binary).

## Test

The differential gates live in the normal pytest suite and import the built
module (skipping cleanly if it isn't built):

```sh
~/miniconda3/bin/python -m pytest tests/test_cpp_*.py -q
```
