#include "agricola/selfplay.hpp"

#include <random>
#include <stdexcept>
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

// Resolve a leaf-mode string ("margin"/"outcome"/"mix") and apply it to a
// search. "margin" is a no-op (the ctor's default scales already apply); for
// "outcome"/"mix" the scales come from the model's manifest (value_scale +
// outcome_scale) and the model must carry an outcome head; "mix" also sets the
// blend weight α. Shared by mcts_match_game, pick_move, and analyze_position.
void apply_leaf_mode(MCTSSearch& search, const NNInference& nn,
                     const std::string& mode, double mix_alpha) {
  if (mode == "margin") return;  // default; scales already set in the ctor
  if (mode != "outcome" && mode != "mix")
    throw std::runtime_error("apply_leaf_mode: leaf_mode must be "
                             "margin/outcome/mix, got '" + mode + "'");
  if (!nn.has_outcome())
    throw std::runtime_error("apply_leaf_mode: leaf_mode '" + mode +
                             "' requires a model with an outcome head");
  search.set_margin_scale(nn.value_scale());
  search.set_outcome_scale(nn.outcome_scale());
  search.set_leaf_mode(mode == "outcome" ? LeafMode::OUTCOME : LeafMode::MIX);
  if (mode == "mix") search.set_mix_alpha(mix_alpha);
}

}  // namespace

std::string mcts_selfplay_trace_with(const NNInference& nn, std::uint64_t seed,
                                     int sims, double c_uct,
                                     double temperature, double prior_mix,
                                     bool select_q) {
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
  search.set_prior_uniform_mix(prior_mix);
  MCTSAgent agent(&search, sims, c_uct, /*fpu_offset=*/0.0, temperature,
                  agent_seed, /*cap_total_sims=*/true);
  agent.set_select_by_q(select_q);

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
                                const std::string& model_dir,
                                double prior_mix, bool select_q) {
  // Load (or reuse a process-cached) NNInference once, then delegate — so a
  // single-game call is byte-identical to the pre-refactor body. The batch
  // path instead holds one NNInference and calls mcts_selfplay_trace_with
  // directly, avoiding even the cache lookup per game.
  std::shared_ptr<NNInference> nn = get_nn_cached(model_dir);
  return mcts_selfplay_trace_with(*nn, seed, sims, c_uct, temperature, prior_mix,
                                  select_q);
}

MatchGameResult mcts_match_game(const NNInference& nn_p0, const NNInference& nn_p1,
                                std::uint64_t seed,
                                int sims_p0, double c_uct_p0,
                                int sims_p1, double c_uct_p1,
                                double temperature_p0,
                                double temperature_p1,
                                double prior_mix_p0,
                                double prior_mix_p1,
                                bool select_q_p0,
                                bool select_q_p1,
                                const std::string& leaf_mode_p0,
                                const std::string& leaf_mode_p1,
                                double mix_alpha_p0,
                                double mix_alpha_p1) {
  SetupResult su = setup(seed);
  GameState state = su.initial;
  const std::vector<std::string>& order = su.round_card_order;

  // Per-seat leaf-mode applied via the shared apply_leaf_mode helper (resolves
  // "margin"/"outcome"/"mix"; for outcome/mix the scales come from that seat's
  // own NN manifest, and mix uses the blend weight α).

  // One search/agent per seat, each over its own value net AND its own
  // (sims, c_uct, temperature) search params. P0 reuses the self-play mixing
  // constants (so a symmetric P0-vs-P0 matches self-play); P1 uses a distinct
  // pair so the two seats never share an RNG stream.
  MCTSSearch search0(&nn_p0, c_uct_p0, seed ^ 0x9E3779B97F4A7C15ULL, /*fpu=*/0.0);
  search0.set_prior_uniform_mix(prior_mix_p0);
  apply_leaf_mode(search0, nn_p0, leaf_mode_p0, mix_alpha_p0);
  MCTSAgent agent0(&search0, sims_p0, c_uct_p0, /*fpu=*/0.0, temperature_p0,
                   seed ^ 0xD1B54A32D192ED03ULL, /*cap_total_sims=*/true);
  agent0.set_select_by_q(select_q_p0);
  MCTSSearch search1(&nn_p1, c_uct_p1, seed ^ 0xBF58476D1CE4E5B9ULL, /*fpu=*/0.0);
  search1.set_prior_uniform_mix(prior_mix_p1);
  apply_leaf_mode(search1, nn_p1, leaf_mode_p1, mix_alpha_p1);
  MCTSAgent agent1(&search1, sims_p1, c_uct_p1, /*fpu=*/0.0, temperature_p1,
                   seed ^ 0x94D049BB133111EBULL, /*cap_total_sims=*/true);
  agent1.set_select_by_q(select_q_p1);

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
                      int sims, double c_uct, double temperature,
                      double prior_mix, const std::string& leaf_mode,
                      double mix_alpha) {
#ifndef AGRICOLA_WITH_NN
  (void)state_json; (void)model_dir; (void)sims; (void)c_uct; (void)temperature;
  (void)prior_mix; (void)leaf_mode; (void)mix_alpha;
  throw std::runtime_error("pick_move: binary was not built with NN support");
#else
  GameState state = game_state_from_string(state_json);

  std::shared_ptr<NNInference> nn = get_nn_cached(model_dir);
  // Use seed 0 — each call gets a fresh search tree, so the RNG seed only
  // affects tie-breaking in tree expansion, not correctness.
  MCTSSearch search(nn.get(), c_uct, /*rng_seed=*/0, /*fpu=*/0.0);
  search.set_prior_uniform_mix(prior_mix);  // 0 = pure policy (default)
  apply_leaf_mode(search, *nn, leaf_mode, mix_alpha);  // margin = no-op
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

std::string analyze_position(const std::string& state_json,
                             const std::string& model_dir, int sims,
                             double c_uct, double temperature,
                             double prior_mix, const std::string& leaf_mode,
                             double mix_alpha) {
#ifndef AGRICOLA_WITH_NN
  (void)state_json; (void)model_dir; (void)sims; (void)c_uct; (void)temperature;
  (void)prior_mix; (void)leaf_mode; (void)mix_alpha;
  throw std::runtime_error("analyze_position: binary was not built with NN support");
#else
  (void)temperature;  // analysis discards the played move; temperature is unused.
  GameState state = game_state_from_string(state_json);

  std::shared_ptr<NNInference> nn = get_nn_cached(model_dir);
  // Mirror pick_move's search setup exactly (fresh tree, seed 0 — only affects
  // tie-breaking). cap_total_sims=false so we run the full `sims` budget.
  MCTSSearch search(nn.get(), c_uct, /*rng_seed=*/0, /*fpu=*/0.0);
  search.set_prior_uniform_mix(prior_mix);  // uniform-mix the prior for coverage
  apply_leaf_mode(search, *nn, leaf_mode, mix_alpha);  // margin = no-op
  MCTSAgent agent(&search, sims, c_uct, /*fpu=*/0.0, temperature,
                  /*rng_seed=*/0, /*cap_total_sims=*/false);

  // Run the search but DISCARD the chosen move — we only want the root stats.
  agent.choose(state);
  MCTSNode* root = agent.last_root();

  // The leaf is the value head, whose mean Q (value_sum/visits) is NORMALIZED
  // (the head's output, target / value_scale at train time). For margin/outcome
  // leaves we multiply by value_scale to recover the head's NATURAL units, and
  // the `value_target` descriptor labels them: "margin" => points of expected
  // score diff; "outcome" => expected win/draw/loss value in [-1,1].
  //
  // For the MIX leaf the backed-up Q is ALREADY a blend of two normalized terms
  // (effective leaf_value_scale 1.0 — see LeafMode::MIX), so there is no single
  // head value_scale to recover. We report the RAW tree Q unchanged and label
  // it "mix" so the UI shows the unitless blend value rather than a meaningless
  // ×value_scale denormalization.
  //
  // The reported unit/scale follow the ANALYSIS leaf_mode (which head the search
  // actually backed up), NOT the model's primary training value_target — analysis
  // can request any of the model's heads independently of how the bot plays. An
  // outcome leaf is normalized by outcome_scale (recover its [-1,1] units); the
  // margin leaf is the primary value head (its natural descriptor is value_target).
  std::string value_target;
  double value_scale;
  if (leaf_mode == "mix") {
    value_target = "mix";
    value_scale = 1.0;
  } else if (leaf_mode == "outcome") {
    value_target = "outcome";
    value_scale = nn->outcome_scale();
  } else {  // margin = the primary value head
    value_target = nn->value_target();
    value_scale = nn->value_scale();
  }

  json children = json::array();
  if (root != nullptr) {
    // root->value_sum is in the root decider's own frame. Each child's value_sum
    // is in THAT CHILD's decider frame; flip to the root (== the human decider)
    // frame so q is consistently "good-for-the-human" (higher = better) — the
    // same sign-flip select_via_puct applies on read.
    for (const auto& [action, child] : root->children) {
      if (child->visits == 0) continue;  // unvisited — omit
      double q = child->value_sum / static_cast<double>(child->visits);
      if (child->decider != root->decider) q = -q;
      q *= value_scale;  // margin/outcome: -> natural units; mix: ×1.0 (raw Q)
      json tp = json::parse(action_to_json(action));  // {type, params}
      json entry = json::object();
      entry["type"] = tp.at("type");
      entry["params"] = tp.at("params");
      entry["visits"] = static_cast<long long>(child->visits);
      entry["q"] = q;
      children.push_back(std::move(entry));
    }
  }

  json out = json::object();
  out["children"] = std::move(children);
  out["value_target"] = value_target;  // "margin" / "outcome" / "mix" — q unit
  return out.dump();
#endif
}

}  // namespace agricola
