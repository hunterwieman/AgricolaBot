// Hand-rolled native MLP forward — the libtorch-free replacement for the
// TorchScript inference backend (CPP_ENGINE_PLAN.md §6). Reproduces a Python
// ConfigurableMLP wrapped in a Normalized{Value,Policy,Pointer}Model:
//
//   x_norm = (x - input_mean) / input_std
//   hidden block (xN): x = gelu(layernorm(linear(x)))     # post-norm
//   final:             y = linear(x)                       # raw, no activation
//
// plus the model-wrapper denormalization (value: y *= target_std). GELU is the
// EXACT erf form (std::erf), LayerNorm uses biased (population) variance with
// eps=1e-5 — both matched to PyTorch defaults. Weights are loaded from the raw
// float32 blob + manifest written by scripts/nn/export_weights.py.
#pragma once

#include <string>
#include <vector>

#include "nlohmann/json.hpp"

namespace agricola {

// The model-global hidden-block activation. The exported manifest's top-level
// "activation" string selects which one (default "gelu" for backward compat);
// it is applied identically after every hidden LayerNorm in forward().
enum class Activation { kGelu, kLeakyRelu };

// One model's forward pass over exported weights. Construct from a manifest
// entry (the per-model JSON object) + the export directory holding its .bin.
class Mlp {
 public:
  Mlp() = default;
  // `entry` is the per-model manifest object (with "file", "layers",
  // "input_mean_len", "input_std_len", optional "target_std"); `dir` is the
  // directory containing the .bin (trailing slash optional). `act` is the
  // model-global hidden activation (default kGelu preserves all existing
  // callers / the pre-leaky-ReLU manifest format).
  Mlp(const nlohmann::json& entry, const std::string& dir,
      Activation act = Activation::kGelu);

  // Forward over a single input row of length input_dim(). Returns the raw
  // network output (length = final Linear out dim), AFTER input normalization
  // and BEFORE any wrapper denormalization (apply target_std() yourself for the
  // value net). `out` is resized to the output dim.
  void forward(const float* x, std::vector<float>& out) const;

  // Convenience: forward over a std::vector input.
  std::vector<float> forward(const std::vector<float>& x) const;

  int input_dim() const { return input_dim_; }
  int output_dim() const { return output_dim_; }
  // Value net only: the target_std denormalization factor (1.0 if absent).
  float target_std() const { return target_std_; }

 private:
  enum class LayerKind { kLinear, kLayerNorm };
  struct Layer {
    LayerKind kind;
    int out = 0;   // linear: out dim
    int in = 0;    // linear: in dim
    int dim = 0;   // layernorm: feature dim
    float eps = 1e-5f;
    // linear: W is row-major [out, in], b is [out].
    // layernorm: gamma + beta are [dim].
    std::vector<float> w;       // linear weights / layernorm gamma
    std::vector<float> b;       // linear bias    / layernorm beta
  };

  std::vector<Layer> layers_;
  std::vector<float> input_mean_;
  std::vector<float> input_std_;
  float target_std_ = 1.0f;
  int input_dim_ = 0;
  int output_dim_ = 0;
  Activation act_ = Activation::kGelu;
};

}  // namespace agricola
