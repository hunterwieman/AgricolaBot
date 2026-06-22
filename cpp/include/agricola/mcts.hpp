// Native MCTS (PUCT + FLATTEN + chance nodes) — a faithful port of the
// production path in agricola/agents/mcts.py (CPP_ENGINE_PLAN.md §7). Skips the
// UCT-only MACRO-fencing machinery entirely (FLATTEN only).
//
// Needs the NN value+policy (NNInference), so the whole file is guarded behind
// AGRICOLA_WITH_NN and only compiled in a torch build.
#pragma once

#ifdef AGRICOLA_WITH_NN

#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <random>
#include <unordered_map>
#include <utility>
#include <vector>

#include "agricola/actions.hpp"
#include "agricola/hash.hpp"
#include "agricola/nn.hpp"
#include "agricola/types.hpp"

namespace agricola {

// ---------------------------------------------------------------------------
// Action hashing for the per-node maps.
//
// Python keys children dicts on Action (hashable frozen dataclass). C++ uses
// std::unordered_map<Action, ..., ActionHash> (Action has a defaulted
// operator==). ActionHash is a fast field-wise hash over the variant (index +
// active alternative's fields) — no serialization. (It replaced a
// std::map+ActionLess whose comparator was the MCTS profile's #1 main-thread
// cost.) Insertion order is NOT relied upon: selection re-derives order from the
// engine's legal_actions list each descent, and root_visit_distribution / chance
// routing depend on membership, not order.
// ---------------------------------------------------------------------------
struct ActionHash {
  std::size_t operator()(const Action& a) const;
};

// ---------------------------------------------------------------------------
// MCTSNode — one node in the search DAG.
// ---------------------------------------------------------------------------
struct MCTSNode {
  GameState state;
  int decider = 0;            // 0/1; 0 as a frame label for chance nodes
  bool is_chance = false;

  // action -> child. Owns nothing (the transposition table owns nodes).
  std::unordered_map<Action, MCTSNode*, ActionHash> children;
  std::vector<MCTSNode*> parents;  // DAG in-edges (maintained, not read at bp)

  long long visits = 0;
  double value_sum = 0.0;  // stored in THIS node's decider frame

  // chance-node round-robin counter (NOT child.visits — a shared DAG child
  // inflates visits and would skew routing).
  std::unordered_map<Action, long long, ActionHash> chance_counts;

  // Lazy per-node caches.
  bool legal_computed = false;
  std::vector<Action> legal;            // FLATTEN: the full legal set (or reveals)
  bool priors_computed = false;
  std::unordered_map<Action, double, ActionHash> priors;  // PUCT P(s,a)

  // Joint shared-trunk embedding (decider perspective), computed lazily and
  // reused by value (at leaf eval) and policy (at expansion) — one trunk forward
  // per node instead of two. Empty until first computed; unused in composite
  // (separate-net) mode and for terminal/chance nodes. ~512 B/node, freed with
  // the node when re_root prunes the table.
  std::vector<float> embedding;

  double mean_q() const { return visits > 0 ? value_sum / visits : 0.0; }
  bool is_terminal() const { return state.phase == Phase::BEFORE_SCORING; }
};

// ---------------------------------------------------------------------------
// MCTSSearch — the DAG + transposition table + search-level config.
// ---------------------------------------------------------------------------
// Which NN head supplies the backed-up leaf value (mirrors
// shared_policy.make_joint_fns' `leaf_mode`). All three read off ONE trunk
// forward (the per-node embedding cache), so margin and outcome together cost a
// single trunk pass.
//   MARGIN  — P0-frame margin (points), divided by the margin value_scale.
//   OUTCOME — P0-frame outcome (≈[-1,1]), divided by the outcome_scale.
//   MIX     — 0.5·(margin/margin_scale) + 0.5·(outcome/outcome_scale), used
//             DIRECTLY as the leaf Q (no further value_scale division; the two
//             terms are already normalized — effective leaf_value_scale 1.0).
enum class LeafMode { MARGIN, OUTCOME, MIX };

class MCTSSearch {
 public:
  // `nn` is borrowed (owned by the caller / a process-wide cache). leaf_value_scale
  // defaults to nn.value_scale().
  MCTSSearch(const NNInference* nn, double c_uct, std::uint64_t rng_seed,
             double fpu_offset = 0.0);

  // Look up or create the node for `state`; link parent->child if given.
  MCTSNode* find_or_create_node(const GameState& state,
                                MCTSNode* parent = nullptr,
                                const Action* action_from_parent = nullptr);

  void add_edge(MCTSNode* parent, MCTSNode* child, const Action& action);

  // Designate `new_root` as the root and prune the table to its live subtree.
  void re_root(MCTSNode* new_root);

  // Leaf value in P0's frame, divided by leaf_value_scale (terminal -> exact
  // margin; mid-game -> NN value(state)). Mirrors MCTSSearch.evaluate_leaf.
  // Takes the node so the value forward can populate/reuse node->embedding (the
  // per-node trunk cache shared with policy at the node's later expansion).
  double evaluate_leaf(MCTSNode* node) const;

  // Lazy caches.
  void ensure_legal(MCTSNode* node);
  void ensure_priors(MCTSNode* node);

  const NNInference* nn() const { return nn_; }
  double c_uct() const { return c_uct_; }
  double fpu_offset() const { return fpu_offset_; }
  // Blend the policy prior with a uniform distribution over the legal set:
  //   prior' = (1 - mix)*policy + mix*(1/k).
  // 0 (default) = pure policy net. A small mix forces the search to explore
  // moves the policy assigns near-zero prior (root + every node).
  void set_prior_uniform_mix(double mix) { prior_uniform_mix_ = mix; }
  // Select the leaf-value head (default MARGIN = backward-compatible). OUTCOME
  // and MIX require the NN to carry an outcome head (NNInference::has_outcome);
  // the scales are sourced from nn->value_scale() / nn->outcome_scale() by
  // default and can be overridden for MIX (the common-state scales).
  void set_leaf_mode(LeafMode mode) { leaf_mode_ = mode; }
  void set_margin_scale(double s) { margin_scale_ = (s == 0.0 ? 1.0 : s); }
  void set_outcome_scale(double s) { outcome_scale_ = (s == 0.0 ? 1.0 : s); }
  std::mt19937_64& rng() { return rng_; }
  MCTSNode* root() const { return root_; }

 private:
  const NNInference* nn_;
  double c_uct_;
  double fpu_offset_;
  double leaf_value_scale_;
  // Leaf-mode + the per-head normalizers. MARGIN uses leaf_value_scale_ as today
  // (and margin_scale_ tracks it for MIX); OUTCOME/MIX use outcome_scale_.
  LeafMode leaf_mode_ = LeafMode::MARGIN;
  double margin_scale_ = 1.0;
  double outcome_scale_ = 1.0;
  double prior_uniform_mix_ = 0.0;
  std::mt19937_64 rng_;
  MCTSNode* root_ = nullptr;

  // Transposition table: owns the nodes (unique_ptr values), keyed on GameState
  // via the Stage-1 state_hash + structural operator==.
  struct StateHash {
    std::size_t operator()(const GameState& s) const {
      return static_cast<std::size_t>(state_hash(s));
    }
  };
  std::unordered_map<GameState, std::unique_ptr<MCTSNode>, StateHash>
      transpositions_;
};

// ---------------------------------------------------------------------------
// MCTSAgent — the per-move loop (PUCT, FLATTEN, temperature play).
// ---------------------------------------------------------------------------
class MCTSAgent {
 public:
  MCTSAgent(MCTSSearch* search, int sims_per_move, double c_uct,
            double fpu_offset, double action_selection_temperature,
            std::uint64_t rng_seed, bool cap_total_sims = true);

  // Run the search at `state` and return the played action. Re-roots to `state`,
  // runs sims to the cap, then samples from the root visit distribution at the
  // configured temperature. After the call, last_root() / root_visit_distribution
  // / root_value_p0 describe the search just performed.
  Action choose(const GameState& state);

  // The root of the most recent search (set by choose()).
  MCTSNode* last_root() const { return last_root_; }

  // Played-move selection mode. Default (false) ranks root children by VISIT
  // count (AlphaZero standard). When true, ranks by sign-corrected mean-Q in
  // the root player's frame instead — argmax at T<=0, softmax(exp(Q/T)) at T>0,
  // over VISITED children only (an unvisited child has no Q estimate). The π /
  // root_value recorded for training are unaffected; only the played move changes.
  void set_select_by_q(bool v) { select_by_q_ = v; }

  // π — the root's raw per-action visit counts {action: child.visits}.
  std::vector<std::pair<Action, long long>> root_visit_distribution(
      MCTSNode* root) const;

  // root_value in P0's frame: q if root.decider==0 else -q (mean-Q flipped).
  double root_value_p0(MCTSNode* root) const;

 private:
  void simulate(MCTSNode* root);

  // Selection. Returns (child, is_new).
  std::pair<MCTSNode*, bool> puct_select_child(MCTSNode* node);
  Action select_via_puct(MCTSNode* parent);
  Action chance_route(MCTSNode* node);
  Action select_action_with_temperature(MCTSNode* root);  // dispatcher
  Action select_action_by_visits(MCTSNode* root);  // visit-count (default)
  Action select_action_by_q(MCTSNode* root);  // Q-ranked alternative

  MCTSSearch* search_;
  int sims_per_move_;
  double c_uct_;
  double fpu_offset_;
  double temperature_;
  bool cap_total_sims_;
  bool select_by_q_ = false;  // false = visit-count selection (default)
  std::mt19937_64 rng_;  // agent RNG — played-move sampling only
  MCTSNode* last_root_ = nullptr;
};

}  // namespace agricola

#endif  // AGRICOLA_WITH_NN
