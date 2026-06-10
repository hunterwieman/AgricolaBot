# Build for the C++ Agricola engine port (CPP_ENGINE_PLAN.md §9).
#
# Three targets, one core library (the "one library, two front-ends" shape):
#   - agricola_core : STATIC library — the engine/MCTS/inference/encoder/policy.
#   - agricola_cpp  : pybind11 module — the differential-test surface (§3.3).
#   - selfplay      : standalone executable — production data-gen (§1).
#
# Stage 0 needs only pybind11 (header/compiled); nlohmann/json is added at Stage
# 1 when the C++ canonical (de)serializer lands. NN inference (value + policy
# heads) and the native MCTS used to require libtorch; they are now a hand-rolled
# MLP (src/mlp.cpp + src/nn.cpp) over raw exported weights — NO libtorch — so the
# full engine (incl. MCTS + NN) builds with a plain `cmake -S cpp -B cpp/build`.
#
# Configure (from repo root), pointing CMake at the pip-installed pybind11:
#   PYBIND11_DIR=$(~/miniconda3/bin/python -m pybind11 --cmakedir)
#   ~/miniconda3/bin/cmake -S cpp -B cpp/build \
#       -Dpybind11_DIR="$PYBIND11_DIR" \
#       -DPython_EXECUTABLE="$HOME/miniconda3/bin/python"
#   ~/miniconda3/bin/cmake --build cpp/build -j
#
# See cpp/README.md.

cmake_minimum_required(VERSION 3.18)
project(agricola_cpp LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)  # defaulted operator== for structural state equality
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()


# --- macOS broken-Command-Line-Tools libc++ workaround ----------------------
# Some Command Line Tools installs ship a clang whose default libc++ search
# path (<toolchain>/usr/include/c++/v1) is empty, while the headers live only
# under the active SDK. Detect *only the broken case* by compile-testing
# <string>, and if it fails, add the SDK's libc++ headers as a system include.
# No-op on healthy toolchains.
include(CheckCXXSourceCompiles)
check_cxx_source_compiles(
  "#include <string>\nint main(){ std::string s; return (int)s.size(); }"
  AGRICOLA_LIBCXX_OK)
if(APPLE AND NOT AGRICOLA_LIBCXX_OK)
  execute_process(
    COMMAND xcrun --show-sdk-path
    OUTPUT_VARIABLE _agricola_sdk OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
  if(_agricola_sdk AND EXISTS "${_agricola_sdk}/usr/include/c++/v1/string")
    message(STATUS "agricola: default libc++ headers missing; adding "
                   "${_agricola_sdk}/usr/include/c++/v1")
    add_compile_options(-isystem "${_agricola_sdk}/usr/include/c++/v1")
  else()
    message(WARNING "agricola: <string> won't compile and no SDK libc++ found; "
                    "you may need to reinstall Command Line Tools "
                    "(xcode-select --install).")
  endif()
endif()

# --- core library -----------------------------------------------------------
add_library(agricola_core STATIC
  src/version.cpp
  src/pasture.cpp
  src/canonical.cpp
  src/hash.cpp
  src/constants.cpp
  src/fences.cpp
  src/fence_universe_data.cpp
  src/helpers.cpp
  src/legality.cpp
  src/action_canonical.cpp
  src/resolution.cpp
  src/engine.cpp
  src/scoring.cpp
  src/setup.cpp
  src/selfplay.cpp
  src/encoder.cpp          # pure — the NN feature encoder (Stage 5)
  src/mlp.cpp              # hand-rolled MLP forward (libtorch-free)
  src/nn.cpp               # value + policy-head inference (uses Mlp)
  src/mcts.cpp             # native PUCT search (uses NNInference)
)
target_include_directories(agricola_core PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${CMAKE_CURRENT_SOURCE_DIR}/third_party)  # vendored nlohmann/json

# --- pybind11 module (differential-test surface) ----------------------------
find_package(pybind11 CONFIG REQUIRED)
pybind11_add_module(agricola_cpp bindings/pybind_module.cpp)
target_link_libraries(agricola_cpp PRIVATE agricola_core)

# --- standalone production binary -------------------------------------------
add_executable(selfplay apps/selfplay.cpp)
target_link_libraries(selfplay PRIVATE agricola_core)

# --- NN inference (hand-rolled MLP — no libtorch) ---------------------------
# nn.cpp / mlp.cpp / mcts.cpp are now plain C++ (raw-weight MLP forward, no
# TorchScript), so they compile into the core lib unconditionally above. The
# AGRICOLA_WITH_NN define gates the nn/mcts declarations in the headers (formerly
# AGRICOLA_WITH_TORCH) and the nn_value / nn_policy / MCTS pybind bindings; it is
# always defined now, so a plain `cmake -S cpp -B cpp/build` builds the full
# engine including MCTS + NN with NO torch flags and NO libtorch dependency.
target_compile_definitions(agricola_core PUBLIC AGRICOLA_WITH_NN=1)
