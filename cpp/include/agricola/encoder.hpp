// The NN input encoder — a faithful port of agricola/agents/nn/encoder.py
// (CPP_ENGINE_PLAN.md §6.2). 170 raw features (normalization happens in the
// model). Block layout: own 0-53 | opp 54-107 | shared 108-161 | mid-action
// 162-169. Pure (no torch) so a no-torch build can still expose `encode` for
// the exact encoder gate.
#pragma once

#include <array>
#include <optional>
#include <string>
#include <vector>

#include "agricola/types.hpp"

namespace agricola {

constexpr int kEncodedDim = 170;

// Candidate encoder (agents/nn/encoder.py `encode_state_candidate`, tag
// "cand_feat178_v1"): per-player block 54->58 (begging dropped; running_score /
// turns_until_next_feeding / can_renovate_to_clay|stone / can_grow_family
// added), so 178 total. Block layout: own 0-57 | opp 58-115 | shared 116-169 |
// mid 170-177. Begging is handled post-hoc on the value margin (begging_margin).
constexpr int kEncodedDimCandidate = 178;

// decider_of(state): empty stack -> current_player; non-empty -> top frame's
// player_idx (std::nullopt for PendingReveal = nature). Mirrors
// agents/base.decider_of. Shared with the policy combiner.
std::optional<int> encoder_decider_of(const GameState& state);

// encode_state(state, player_idx) -> 170 float32 features, byte-identical to
// the Python encoder (golden-tested). The own block reflects player_idx; the
// opponent block reflects 1-player_idx; perspective-relative shared features
// (current_player_is_own, is_starting_player) are computed against player_idx.
std::array<float, kEncodedDim> encode(const GameState& state, int player_idx);

// encode_state_candidate(state, player_idx) -> 178 float32 features,
// byte-identical to the Python candidate encoder.
std::array<float, kEncodedDimCandidate> encode_candidate(const GameState& state,
                                                         int player_idx);

// The P-frame contribution of current begging markers to the score margin:
// -3 * (begging[perspective] - begging[1-perspective]). Stripped from the
// candidate value target; added back at inference (margin model).
double begging_margin(const GameState& state, int perspective);

// ---------------------------------------------------------------------------
// Encoder registry (forward-compatible model loading)
// ---------------------------------------------------------------------------
//
// A model declares which encoder it was trained with via an `encoder_tag` in its
// weights manifest (scripts/nn/export_weights.py). Inference looks the tag up
// here and dispatches generically — NO `if (input_dim == 178)` branches. Adding
// a future encoder = one new EncoderSpec entry + its encode fn, nothing else.
// (Models are assumed to keep the same multi-head output structure; only the
// input encoder / trunk widths / weights vary.)
struct EncoderSpec {
  const char* tag;        // manifest id ("v2", "cand_feat178_v1", ...)
  int dim;                // feature-vector length (must match the trunk input)
  bool strip_begging;     // value post-processing: add begging_margin() back
  // Encode into a caller-provided buffer (runtime size unifies the per-encoder
  // array widths). The buffer is resized to `dim`.
  void (*encode_into)(const GameState&, int player_idx, std::vector<float>& out);
};

// Look up the EncoderSpec for a manifest tag (empty tag -> "v2" for back-compat
// with pre-registry exports). Throws std::runtime_error on an unknown tag.
const EncoderSpec& encoder_for_tag(const std::string& tag);

}  // namespace agricola
