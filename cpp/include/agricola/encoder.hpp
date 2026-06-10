// The NN input encoder — a faithful port of agricola/agents/nn/encoder.py
// (CPP_ENGINE_PLAN.md §6.2). 170 raw features (normalization happens in the
// model). Block layout: own 0-53 | opp 54-107 | shared 108-161 | mid-action
// 162-169. Pure (no torch) so a no-torch build can still expose `encode` for
// the exact encoder gate.
#pragma once

#include <array>
#include <optional>

#include "agricola/types.hpp"

namespace agricola {

constexpr int kEncodedDim = 170;

// decider_of(state): empty stack -> current_player; non-empty -> top frame's
// player_idx (std::nullopt for PendingReveal = nature). Mirrors
// agents/base.decider_of. Shared with the policy combiner.
std::optional<int> encoder_decider_of(const GameState& state);

// encode_state(state, player_idx) -> 170 float32 features, byte-identical to
// the Python encoder (golden-tested). The own block reflects player_idx; the
// opponent block reflects 1-player_idx; perspective-relative shared features
// (current_player_is_own, is_starting_player) are computed against player_idx.
std::array<float, kEncodedDim> encode(const GameState& state, int player_idx);

}  // namespace agricola
