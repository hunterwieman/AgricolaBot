// Structural hash of a GameState — the transposition-table key (§5.3).
//
// Stage 1 impl: FNV-1a over the canonical serialization. Correctness-first
// (equal states -> equal canonical string -> equal hash), deterministic across
// processes. A fast field-wise structural hash (cached on the state, S5) is a
// Stage 6 optimization gated the same way.
#pragma once

#include <cstdint>

#include "agricola/types.hpp"

namespace agricola {

std::uint64_t state_hash(const GameState& s);

}  // namespace agricola
