// Standalone self-play data-gen binary (CPP_ENGINE_PLAN.md §1, §8).
//
// Two modes:
//   * RANDOM (Stage 4, default): random / legal_actions-only self-play, no NN.
//   * MCTS (Stage 6, --mcts): the PRODUCTION data-gen path — shared-tree
//     MCTS-vs-MCTS (NN value leaf + combined policy, PUCT / FLATTEN / full
//     legality), emitting π + root_value per searched decision. Requires a
//     torch build (--mcts errors out otherwise).
//
// Both write an agricola-cpp-trace-v1 JSON trace that replays through the Python
// engine via agricola.agents.nn.trace_replay.replay_trace.
//
//   selfplay --seed N --out PATH                       # random, seed N to PATH
//   selfplay N                                         # random, seed N to stdout
//   selfplay --mcts --seed N --sims S --model-dir DIR --out PATH
//   selfplay --mcts --seed N --sims S --c-uct 1.4 --temperature 1.0 \
//            --model-dir nn_models/cpp_export --out trace.json
//
// MCTS BATCH mode (one NN load, many games — the data-gen weight-reload fix):
//   selfplay --mcts --game-idxs "i0,i1,..." --base-seed B --model-dir DIR \
//            --out-dir DIR2 [--sims S --c-uct C --temperature T]
//   For each idx i, plays seed = B + i and writes DIR2/trace_<i>.json.

#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <random>
#include <sstream>
#include <string>
#include <vector>

#include "agricola/selfplay.hpp"

#ifdef AGRICOLA_WITH_NN
#include "agricola/nn.hpp"
#endif

namespace {

void usage(const char* prog) {
  std::cerr
      << "usage: " << prog << " [--seed N] [--out PATH]            # random\n"
      << "       " << prog << " N                                  # random\n"
      << "       " << prog
      << " --mcts --seed N --model-dir DIR [--sims S]\n"
      << "              [--c-uct C] [--temperature T] [--out PATH]  # MCTS\n"
      << "       " << prog
      << " --mcts --game-idxs \"i0,i1,...\" --base-seed B\n"
      << "              --model-dir DIR --out-dir DIR2 [--sims S]\n"
      << "              [--c-uct C] [--temperature T]               # MCTS batch\n";
}

// Parse a comma-separated list of non-negative game indices ("0,1,2"). Returns
// false on any malformed / empty token so the caller can error out.
bool parse_game_idxs(const std::string& s, std::vector<long long>& out) {
  out.clear();
  std::stringstream ss(s);
  std::string tok;
  while (std::getline(ss, tok, ',')) {
    // Trim surrounding whitespace (tolerate "0, 1, 2").
    size_t a = tok.find_first_not_of(" \t\r\n");
    size_t b = tok.find_last_not_of(" \t\r\n");
    if (a == std::string::npos) continue;  // skip empty token (e.g. trailing ,)
    std::string trimmed = tok.substr(a, b - a + 1);
    char* end = nullptr;
    long long v = std::strtoll(trimmed.c_str(), &end, 10);
    if (end == trimmed.c_str() || *end != '\0' || v < 0) return false;
    out.push_back(v);
  }
  return !out.empty();
}

}  // namespace

int main(int argc, char** argv) {
  std::uint64_t seed = 0;
  bool have_seed = false;
  std::string out_path;     // empty -> stdout
  bool mcts = false;
  int sims = 160;           // matches Stage-6 default sims_per_move
  double c_uct = 1.4;
  double temperature = 1.0; // production self-play default (sample ∝ visits)
  std::string model_dir = "nn_models/cpp_export";

  // Batch-mode args (one NN load, many games).
  std::string out_dir;      // empty -> single-game mode
  std::string game_idxs_arg;
  bool have_game_idxs = false;
  std::uint64_t base_seed = 0;

  // Two-net match-mode args (P0 = model_dir_p0, P1 = model_dir_p1).
  bool match = false;
  std::string model_dir_p0;
  std::string model_dir_p1;

  // Match-sweep args: per game, each seat independently draws sims (uniform over
  // --sweep-sims) and c_uct (uniform over [--cuct-lo, --cuct-hi]) from a per-game
  // RNG seeded by the game seed (reproducible). Reported in each GAME line.
  bool sweep = false;
  std::string sweep_sims_arg = "160,320,520,800,1200,1600";
  double cuct_lo = 0.1;
  double cuct_hi = 1.0;

  // Fixed per-seat overrides (non-sweep match): a negative sentinel means "use
  // the shared --sims / --c-uct for that seat". Lets a match pit e.g. 800 sims
  // (P0) vs 500 sims (P1) with separate trees.
  int sims_p0 = -1, sims_p1 = -1;
  double c_uct_p0 = -1.0, c_uct_p1 = -1.0;

  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    if (arg == "--seed" && i + 1 < argc) {
      seed = std::strtoull(argv[++i], nullptr, 10);
      have_seed = true;
    } else if (arg == "--out" && i + 1 < argc) {
      out_path = argv[++i];
    } else if (arg == "--out-dir" && i + 1 < argc) {
      out_dir = argv[++i];
    } else if (arg == "--game-idxs" && i + 1 < argc) {
      game_idxs_arg = argv[++i];
      have_game_idxs = true;
    } else if (arg == "--base-seed" && i + 1 < argc) {
      base_seed = std::strtoull(argv[++i], nullptr, 10);
    } else if (arg == "--mcts") {
      mcts = true;
    } else if (arg == "--sims" && i + 1 < argc) {
      sims = std::atoi(argv[++i]);
    } else if (arg == "--c-uct" && i + 1 < argc) {
      c_uct = std::atof(argv[++i]);
    } else if (arg == "--temperature" && i + 1 < argc) {
      temperature = std::atof(argv[++i]);
    } else if (arg == "--model-dir" && i + 1 < argc) {
      model_dir = argv[++i];
    } else if (arg == "--match") {
      match = true;
    } else if (arg == "--model-dir-p0" && i + 1 < argc) {
      model_dir_p0 = argv[++i];
    } else if (arg == "--model-dir-p1" && i + 1 < argc) {
      model_dir_p1 = argv[++i];
    } else if (arg == "--sweep") {
      sweep = true;
    } else if (arg == "--sweep-sims" && i + 1 < argc) {
      sweep_sims_arg = argv[++i];
    } else if (arg == "--cuct-lo" && i + 1 < argc) {
      cuct_lo = std::atof(argv[++i]);
    } else if (arg == "--cuct-hi" && i + 1 < argc) {
      cuct_hi = std::atof(argv[++i]);
    } else if (arg == "--sims-p0" && i + 1 < argc) {
      sims_p0 = std::atoi(argv[++i]);
    } else if (arg == "--sims-p1" && i + 1 < argc) {
      sims_p1 = std::atoi(argv[++i]);
    } else if (arg == "--c-uct-p0" && i + 1 < argc) {
      c_uct_p0 = std::atof(argv[++i]);
    } else if (arg == "--c-uct-p1" && i + 1 < argc) {
      c_uct_p1 = std::atof(argv[++i]);
    } else if (arg == "-h" || arg == "--help") {
      usage(argv[0]);
      return 0;
    } else if (!arg.empty() && arg[0] != '-' && !have_seed) {
      seed = std::strtoull(arg.c_str(), nullptr, 10);  // positional bare seed
      have_seed = true;
    } else {
      usage(argv[0]);
      return 2;
    }
  }

  // ---- Two-net MATCH mode: --match present ----
  if (match) {
#ifndef AGRICOLA_WITH_NN
    std::cerr << "selfplay: --match requires an NN build\n";
    return 1;
#else
    if (!mcts) {
      std::cerr << "selfplay: --match requires --mcts\n";
      return 2;
    }
    if (model_dir_p0.empty() || model_dir_p1.empty()) {
      std::cerr << "selfplay: --match requires --model-dir-p0 and --model-dir-p1\n";
      return 2;
    }
    std::vector<long long> idxs;
    if (have_game_idxs) {
      if (!parse_game_idxs(game_idxs_arg, idxs)) {
        std::cerr << "selfplay: --game-idxs must be a non-empty comma-separated "
                     "list of non-negative integers\n";
        return 2;
      }
    } else {
      idxs.push_back(0);  // single game from base_seed
    }
    // In --sweep, each seat independently draws (sims, c_uct) per game.
    std::vector<long long> sweep_sims;
    if (sweep && !parse_game_idxs(sweep_sims_arg, sweep_sims)) {
      std::cerr << "selfplay: --sweep-sims must be a non-empty comma-separated "
                   "list of positive integers\n";
      return 2;
    }
    // Load both nets ONCE, reuse across every game.
    agricola::NNInference nn0(model_dir_p0);
    agricola::NNInference nn1(model_dir_p1);
    long long p0w = 0, p1w = 0, draws = 0;
    for (long long idx : idxs) {
      std::uint64_t game_seed = base_seed + static_cast<std::uint64_t>(idx);
      int s0 = sims, s1 = sims;
      double c0 = c_uct, c1 = c_uct;
      if (sweep) {
        // Per-game RNG (reproducible from the game seed, mixed so adjacent
        // seeds don't give correlated draws). Four independent draws: each
        // seat's sims and c_uct, with replacement.
        std::uint64_t z = game_seed + 0x9E3779B97F4A7C15ULL;
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
        z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
        z = z ^ (z >> 31);
        std::mt19937_64 rng(z);
        std::uniform_int_distribution<size_t> pick(0, sweep_sims.size() - 1);
        std::uniform_real_distribution<double> uc(cuct_lo, cuct_hi);
        s0 = static_cast<int>(sweep_sims[pick(rng)]);
        c0 = uc(rng);
        s1 = static_cast<int>(sweep_sims[pick(rng)]);
        c1 = uc(rng);
      } else {
        // Fixed per-seat overrides (negative = use the shared value).
        if (sims_p0 >= 0) s0 = sims_p0;
        if (sims_p1 >= 0) s1 = sims_p1;
        if (c_uct_p0 >= 0) c0 = c_uct_p0;
        if (c_uct_p1 >= 0) c1 = c_uct_p1;
      }
      agricola::MatchGameResult r = agricola::mcts_match_game(
          nn0, nn1, game_seed, s0, c0, s1, c1, temperature);
      std::cout << "GAME seed=" << r.seed << " p0=" << r.p0_score
                << " p1=" << r.p1_score << " winner=" << r.winner;
      if (sweep) {
        std::cout << " sims0=" << s0 << " cuct0=" << c0
                  << " sims1=" << s1 << " cuct1=" << c1;
      }
      std::cout << std::endl;  // flush per game so piped progress is live
      if (r.winner == 0) ++p0w;
      else if (r.winner == 1) ++p1w;
      else ++draws;
    }
    std::cout << "MATCH p0_wins=" << p0w << " p1_wins=" << p1w
              << " draws=" << draws << " games=" << idxs.size() << "\n";
    return 0;
#endif
  }

  // ---- MCTS BATCH mode: --out-dir / --game-idxs present ----
  if (!out_dir.empty() || have_game_idxs) {
    if (!mcts) {
      std::cerr << "selfplay: batch mode (--out-dir/--game-idxs) requires --mcts\n";
      usage(argv[0]);
      return 2;
    }
#ifndef AGRICOLA_WITH_NN
    std::cerr << "selfplay: --mcts requires an NN build\n";
    return 1;
#else
    if (out_dir.empty()) {
      std::cerr << "selfplay: --game-idxs requires --out-dir\n";
      usage(argv[0]);
      return 2;
    }
    if (!have_game_idxs) {
      std::cerr << "selfplay: --out-dir requires --game-idxs\n";
      usage(argv[0]);
      return 2;
    }
    std::vector<long long> idxs;
    if (!parse_game_idxs(game_idxs_arg, idxs)) {
      std::cerr << "selfplay: --game-idxs must be a non-empty comma-separated "
                   "list of non-negative integers (got: \""
                << game_idxs_arg << "\")\n";
      return 2;
    }
    std::error_code ec;
    std::filesystem::create_directories(out_dir, ec);
    if (ec) {
      std::cerr << "selfplay: cannot create out-dir " << out_dir << ": "
                << ec.message() << "\n";
      return 1;
    }

    // Load the NN ONCE, then play every game reusing it.
    agricola::NNInference nn(model_dir);
    long long written = 0;
    for (long long idx : idxs) {
      std::uint64_t game_seed = base_seed + static_cast<std::uint64_t>(idx);
      std::string trace = agricola::mcts_selfplay_trace_with(
          nn, game_seed, sims, c_uct, temperature);
      std::filesystem::path p =
          std::filesystem::path(out_dir) / ("trace_" + std::to_string(idx) + ".json");
      std::ofstream f(p);
      if (!f) {
        std::cerr << "selfplay: cannot open " << p.string() << " for writing\n";
        return 1;
      }
      f << trace << "\n";
      ++written;
    }
    std::cerr << "selfplay: batch wrote " << written << " traces to " << out_dir
              << "\n";
    return 0;
#endif
  }

  // ---- single-game mode (unchanged) ----
  std::string trace;
  if (mcts) {
#ifdef AGRICOLA_WITH_NN
    trace = agricola::mcts_selfplay_trace(seed, sims, c_uct, temperature,
                                          model_dir);
#else
    std::cerr << "selfplay: --mcts requires an NN build\n";
    return 1;
#endif
  } else {
    trace = agricola::random_selfplay_trace(seed);
  }

  if (out_path.empty()) {
    std::cout << trace << "\n";
  } else {
    std::ofstream f(out_path);
    if (!f) {
      std::cerr << "selfplay: cannot open " << out_path << " for writing\n";
      return 1;
    }
    f << trace << "\n";
  }
  return 0;
}
