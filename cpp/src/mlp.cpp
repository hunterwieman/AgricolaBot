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

#if defined(__ARM_NEON)
#include <arm_neon.h>
#endif

namespace agricola {

namespace {

inline float gelu_erf(float v) {
  // 0.5 * v * (1 + erf(v / sqrt(2))).  1/sqrt(2) = 0.70710678118654752440.
  return 0.5f * v *
         (1.0f + std::erf(v * 0.7071067811865475244f));
}

// torch.nn.LeakyReLU(negative_slope=0.01) — the default slope.
inline float leaky_relu(float v) { return v >= 0.0f ? v : 0.01f * v; }

// Dot product a·b over n floats. The linear-layer inner loop (the trunk's three
// matmuls) is ~71% of MCTS wall, so it is hand-vectorized: 4 NEON accumulators
// (16 floats/iter) + horizontal add, scalar tail. The lane-parallel reduction
// reorders the float sum vs the scalar left-to-right accumulate, so it is NOT
// bit-identical to the old code — but the differential gate vs Python is ≤1e-4,
// and torch's own CPU reduction order already differs, so both stay well inside
// it (verified: see test_cpp_nn.py). Plain build (no -ffast-math) — the explicit
// intrinsics vectorize what the compiler can't reassociate on its own.
inline float dot(const float* a, const float* b, int n) {
#if defined(__ARM_NEON)
  float32x4_t s0 = vdupq_n_f32(0.0f), s1 = vdupq_n_f32(0.0f),
              s2 = vdupq_n_f32(0.0f), s3 = vdupq_n_f32(0.0f);
  int i = 0;
  for (; i + 16 <= n; i += 16) {
    s0 = vmlaq_f32(s0, vld1q_f32(a + i), vld1q_f32(b + i));
    s1 = vmlaq_f32(s1, vld1q_f32(a + i + 4), vld1q_f32(b + i + 4));
    s2 = vmlaq_f32(s2, vld1q_f32(a + i + 8), vld1q_f32(b + i + 8));
    s3 = vmlaq_f32(s3, vld1q_f32(a + i + 12), vld1q_f32(b + i + 12));
  }
  for (; i + 4 <= n; i += 4)
    s0 = vmlaq_f32(s0, vld1q_f32(a + i), vld1q_f32(b + i));
  float acc = vaddvq_f32(vaddq_f32(vaddq_f32(s0, s1), vaddq_f32(s2, s3)));
  for (; i < n; ++i) acc += a[i] * b[i];
  return acc;
#else
  float acc = 0.0f;
  for (int i = 0; i < n; ++i) acc += a[i] * b[i];
  return acc;
#endif
}

}  // namespace

Mlp::Mlp(const nlohmann::json& entry, const std::string& dir, Activation act)
    : act_(act) {
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
  // Reusable activation scratch. thread_local so a shared const Mlp stays safe
  // under concurrent callers, while a single thread reuses the buffers across
  // calls — the per-forward malloc/free of `cur`/`nxt` (thousands of forwards per
  // move) is paid once instead of every call. Sized up on demand; never shrunk.
  thread_local std::vector<float> cur, nxt;
  cur.resize(static_cast<size_t>(input_dim_));
  // Input normalization into the working buffer.
  for (int i = 0; i < input_dim_; ++i)
    cur[i] = (x[i] - input_mean_[i]) / input_std_[i];

  // The Python net is [Linear -> LayerNorm -> ACT -> Dropout] x N -> Linear,
  // where ACT is the model-global activation (gelu or leaky_relu, selected by
  // act_ from the manifest's top-level "activation"). The exported layer list
  // contains only the parameterized layers (Linear, LayerNorm) in order.
  // Reconstruct the activation pattern: ACT is applied after every LayerNorm
  // (each hidden block ends LayerNorm; the final layer is a bare Linear with no
  // following LayerNorm, hence no activation).
  for (const Layer& L : layers_) {
    if (L.kind == LayerKind::kLinear) {
      nxt.resize(static_cast<size_t>(L.out));  // every entry overwritten below
      const float* xx = cur.data();
      const int in = L.in;
      for (int o = 0; o < L.out; ++o) {
        const float* wrow = L.w.data() + static_cast<size_t>(o) * in;
        nxt[o] = L.b[o] + dot(wrow, xx, in);
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
        cur[i] = act_ == Activation::kLeakyRelu ? leaky_relu(normed)
                                                : gelu_erf(normed);
      }
    }
  }
  out.assign(cur.begin(), cur.end());  // copy out; keep the thread_local capacity
}

std::vector<float> Mlp::forward(const std::vector<float>& x) const {
  std::vector<float> out;
  forward(x.data(), out);
  return out;
}

}  // namespace agricola
