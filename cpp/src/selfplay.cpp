#include "agricola/selfplay.hpp"

#include <random>
#include <string>
#include <variant>
#include <vector>

#include "nlohmann/json.hpp"

#include "agricola/actions.hpp"
#include "agricola/canonical.hpp"
#include "agricola/engine.hpp"
#include "agricola/legality.hpp"
#include "agricola/scoring.hpp"
#include "agricola/setup.hpp"
#include "agricola/types.hpp"

#ifdef AGRICOLA_WITH_NN
#include <memory>
#include <unordered_map>

#include "agricola/mcts.hpp"
#include "agricola/nn.hpp"
#endif

namespace agricola {

namespace {

using json = nlohmann::ordered_json;

const char* phase_name(Phase p) {
  switch (p) {
    case Phase::WORK: return "WORK";
    case Phase::RETURN_HOME: return "RETURN_HOME";
    case Phase::PREPARATION: return "PREPARATION";
    case Phase::HARVEST_FIELD: return "HARVEST_FIELD";
    case Phase::HARVEST_FEED: return "HARVEST_FEED";
    case Phase::HARVEST_BREED: return "HARVEST_BREED";
    case Phase::BEFORE_SCORING: return "BEFORE_SCORING";
  }
  return "WORK";
}

// decider_of(state) (agents/base.py): empty stack -> current_player; non-empty
// stack -> top frame's player_idx (std::optional<int>, nullopt only for the
// PendingReveal nature frame). std::visit extracts player_idx uniformly since
// every pending frame declares it.
std::optional<int> decider_of(const GameState& s) {
  if (s.pending_stack.empty())
    return std::optional<int>(s.current_player);
  return std::visit([](const auto& frame) { return frame.player_idx; },
                    s.pending_stack.back());
}

// Build one trace action entry matching trace_replay._action_entry's shape:
// {round, phase, decider, type, params}. We reuse action_to_json (the Stage-2/3
// {type, params} serializer that already matches action_to_params) and splice
// its fields into the entry so type+params are byte-identical to the Python
// reader's expectations. (display ignored on read; visit_distribution /
// root_value attached separately for searched decisions, Stage 6.)
json make_action_entry(const GameState& state, const Action& action) {
  json type_params = json::parse(action_to_json(action));

  json entry = json::object();
  entry["round"] = state.round_number;
  entry["phase"] = phase_name(state.phase);
  std::optional<int> d = decider_of(state);
  if (d.has_value())
    entry["decider"] = *d;
  else
    entry["decider"] = nullptr;
  entry["type"] = type_params.at("type");
  entry["params"] = type_params.at("params");
  return entry;
}

}  // namespace

std::string random_selfplay_trace(std::uint64_t seed) {
  SetupResult su = setup(seed);
  GameState state = su.initial;
  const std::vector<std::string>& order = su.round_card_order;

  // Action-choice RNG: a SEPARATE deterministic stream from setup's. Derived
  // from the same seed by a fixed mixing constant so a given seed always yields
  // the same game, while never sharing setup's mt19937_64 state.
  std::mt19937_64 rng(seed ^ 0x9E3779B97F4A7C15ULL);

  json actions = json::array();

  while (state.phase != Phase::BEFORE_SCORING) {
    std::optional<int> decider = decider_of(state);
    Action action;
    if (!decider.has_value()) {
      // Nature: the round-card reveal. Routed to the dealer (the hidden order),
      // exactly as play_game routes decider==None to env.resolve.
      action = reveal_action(state, order);
    } else {
      // Player decision: uniformly-random over the engine's full legal set.
      // (legal_actions never emits `lessons` placements or FireTrigger options
      // in Family play, so this already matches filter_implemented(legal_actions)
      // — CPP_ENGINE_PLAN.md Stage 2 note.)
      std::vector<Action> legal = legal_actions(state);
      std::uniform_int_distribution<size_t> pick(0, legal.size() - 1);
      action = legal[pick(rng)];
    }
    actions.push_back(make_action_entry(state, action));
    state = step(state, action);
  }

  json envelope = json::object();
  envelope["schema"] = "agricola-cpp-trace-v1";
  envelope["seed"] = seed;
  // initial_state is the canonical dump of the round-1 WORK state (a parsed JSON
  // object, exactly what trace_replay.from_canonical expects), not a string.
  envelope["initial_state"] = json::parse(to_canonical_string(su.initial));
  envelope["actions"] = std::move(actions);

  // Compact, like Python json.dumps(separators=(",",":")). ordered_json keeps
  // insertion order. dump() with no indent is compact.
  return envelope.dump();
}

#ifdef AGRICOLA_WITH_NN

namespace {

using json = nlohmann::ordered_json;

// Process-wide NNInference cache (loading .ts every game is wasteful when many
// games share a model_dir). Shared across mcts_selfplay_trace calls in one
// process; not thread-safe (production parallelism is process-per-worker).
std::shared_ptr<NNInference> get_nn_cached(const std::string& model_dir) {
  static std::unordered_map<std::string, std::shared_ptr<NNInference>> cache;
  auto it = cache.find(model_dir);
  if (it != cache.end()) return it->second;
  auto inf = std::make_shared<NNInference>(model_dir);
  cache[model_dir] = inf;
  return inf;
}

// Attach π + visit_distribution_types + root_value to a searched-decision entry,
// matching trace_replay._action_entry's visit_distribution carriage:
//   visit_distribution        = [[params, count], ...]
//   visit_distribution_types  = [TypeName, ...]   (parallel — recovers each key)
//   root_value                = float
void attach_search_targets(
    json& entry,
    const std::vector<std::pair<Action, long long>>& visit_dist,
    double root_value) {
  json vd = json::array();
  json types = json::array();
  for (const auto& [a, n] : visit_dist) {
    json tp = json::parse(action_to_json(a));  // {type, params}
    json pair = json::array();
    pair.push_back(tp.at("params"));
    pair.push_back(static_cast<long long>(n));
    vd.push_back(std::move(pair));
    types.push_back(tp.at("type"));
  }
  entry["visit_distribution"] = std::move(vd);
  entry["visit_distribution_types"] = std::move(types);
  entry["root_value"] = root_value;
}

}  // namespace

std::string mcts_selfplay_trace_with(const NNInference& nn, std::uint64_t seed,
                                     int sims, double c_uct,
                                     double temperature) {
  SetupResult su = setup(seed);
  GameState state = su.initial;
  const std::vector<std::string>& order = su.round_card_order;

  // Two independent RNG streams, both deterministic from `seed`:
  //   search.rng — tree tiebreaks + chance round-robin
  //   agent.rng  — played-move sampling
  // Distinct mixing constants so they never share state (CPP_ENGINE_PLAN.md §7.5).
  std::uint64_t search_seed = seed ^ 0x9E3779B97F4A7C15ULL;
  std::uint64_t agent_seed = seed ^ 0xD1B54A32D192ED03ULL;

  // ONE search/agent drives BOTH seats (shared tree; re_root each move carries
  // stats across the P0<->P1 boundary). Mirrors play_selfplay_recording_game.
  MCTSSearch search(&nn, c_uct, search_seed, /*fpu_offset=*/0.0);
  MCTSAgent agent(&search, sims, c_uct, /*fpu_offset=*/0.0, temperature,
                  agent_seed, /*cap_total_sims=*/true);

  json actions = json::array();

  while (state.phase != Phase::BEFORE_SCORING) {
    std::optional<int> decider = decider_of(state);
    if (!decider.has_value()) {
      // Nature's round-card reveal — resolved by the dealer, never recorded /
      // searched (mirrors play_selfplay_recording_game's dealer branch).
      Action action = reveal_action(state, order);
      actions.push_back(make_action_entry(state, action));
      state = step(state, action);
      continue;
    }

    std::vector<Action> legal = legal_actions(state);
    if (legal.size() <= 1) {
      // Forced move: the single legal action is what any search would also play.
      // Step directly — identical trajectory, no wasted sims, NOT recorded with
      // π (singletons carry no search targets).
      Action action = legal[0];
      actions.push_back(make_action_entry(state, action));
      state = step(state, action);
      continue;
    }

    // Genuine multi-option decision: search it, record π + root_value.
    GameState snapshot = state;  // captured BEFORE the agent acts
    Action chosen = agent.choose(state);
    MCTSNode* root = agent.last_root();
    json entry = make_action_entry(snapshot, chosen);
    attach_search_targets(entry, agent.root_visit_distribution(root),
                          agent.root_value_p0(root));
    actions.push_back(std::move(entry));
    state = step(state, chosen);
  }

  json envelope = json::object();
  envelope["schema"] = "agricola-cpp-trace-v1";
  envelope["seed"] = seed;
  envelope["initial_state"] = json::parse(to_canonical_string(su.initial));
  envelope["actions"] = std::move(actions);
  return envelope.dump();
}

std::string mcts_selfplay_trace(std::uint64_t seed, int sims, double c_uct,
                                double temperature,
                                const std::string& model_dir) {
  // Load (or reuse a process-cached) NNInference once, then delegate — so a
  // single-game call is byte-identical to the pre-refactor body. The batch
  // path instead holds one NNInference and calls mcts_selfplay_trace_with
  // directly, avoiding even the cache lookup per game.
  std::shared_ptr<NNInference> nn = get_nn_cached(model_dir);
  return mcts_selfplay_trace_with(*nn, seed, sims, c_uct, temperature);
}

MatchGameResult mcts_match_game(const NNInference& nn_p0, const NNInference& nn_p1,
                                std::uint64_t seed,
                                int sims_p0, double c_uct_p0,
                                int sims_p1, double c_uct_p1,
                                double temperature) {
  SetupResult su = setup(seed);
  GameState state = su.initial;
  const std::vector<std::string>& order = su.round_card_order;

  // One search/agent per seat, each over its own value net AND its own
  // (sims, c_uct) search params. P0 reuses the self-play mixing constants (so a
  // symmetric P0-vs-P0 matches self-play); P1 uses a distinct pair so the two
  // seats never share an RNG stream.
  MCTSSearch search0(&nn_p0, c_uct_p0, seed ^ 0x9E3779B97F4A7C15ULL, /*fpu=*/0.0);
  MCTSAgent agent0(&search0, sims_p0, c_uct_p0, /*fpu=*/0.0, temperature,
                   seed ^ 0xD1B54A32D192ED03ULL, /*cap_total_sims=*/true);
  MCTSSearch search1(&nn_p1, c_uct_p1, seed ^ 0xBF58476D1CE4E5B9ULL, /*fpu=*/0.0);
  MCTSAgent agent1(&search1, sims_p1, c_uct_p1, /*fpu=*/0.0, temperature,
                   seed ^ 0x94D049BB133111EBULL, /*cap_total_sims=*/true);

  while (state.phase != Phase::BEFORE_SCORING) {
    std::optional<int> decider = decider_of(state);
    if (!decider.has_value()) {
      state = step(state, reveal_action(state, order));  // nature reveal
      continue;
    }
    std::vector<Action> legal = legal_actions(state);
    if (legal.size() <= 1) {
      state = step(state, legal[0]);                     // forced move
      continue;
    }
    Action chosen = (*decider == 0) ? agent0.choose(state) : agent1.choose(state);
    state = step(state, chosen);
  }

  int p0 = score(state, 0);
  int p1 = score(state, 1);
  int winner;
  if (p0 != p1) {
    winner = (p0 > p1) ? 0 : 1;
  } else {
    int t0 = tiebreaker(state, 0);
    int t1 = tiebreaker(state, 1);
    winner = (t0 > t1) ? 0 : (t1 > t0) ? 1 : -1;
  }
  return MatchGameResult{seed, p0, p1, winner};
}

#endif  // AGRICOLA_WITH_NN

std::string pick_move(const std::string& state_json, const std::string& model_dir,
                      int sims, double c_uct, double temperature) {
#ifndef AGRICOLA_WITH_NN
  (void)state_json; (void)model_dir; (void)sims; (void)c_uct; (void)temperature;
  throw std::runtime_error("pick_move: binary was not built with NN support");
#else
  GameState state = game_state_from_string(state_json);

  std::shared_ptr<NNInference> nn = get_nn_cached(model_dir);
  // Use seed 0 — each call gets a fresh search tree, so the RNG seed only
  // affects tie-breaking in tree expansion, not correctness.
  MCTSSearch search(nn.get(), c_uct, /*rng_seed=*/0, /*fpu=*/0.0);
  MCTSAgent agent(&search, sims, c_uct, /*fpu=*/0.0, temperature,
                  /*rng_seed=*/0, /*cap_total_sims=*/false);

  Action chosen = agent.choose(state);
  MCTSNode* root = agent.last_root();

  json out;
  out["action"] = json::parse(action_to_json(chosen));
  out["root_value"] = (root != nullptr) ? root->mean_q() : 0.0;
  return out.dump();
#endif
}

}  // namespace agricola
