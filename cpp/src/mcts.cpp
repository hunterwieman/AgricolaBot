// Native MCTS — PUCT + FLATTEN + chance nodes. A faithful port of the production
// path in agricola/agents/mcts.py (MCTSNode / MCTSSearch / MCTSAgent), guarded
// behind AGRICOLA_WITH_NN (needs NNInference). See CPP_ENGINE_PLAN.md §7 and
// MCTS_IMPLEMENTATION.md.
//
// Mirrored Python (cited inline by symbol):
//   MCTSSearch.find_or_create_node / add_edge / re_root / evaluate_leaf
//   MCTSAgent._simulate / _puct_select_child / _select_via_puct / _chance_route
//     / root_visit_distribution / _select_action_with_temperature
//   selfplay_recording._root_value_p0
#include "agricola/mcts.hpp"

#ifdef AGRICOLA_WITH_NN

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

#include "agricola/encoder.hpp"   // encoder_decider_of
#include "agricola/engine.hpp"    // step
#include "agricola/legality.hpp"  // legal_actions
#include "agricola/scoring.hpp"

namespace agricola {

// Fast field-wise Action hash for the per-node unordered_maps (children /
// chance_counts / priors). No serialization — the std::map+comparator this
// replaced was the MCTS profile's #1 main-thread cost (variant operator< on
// every selection step). Hashes the variant index + the active alternative's
// fields; Action's defaulted operator== resolves bucket collisions.
namespace {
inline void amix(std::size_t& h, std::size_t v) {
  h ^= v + 0x9e3779b97f4a7c15ULL + (h << 6) + (h >> 2);
}
inline void af(std::size_t& h, int v) { amix(h, static_cast<std::size_t>(static_cast<unsigned>(v))); }
inline void af(std::size_t& h, const std::string& s) {
  for (unsigned char c : s) amix(h, c);
  amix(h, s.size());
}
inline void af(std::size_t& h, const std::optional<int>& v) {
  if (v) { amix(h, 1); af(h, *v); } else { amix(h, 0); }
}
inline void hf(std::size_t& h, const PlaceWorker& a) { af(h, a.space); }
inline void hf(std::size_t& h, const ChooseSubAction& a) { af(h, a.name); }
inline void hf(std::size_t& h, const CommitSow& a) { af(h, a.grain); af(h, a.veg); }
inline void hf(std::size_t& h, const CommitBake& a) { af(h, a.grain); }
inline void hf(std::size_t& h, const CommitPlow& a) { af(h, a.row); af(h, a.col); }
inline void hf(std::size_t& h, const CommitBuildStable& a) { af(h, a.row); af(h, a.col); }
inline void hf(std::size_t& h, const CommitBuildRoom& a) { af(h, a.row); af(h, a.col); }
inline void hf(std::size_t& h, const CommitBuildMajor& a) { af(h, a.major_idx); af(h, a.return_fireplace_idx); }
inline void hf(std::size_t&, const CommitRenovate&) {}
inline void hf(std::size_t& h, const CommitAccommodate& a) { af(h, a.sheep); af(h, a.boar); af(h, a.cattle); }
inline void hf(std::size_t& h, const CommitBuildPasture& a) {
  for (const auto& [r, c] : a.cells) { af(h, r); af(h, c); }
  amix(h, a.cells.size());
}
inline void hf(std::size_t& h, const CommitHarvestConversion& a) { af(h, a.conversion_id); }
inline void hf(std::size_t& h, const CommitConvert& a) { af(h, a.grain); af(h, a.veg); af(h, a.sheep); af(h, a.boar); af(h, a.cattle); }
inline void hf(std::size_t& h, const CommitBreed& a) { af(h, a.sheep); af(h, a.boar); af(h, a.cattle); }
inline void hf(std::size_t& h, const FireTrigger& a) { af(h, a.card_id); }
inline void hf(std::size_t&, const Stop&) {}
inline void hf(std::size_t&, const Proceed&) {}
inline void hf(std::size_t& h, const RevealCard& a) { af(h, a.card); }
}  // namespace

std::size_t ActionHash::operator()(const Action& a) const {
  std::size_t h = 1469598103934665603ULL;
  amix(h, a.index());
  std::visit([&](const auto& x) { hf(h, x); }, a);
  return h;
}

// ---------------------------------------------------------------------------
// MCTSSearch
// ---------------------------------------------------------------------------

MCTSSearch::MCTSSearch(const NNInference* nn, double c_uct,
                       std::uint64_t rng_seed, double fpu_offset)
    : nn_(nn),
      c_uct_(c_uct),
      fpu_offset_(fpu_offset),
      leaf_value_scale_(nn ? nn->value_scale() : 1.0),
      rng_(rng_seed) {
  if (leaf_value_scale_ == 0.0) leaf_value_scale_ = 1.0;
  // Default the per-head normalizers from the model (MIX can override the pair
  // with the common-state scales). margin_scale_ tracks leaf_value_scale_.
  margin_scale_ = leaf_value_scale_;
  outcome_scale_ = (nn && nn->has_outcome()) ? nn->outcome_scale() : 1.0;
  if (outcome_scale_ == 0.0) outcome_scale_ = 1.0;
}

MCTSNode* MCTSSearch::find_or_create_node(const GameState& state,
                                          MCTSNode* parent,
                                          const Action* action_from_parent) {
  auto it = transpositions_.find(state);
  if (it != transpositions_.end()) {
    MCTSNode* existing = it->second.get();
    if (parent != nullptr && action_from_parent != nullptr)
      add_edge(parent, existing, *action_from_parent);
    return existing;
  }
  std::optional<int> d = encoder_decider_of(state);  // == agents/base.decider_of
  bool is_chance = !d.has_value();
  auto node = std::make_unique<MCTSNode>();
  node->state = state;
  node->decider = is_chance ? 0 : *d;  // frame label when chance; player else
  node->is_chance = is_chance;
  MCTSNode* raw = node.get();
  transpositions_.emplace(state, std::move(node));
  if (parent != nullptr && action_from_parent != nullptr)
    add_edge(parent, raw, *action_from_parent);
  return raw;
}

void MCTSSearch::add_edge(MCTSNode* parent, MCTSNode* child,
                          const Action& action) {
  parent->children[action] = child;
  if (std::find(child->parents.begin(), child->parents.end(), parent) ==
      child->parents.end())
    child->parents.push_back(parent);
}

void MCTSSearch::re_root(MCTSNode* new_root) {
  if (new_root == root_) return;
  // Walk the live subtree from new_root by pointer identity.
  std::unordered_map<MCTSNode*, bool> reachable;
  std::vector<MCTSNode*> queue{new_root};
  while (!queue.empty()) {
    MCTSNode* node = queue.back();
    queue.pop_back();
    if (reachable.count(node)) continue;
    reachable[node] = true;
    for (auto& [a, child] : node->children) queue.push_back(child);
  }
  // Scrub stale back-edges FIRST: a surviving node may list a soon-to-be-freed
  // parent. Python keeps those parents alive (its list holds refs); C++ frees
  // them below, so we must drop dangling parent pointers before erase to keep
  // `add_edge`'s identity dedup sound. (parents is never read at backprop; this
  // is purely to avoid comparing dangling pointers later.)
  for (auto& [s, node] : transpositions_) {
    if (!reachable.count(node.get())) continue;
    auto& ps = node->parents;
    ps.erase(std::remove_if(ps.begin(), ps.end(),
                            [&](MCTSNode* p) { return !reachable.count(p); }),
             ps.end());
  }
  // Drop every transposition entry not reachable from new_root (frees its
  // unique_ptr). Erase-by-iteration over the owning map.
  for (auto it = transpositions_.begin(); it != transpositions_.end();) {
    if (!reachable.count(it->second.get()))
      it = transpositions_.erase(it);
    else
      ++it;
  }
  root_ = new_root;
}

double MCTSSearch::evaluate_leaf(MCTSNode* node) const {
  // Leaf value in P0's frame, by mode (mirrors shared_policy.make_joint_fns'
  // leaf_mode). All heads read off node->embedding — value() fills it on the
  // first call (joint mode); outcome() then reuses the SAME embedding (one trunk
  // forward), and policy at the node's later expansion reuses it again.
  //   MARGIN  — margin / margin_scale (terminal branch divides the exact margin
  //             too, exactly as before; margin_scale_ == leaf_value_scale_).
  //   OUTCOME — outcome / outcome_scale.
  //   MIX     — α·(margin/margin_scale) + (1-α)·(outcome/outcome_scale), already
  //             in Q units, so NO further division. α = mix_alpha_ (default 0.5).
  if (leaf_mode_ == LeafMode::MARGIN)
    return nn_->value(node->state, node->embedding) / margin_scale_;
  if (leaf_mode_ == LeafMode::OUTCOME)
    return nn_->outcome(node->state, node->embedding) / outcome_scale_;
  // MIX: value() fills the per-node embedding, outcome() reuses it (no 2nd trunk
  // forward).
  double m = nn_->value(node->state, node->embedding) / margin_scale_;
  double o = nn_->outcome(node->state, node->embedding) / outcome_scale_;
  return mix_alpha_ * m + (1.0 - mix_alpha_) * o;
}

void MCTSSearch::ensure_legal(MCTSNode* node) {
  if (node->legal_computed) return;
  node->legal_computed = true;
  if (node->is_terminal()) {
    node->legal.clear();
    return;
  }
  // FLATTEN: the engine's full legal set, unmodified (the policy prior is the
  // sole prune). filter_implemented is a no-op in Family play (no lessons /
  // FireTrigger emitted), so legal_actions == filter_implemented(legal_actions).
  node->legal = legal_actions(node->state);
}

void MCTSSearch::ensure_priors(MCTSNode* node) {
  if (node->priors_computed) return;
  if (node->is_chance) return;  // chance nodes never get priors
  node->priors_computed = true;
  ensure_legal(node);
  // policy_fn(state, legal) -> {action: prior} over the full legal set; omitted
  // actions default to prior 0 in select_via_puct.
  for (const auto& [a, pr] : nn_->policy(node->state, node->embedding))
    node->priors[a] = pr;
  // Optional uniform mixing: prior' = (1-mix)*policy + mix*(1/k) over the legal
  // set. Guarantees every legal move a non-zero prior so PUCT will explore it.
  if (prior_uniform_mix_ > 0.0 && !node->legal.empty()) {
    const double w = prior_uniform_mix_;
    const double u = 1.0 / static_cast<double>(node->legal.size());
    for (const Action& a : node->legal) {
      auto it = node->priors.find(a);
      const double p = (it != node->priors.end()) ? it->second : 0.0;
      node->priors[a] = (1.0 - w) * p + w * u;
    }
  }
}

// ---------------------------------------------------------------------------
// MCTSAgent
// ---------------------------------------------------------------------------

MCTSAgent::MCTSAgent(MCTSSearch* search, int sims_per_move, double c_uct,
                     double fpu_offset, double action_selection_temperature,
                     std::uint64_t rng_seed, bool cap_total_sims)
    : search_(search),
      sims_per_move_(sims_per_move),
      c_uct_(c_uct),
      fpu_offset_(fpu_offset),
      temperature_(action_selection_temperature),
      cap_total_sims_(cap_total_sims),
      rng_(rng_seed) {}

Action MCTSAgent::choose(const GameState& state) {
  // No mid-macro replay queue: FLATTEN has no MacroFencingAction.
  MCTSNode* root = search_->find_or_create_node(state);
  search_->re_root(root);

  if (cap_total_sims_) {
    while (root->visits < sims_per_move_) simulate(root);
  } else {
    for (int i = 0; i < sims_per_move_; ++i) simulate(root);
  }
  return select_action_with_temperature(root);
}

void MCTSAgent::simulate(MCTSNode* root) {
  std::vector<MCTSNode*> path{root};
  MCTSNode* node = root;

  // ---------- SELECT + EXPAND ----------
  while (true) {
    if (node->is_terminal()) break;

    if (node->is_chance) {
      Action action = chance_route(node);
      auto it = node->children.find(action);
      bool is_new = (it == node->children.end());
      MCTSNode* child;
      if (is_new) {
        GameState next = step(node->state, action);
        child = search_->find_or_create_node(next, node, &action);
      } else {
        child = it->second;
      }
      path.push_back(child);
      node = child;
      if (is_new) break;  // fresh post-reveal decision node = leaf
      continue;           // existing outcome -> keep descending
    }

    // ---- decision node ----
    search_->ensure_legal(node);
    if (node->legal.empty()) break;  // defensive: non-terminal with no actions

    auto [child, is_new] = puct_select_child(node);
    path.push_back(child);
    node = child;
    if (is_new) {
      if (node->is_chance) continue;  // route through reveal next iteration
      if (!node->is_terminal()) {
        search_->ensure_legal(node);
        if (node->legal.size() == 1)
          continue;  // FORCED move: step through in this same sim
      }
      break;  // multi-option decision or terminal -> evaluate
    }
    // existing child -> keep descending
  }

  // ---------- EVALUATE ----------
  double leaf_value_p0 = search_->evaluate_leaf(node);

  // ---------- BACKPROP ----------
  for (MCTSNode* n : path) {
    if (n->decider == 0)
      n->value_sum += leaf_value_p0;
    else
      n->value_sum -= leaf_value_p0;
    n->visits += 1;
  }
}

std::pair<MCTSNode*, bool> MCTSAgent::puct_select_child(MCTSNode* node) {
  Action action = select_via_puct(node);
  auto it = node->children.find(action);
  bool is_new = (it == node->children.end());
  MCTSNode* child;
  if (is_new) {
    GameState next = step(node->state, action);
    child = search_->find_or_create_node(next, node, &action);
  } else {
    child = it->second;
  }
  return {child, is_new};
}

Action MCTSAgent::select_via_puct(MCTSNode* parent) {
  // parent->legal is the engine order (== Python _legal_actions order), so the
  // tie-collection order matches Python's.
  if (parent->legal.size() == 1) return parent->legal[0];  // forced — no prior
  search_->ensure_priors(parent);

  double parent_q = parent->visits > 0 ? parent->mean_q() : 0.0;
  double sqrt_total =
      std::sqrt(static_cast<double>(std::max<long long>(parent->visits, 1)));

  double best_score = -std::numeric_limits<double>::infinity();
  std::vector<const Action*> best_actions;
  for (const Action& action : parent->legal) {
    auto cit = parent->children.find(action);
    double prior = 0.0;
    auto pit = parent->priors.find(action);
    if (pit != parent->priors.end()) prior = pit->second;

    double q;
    long long n;
    if (cit == parent->children.end() || cit->second->visits == 0) {
      q = parent_q - fpu_offset_;  // FPU reduction
      n = 0;
    } else {
      MCTSNode* child = cit->second;
      q = child->value_sum / child->visits;
      if (child->decider != parent->decider) q = -q;  // sign-flip on read
      n = child->visits;
    }
    double score = q + c_uct_ * prior * sqrt_total / (1.0 + n);
    if (score > best_score) {
      best_score = score;
      best_actions.clear();
      best_actions.push_back(&action);
    } else if (score == best_score) {
      best_actions.push_back(&action);
    }
  }
  if (best_actions.size() == 1) return *best_actions[0];
  std::uniform_int_distribution<size_t> pick(0, best_actions.size() - 1);
  return *best_actions[pick(search_->rng())];
}

Action MCTSAgent::chance_route(MCTSNode* node) {
  search_->ensure_legal(node);
  const std::vector<Action>& candidates = node->legal;  // the ≤3 RevealCards
  // min count over candidates.
  long long min_count = std::numeric_limits<long long>::max();
  for (const Action& a : candidates) {
    auto it = node->chance_counts.find(a);
    long long c = (it == node->chance_counts.end()) ? 0 : it->second;
    min_count = std::min(min_count, c);
  }
  std::vector<const Action*> least;
  for (const Action& a : candidates) {
    auto it = node->chance_counts.find(a);
    long long c = (it == node->chance_counts.end()) ? 0 : it->second;
    if (c == min_count) least.push_back(&a);
  }
  const Action* chosen;
  if (least.size() == 1) {
    chosen = least[0];
  } else {
    std::uniform_int_distribution<size_t> pick(0, least.size() - 1);
    chosen = least[pick(search_->rng())];
  }
  node->chance_counts[*chosen] += 1;
  return *chosen;
}

std::vector<std::pair<Action, long long>> MCTSAgent::root_visit_distribution(
    MCTSNode* root) const {
  // {action: child.visits} over root.children. The global child.visits at the
  // root == the played-move distribution. Order follows the map (deterministic);
  // the replayer keys by action, so order is immaterial.
  std::vector<std::pair<Action, long long>> out;
  for (const auto& [a, child] : root->children) out.push_back({a, child->visits});
  return out;
}

double MCTSAgent::root_value_p0(MCTSNode* root) const {
  // root.value_sum/mean_q is in the root decider's own frame; flip to P0's.
  double q = root->mean_q();
  return root->decider == 0 ? q : -q;
}

Action MCTSAgent::select_action_by_q(MCTSNode* root) {
  // Rank VISITED root children by mean-Q in the root player's frame. A child's
  // value_sum is stored in the child's own decider frame, so flip the sign when
  // the child's decider differs from the root's (mirrors select_via_puct's
  // q = -q sign-flip on read). Unvisited children have no Q estimate and are
  // skipped — mean_q() would return a meaningless 0.0 placeholder.
  std::vector<std::pair<Action, double>> items;
  for (const auto& [a, child] : root->children) {
    if (child->visits == 0) continue;
    double q = child->mean_q();
    if (child->decider != root->decider) q = -q;  // -> root-player frame
    items.push_back({a, q});
  }
  if (items.empty())  // no visited children — defer to the visit-count path
    return select_action_by_visits(root);

  if (temperature_ <= 0.0) {
    double best = items[0].second;
    for (const auto& [a, q] : items) best = std::max(best, q);
    std::vector<const Action*> ties;
    for (const auto& it : items)
      if (it.second == best) ties.push_back(&it.first);
    if (ties.size() == 1) return *ties[0];
    std::uniform_int_distribution<size_t> pick(0, ties.size() - 1);
    return *ties[pick(rng_)];
  }

  // probs[a] ∝ exp(Q(a)/T). Subtract max for numerical stability (Q is signed,
  // so the visit-count path's visits^(1/T) trick does not apply here).
  double mx = items[0].second;
  for (const auto& [a, q] : items) mx = std::max(mx, q);
  std::vector<double> scaled(items.size());
  double total = 0.0;
  for (size_t i = 0; i < items.size(); ++i) {
    scaled[i] = std::exp((items[i].second - mx) / temperature_);
    total += scaled[i];
  }
  std::uniform_real_distribution<double> u(0.0, 1.0);
  double r = u(rng_) * total;
  double acc = 0.0;
  for (size_t i = 0; i < items.size(); ++i) {
    acc += scaled[i];
    if (r < acc) return items[i].first;
  }
  return items.back().first;
}

Action MCTSAgent::select_action_with_temperature(MCTSNode* root) {
  last_root_ = root;
  return select_by_q_ ? select_action_by_q(root) : select_action_by_visits(root);
}

Action MCTSAgent::select_action_by_visits(MCTSNode* root) {
  std::vector<std::pair<Action, long long>> items;
  for (const auto& [a, child] : root->children) items.push_back({a, child->visits});
  if (items.empty())
    throw std::runtime_error("MCTSAgent: no children at root to choose from");

  if (temperature_ <= 0.0) {
    long long best = items[0].second;
    for (const auto& [a, v] : items) best = std::max(best, v);
    std::vector<const Action*> ties;
    for (const auto& it : items)
      if (it.second == best) ties.push_back(&it.first);
    if (ties.size() == 1) return *ties[0];
    std::uniform_int_distribution<size_t> pick(0, ties.size() - 1);
    return *ties[pick(rng_)];
  }

  // probs[a] ∝ visits^(1/T).
  std::vector<double> scaled(items.size());
  double total = 0.0;
  for (size_t i = 0; i < items.size(); ++i) {
    scaled[i] = std::pow(static_cast<double>(items[i].second), 1.0 / temperature_);
    total += scaled[i];
  }
  if (total == 0.0) {  // all visits zero — uniform fallback
    std::uniform_int_distribution<size_t> pick(0, items.size() - 1);
    return items[pick(rng_)].first;
  }
  // Sample proportional to scaled. np.random.Generator.choice(p=...) draws a
  // uniform in [0,1) and walks the cumulative distribution; we mirror that with
  // a uniform draw on the normalized weights (the exact RNG stream differs from
  // NumPy, which is fine — §7.5: same-seed determinism, not NumPy bit-parity).
  std::uniform_real_distribution<double> u(0.0, 1.0);
  double r = u(rng_) * total;
  double acc = 0.0;
  for (size_t i = 0; i < items.size(); ++i) {
    acc += scaled[i];
    if (r < acc) return items[i].first;
  }
  return items.back().first;
}

}  // namespace agricola

#endif  // AGRICOLA_WITH_NN
