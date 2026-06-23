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
//   selfplay --mcts --seed N --sims S --c-uct 1.0 --temperature 1.0 \
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
      << "              [--c-uct C] [--temperature T]               # MCTS batch\n"
      << "       " << prog
      << " --move --model-dir DIR [--sims S] [--c-uct C] [--temperature T]\n"
      << "              [--leaf-mode margin|outcome|mix] [--mix-alpha A]\n"
      << "              reads GameState JSON from stdin, writes chosen action JSON\n"
      << "       " << prog
      << " --analyze --model-dir DIR [--sims S] [--c-uct C] [--temperature T]\n"
      << "              [--leaf-mode margin|outcome|mix] [--mix-alpha A]\n"
      << "              reads GameState JSON from stdin, writes root children "
         "{visits,q} JSON\n";
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
  double c_uct = 1.0;
  double temperature = 1.0; // production self-play default (sample ∝ visits)
  std::string model_dir = "nn_models/cpp_export";
  double prior_mix = 0.0;   // policy-prior uniform mix for --move / --analyze
  // Single-position leaf head for --move / --analyze: "margin" (default,
  // backward-compatible) / "outcome" / "mix"; mix_alpha is the mix blend weight.
  std::string leaf_mode = "margin";
  double mix_alpha = 0.5;

  // Batch-mode args (one NN load, many games).
  std::string out_dir;      // empty -> single-game mode
  std::string game_idxs_arg;
  bool have_game_idxs = false;
  std::uint64_t base_seed = 0;

  // Single-move mode: read GameState JSON from stdin, output chosen action JSON.
  bool move_mode = false;

  // Analyze mode: read GameState JSON from stdin, output ALL root children with
  // visits + q (read-only decision support for the web UI; no move played).
  bool analyze_mode = false;

  // Two-net match-mode args (P0 = model_dir_p0, P1 = model_dir_p1).
  bool match = false;
  std::string model_dir_p0;
  std::string model_dir_p1;
  // Per-seat policy-prior uniform mixing (0 = pure policy net).
  double prior_mix_p0 = 0.0;
  double prior_mix_p1 = 0.0;

  // Match-sweep args: per game, each seat independently draws sims (uniform over
  // --sweep-sims) and c_uct (uniform over [--cuct-lo, --cuct-hi]) from a per-game
  // RNG seeded by the game seed (reproducible). Reported in each GAME line.
  bool sweep = false;
  std::string sweep_sims_arg = "160,320,520,800,1200,1600";
  double cuct_lo = 0.1;
  double cuct_hi = 1.0;
  // Mix-rate (α) sweep: when set, BOTH seats run leaf-mode "mix" and each seat
  // draws α per game uniformly from [alpha_lo, alpha_hi] using the SAME per-game
  // RNG as the sims/c_uct sweep (reproducible). Reported as alpha0/alpha1 in the
  // GAME line. Composes with fixed sims/c_uct (set --cuct-lo == --cuct-hi and a
  // single --sweep-sims value to hold those constant).
  bool sweep_alpha = false;
  double alpha_lo = 0.0;
  double alpha_hi = 1.0;

  // Fixed per-seat overrides (non-sweep match): a negative sentinel means "use
  // the shared --sims / --c-uct / --temperature for that seat". Lets a match pit
  // e.g. 800 sims (P0) vs 500 sims (P1), or T=0 (P0) vs T=0.3 (P1).
  int sims_p0 = -1, sims_p1 = -1;
  double c_uct_p0 = -1.0, c_uct_p1 = -1.0;
  double temperature_p0 = -1.0, temperature_p1 = -1.0;  // negative = use shared
  // Per-seat played-move selection: "visits" (default) or "q" (rank by mean-Q).
  bool select_q_p0 = false, select_q_p1 = false;
  // Per-seat leaf-value head: "margin" (default), "outcome", or "mix" — selects
  // which NN head supplies the backed-up leaf Q (mirrors the Python leaf_mode).
  std::string leaf_mode_p0 = "margin", leaf_mode_p1 = "margin";
  // Self-play path (single agent both seats) selection: "visits" / "q".
  bool select_q = false;

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
    } else if (arg == "--move") {
      move_mode = true;
    } else if (arg == "--analyze") {
      analyze_mode = true;
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
    } else if (arg == "--sweep-alpha") {
      sweep_alpha = true;
    } else if (arg == "--alpha-lo" && i + 1 < argc) {
      alpha_lo = std::atof(argv[++i]);
    } else if (arg == "--alpha-hi" && i + 1 < argc) {
      alpha_hi = std::atof(argv[++i]);
    } else if (arg == "--sims-p0" && i + 1 < argc) {
      sims_p0 = std::atoi(argv[++i]);
    } else if (arg == "--sims-p1" && i + 1 < argc) {
      sims_p1 = std::atoi(argv[++i]);
    } else if (arg == "--c-uct-p0" && i + 1 < argc) {
      c_uct_p0 = std::atof(argv[++i]);
    } else if (arg == "--c-uct-p1" && i + 1 < argc) {
      c_uct_p1 = std::atof(argv[++i]);
    } else if (arg == "--prior-mix-p0" && i + 1 < argc) {
      prior_mix_p0 = std::atof(argv[++i]);
    } else if (arg == "--prior-mix-p1" && i + 1 < argc) {
      prior_mix_p1 = std::atof(argv[++i]);
    } else if (arg == "--temperature-p0" && i + 1 < argc) {
      temperature_p0 = std::atof(argv[++i]);
    } else if (arg == "--temperature-p1" && i + 1 < argc) {
      temperature_p1 = std::atof(argv[++i]);
    } else if (arg == "--select-by-p0" && i + 1 < argc) {
      select_q_p0 = (std::string(argv[++i]) == "q");
    } else if (arg == "--select-by-p1" && i + 1 < argc) {
      select_q_p1 = (std::string(argv[++i]) == "q");
    } else if (arg == "--leaf-mode-p0" && i + 1 < argc) {
      leaf_mode_p0 = argv[++i];
    } else if (arg == "--leaf-mode-p1" && i + 1 < argc) {
      leaf_mode_p1 = argv[++i];
    } else if (arg == "--select-by" && i + 1 < argc) {
      select_q = (std::string(argv[++i]) == "q");  // self-play single-agent path
    } else if (arg == "--prior-mix" && i + 1 < argc) {
      prior_mix = std::atof(argv[++i]);  // --move / --analyze single-position mix
    } else if (arg == "--leaf-mode" && i + 1 < argc) {
      leaf_mode = argv[++i];  // --move / --analyze leaf head (margin/outcome/mix)
    } else if (arg == "--mix-alpha" && i + 1 < argc) {
      mix_alpha = std::atof(argv[++i]);  // --leaf-mode mix blend weight α
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

  // ---- Single-move mode: --move ----
  if (move_mode) {
#ifndef AGRICOLA_WITH_NN
    std::cerr << "selfplay: --move requires an NN build\n";
    return 1;
#else
    std::string state_json((std::istreambuf_iterator<char>(std::cin)),
                           std::istreambuf_iterator<char>());
    if (state_json.empty()) {
      std::cerr << "selfplay: --move expects GameState JSON on stdin\n";
      return 2;
    }
    std::string result = agricola::pick_move(state_json, model_dir, sims, c_uct,
                                             temperature, prior_mix, leaf_mode,
                                             mix_alpha);
    std::cout << result << "\n";
    return 0;
#endif
  }

  // ---- Analyze mode: --analyze ----
  if (analyze_mode) {
#ifndef AGRICOLA_WITH_NN
    std::cerr << "selfplay: --analyze requires an NN build\n";
    return 1;
#else
    std::string state_json((std::istreambuf_iterator<char>(std::cin)),
                           std::istreambuf_iterator<char>());
    if (state_json.empty()) {
      std::cerr << "selfplay: --analyze expects GameState JSON on stdin\n";
      return 2;
    }
    try {
      std::string result = agricola::analyze_position(state_json, model_dir, sims,
                                                      c_uct, temperature, prior_mix,
                                                      leaf_mode, mix_alpha);
      std::cout << result << "\n";
      return 0;
    } catch (const std::exception& e) {
      // e.g. a non-margin value head can't be reported in points. Exit non-zero
      // (no JSON) — the web caller treats that as "no analysis overlay".
      std::cerr << "selfplay: --analyze failed: " << e.what() << "\n";
      return 3;
    }
#endif
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
    // --sweep-alpha shares the per-game RNG path with the sims/c_uct sweep so it
    // composes (hold sims/c_uct fixed via a single --sweep-sims value + equal
    // --cuct-lo/--cuct-hi). Either flag activates the RNG-draw path.
    const bool sweep_any = sweep || sweep_alpha;
    // When sweeping α, BOTH seats run the MIX leaf (scales from each manifest).
    if (sweep_alpha) {
      leaf_mode_p0 = "mix";
      leaf_mode_p1 = "mix";
    }
    // In --sweep, each seat independently draws (sims, c_uct) per game.
    std::vector<long long> sweep_sims;
    if (sweep_any && !parse_game_idxs(sweep_sims_arg, sweep_sims)) {
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
      double a0 = 0.5, a1 = 0.5;  // MIX α (reported only when sweeping α)
      if (sweep_any) {
        // Per-game RNG (reproducible from the game seed, mixed so adjacent
        // seeds don't give correlated draws). Draws (in a FIXED order so the
        // sims/c_uct stream is identical with or without --sweep-alpha): each
        // seat's sims and c_uct, then — when sweeping α — each seat's α.
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
        if (sweep_alpha) {
          std::uniform_real_distribution<double> ua(alpha_lo, alpha_hi);
          a0 = ua(rng);
          a1 = ua(rng);
        }
      } else {
        // Fixed per-seat overrides (negative = use the shared value).
        if (sims_p0 >= 0) s0 = sims_p0;
        if (sims_p1 >= 0) s1 = sims_p1;
        if (c_uct_p0 >= 0) c0 = c_uct_p0;
        if (c_uct_p1 >= 0) c1 = c_uct_p1;
      }
      double t0 = temperature_p0 >= 0 ? temperature_p0 : temperature;
      double t1 = temperature_p1 >= 0 ? temperature_p1 : temperature;
      agricola::MatchGameResult r = agricola::mcts_match_game(
          nn0, nn1, game_seed, s0, c0, s1, c1, t0, t1,
          prior_mix_p0, prior_mix_p1, select_q_p0, select_q_p1,
          leaf_mode_p0, leaf_mode_p1, a0, a1);
      std::cout << "GAME seed=" << r.seed << " p0=" << r.p0_score
                << " p1=" << r.p1_score << " winner=" << r.winner;
      if (sweep_any) {
        std::cout << " sims0=" << s0 << " cuct0=" << c0
                  << " sims1=" << s1 << " cuct1=" << c1;
      }
      if (sweep_alpha) {
        std::cout << " alpha0=" << a0 << " alpha1=" << a1;
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
          nn, game_seed, sims, c_uct, temperature, prior_mix, select_q);
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
                                          model_dir, prior_mix, select_q);
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
