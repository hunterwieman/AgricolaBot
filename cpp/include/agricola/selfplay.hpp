// Trace-emitting self-play driver (CPP_ENGINE_PLAN.md §8 Stage 4).
//
// Plays one full Family game with the C++ engine, picking uniformly-random legal
// actions at player decisions and routing nature's round-card reveals to the
// dealer (setup's round_card_order). Emits a trace JSON string matching the
// agricola-cpp-trace-v1 envelope that agents/nn/trace_replay.replay_trace reads:
//   {"schema","seed","initial_state","actions":[{round,phase,decider,type,params}]}
//
// Stage 4 is random / legal_actions-only (no NN, no MCTS, no visit_distribution
// / root_value — those land at Stage 6). Two independent RNG streams, both
// deterministic from `seed`: one for setup (setup.cpp), one for action choice.
#pragma once

#include <cstdint>
#include <string>

namespace agricola {

class NNInference;  // fwd-decl for the reuse overload (nn.hpp guarded by NN).

// Play one random self-play game from setup(seed) and return its trace JSON
// (the agricola-cpp-trace-v1 envelope as a compact string).
std::string random_selfplay_trace(std::uint64_t seed);

// Pick one move for the current position described by `state_json` (a canonical
// GameState JSON string as produced by agricola.canonical.dumps). Runs MCTS
// with the given NN, sims, c_uct, and temperature and returns a compact JSON
// object: {"action": {type, params}, "root_value": float}.
// Intended for the web UI: play_web.py shells out per AI turn and parses stdout.
// `leaf_mode` ("margin" [default, backward-compatible] / "outcome" / "mix")
// selects the leaf-value head the search backs up; "mix" blends margin/outcome
// at `mix_alpha` (α=1 pure margin, α=0 pure outcome). outcome/mix require the
// model to carry an outcome head.
std::string pick_move(const std::string& state_json, const std::string& model_dir,
                      int sims, double c_uct, double temperature,
                      double prior_mix = 0.0,
                      const std::string& leaf_mode = "margin",
                      double mix_alpha = 0.5);

// Read-only position analysis for the web UI's "Show analysis" feature. Runs the
// SAME MCTS as pick_move on the position described by `state_json` (canonical
// GameState JSON), but instead of returning a chosen move it emits EVERY visited
// root child with its visit count and value. The chosen-move result is discarded
// — analysis is purely informational decision support. Output is a compact JSON
// object:
//   {"children": [{"type": "<ActionType>", "params": {...},
//                  "visits": <int>, "q": <float|null>}, ...]}
// `q` is the child's mean value in the ROOT DECIDER'S perspective (higher = better
// for the player to move, the human). The {type, params} serialization is
// identical to pick_move's --move action, so it round-trips through the same
// action_from_params on the Python side. Unvisited children (visits 0) are
// omitted. Requires an NN build.
// `leaf_mode` selects the leaf-value head the analysis search backs up (same
// semantics as pick_move). For "margin"/"outcome" the emitted `q` is the
// child's normalized mean Q multiplied by the head's value_scale (natural
// units) and `value_target` is the head's descriptor. For "mix" the emitted
// `q` is the RAW tree Q (already in normalized [-1,1]-ish blend units, NOT
// multiplied by value_scale) and `value_target` is "mix".
std::string analyze_position(const std::string& state_json,
                             const std::string& model_dir, int sims,
                             double c_uct, double temperature,
                             double prior_mix = 0.0,
                             const std::string& leaf_mode = "margin",
                             double mix_alpha = 0.5);

#ifdef AGRICOLA_WITH_NN
// Stage 6 production self-play (CPP_ENGINE_PLAN.md §7) — a faithful mirror of
// agents/nn/selfplay_recording.play_selfplay_recording_game:
//   * shared tree: ONE MCTSSearch/MCTSAgent (NN value leaf + combined policy,
//     PUCT / FLATTEN / full legality, cap_total_sims) drives both seats;
//   * forced (singleton) decisions are stepped through uninvoked (not searched,
//     not recorded); nature reveals are routed to the dealer;
//   * each non-singleton SEARCHED decision entry carries visit_distribution +
//     visit_distribution_types + root_value (the AlphaZero π / value targets).
//
// `model_dir` holds value.ts + the head .ts files + manifest.json (the
// nn_models/cpp_export bundle). Returns the agricola-cpp-trace-v1 envelope
// string; replays cleanly through trace_replay.replay_trace -> a v3 GameRecord.
std::string mcts_selfplay_trace(std::uint64_t seed, int sims, double c_uct,
                                double temperature,
                                const std::string& model_dir,
                                double prior_mix = 0.0,
                                bool select_q = false);

// Same as mcts_selfplay_trace, but reuses an ALREADY-LOADED NNInference instead
// of loading `model_dir` per call — the batch path's weight-reload elimination.
// The single-arg mcts_selfplay_trace is a thin wrapper that loads once and calls
// this, so per-game behavior is byte-identical. `nn` is borrowed (caller owns).
std::string mcts_selfplay_trace_with(const NNInference& nn, std::uint64_t seed,
                                     int sims, double c_uct, double temperature,
                                     double prior_mix = 0.0,
                                     bool select_q = false);

// Two-net head-to-head MATCH (evaluation, NOT self-play data). P0 plays with
// `nn_p0`, P1 with `nn_p1`, each driven by its OWN MCTSSearch/MCTSAgent (separate
// trees — they have different value nets; the policy heads are typically the same
// across the two model dirs). Plays one full Family game from setup(seed) to
// terminal — forced moves stepped through, nature reveals dealt — and returns the
// final scores + winner. Winner = 0/1 by higher score, tiebreaker on a tie, or -1
// for a true draw (equal score AND tiebreaker), matching schema.compute_winner.
// No trace is emitted; a match only needs outcomes. P0 reuses the self-play RNG
// mixing constants so a P0-vs-P0 sanity check would match self-play trajectories.
struct MatchGameResult {
  std::uint64_t seed;
  int p0_score;
  int p1_score;
  int winner;  // 0 = P0 (nn_p0), 1 = P1 (nn_p1), -1 = true draw
};

// Per-seat search params: P0 searches with (sims_p0, c_uct_p0, temperature_p0),
// P1 with (sims_p1, c_uct_p1, temperature_p1). Pass equal values for a symmetric match.
MatchGameResult mcts_match_game(const NNInference& nn_p0, const NNInference& nn_p1,
                                std::uint64_t seed,
                                int sims_p0, double c_uct_p0,
                                int sims_p1, double c_uct_p1,
                                double temperature_p0,
                                double temperature_p1,
                                double prior_mix_p0 = 0.0,
                                double prior_mix_p1 = 0.0,
                                bool select_q_p0 = false,
                                bool select_q_p1 = false,
                                // Per-seat leaf-value head: "margin" (default),
                                // "outcome", or "mix" (mirrors
                                // shared_policy.make_joint_fns' leaf_mode). For a
                                // seat in outcome/mix mode the scales come from
                                // THAT seat's model manifest (value_scale +
                                // outcome_scale). Strings keep this header free of
                                // the NN-guarded LeafMode enum.
                                const std::string& leaf_mode_p0 = "margin",
                                const std::string& leaf_mode_p1 = "margin",
                                // Per-seat MIX-leaf blend weight α (only used when
                                // that seat's leaf_mode == "mix"): leaf Q =
                                // α·(margin/margin_scale) + (1-α)·(outcome/outcome_scale).
                                // Default 0.5 = even mix; α=1 pure margin, α=0 pure
                                // outcome.
                                double mix_alpha_p0 = 0.5,
                                double mix_alpha_p1 = 0.5);
#endif

}  // namespace agricola
