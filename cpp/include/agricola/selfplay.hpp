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
std::string pick_move(const std::string& state_json, const std::string& model_dir,
                      int sims, double c_uct, double temperature);

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
                                const std::string& model_dir);

// Same as mcts_selfplay_trace, but reuses an ALREADY-LOADED NNInference instead
// of loading `model_dir` per call — the batch path's weight-reload elimination.
// The single-arg mcts_selfplay_trace is a thin wrapper that loads once and calls
// this, so per-game behavior is byte-identical. `nn` is borrowed (caller owns).
std::string mcts_selfplay_trace_with(const NNInference& nn, std::uint64_t seed,
                                     int sims, double c_uct, double temperature);

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

// Per-seat search params: P0 searches with (sims_p0, c_uct_p0), P1 with
// (sims_p1, c_uct_p1). Pass equal values for both seats for a symmetric match.
MatchGameResult mcts_match_game(const NNInference& nn_p0, const NNInference& nn_p1,
                                std::uint64_t seed,
                                int sims_p0, double c_uct_p0,
                                int sims_p1, double c_uct_p1,
                                double temperature);
#endif

}  // namespace agricola
