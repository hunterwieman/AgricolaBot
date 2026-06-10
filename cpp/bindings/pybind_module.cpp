// pybind11 module `agricola_cpp` — the differential-test surface
// (CPP_ENGINE_PLAN.md §3.3). Production data-gen uses the standalone `selfplay`
// binary and never crosses into Python.
//
// All real bindings take/return the canonical JSON strings that
// agricola/canonical.py defines, so the Python differential tests can drive the
// C++ engine on serialized states and compare byte-for-byte.

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <array>
#include <cstdint>
#include <string>
#include <utility>
#include <vector>

#include "agricola/actions.hpp"
#include "agricola/canonical.hpp"
#include "agricola/encoder.hpp"
#include "agricola/engine.hpp"
#include "agricola/hash.hpp"
#include "agricola/legality.hpp"
#include "agricola/pasture.hpp"
#include "agricola/scoring.hpp"
#include "agricola/selfplay.hpp"
#include "agricola/types.hpp"
#include "agricola/version.hpp"

#ifdef AGRICOLA_WITH_NN
#include <memory>
#include <unordered_map>

#include "agricola/mcts.hpp"
#include "agricola/nn.hpp"
#endif

namespace py = pybind11;

PYBIND11_MODULE(agricola_cpp, m) {
  m.doc() = "Agricola C++ engine port — differential-test binding.";

  m.attr("ENCODING_VERSION") = agricola::kEncodingVersion;
  m.attr("DATA_VERSION") = agricola::kDataVersion;

  m.def("version", &agricola::version,
        "Human-readable core-library version string.");
  m.def("ping", []() { return std::string("agricola_cpp ok"); },
        "Liveness check.");
  m.def("echo", [](const std::string& s) { return s; }, py::arg("s"),
        "Identity over a string (proves the canonical-JSON transport).");

  // --- Stage 1: state model / serde / pasture / hash ------------------------

  m.def(
      "canonical_roundtrip",
      [](const std::string& dump) {
        return agricola::to_canonical_string(
            agricola::game_state_from_string(dump));
      },
      py::arg("dump"),
      "Deserialize a canonical GameState dump and re-serialize it. The result "
      "must equal the input byte-for-byte (serde-exactness gate).");

  m.def(
      "recompute_pastures",
      [](const std::string& dump) {
        agricola::GameState s = agricola::game_state_from_string(dump);
        for (auto& p : s.players)
          p.farmyard.pastures = agricola::compute_pastures(p.farmyard);
        return agricola::to_canonical_string(s);
      },
      py::arg("dump"),
      "Deserialize, recompute each player's farmyard pastures via the C++ "
      "flood-fill (discarding the stored decomposition), and re-serialize. "
      "Equal to the input iff the flood-fill matches Python's cached pastures.");

  m.def(
      "state_hash",
      [](const std::string& dump) -> std::uint64_t {
        return agricola::state_hash(agricola::game_state_from_string(dump));
      },
      py::arg("dump"), "Structural hash of the deserialized state.");

  m.def(
      "states_equal",
      [](const std::string& a, const std::string& b) {
        return agricola::game_state_from_string(a) ==
               agricola::game_state_from_string(b);
      },
      py::arg("a"), py::arg("b"),
      "Structural equality of two deserialized states.");

  // --- Stage 2: legal_actions ----------------------------------------------

  m.def(
      "legal_actions",
      [](const std::string& dump) {
        agricola::GameState s = agricola::game_state_from_string(dump);
        std::vector<std::string> out;
        for (const auto& a : agricola::legal_actions(s))
          out.push_back(agricola::action_to_json(a));
        return out;
      },
      py::arg("dump"),
      "Deserialize a canonical GameState dump and return each legal action as "
      "a {type, params} JSON string (matching trace_replay.action_to_params).");

  // --- Stage 3: step + scoring ---------------------------------------------

  m.def(
      "step",
      [](const std::string& state_dump, const std::string& action_dump) {
        agricola::GameState s = agricola::game_state_from_string(state_dump);
        agricola::Action a = agricola::action_from_json(action_dump);
        return agricola::to_canonical_string(agricola::step(s, a));
      },
      py::arg("state_dump"), py::arg("action_dump"),
      "Apply one action to a canonical GameState dump and return the resulting "
      "canonical dump. Must equal Python step(state, action) byte-for-byte.");

  m.def(
      "score",
      [](const std::string& dump, int player) {
        return agricola::score(agricola::game_state_from_string(dump), player);
      },
      py::arg("dump"), py::arg("player"),
      "Total end-game score for a player (== Python scoring.score[0]).");

  m.def(
      "tiebreaker",
      [](const std::string& dump, int player) {
        return agricola::tiebreaker(agricola::game_state_from_string(dump),
                                    player);
      },
      py::arg("dump"), py::arg("player"),
      "End-game tiebreaker for a player (== Python scoring.tiebreaker).");

  // --- Stage 4: setup + self-play trace ------------------------------------

  m.def(
      "random_selfplay_trace",
      [](std::uint64_t seed) { return agricola::random_selfplay_trace(seed); },
      py::arg("seed"),
      "Play one random Family self-play game from setup(seed) and return its "
      "agricola-cpp-trace-v1 JSON envelope (string). The trace replays cleanly "
      "through agricola.agents.nn.trace_replay.replay_trace.");

  // --- Stage 5: NN inference (encoder always; value/policy need torch) -------

  // The encoder is pure (no torch), so it is exposed unconditionally — the
  // exact-encoder gate then runs even on a no-torch build.
  m.def(
      "encode",
      [](const std::string& dump, int player_idx) {
        agricola::GameState s = agricola::game_state_from_string(dump);
        std::array<float, agricola::kEncodedDim> e =
            agricola::encode(s, player_idx);
        return std::vector<float>(e.begin(), e.end());
      },
      py::arg("dump"), py::arg("player_idx"),
      "170-feature NN encoding of a state from player_idx's perspective "
      "(== Python encode_state(state, player_idx)).");

#ifdef AGRICOLA_WITH_NN
  // Cache one NNInference per model_dir — loading .ts every call is fine for the
  // gate, but caching keeps repeated calls cheap.
  static std::unordered_map<std::string, std::shared_ptr<agricola::NNInference>>
      kNNCache;
  auto get_nn = [](const std::string& model_dir) {
    auto it = kNNCache.find(model_dir);
    if (it == kNNCache.end()) {
      auto inf = std::make_shared<agricola::NNInference>(model_dir);
      kNNCache[model_dir] = inf;
      return inf;
    }
    return it->second;
  };

  m.def(
      "nn_value",
      [get_nn](const std::string& dump, const std::string& model_dir) {
        agricola::GameState s = agricola::game_state_from_string(dump);
        return get_nn(model_dir)->value(s);
      },
      py::arg("dump"), py::arg("model_dir"),
      "predict_margin from perspective 0 (== nn_evaluator(state, 0, model)). "
      "model_dir holds value.ts + manifest.json (nn_models/cpp_export).");

  m.def(
      "nn_policy",
      [get_nn](const std::string& dump, const std::string& model_dir) {
        agricola::GameState s = agricola::game_state_from_string(dump);
        auto pairs = get_nn(model_dir)->policy(s);
        std::vector<std::pair<std::string, double>> out;
        out.reserve(pairs.size());
        for (const auto& [a, pr] : pairs)
          out.push_back({agricola::action_to_json(a), pr});
        return out;
      },
      py::arg("dump"), py::arg("model_dir"),
      "make_policy_fn's {action: prior} as a list of [action_json, prior] "
      "pairs over the full legal set (omitted legal actions = prior 0).");

  // --- Stage 6: native MCTS self-play + a stateful eval agent ---------------

  m.def(
      "mcts_selfplay_trace",
      [](std::uint64_t seed, int sims, double c_uct, double temperature,
         const std::string& model_dir) {
        return agricola::mcts_selfplay_trace(seed, sims, c_uct, temperature,
                                             model_dir);
      },
      py::arg("seed"), py::arg("sims"), py::arg("c_uct"),
      py::arg("temperature"), py::arg("model_dir"),
      "Shared-tree native MCTS self-play game (NN value leaf + combined policy, "
      "PUCT/FLATTEN/full legality) -> agricola-cpp-trace-v1 JSON string with "
      "visit_distribution + visit_distribution_types + root_value on each "
      "non-singleton searched decision. Replays via trace_replay.replay_trace.");

  // A stateful native-MCTS agent for per-move head-to-head eval (e.g. vs the
  // Python MCTSAgent over play_game). One NNInference + one MCTSSearch/MCTSAgent
  // are constructed once; `choose(state_dump)` re-roots to the JSON state, runs
  // `sims` sims natively, and returns the played action as a {type,params} JSON
  // string. State crosses as JSON per move (fine for a per-move eval harness;
  // the production loop is the in-process selfplay binary).
  struct CppMctsAgent {
    std::shared_ptr<agricola::NNInference> nn;
    std::unique_ptr<agricola::MCTSSearch> search;
    std::unique_ptr<agricola::MCTSAgent> agent;

    CppMctsAgent(const std::string& model_dir, int sims, double c_uct,
                 double temperature, std::uint64_t seed) {
      nn = std::make_shared<agricola::NNInference>(model_dir);
      search = std::make_unique<agricola::MCTSSearch>(
          nn.get(), c_uct, seed ^ 0x9E3779B97F4A7C15ULL, /*fpu_offset=*/0.0);
      agent = std::make_unique<agricola::MCTSAgent>(
          search.get(), sims, c_uct, /*fpu_offset=*/0.0, temperature,
          seed ^ 0xD1B54A32D192ED03ULL, /*cap_total_sims=*/true);
    }

    std::string choose(const std::string& state_dump) {
      agricola::GameState s = agricola::game_state_from_string(state_dump);
      agricola::Action a = agent->choose(s);
      return agricola::action_to_json(a);
    }
  };

  py::class_<CppMctsAgent>(m, "CppMctsAgent")
      .def(py::init<const std::string&, int, double, double, std::uint64_t>(),
           py::arg("model_dir"), py::arg("sims"), py::arg("c_uct") = 1.4,
           py::arg("temperature") = 0.2, py::arg("seed") = 0)
      .def("choose", &CppMctsAgent::choose, py::arg("state_dump"),
           "Run `sims` native MCTS sims on the JSON-encoded state and return the "
           "played action as a {type,params} JSON string.");

  // Component-test introspection hook (CPP_ENGINE_PLAN.md §7.6): run `sims`
  // sims on the JSON state and return the root internals so the gate can check
  // the deterministic pieces (visit-budget conservation, chance round-robin
  // uniformity, single-option short-circuit). Returns a dict:
  //   {"visit_distribution": [[action_json, count], ...],   # root children
  //    "chance_counts":      [[action_json, count], ...],   # root, if chance
  //    "root_value": float, "root_visits": int, "is_chance": bool}
  m.def(
      "mcts_debug_root",
      [](const std::string& model_dir, const std::string& state_dump, int sims,
         double c_uct, std::uint64_t seed) {
        auto nn = std::make_shared<agricola::NNInference>(model_dir);
        agricola::MCTSSearch search(nn.get(), c_uct,
                                    seed ^ 0x9E3779B97F4A7C15ULL, 0.0);
        agricola::MCTSAgent agent(&search, sims, c_uct, 0.0, /*temp=*/0.0,
                                  seed ^ 0xD1B54A32D192ED03ULL, true);
        agricola::GameState s = agricola::game_state_from_string(state_dump);
        agent.choose(s);
        agricola::MCTSNode* root = agent.last_root();

        py::dict out;
        py::list vd;
        for (const auto& [a, n] : agent.root_visit_distribution(root)) {
          py::list pair;
          pair.append(agricola::action_to_json(a));
          pair.append(static_cast<long long>(n));
          vd.append(pair);
        }
        out["visit_distribution"] = vd;
        py::list cc;
        for (const auto& [a, n] : root->chance_counts) {
          py::list pair;
          pair.append(agricola::action_to_json(a));
          pair.append(static_cast<long long>(n));
          cc.append(pair);
        }
        out["chance_counts"] = cc;
        out["root_value"] = agent.root_value_p0(root);
        out["root_visits"] = static_cast<long long>(root->visits);
        out["is_chance"] = root->is_chance;
        return out;
      },
      py::arg("model_dir"), py::arg("state_dump"), py::arg("sims"),
      py::arg("c_uct") = 1.4, py::arg("seed") = 0,
      "Run native MCTS on a JSON state and return root internals "
      "(visit_distribution, chance_counts, root_value, root_visits, is_chance) "
      "for component tests.");

  m.attr("HAS_TORCH") = true;
#else
  m.attr("HAS_TORCH") = false;
#endif
}
