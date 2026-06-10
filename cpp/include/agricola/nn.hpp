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

  // The value net's `value_scale` (manifest "value"/"value_scale"; ≈11.526).
  // MCTS divides each leaf value by this (leaf_value_scale = model.value_scale)
  // so a single c_uct is comparable across value heads of different magnitude.
  double value_scale() const;

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace agricola
