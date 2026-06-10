// Canonical GameState <-> JSON, byte-for-byte identical to agricola/canonical.py
// (CPP_ENGINE_PLAN.md §3.1). The shared contract validated by the differential
// harness. nlohmann::ordered_json preserves field insertion order; we write
// fields in the Python dataclass declaration order so dumps match exactly.
#pragma once

#include <string>

#include "agricola/types.hpp"

namespace agricola {

// Serialize to the canonical compact JSON string (== Python json.dumps with
// separators=(",",":"), ensure_ascii=False).
std::string to_canonical_string(const GameState& state);

// Inverse of to_canonical_string.
GameState game_state_from_string(const std::string& text);

// Canonical JSON for a single pending frame. Used by the fast state hash to
// fully discriminate pending frames (their flags/counters) cheaply — frames are
// small and the stack is usually short, so this is far cheaper than serializing
// the whole state.
std::string pending_to_canonical(const PendingDecision& frame);

}  // namespace agricola
