// Core library surface for the C++ Agricola engine port (CPP_ENGINE_PLAN.md).
//
// Stage 0 is scaffolding only: this header exists to establish the
// library / binding / app three-target shape. The real engine surface
// (GameState, legal_actions, step, encode, value, policy, mcts) lands in
// Stages 1-6. The version constants below MUST stay in lockstep with the
// Python side (agricola/agents/nn/{encoder,schema}.py) — the differential
// gates check them.
#pragma once

#include <string>

namespace agricola {

// Mirror of Python ENCODING_VERSION (encoder.py) and DATA_VERSION (schema.py).
// Asserted equal in the differential harness.
inline constexpr int kEncodingVersion = 2;
inline constexpr int kDataVersion = 3;

// Human-readable build/version string for the core library.
std::string version();

}  // namespace agricola
