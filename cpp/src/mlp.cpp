// Hand-rolled native MLP forward (see mlp.hpp). Plain loops; no heavy deps.
//
// Numerical contract (the ≤1e-4 gate vs Python):
//   - linear:    y[o] = b[o] + sum_i W[o,i] * x[i]      (float accumulate)
//   - layernorm: mean/var over the feature dim, BIASED variance (divide by N,
//                not N-1 — matches torch.nn.LayerNorm), eps=1e-5 added INSIDE
//                the sqrt; then *gamma + beta.
//   - gelu:      exact erf form  0.5*x*(1+erf(x/sqrt(2)))  (torch default).
//   - input norm applied first: (x - input_mean) / input_std.
#include "agricola/mlp.hpp"

#include <cmath>
#include <fstream>
#include <stdexcept>

namespace agricola {

namespace {

inline float gelu_erf(float v) {
  // 0.5 * v * (1 + erf(v / sqrt(2))).  1/sqrt(2) = 0.70710678118654752440.
  return 0.5f * v *
         (1.0f + std::erf(v * 0.7071067811865475244f));
}

}  // namespace

Mlp::Mlp(const nlohmann::json& entry, const std::string& dir) {
  std::string base = dir;
  if (!base.empty() && base.back() != '/') base += '/';

  // --- read the raw float32 blob -------------------------------------------
  std::string file = entry.at("file").get<std::string>();
  std::string path = base + file;
  std::ifstream f(path, std::ios::binary | std::ios::ate);
  if (!f) throw std::runtime_error("Mlp: cannot open weight blob " + path);
  std::streamsize bytes = f.tellg();
  f.seekg(0, std::ios::beg);
  std::vector<float> blob(static_cast<size_t>(bytes) / sizeof(float));
  if (!f.read(reinterpret_cast<char*>(blob.data()), bytes))
    throw std::runtime_error("Mlp: short read on " + path);

  size_t pos = 0;
  auto take = [&](size_t n) -> const float* {
    if (pos + n > blob.size())
      throw std::runtime_error("Mlp: blob underrun reading " + path +
                               " (need more floats than present)");
    const float* p = blob.data() + pos;
    pos += n;
    return p;
  };

  // --- layers, in forward order --------------------------------------------
  input_dim_ = entry.at("input_dim").get<int>();
  int cur_dim = input_dim_;
  output_dim_ = input_dim_;
  for (const auto& lj : entry.at("layers")) {
    std::string kind = lj.at("kind").get<std::string>();
    Layer L;
    if (kind == "linear") {
      L.kind = LayerKind::kLinear;
      L.out = lj.at("out").get<int>();
      L.in = lj.at("in").get<int>();
      if (L.in != cur_dim)
        throw std::runtime_error("Mlp: linear in-dim mismatch in " + path);
      const float* w = take(static_cast<size_t>(L.out) * L.in);
      const float* b = take(static_cast<size_t>(L.out));
      L.w.assign(w, w + static_cast<size_t>(L.out) * L.in);
      L.b.assign(b, b + static_cast<size_t>(L.out));
      cur_dim = L.out;
      output_dim_ = L.out;
    } else if (kind == "layernorm") {
      L.kind = LayerKind::kLayerNorm;
      L.dim = lj.at("dim").get<int>();
      L.eps = lj.value("eps", 1e-5);
      if (L.dim != cur_dim)
        throw std::runtime_error("Mlp: layernorm dim mismatch in " + path);
      const float* g = take(static_cast<size_t>(L.dim));
      const float* be = take(static_cast<size_t>(L.dim));
      L.w.assign(g, g + L.dim);
      L.b.assign(be, be + L.dim);
    } else {
      throw std::runtime_error("Mlp: unknown layer kind '" + kind + "' in " +
                               path);
    }
    layers_.push_back(std::move(L));
  }

  // --- normalization tail: input_mean, input_std, (target_std) -------------
  int im_len = entry.at("input_mean_len").get<int>();
  int is_len = entry.at("input_std_len").get<int>();
  if (im_len != input_dim_ || is_len != input_dim_)
    throw std::runtime_error("Mlp: input_mean/std length != input_dim in " +
                             path);
  const float* im = take(static_cast<size_t>(im_len));
  input_mean_.assign(im, im + im_len);
  const float* is = take(static_cast<size_t>(is_len));
  input_std_.assign(is, is + is_len);

  if (entry.contains("target_std")) {
    int ts_len = entry.at("target_std").get<int>();
    const float* ts = take(static_cast<size_t>(ts_len));
    // Scalar buffer exported as length-1.
    target_std_ = ts_len > 0 ? ts[0] : 1.0f;
  }
}

void Mlp::forward(const float* x, std::vector<float>& out) const {
  // Input normalization into a working buffer.
  std::vector<float> cur(static_cast<size_t>(input_dim_));
  for (int i = 0; i < input_dim_; ++i)
    cur[i] = (x[i] - input_mean_[i]) / input_std_[i];

  std::vector<float> nxt;
  // The Python net is [Linear -> LayerNorm -> GELU -> Dropout] x N -> Linear.
  // The exported layer list contains only the parameterized layers (Linear,
  // LayerNorm) in order. Reconstruct the activation pattern: GELU is applied
  // after every LayerNorm (each hidden block ends LayerNorm; the final layer is
  // a bare Linear with no following LayerNorm, hence no GELU).
  for (const Layer& L : layers_) {
    if (L.kind == LayerKind::kLinear) {
      nxt.assign(static_cast<size_t>(L.out), 0.0f);
      for (int o = 0; o < L.out; ++o) {
        const float* wrow = L.w.data() + static_cast<size_t>(o) * L.in;
        float acc = L.b[o];
        for (int i = 0; i < L.in; ++i) acc += wrow[i] * cur[i];
        nxt[o] = acc;
      }
      cur.swap(nxt);
    } else {  // LayerNorm + GELU (post-norm hidden block activation)
      int d = L.dim;
      double mean = 0.0;
      for (int i = 0; i < d; ++i) mean += cur[i];
      mean /= d;
      double var = 0.0;
      for (int i = 0; i < d; ++i) {
        double dv = static_cast<double>(cur[i]) - mean;
        var += dv * dv;
      }
      var /= d;  // biased (population) variance — matches torch.nn.LayerNorm.
      float inv = static_cast<float>(1.0 / std::sqrt(var + L.eps));
      float m = static_cast<float>(mean);
      for (int i = 0; i < d; ++i) {
        float normed = (cur[i] - m) * inv * L.w[i] + L.b[i];
        cur[i] = gelu_erf(normed);
      }
    }
  }
  out = std::move(cur);
}

std::vector<float> Mlp::forward(const std::vector<float>& x) const {
  std::vector<float> out;
  forward(x.data(), out);
  return out;
}

}  // namespace agricola
