// Native NN inference — value net + 9 policy heads + the make_policy_fn combiner
// (CPP_ENGINE_PLAN.md §6). A faithful port of:
//   agents/nn/agent.nn_evaluator (value: terminal margin / predict_margin)
//   agents/nn/policy.make_policy_fn (the 5-branch combiner)
//   agents/nn/policy_heads (the 7 fixed + 2 pointer heads)
//   agents/restricted cell-priority constants + _filter_cell_priority
//
// Forward passes are computed by a hand-rolled native MLP (agricola/mlp.hpp) over
// raw float32 weights exported by scripts/nn/export_weights.py — NO libtorch, no
// TorchScript dispatcher overhead. Each model's forward emits raw logits (fixed)
// / raw per-candidate scores (pointer) / margin (value); masking, softmax, and
// the value short-circuit happen here, exactly as before.
#include "agricola/nn.hpp"

#include "agricola/mlp.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <variant>
#include <vector>

#include "nlohmann/json.hpp"
#include "agricola/constants.hpp"
#include "agricola/encoder.hpp"
#include "agricola/fences.hpp"
#include "agricola/hash.hpp"
#include "agricola/helpers.hpp"
#include "agricola/legality.hpp"
#include "agricola/scoring.hpp"

namespace agricola {

namespace {

using json = nlohmann::json;

// --- cell-priority constants (agents/restricted.py) -------------------------
const std::vector<Coord> kStablePriority = {{0, 4}, {0, 3}, {1, 4}, {1, 3}};
const std::vector<Coord> kRoomPriority = {{0, 0}, {2, 1}, {1, 1}, {2, 2}};
const std::vector<Coord> kPlowPriority = {
    {0, 1}, {0, 2}, {1, 1}, {0, 0}, {1, 2}, {2, 2}, {2, 3}};

// Masked softmax over a logit vector with a parallel legality mask. Mirrors
// NormalizedPolicyModel.policy_probs: illegal -> -inf; an all-illegal row is
// treated as all-legal (NaN guard). Returns probabilities over all classes.
std::vector<double> masked_softmax(const std::vector<float>& logits,
                                   const std::vector<bool>& legal) {
  int n = static_cast<int>(logits.size());
  bool any = false;
  for (bool b : legal)
    if (b) any = true;
  std::vector<double> eff(n);
  double mx = -1e300;
  for (int i = 0; i < n; ++i) {
    bool ok = any ? legal[i] : true;
    eff[i] = ok ? static_cast<double>(logits[i]) : -1e300;
    if (ok && eff[i] > mx) mx = eff[i];
  }
  double sum = 0.0;
  std::vector<double> probs(n, 0.0);
  for (int i = 0; i < n; ++i) {
    bool ok = any ? legal[i] : true;
    if (!ok) {
      probs[i] = 0.0;
      continue;
    }
    double e = std::exp(eff[i] - mx);
    probs[i] = e;
    sum += e;
  }
  if (sum > 0)
    for (int i = 0; i < n; ++i) probs[i] /= sum;
  return probs;
}

// Plain softmax over per-candidate scores (pointer heads).
std::vector<double> softmax(const std::vector<double>& scores) {
  std::vector<double> out(scores.size(), 0.0);
  if (scores.empty()) return out;
  double mx = scores[0];
  for (double s : scores) mx = std::max(mx, s);
  double sum = 0.0;
  for (size_t i = 0; i < scores.size(); ++i) {
    out[i] = std::exp(scores[i] - mx);
    sum += out[i];
  }
  if (sum > 0)
    for (auto& v : out) v /= sum;
  return out;
}

// --- decision-type ownership (mirrors policy_heads.py *_owns) ----------------
const PendingDecision* top_frame(const GameState& s) {
  return s.pending_stack.empty() ? nullptr : &s.pending_stack.back();
}

template <typename T>
bool top_is(const GameState& s) {
  const auto* t = top_frame(s);
  return t && std::holds_alternative<T>(*t);
}

bool placement_owns(const GameState& s) {
  return s.phase != Phase::BEFORE_SCORING && s.pending_stack.empty() &&
         encoder_decider_of(s).has_value();
}
bool subaction_owns(const GameState& s) {
  return top_is<PendingGrainUtilization>(s) || top_is<PendingCultivation>(s) ||
         top_is<PendingSideJob>(s) || top_is<PendingFarmExpansion>(s) ||
         top_is<PendingHouseRedevelopment>(s) ||
         top_is<PendingFarmRedevelopment>(s);
}
bool major_owns(const GameState& s) { return top_is<PendingBuildMajor>(s); }
bool sow_owns(const GameState& s) { return top_is<PendingSow>(s); }
bool bake_owns(const GameState& s) { return top_is<PendingBakeBread>(s); }
bool fencing_owns(const GameState& s) { return top_is<PendingBuildFences>(s); }
bool build_stop_owns(const GameState& s) {
  const auto* t = top_frame(s);
  if (!t) return false;
  if (std::holds_alternative<PendingBuildRooms>(*t))
    return std::get<PendingBuildRooms>(*t).num_built >= 1;
  if (std::holds_alternative<PendingBuildStables>(*t))
    return std::get<PendingBuildStables>(*t).num_built >= 1;
  return false;
}
bool animal_owns(const GameState& s) {
  if (s.phase == Phase::BEFORE_SCORING || s.pending_stack.empty()) return false;
  if (!encoder_decider_of(s).has_value()) return false;
  const auto* t = top_frame(s);
  if (std::holds_alternative<PendingHarvestBreed>(*t))
    return !std::get<PendingHarvestBreed>(*t).breed_chosen;
  return std::holds_alternative<PendingSheepMarket>(*t) ||
         std::holds_alternative<PendingPigMarket>(*t) ||
         std::holds_alternative<PendingCattleMarket>(*t);
}
bool harvest_feed_owns(const GameState& s) {
  if (s.phase == Phase::BEFORE_SCORING || s.pending_stack.empty()) return false;
  if (!encoder_decider_of(s).has_value()) return false;
  const auto* t = top_frame(s);
  return std::holds_alternative<PendingHarvestFeed>(*t) &&
         !std::get<PendingHarvestFeed>(*t).conversion_done;
}

// --- fixed-head vocab + per-action label/class-index -------------------------
// Each head maps a class index <-> a label string; an action's class index is
// found via its label. We build the label->index maps once (static).

// choose_subaction vocab (policy_heads.CHOOSE_SUBACTION_VOCAB).
const std::vector<std::string> kSubactionVocab = {
    "sow",          "bake_bread",   "build_stables", "build_rooms",
    "plow",         "build_fences", "improvement",   "__stop__"};

// commit_build_major vocab (_build_major_vocab): m0..m9, with m2/m3 also having
// m{mi}_rf{fp} for fp in {0,1} right after.
std::vector<std::string> build_major_vocab() {
  std::vector<std::string> v;
  for (int mi = 0; mi < NUM_MAJOR_IMPROVEMENTS; ++mi) {
    v.push_back("m" + std::to_string(mi));
    if (mi == 2 || mi == 3) {  // COOKING_HEARTH_INDICES
      v.push_back("m" + std::to_string(mi) + "_rf0");
      v.push_back("m" + std::to_string(mi) + "_rf1");
    }
  }
  return v;
}

// commit_sow vocab: g{g}v{s-g} for s in 1..13, g in 0..s.
std::vector<std::string> sow_vocab() {
  std::vector<std::string> v;
  for (int s = 1; s <= 13; ++s)
    for (int g = 0; g <= s; ++g)
      v.push_back("g" + std::to_string(g) + "v" + std::to_string(s - g));
  return v;
}

// commit_bake vocab: n1..n6.
std::vector<std::string> bake_vocab() {
  std::vector<std::string> v;
  for (int n = 1; n <= 6; ++n) v.push_back("n" + std::to_string(n));
  return v;
}

template <typename T>
const T* as(const Action& a) {
  return std::holds_alternative<T>(a) ? &std::get<T>(a) : nullptr;
}

// Label of an action under a given head, or "" if not this head's class.
std::string label_placement(const Action& a) {
  if (auto* p = as<PlaceWorker>(a)) return p->space;
  return "";
}
std::string label_subaction(const Action& a) {
  if (auto* c = as<ChooseSubAction>(a)) {
    if (c->name == "build_stable") return "build_stables";  // _SUBACTION_ALIAS
    return c->name;
  }
  // Proceed-as-Stop alias (SPACE_HOST_REFACTOR.md §9): the Proceed-host parents
  // end their before-phase with Proceed (after-phase with Stop). Both map to the
  // head's __stop__ slot — never co-legal, so the alias is unambiguous and keeps
  // the C++ policy prior identical to Python's.
  if (as<Stop>(a) || as<Proceed>(a)) return "__stop__";
  return "";
}
std::string label_major(const Action& a) {
  auto* m = as<CommitBuildMajor>(a);
  if (!m) return "";
  if (!m->return_fireplace_idx.has_value())
    return "m" + std::to_string(m->major_idx);
  return "m" + std::to_string(m->major_idx) + "_rf" +
         std::to_string(*m->return_fireplace_idx);
}
std::string label_sow(const Action& a) {
  auto* s = as<CommitSow>(a);
  if (!s) return "";
  int sum = s->grain + s->veg;
  if (sum < 1 || sum > 13) return "";
  return "g" + std::to_string(s->grain) + "v" + std::to_string(s->veg);
}
std::string label_bake(const Action& a) {
  auto* b = as<CommitBake>(a);
  if (!b) return "";
  if (b->grain < 1 || b->grain > 6) return "";
  return "n" + std::to_string(b->grain);
}

// --- the loaded model bundle -------------------------------------------------
struct LoadedHead {
  Mlp mlp;
  int num_classes = 0;
  // label -> class index (for fixed heads); empty for pointer heads.
  std::unordered_map<std::string, int> label_to_idx;
  std::vector<std::string> vocab;
};

}  // namespace

struct NNInference::Impl {
  // ---- composite (separate value net + per-head MLPs) ----
  Mlp value_mlp;
  double value_scale = 1.0;
  std::string value_target = "margin";  // "margin" (points) or "outcome" (sign)
  // Outcome head (joint shared-trunk only): reads the SAME decider embedding as
  // value_mlp, emits sign(margin) ∈ {-1,0,+1} in win/draw/loss space (no
  // target_std, no begging add-back). `has_outcome` is false unless the manifest
  // carried a non-null "outcome" entry.
  bool has_outcome = false;
  Mlp outcome_mlp;
  double outcome_scale = 1.0;
  // Model-global hidden activation (manifest "activation"; default gelu). Every
  // Mlp in the bundle (trunk + value + outcome + all heads) shares it.
  Activation act = Activation::kGelu;
  std::unordered_map<std::string, LoadedHead> fixed;   // head name -> head
  std::unordered_map<std::string, LoadedHead> pointer;  // animal_frontier/harvest_feed
  int harvest_feed_dim = 10;
  int animal_dim = 4;

  // ---- joint (one shared trunk feeds value + every head) ----
  // The two modes share the manifest loader, the Mlp primitive, the head maps,
  // and the entire policy dispatch (policy() below) — ONLY the forward differs.
  // In joint mode the trunk runs once per node and the embedding is cached, so
  // value() and policy() for the same leaf share one forward (CPP_ENGINE_PLAN /
  // shared_policy.py). `value_mlp`/`fixed`/`pointer` then take the EMBEDDING
  // (identity input-norm; pointer heads norm only the candidate slice).
  bool joint = false;
  // The encoder this model was trained with, resolved from the manifest's
  // encoder_tag via the registry (forward-compatible: no per-model branches).
  const EncoderSpec* enc_spec = nullptr;
  mutable std::vector<float> enc_buf_;  // reusable raw-encoding scratch
  Mlp trunk_mlp;
  std::vector<float> embed_gamma, embed_beta;  // standalone embed_norm (empty=none)
  float embed_eps = 1e-5f;

  // ---- siamese front end (SiameseSharedTrunkModel) ----
  // When `siamese`, the trunk does NOT take the raw encoding. Instead the full
  // (already encoder-produced) input is normalized once here via siam_in_mean/std
  // (the real 170-dim norm), sliced into own(P) | opp(P) | rest, own and opp are
  // each run through the SAME player_encoder (shared weights, identity input-norm),
  // and [emb_own ; emb_opp ; rest] is fed to the trunk (whose own input-norm is
  // identity). Mirrors shared_model.SiameseSharedTrunkModel.embed exactly.
  bool siamese = false;
  Mlp player_encoder;                       // P -> player_encoder_out (identity norm)
  int player_block = 0;                     // P
  int player_encoder_out = 0;
  std::vector<float> siam_in_mean, siam_in_std;  // full-input norm (length = enc dim)

  // Single-entry embedding cache keyed by state_hash. value() then policy() are
  // called consecutively for a leaf, so this captures the one-forward win; a
  // miss just recomputes (correct).
  mutable std::uint64_t emb_hash_ = 0;
  mutable bool emb_valid_ = false;
  mutable std::vector<float> emb_buf_;

  // Compute trunk(encode(s, decider)) + standalone embed_norm into `dst`. The
  // DECIDER-perspective embedding is shared by value (sign-flipped to P0) and
  // every policy head.
  void compute_embed(const GameState& s, std::vector<float>& dst) const {
    enc_spec->encode_into(s, *encoder_decider_of(s), enc_buf_);
    if (siamese) {
      // Normalize the FULL input once (the real 170-dim norm), then slice
      // own(P) | opp(P) | rest, run own/opp through the SHARED player_encoder
      // (identity input-norm), and feed [emb_own ; emb_opp ; rest] to the trunk
      // (identity input-norm). Matches SiameseSharedTrunkModel.embed.
      const int D = static_cast<int>(enc_buf_.size());
      const int P = player_block;
      std::vector<float> normed(D);
      for (int i = 0; i < D; ++i)
        normed[i] = (enc_buf_[i] - siam_in_mean[i]) / siam_in_std[i];
      std::vector<float> emb_own, emb_opp;
      player_encoder.forward(normed.data(), emb_own);            // own = normed[0:P]
      player_encoder.forward(normed.data() + P, emb_opp);        // opp = normed[P:2P]
      const int rest = D - 2 * P;
      std::vector<float> fused(static_cast<size_t>(2) * player_encoder_out + rest);
      std::copy(emb_own.begin(), emb_own.end(), fused.begin());
      std::copy(emb_opp.begin(), emb_opp.end(),
                fused.begin() + player_encoder_out);
      std::copy(normed.begin() + 2 * P, normed.end(),
                fused.begin() + 2 * player_encoder_out);        // rest (norm-invariant)
      trunk_mlp.forward(fused.data(), dst);  // raw embedding (pre embed_norm)
    } else {
      trunk_mlp.forward(enc_buf_.data(), dst);  // raw embedding (pre embed_norm)
    }
    if (!embed_gamma.empty()) {               // apply standalone embed_norm (no GELU)
      int d = static_cast<int>(dst.size());
      double mean = 0.0;
      for (float v : dst) mean += v;
      mean /= d;
      double var = 0.0;
      for (float v : dst) {
        double dd = v - mean;
        var += dd * dd;
      }
      var /= d;  // biased (population) variance — matches torch.nn.LayerNorm
      double inv = 1.0 / std::sqrt(var + static_cast<double>(embed_eps));
      for (int i = 0; i < d; ++i)
        dst[i] = static_cast<float>((dst[i] - mean) * inv) * embed_gamma[i] +
                 embed_beta[i];
    }
  }

  // The decider-perspective embedding, cached. With `ext` (a caller-owned buffer,
  // e.g. MCTSNode::embedding): empty → compute & store there; non-empty → reuse
  // (no forward). This is the per-node cache that collapses the value + policy
  // trunk forwards for a node into one. Without `ext`, falls back to the internal
  // single-entry state_hash cache (the no-node callers / pointer candidate loop).
  const std::vector<float>& trunk_embed(const GameState& s,
                                        std::vector<float>* ext = nullptr) const {
    if (ext) {
      if (!ext->empty()) return *ext;  // per-node cache hit — no trunk forward
      compute_embed(s, *ext);
      return *ext;
    }
    std::uint64_t h = state_hash(s);
    if (emb_valid_ && emb_hash_ == h) return emb_buf_;
    compute_embed(s, emb_buf_);
    emb_hash_ = h;
    emb_valid_ = true;
    return emb_buf_;
  }

  // ---- value ---- (P0-frame margin; terminal short-circuit is exact)
  double value(const GameState& s, std::vector<float>* ext = nullptr) const {
    if (s.phase == Phase::BEFORE_SCORING)
      return static_cast<double>(score(s, 0) - score(s, 1));
    std::vector<float> out;
    if (joint) {
      int d = *encoder_decider_of(s);
      value_mlp.forward(trunk_embed(s, ext).data(), out);   // head on the embedding
      double v = static_cast<double>(out[0]) *
                 static_cast<double>(value_mlp.target_std());
      v = d == 0 ? v : -v;                             // decider-frame -> P0
      if (enc_spec->strip_begging) v += begging_margin(s, 0);  // add begging back
      return v;
    }
    enc_spec->encode_into(s, 0, enc_buf_);
    value_mlp.forward(enc_buf_.data(), out);
    return static_cast<double>(out[0]) *
           static_cast<double>(value_mlp.target_std());
  }

  // ---- outcome ---- (P0-frame outcome ≈[-1,1]; terminal short-circuit exact)
  // Joint mode only (the outcome head reads the shared embedding). Mirrors
  // shared_policy.value_fn's outcome branch: no target_std, no begging add-back.
  double outcome(const GameState& s, std::vector<float>* ext = nullptr) const {
    if (s.phase == Phase::BEFORE_SCORING) {
      double m = static_cast<double>(score(s, 0) - score(s, 1));
      return m > 0 ? 1.0 : (m < 0 ? -1.0 : 0.0);  // true terminal outcome
    }
    int d = *encoder_decider_of(s);
    std::vector<float> out;
    outcome_mlp.forward(trunk_embed(s, ext).data(), out);  // head on the embedding
    double v = static_cast<double>(out[0]);
    return d == 0 ? v : -v;                                 // decider-frame -> P0
  }

  // ---- fixed head logits ----
  std::vector<float> fixed_logits(const LoadedHead& h, const GameState& s,
                                  std::vector<float>* ext = nullptr) const {
    std::vector<float> out;
    if (joint) {
      h.mlp.forward(trunk_embed(s, ext).data(), out);
      return out;
    }
    enc_spec->encode_into(s, *encoder_decider_of(s), enc_buf_);
    h.mlp.forward(enc_buf_.data(), out);  // raw logits, length == num_classes
    return out;
  }

  // ---- pointer head per-candidate scores ----
  // composite: rows are [state(170) ; candidate(D)]. joint: [embedding(E) ;
  // candidate(D)] off the cached trunk embedding.
  std::vector<double> pointer_scores(
      const LoadedHead& h, const GameState& s,
      const std::vector<std::vector<float>>& cand_feats, int cdim,
      std::vector<float>* ext = nullptr) const {
    int k = static_cast<int>(cand_feats.size());
    if (k == 0) return {};
    std::vector<double> scores(k);
    std::vector<float> out;
    if (joint) {
      const std::vector<float>& e = trunk_embed(s, ext);
      std::vector<float> row(e.size() + static_cast<size_t>(cdim));
      std::copy(e.begin(), e.end(), row.begin());
      for (int i = 0; i < k; ++i) {
        std::copy(cand_feats[i].begin(), cand_feats[i].end(),
                  row.begin() + e.size());
        h.mlp.forward(row.data(), out);
        scores[i] = static_cast<double>(out[0]);
      }
      return scores;
    }
    enc_spec->encode_into(s, *encoder_decider_of(s), enc_buf_);
    const int edim = enc_spec->dim;
    std::vector<float> row(static_cast<size_t>(edim) + cdim);
    std::copy(enc_buf_.begin(), enc_buf_.end(), row.begin());
    for (int i = 0; i < k; ++i) {
      std::copy(cand_feats[i].begin(), cand_feats[i].end(),
                row.begin() + edim);
      h.mlp.forward(row.data(), out);  // scalar score (output_dim == 1)
      scores[i] = static_cast<double>(out[0]);
    }
    return scores;
  }
};

// ---------------------------------------------------------------------------
// Loading
// ---------------------------------------------------------------------------

NNInference::NNInference(const std::string& model_dir) : impl_(new Impl()) {
  std::string base = model_dir;
  if (!base.empty() && base.back() != '/') base += '/';

  // weights_manifest.json (raw-f32 export); the legacy .ts manifest.json is no
  // longer read (the hand-rolled MLP replaces TorchScript).
  std::ifstream mf(base + "weights_manifest.json");
  if (!mf) throw std::runtime_error("NNInference: cannot open " + base +
                                    "weights_manifest.json "
                                    "(run scripts/nn/export_weights.py)");
  nlohmann::json manifest;
  mf >> manifest;
  int enc_ver = manifest.value("encoding_version", -1);
  if (enc_ver != 2)
    throw std::runtime_error(
        "NNInference: manifest encoding_version=" + std::to_string(enc_ver) +
        " != 2 (kEncodingVersion)");

  // Joint (shared-trunk) export: load the trunk + standalone embed_norm. The
  // value/head blobs below then take the EMBEDDING (identity input-norm), and
  // value()/policy() route through trunk_embed(). Composite export: skip this;
  // value/heads take the raw state encoding as before. The head-loading code
  // (value_mlp + make_fixed + make_pointer) is IDENTICAL for both modes.
  // Resolve the encoder from the manifest tag (empty -> "v2" for back-compat).
  // Forward-compatible: a new model just declares its encoder_tag; no code here
  // changes. The composite (non-joint) path uses it too.
  impl_->enc_spec = &encoder_for_tag(manifest.value("encoder_tag", std::string()));

  // Model-global hidden activation (top-level "activation"; default "gelu" for
  // backward compat with pre-leaky-ReLU manifests). Threaded into EVERY Mlp.
  {
    std::string act_str = manifest.value("activation", std::string("gelu"));
    impl_->act = (act_str == "leaky_relu") ? Activation::kLeakyRelu
                                            : Activation::kGelu;
  }
  const Activation act = impl_->act;

  impl_->joint = (manifest.value("format", std::string()) == "shared_trunk_v1");
  if (impl_->joint) {
    impl_->trunk_mlp = Mlp(manifest["trunk"], base, act);
    // Siamese front end: the trunk takes the FUSED vector, not the raw encoding,
    // so the encoder-dim check is against the player_encoder input, and the
    // full-input norm is carried here (applied before slicing in compute_embed).
    impl_->siamese = manifest.value("siamese", false);
    if (impl_->siamese) {
      impl_->player_block = manifest.at("player_block").get<int>();
      impl_->player_encoder_out = manifest.at("player_encoder_out").get<int>();
      impl_->player_encoder = Mlp(manifest["player_encoder"], base, act);
      if (impl_->player_encoder.input_dim() != impl_->player_block)
        throw std::runtime_error(
            "NNInference: siamese player_encoder input_dim=" +
            std::to_string(impl_->player_encoder.input_dim()) +
            " != player_block=" + std::to_string(impl_->player_block));
      if (impl_->enc_spec->dim != 2 * impl_->player_block +
              (impl_->trunk_mlp.input_dim() - 2 * impl_->player_encoder_out))
        throw std::runtime_error(
            "NNInference: siamese layout mismatch (encoder dim vs "
            "player_block/trunk input)");
      // Full-input normalization blob (mean then std, each length = encoder dim).
      const auto& sn = manifest.at("siamese_input_norm");
      int dim = sn.at("dim").get<int>();
      if (dim != impl_->enc_spec->dim)
        throw std::runtime_error(
            "NNInference: siamese_input_norm dim != encoder dim");
      std::ifstream nf(base + sn["file"].get<std::string>(), std::ios::binary);
      if (!nf)
        throw std::runtime_error("NNInference: cannot open siamese_input_norm blob");
      impl_->siam_in_mean.resize(dim);
      impl_->siam_in_std.resize(dim);
      nf.read(reinterpret_cast<char*>(impl_->siam_in_mean.data()),
              static_cast<std::streamsize>(dim) * sizeof(float));
      nf.read(reinterpret_cast<char*>(impl_->siam_in_std.data()),
              static_cast<std::streamsize>(dim) * sizeof(float));
      if (!nf)
        throw std::runtime_error("NNInference: short siamese_input_norm blob");
    } else if (impl_->enc_spec->dim != impl_->trunk_mlp.input_dim()) {
      throw std::runtime_error(
          "NNInference: encoder '" + std::string(impl_->enc_spec->tag) +
          "' dim=" + std::to_string(impl_->enc_spec->dim) +
          " != trunk input_dim=" + std::to_string(impl_->trunk_mlp.input_dim()) +
          " (encoder_tag/manifest mismatch)");
    }
    if (manifest.contains("embed_norm") && !manifest["embed_norm"].is_null()) {
      const auto& en = manifest["embed_norm"];
      int dim = en.value("dim", impl_->trunk_mlp.output_dim());
      impl_->embed_eps = en.value("eps", 1e-5f);
      std::ifstream bf(base + en["file"].get<std::string>(), std::ios::binary);
      if (!bf)
        throw std::runtime_error("NNInference: cannot open embed_norm blob");
      impl_->embed_gamma.resize(dim);
      impl_->embed_beta.resize(dim);
      bf.read(reinterpret_cast<char*>(impl_->embed_gamma.data()),
              static_cast<std::streamsize>(dim) * sizeof(float));
      bf.read(reinterpret_cast<char*>(impl_->embed_beta.data()),
              static_cast<std::streamsize>(dim) * sizeof(float));
      if (!bf) throw std::runtime_error("NNInference: short embed_norm blob");
    }
  }

  impl_->value_mlp = Mlp(manifest["value"], base, act);
  if (manifest["value"].contains("value_scale"))
    impl_->value_scale = manifest["value"]["value_scale"].get<double>();
  // What the value head predicts: "margin" (score diff, points) or "outcome"
  // (sign of margin). Consumers that read the value as points must guard on this.
  // Default "margin" for backward compat with pre-field exports (all margin).
  if (manifest["value"].contains("value_target"))
    impl_->value_target = manifest["value"]["value_target"].get<std::string>();

  // Outcome head (shared-trunk exports only; tolerate "outcome": null / absent).
  // Reads the shared embedding (identity input-norm), so it only makes sense in
  // joint mode. The leaf-mode {outcome, mix} paths require it; margin mode ignores.
  if (manifest.contains("outcome") && !manifest["outcome"].is_null()) {
    impl_->outcome_mlp = Mlp(manifest["outcome"], base, act);
    impl_->has_outcome = true;
    if (manifest["outcome"].contains("outcome_scale"))
      impl_->outcome_scale = manifest["outcome"]["outcome_scale"].get<double>();
  }

  // Build fixed-head label->index maps that mirror policy_heads.py vocabs.
  auto make_fixed = [&](const std::string& name, const nlohmann::json& entry,
                        const std::vector<std::string>& vocab) {
    LoadedHead h;
    h.mlp = Mlp(entry, base, act);
    h.vocab = vocab;
    h.num_classes = static_cast<int>(vocab.size());
    for (int i = 0; i < h.num_classes; ++i) h.label_to_idx[vocab[i]] = i;
    impl_->fixed[name] = std::move(h);
  };

  const auto& fh = manifest["fixed_heads"];
  // placement vocab = SPACE_IDS.
  std::vector<std::string> placement_vocab(SPACE_IDS.begin(), SPACE_IDS.end());
  // fencing vocab = p0..p108 + __stop__ (RESTRICTED universe order).
  std::vector<std::string> fencing_vocab;
  {
    int n = static_cast<int>(restricted_universe_entries().size());
    for (int i = 0; i < n; ++i) fencing_vocab.push_back("p" + std::to_string(i));
    fencing_vocab.push_back("__stop__");
  }
  if (fh.contains("placement"))
    make_fixed("placement", fh["placement"], placement_vocab);
  if (fh.contains("choose_subaction"))
    make_fixed("choose_subaction", fh["choose_subaction"], kSubactionVocab);
  if (fh.contains("commit_build_major"))
    make_fixed("commit_build_major", fh["commit_build_major"],
               build_major_vocab());
  if (fh.contains("commit_sow"))
    make_fixed("commit_sow", fh["commit_sow"], sow_vocab());
  if (fh.contains("commit_bake"))
    make_fixed("commit_bake", fh["commit_bake"], bake_vocab());
  if (fh.contains("fencing"))
    make_fixed("fencing", fh["fencing"], fencing_vocab);
  if (fh.contains("build_stop"))
    make_fixed("build_stop", fh["build_stop"],
               std::vector<std::string>{"__build__", "__stop__"});

  const auto& ph = manifest["pointer_heads"];
  auto make_pointer = [&](const std::string& name) {
    if (!ph.contains(name)) return;
    LoadedHead h;
    h.mlp = Mlp(ph[name], base, act);
    impl_->pointer[name] = std::move(h);
    if (name == "harvest_feed")
      impl_->harvest_feed_dim = ph[name].value("candidate_dim", 10);
    if (name == "animal_frontier")
      impl_->animal_dim = ph[name].value("candidate_dim", 4);
  };
  make_pointer("animal_frontier");
  make_pointer("harvest_feed");
}

NNInference::~NNInference() = default;

double NNInference::value(const GameState& state) const {
  return impl_->value(state, nullptr);
}

double NNInference::value(const GameState& state, std::vector<float>& emb) const {
  return impl_->value(state, &emb);
}

double NNInference::value_scale() const { return impl_->value_scale; }

const std::string& NNInference::value_target() const { return impl_->value_target; }

double NNInference::outcome(const GameState& state) const {
  return impl_->outcome(state, nullptr);
}

double NNInference::outcome(const GameState& state, std::vector<float>& emb) const {
  return impl_->outcome(state, &emb);
}

bool NNInference::has_outcome() const { return impl_->has_outcome; }

double NNInference::outcome_scale() const { return impl_->outcome_scale; }

// ---------------------------------------------------------------------------
// Policy combiner
// ---------------------------------------------------------------------------

namespace {

// _filter_cell_priority(actions, priority, CommitClass) — keep only the highest-
// priority cell among Commit* of CommitClass (plus all non-CommitClass actions).
// If no priority cell is legal, return the original set.
template <typename CommitT>
std::vector<Action> filter_cell_priority(const std::vector<Action>& actions,
                                         const std::vector<Coord>& priority) {
  std::vector<Action> commits, others;
  for (const auto& a : actions) {
    if (std::holds_alternative<CommitT>(a))
      commits.push_back(a);
    else
      others.push_back(a);
  }
  if (commits.empty()) return actions;
  std::map<Coord, Action> by_cell;
  for (const auto& a : commits) {
    const auto& c = std::get<CommitT>(a);
    by_cell[{c.row, c.col}] = a;
  }
  for (const auto& rc : priority) {
    auto it = by_cell.find(rc);
    if (it != by_cell.end()) {
      std::vector<Action> out = others;
      out.push_back(it->second);
      return out;
    }
  }
  return actions;
}

std::vector<std::pair<Action, double>> uniform(const std::vector<Action>& acts) {
  std::vector<std::pair<Action, double>> out;
  if (acts.empty()) return out;
  double p = 1.0 / static_cast<double>(acts.size());
  for (const auto& a : acts) out.push_back({a, p});
  return out;
}

}  // namespace

std::vector<std::pair<Action, double>> NNInference::policy(
    const GameState& state) const {
  return policy_impl(state, nullptr);
}

std::vector<std::pair<Action, double>> NNInference::policy(
    const GameState& state, std::vector<float>& emb) const {
  return policy_impl(state, &emb);
}

std::vector<std::pair<Action, double>> NNInference::policy_impl(
    const GameState& state, std::vector<float>* ext) const {
  std::vector<Action> legal = legal_actions(state);

  // 1. Fixed-vocab head over the FULL legal set (disjoint ownership).
  struct FixedOwner {
    const char* name;
    bool (*owns)(const GameState&);
    std::string (*label)(const Action&);
  };
  static const FixedOwner kFixedOwners[] = {
      {"placement", placement_owns, label_placement},
      {"choose_subaction", subaction_owns, label_subaction},
      {"commit_build_major", major_owns, label_major},
      {"commit_sow", sow_owns, label_sow},
      {"commit_bake", bake_owns, label_bake},
      {"fencing", fencing_owns, nullptr},  // label handled specially below
  };
  for (const auto& fo : kFixedOwners) {
    auto it = impl_->fixed.find(fo.name);
    if (it == impl_->fixed.end()) continue;
    if (!fo.owns(state)) continue;
    const LoadedHead& h = it->second;

    // Map each legal action -> class index (label_to_idx). Fencing uses the
    // RESTRICTED universe cell-set -> class index.
    std::vector<std::pair<Action, int>> candidates;
    if (std::string(fo.name) == "fencing") {
      const auto& entries = restricted_universe_entries();
      for (const auto& a : legal) {
        if (auto* cp = as<CommitBuildPasture>(a)) {
          int idx = -1;
          for (int i = 0; i < static_cast<int>(entries.size()); ++i)
            if (entries[i].cells == cp->cells) {
              idx = i;
              break;
            }
          if (idx >= 0) candidates.push_back({a, idx});
        } else if (std::holds_alternative<Stop>(a) ||
                   std::holds_alternative<Proceed>(a)) {
          // Proceed-as-Stop alias (§9): post the build-host refactor the
          // before-phase "stop fencing" action is Proceed (the work-complete
          // flip), the after-phase Stop a singleton. Both map to __stop__.
          candidates.push_back({a, static_cast<int>(entries.size())});  // __stop__
        }
      }
    } else {
      for (const auto& a : legal) {
        std::string lab = fo.label(a);
        if (lab.empty()) continue;
        auto li = h.label_to_idx.find(lab);
        if (li != h.label_to_idx.end()) candidates.push_back({a, li->second});
      }
    }
    if (candidates.empty()) break;  // head abstains -> fall through

    std::vector<bool> mask(h.num_classes, false);
    for (const auto& [a, i] : candidates) mask[i] = true;
    std::vector<float> logits = impl_->fixed_logits(h, state, ext);
    std::vector<double> probs = masked_softmax(logits, mask);
    std::vector<std::pair<Action, double>> out;
    for (const auto& [a, i] : candidates) out.push_back({a, probs[i]});
    return out;
  }

  // 1b. Pointer head over its frontier candidates (== the legal set).
  // animal_frontier: CommitBreed / CommitAccommodate -> (s,b,c,food_gained).
  if (animal_owns(state) && impl_->pointer.count("animal_frontier")) {
    const auto* t = top_frame(state);
    int pidx = *encoder_decider_of(state);
    const PlayerState& p = state.players[pidx];
    auto cr = cooking_rates(state, pidx);
    std::array<int, 3> rates3{cr[0], cr[1], cr[2]};
    std::vector<Action> acts;
    std::vector<std::vector<float>> feats;
    if (std::holds_alternative<PendingHarvestBreed>(*t)) {
      for (const auto& [cfg, food] : breeding_frontier(p, rates3)) {
        acts.push_back(CommitBreed{cfg[0], cfg[1], cfg[2]});
        feats.push_back({static_cast<float>(cfg[0]), static_cast<float>(cfg[1]),
                         static_cast<float>(cfg[2]), static_cast<float>(food)});
      }
    } else {
      Animals gained{};
      if (std::holds_alternative<PendingSheepMarket>(*t))
        gained.sheep = std::get<PendingSheepMarket>(*t).gained;
      else if (std::holds_alternative<PendingPigMarket>(*t))
        gained.boar = std::get<PendingPigMarket>(*t).gained;
      else if (std::holds_alternative<PendingCattleMarket>(*t))
        gained.cattle = std::get<PendingCattleMarket>(*t).gained;
      for (const auto& [cfg, food] : pareto_frontier(p, gained, rates3)) {
        acts.push_back(CommitAccommodate{cfg[0], cfg[1], cfg[2]});
        feats.push_back({static_cast<float>(cfg[0]), static_cast<float>(cfg[1]),
                         static_cast<float>(cfg[2]), static_cast<float>(food)});
      }
    }
    if (!acts.empty()) {
      std::vector<double> scores =
          impl_->pointer_scores(impl_->pointer.at("animal_frontier"), state,
                                feats, impl_->animal_dim, ext);
      std::vector<double> probs = softmax(scores);
      std::vector<std::pair<Action, double>> out;
      for (size_t i = 0; i < acts.size(); ++i) out.push_back({acts[i], probs[i]});
      return out;
    }
  }

  // harvest_feed: candidates come straight from legal_actions (toggles +
  // converts), so the set + order match the engine. Featurize each.
  if (harvest_feed_owns(state) && impl_->pointer.count("harvest_feed")) {
    int pidx = *encoder_decider_of(state);
    const PlayerState& p = state.players[pidx];
    // Per-CommitConvert begging recovered from harvest_feed_frontier.
    bool has_convert = false;
    for (const auto& a : legal)
      if (std::holds_alternative<CommitConvert>(a)) has_convert = true;
    std::map<std::array<int, 5>, int> begging_by_consumed;
    if (has_convert) {
      auto rates = cooking_rates(state, pidx);
      int food_owed = std::max(0, 2 * p.people_total - p.newborns - p.resources.food);
      int g0 = p.resources.grain, v0 = p.resources.veg;
      int s0 = p.animals.sheep, b0 = p.animals.boar, c0 = p.animals.cattle;
      for (const auto& [rem, beg] : harvest_feed_frontier(p, food_owed, rates)) {
        begging_by_consumed[{g0 - rem[0], v0 - rem[1], s0 - rem[2],
                             b0 - rem[3], c0 - rem[4]}] = beg;
      }
    }
    static const std::array<std::string, 3> kCraftOrder = {"joinery", "pottery",
                                                           "basketmaker"};
    std::vector<Action> acts;
    std::vector<std::vector<float>> feats;
    int D = impl_->harvest_feed_dim;  // 10
    for (const auto& a : legal) {
      if (auto* hc = as<CommitHarvestConversion>(a)) {
        std::vector<float> f(D, 0.0f);
        f[0] = 1.0f;  // is_toggle
        for (int j = 0; j < 3; ++j)
          if (hc->conversion_id == kCraftOrder[j]) f[1 + j] = 1.0f;
        acts.push_back(a);
        feats.push_back(f);
      } else if (auto* cv = as<CommitConvert>(a)) {
        std::vector<float> f(D, 0.0f);
        f[4] = static_cast<float>(cv->grain);
        f[5] = static_cast<float>(cv->veg);
        f[6] = static_cast<float>(cv->sheep);
        f[7] = static_cast<float>(cv->boar);
        f[8] = static_cast<float>(cv->cattle);
        auto it = begging_by_consumed.find(
            {cv->grain, cv->veg, cv->sheep, cv->boar, cv->cattle});
        f[9] = it != begging_by_consumed.end()
                   ? static_cast<float>(it->second)
                   : 0.0f;
        acts.push_back(a);
        feats.push_back(f);
      }
    }
    if (!acts.empty()) {
      std::vector<double> scores = impl_->pointer_scores(
          impl_->pointer.at("harvest_feed"), state, feats, D, ext);
      std::vector<double> probs = softmax(scores);
      std::vector<std::pair<Action, double>> out;
      for (size_t i = 0; i < acts.size(); ++i) out.push_back({acts[i], probs[i]});
      return out;
    }
  }

  // 1c. build_stop: multi-shot Build Rooms / Build Stables with Stop legal.
  if (impl_->fixed.count("build_stop") && build_stop_owns(state)) {
    const LoadedHead& h = impl_->fixed.at("build_stop");
    // Legal mask over {__build__, __stop__}.
    bool has_build = false, has_stop = false;
    const auto* t = top_frame(state);
    bool is_rooms = std::holds_alternative<PendingBuildRooms>(*t);
    for (const auto& a : legal) {
      if (is_rooms && std::holds_alternative<CommitBuildRoom>(a)) has_build = true;
      if (!is_rooms && std::holds_alternative<CommitBuildStable>(a))
        has_build = true;
      // Proceed-as-Stop alias (§9): the builder's before-phase "stop building"
      // action is now Proceed (the work-complete flip), not Stop. Both map to the
      // head's stop class. (Never co-legal: before-phase = Proceed, after = Stop.)
      if (std::holds_alternative<Stop>(a) || std::holds_alternative<Proceed>(a))
        has_stop = true;
    }
    std::vector<bool> mask = {has_build, has_stop};
    std::vector<float> logits = impl_->fixed_logits(h, state, ext);
    std::vector<double> probs = masked_softmax(logits, mask);
    double p_build = probs[0], p_stop = probs[1];

    // Cell-priority build cell + Stop, renormalized (mirrors
    // _build_stop_distribution).
    std::vector<Action> kept =
        is_rooms ? filter_cell_priority<CommitBuildRoom>(legal, kRoomPriority)
                 : filter_cell_priority<CommitBuildStable>(legal, kStablePriority);
    std::vector<Action> build_opts, stop_opts;
    for (const auto& a : kept) {
      if (is_rooms ? std::holds_alternative<CommitBuildRoom>(a)
                   : std::holds_alternative<CommitBuildStable>(a))
        build_opts.push_back(a);
      else if (std::holds_alternative<Stop>(a) ||
               std::holds_alternative<Proceed>(a))  // Proceed-as-Stop alias (§9)
        stop_opts.push_back(a);
    }
    std::vector<std::pair<Action, double>> out;
    if (!build_opts.empty() && p_build > 0) {
      double share = p_build / static_cast<double>(build_opts.size());
      for (const auto& a : build_opts) out.push_back({a, share});
    }
    if (!stop_opts.empty() && p_stop > 0) out.push_back({stop_opts[0], p_stop});
    double total = 0.0;
    for (auto& [a, pr] : out) total += pr;
    if (total > 0) {
      for (auto& [a, pr] : out) pr /= total;
      return out;
    }
    return uniform(kept);
  }

  // 2. Cell commit -> uniform over the cell-priority-filtered set.
  const auto* t = top_frame(state);
  if (t) {
    if (std::holds_alternative<PendingPlow>(*t))
      return uniform(filter_cell_priority<CommitPlow>(legal, kPlowPriority));
    if (std::holds_alternative<PendingBuildStables>(*t))
      return uniform(
          filter_cell_priority<CommitBuildStable>(legal, kStablePriority));
    if (std::holds_alternative<PendingBuildRooms>(*t))
      return uniform(filter_cell_priority<CommitBuildRoom>(legal, kRoomPriority));
  }

  // 3. Unhandled -> uniform over the full legal set.
  return uniform(legal);
}

}  // namespace agricola
