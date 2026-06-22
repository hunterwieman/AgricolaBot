// Native NN inference (CPP_ENGINE_PLAN.md §6) — value net + 9 policy heads +
// the make_policy_fn combiner. Forwards are computed by a hand-rolled native
// MLP (agricola/mlp.hpp) over raw float32 weights exported by
// scripts/nn/export_weights.py — no libtorch / TorchScript. The encoder is pure
// and lives in encoder.hpp.
#pragma once

#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "agricola/actions.hpp"
#include "agricola/types.hpp"

namespace agricola {

// Loads the raw-weight blobs (value + 9 heads) + weights_manifest.json from
// `model_dir` (scripts/nn/export_weights.py). Hard-checks manifest
// encoding_version against kEncodingVersion.
class NNInference {
 public:
  explicit NNInference(const std::string& model_dir);
  ~NNInference();

  // value(state) = predict_margin from perspective 0 (== nn_evaluator(state, 0,
  // model)): a terminal state returns the exact margin score(0)-score(1); a
  // mid-game state returns the value net's margin estimate.
  double value(const GameState& state) const;

  // policy(state) = make_policy_fn's {action: prior} over the FULL legal set,
  // dispatching by decision type (fixed head / pointer head / build_stop /
  // cell-priority uniform / full-legal uniform). Omitted legal actions = 0.
  std::vector<std::pair<Action, double>> policy(const GameState& state) const;

  // Cache-aware overloads (joint shared-trunk mode only). `emb` is a caller-owned
  // embedding buffer, typically MCTSNode::embedding: empty on input → the trunk
  // forward is computed and STORED in `emb`; non-empty → reused (no trunk
  // forward). value() at a leaf and policy() at that node's later expansion both
  // need the SAME decider-perspective embedding, so threading one buffer through
  // collapses the two trunk forwards per node to one. In composite (separate-net)
  // mode there is no shared embedding, so `emb` is left untouched and these
  // behave exactly like the no-arg forms. Identical NN outputs either way.
  double value(const GameState& state, std::vector<float>& emb) const;
  std::vector<std::pair<Action, double>> policy(const GameState& state,
                                                std::vector<float>& emb) const;

  // The value net's `value_scale` (manifest "value"/"value_scale"; ≈11.526).
  // MCTS divides each leaf value by this (leaf_value_scale = model.value_scale)
  // so a single c_uct is comparable across value heads of different magnitude.
  double value_scale() const;

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;

  // Shared body of both policy() overloads; `emb` threads the per-node embedding
  // cache through the head dispatch (nullptr = internal single-entry cache).
  std::vector<std::pair<Action, double>> policy_impl(
      const GameState& state, std::vector<float>* emb) const;
};

}  // namespace agricola
