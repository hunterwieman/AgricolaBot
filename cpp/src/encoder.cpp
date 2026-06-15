// NN input encoder — faithful port of agricola/agents/nn/encoder.py
// (CPP_ENGINE_PLAN.md §6.2). Mirrors the fast index-writer path
// (_write_player_block / _write_shared_block / _write_midaction_block) plus the
// terminal-state zeroing. Golden-tested byte-identical to Python `encode_state`.
#include "agricola/encoder.hpp"

#include <algorithm>
#include <array>
#include <functional>
#include <set>
#include <stdexcept>
#include <string>
#include <variant>
#include <vector>

#include "agricola/constants.hpp"
#include "agricola/helpers.hpp"
#include "agricola/legality.hpp"
#include "agricola/scoring.hpp"

namespace agricola {

namespace {

// --- decider_of (agents/base.py) -------------------------------------------
std::optional<int> frame_player_idx(const PendingDecision& f) {
  return std::visit([](const auto& v) { return v.player_idx; }, f);
}

// The 10 accumulation spaces, in the encoder's fixed order (FIRST_NN §4.2 /
// encoder._ACCUMULATION_SPACES). NOT canonical SPACE_IDS order.
const std::array<const char*, 10> kAccumSpaces = {
    "forest",  "clay_pit",     "reed_bank",   "western_quarry", "eastern_quarry",
    "fishing", "meeting_place", "sheep_market", "pig_market",     "cattle_market"};

bool is_harvest_phase(Phase ph) {
  return ph == Phase::HARVEST_FIELD || ph == Phase::HARVEST_FEED ||
         ph == Phase::HARVEST_BREED;
}

// --- mid-action: which of the 7 sub-action categories a frame contributes ----
// Mirrors encoder._frame_subaction_categories. Indices into the 7-wide block:
//   build_rooms=0 build_stables=1 plow=2 bake_bread=3 sow=4 build_fences=5
//   build_major=6  (encoder._SUBACTION_CATEGORIES order).
constexpr int kBuildRooms = 0, kBuildStables = 1, kPlow = 2, kBake = 3, kSow = 4,
              kBuildFences = 5, kBuildMajor = 6;

void frame_categories(const PendingDecision& f, std::array<float, 7>& bits) {
  auto set = [&](int i) { bits[i] = 1.0f; };
  std::visit(
      [&](const auto& fr) {
        using T = std::decay_t<decltype(fr)>;
        if constexpr (std::is_same_v<T, PendingGrainUtilization>) {
          if (!fr.sow_chosen) set(kSow);
          if (!fr.bake_chosen) set(kBake);
        } else if constexpr (std::is_same_v<T, PendingFarmExpansion>) {
          if (!fr.room_chosen) set(kBuildRooms);
          if (!fr.stable_chosen) set(kBuildStables);
        } else if constexpr (std::is_same_v<T, PendingFarmland>) {
          if (!fr.plow_chosen) set(kPlow);
        } else if constexpr (std::is_same_v<T, PendingCultivation>) {
          if (!fr.plow_chosen) set(kPlow);
          if (!fr.sow_chosen) set(kSow);
        } else if constexpr (std::is_same_v<T, PendingSideJob>) {
          if (!fr.stable_chosen) set(kBuildStables);
          if (!fr.bake_chosen) set(kBake);
        } else if constexpr (std::is_same_v<T, PendingHouseRedevelopment>) {
          if (!fr.improvement_chosen) set(kBuildMajor);
        } else if constexpr (std::is_same_v<T, PendingFarmRedevelopment>) {
          if (!fr.build_fences_chosen) set(kBuildFences);
        } else if constexpr (std::is_same_v<T, PendingMajorMinorImprovement>) {
          if (!fr.major_chosen) set(kBuildMajor);
        } else if constexpr (std::is_same_v<T, PendingClayOven> ||
                             std::is_same_v<T, PendingStoneOven>) {
          if (!fr.bake_chosen) set(kBake);
        } else if constexpr (std::is_same_v<T, PendingFencing>) {
          if (!fr.build_fences_chosen) set(kBuildFences);
        } else if constexpr (std::is_same_v<T, PendingSow>) {
          set(kSow);
        } else if constexpr (std::is_same_v<T, PendingBakeBread>) {
          set(kBake);
        } else if constexpr (std::is_same_v<T, PendingPlow>) {
          set(kPlow);
        } else if constexpr (std::is_same_v<T, PendingBuildStables>) {
          set(kBuildStables);
        } else if constexpr (std::is_same_v<T, PendingBuildRooms>) {
          set(kBuildRooms);
        } else if constexpr (std::is_same_v<T, PendingBuildMajor>) {
          set(kBuildMajor);
        } else if constexpr (std::is_same_v<T, PendingBuildFences>) {
          set(kBuildFences);
        }
        // PendingRenovate, market, harvest, reveal: nothing.
      },
      f);
}

// --- per-player block (54 features) -----------------------------------------
void write_player_block(float* out, int base, const GameState& state,
                        const PlayerState& p, int player_idx) {
  const Resources& r = p.resources;
  out[base + 0] = static_cast<float>(r.wood);
  out[base + 1] = static_cast<float>(r.clay);
  out[base + 2] = static_cast<float>(r.reed);
  out[base + 3] = static_cast<float>(r.stone);
  out[base + 4] = static_cast<float>(r.food);

  int grain3 = 0, grain2 = 0, grain1 = 0, veg2 = 0, veg1 = 0, empty_plowed = 0;
  for (const auto& row : p.farmyard.grid) {
    for (const auto& cell : row) {
      if (cell.cell_type != CellType::FIELD) continue;
      if (cell.grain > 0) {
        if (cell.grain >= 3)
          ++grain3;
        else if (cell.grain == 2)
          ++grain2;
        else
          ++grain1;
      } else if (cell.veg > 0) {
        if (cell.veg >= 2)
          ++veg2;
        else
          ++veg1;
      } else {
        ++empty_plowed;
      }
    }
  }
  out[base + 5] = static_cast<float>(grain3);
  out[base + 6] = static_cast<float>(grain2);
  out[base + 7] = static_cast<float>(grain1);
  out[base + 8] = static_cast<float>(veg2);
  out[base + 9] = static_cast<float>(veg1);
  out[base + 10] = static_cast<float>(empty_plowed);

  out[base + 11] = static_cast<float>(r.grain);
  out[base + 12] = static_cast<float>(r.veg);

  auto [caps, flex] = extract_slots(p);
  std::vector<int> caps_sorted = caps;
  std::sort(caps_sorted.begin(), caps_sorted.end(), std::greater<int>());
  for (int i = 0; i < 5; ++i)
    out[base + 13 + i] =
        i < static_cast<int>(caps_sorted.size())
            ? static_cast<float>(caps_sorted[i])
            : 0.0f;
  out[base + 18] = static_cast<float>(flex);

  int fenced_stables = 0;
  for (const auto& past : p.farmyard.pastures) fenced_stables += past.num_stables;
  out[base + 19] = static_cast<float>(fenced_stables);

  out[base + 20] = static_cast<float>(p.animals.sheep);
  out[base + 21] = static_cast<float>(p.animals.boar);
  out[base + 22] = static_cast<float>(p.animals.cattle);

  int n_rooms = 0;
  for (const auto& row : p.farmyard.grid)
    for (const auto& cell : row)
      if (cell.cell_type == CellType::ROOM) ++n_rooms;
  out[base + 23] =
      p.house_material == HouseMaterial::WOOD ? static_cast<float>(n_rooms) : 0.0f;
  out[base + 24] =
      p.house_material == HouseMaterial::CLAY ? static_cast<float>(n_rooms) : 0.0f;
  out[base + 25] =
      p.house_material == HouseMaterial::STONE ? static_cast<float>(n_rooms) : 0.0f;

  out[base + 26] = static_cast<float>(p.people_total);
  out[base + 27] =
      state.phase == Phase::WORK ? static_cast<float>(p.people_home) : 0.0f;
  if (is_harvest_round(state.round_number))
    out[base + 28] = static_cast<float>(2 * p.people_total - p.newborns);
  else
    out[base + 28] = static_cast<float>(2 * p.people_total);

  out[base + 29] = static_cast<float>(p.begging_markers);
  std::set<Coord> enc = enclosed_cells(p.farmyard);
  int n_unused = 0;
  for (int ri = 0; ri < kRows; ++ri)
    for (int ci = 0; ci < kCols; ++ci)
      if (p.farmyard.grid[ri][ci].cell_type == CellType::EMPTY &&
          enc.find({ri, ci}) == enc.end())
        ++n_unused;
  out[base + 30] = static_cast<float>(n_unused);

  std::array<int, 4> rates = cooking_rates(state, player_idx);
  out[base + 31] = static_cast<float>(rates[0]);
  out[base + 32] = static_cast<float>(rates[1]);
  out[base + 33] = static_cast<float>(rates[2]);
  out[base + 34] = static_cast<float>(rates[3]);

  const auto& owners = state.board.major_improvement_owners;
  for (int mi = 0; mi < NUM_MAJOR_IMPROVEMENTS; ++mi)
    out[base + 35 + mi] =
        (owners[mi].has_value() && *owners[mi] == player_idx) ? 1.0f : 0.0f;

  int s = p.animals.sheep, b = p.animals.boar, c = p.animals.cattle;
  out[base + 45] =
      (s >= 2 && can_accommodate(caps, flex, s + 1, b, c)) ? 1.0f : 0.0f;
  out[base + 46] =
      (b >= 2 && can_accommodate(caps, flex, s, b + 1, c)) ? 1.0f : 0.0f;
  out[base + 47] =
      (c >= 2 && can_accommodate(caps, flex, s, b, c + 1)) ? 1.0f : 0.0f;

  auto used = [&](const char* id) {
    return std::find(p.harvest_conversions_used.begin(),
                     p.harvest_conversions_used.end(),
                     std::string(id)) != p.harvest_conversions_used.end();
  };
  out[base + 48] = used("joinery") ? 1.0f : 0.0f;
  out[base + 49] = used("pottery") ? 1.0f : 0.0f;
  out[base + 50] = used("basketmaker") ? 1.0f : 0.0f;

  out[base + 51] = state.starting_player == player_idx ? 1.0f : 0.0f;

  float has_fed;
  if (state.phase == Phase::HARVEST_BREED) {
    has_fed = 1.0f;
  } else if (state.phase == Phase::HARVEST_FEED) {
    bool still_to_feed = false;
    for (const auto& f : state.pending_stack) {
      if (std::holds_alternative<PendingHarvestFeed>(f)) {
        const auto& hf = std::get<PendingHarvestFeed>(f);
        if (hf.player_idx.has_value() && *hf.player_idx == player_idx) {
          still_to_feed = true;
          break;
        }
      }
    }
    has_fed = still_to_feed ? 0.0f : 1.0f;
  } else {
    has_fed = 0.0f;
  }
  out[base + 52] = has_fed;

  int future_food = 0;
  for (const auto& fr : p.future_resources) future_food += fr.food;
  out[base + 53] = static_cast<float>(future_food);
}

// --- shared / board block (54 features) -------------------------------------
void write_shared_block(float* out, int base, const GameState& state,
                        int player_idx) {
  const BoardState& board = state.board;
  const auto& spaces = board.action_spaces;  // canonical-ordered
  int rn = state.round_number;

  out[base + 0] = static_cast<float>(rn);
  std::optional<int> dec = encoder_decider_of(state);
  out[base + 1] =
      (dec.has_value() && *dec == player_idx) ? 1.0f : 0.0f;
  out[base + 2] = is_harvest_phase(state.phase) ? 1.0f : 0.0f;

  // rounds_until_next_harvest: 0 on a harvest round, else distance to next.
  static const std::array<int, 6> kHarvestRounds = {4, 7, 9, 11, 13, 14};
  int best = -1;
  for (int h : kHarvestRounds) {
    if (h >= rn) {
      int d = h - rn;
      if (best < 0 || d < best) best = d;
    }
  }
  out[base + 3] = best < 0 ? 0.0f : static_cast<float>(best);

  // Accumulation amounts (10), in encoder accumulation-space order.
  for (int i = 0; i < 10; ++i) {
    int sidx = space_index(kAccumSpaces[i]);
    const auto& sp = spaces[sidx];
    const Resources& a = sp.accumulated;
    out[base + 4 + i] = static_cast<float>(
        a.wood + a.clay + a.reed + a.stone + a.food + a.grain + a.veg +
        sp.accumulated_amount);
  }

  // Stage cards revealed (14): SPACE_IDS[11:] in canonical order.
  for (int i = 0; i < 14; ++i)
    out[base + 14 + i] = spaces[11 + i].revealed ? 1.0f : 0.0f;

  // Space available now (25): SPACE_IDS order == canonical action_spaces order.
  for (int i = 0; i < 25; ++i) {
    const auto& sp = spaces[i];
    out[base + 28 + i] =
        (sp.revealed && sp.workers[0] == 0 && sp.workers[1] == 0) ? 1.0f : 0.0f;
  }

  out[base + 53] = state.phase == Phase::BEFORE_SCORING ? 1.0f : 0.0f;
}

// --- mid-action block (8 features) ------------------------------------------
void write_midaction_block(float* out, int base, const GameState& state) {
  std::array<float, 7> bits{0, 0, 0, 0, 0, 0, 0};
  for (const auto& frame : state.pending_stack) frame_categories(frame, bits);
  for (int i = 0; i < 7; ++i) out[base + i] = bits[i];

  // stop_is_legal: never legal at an empty stack (Stop pops a frame); else
  // dispatch to legal_actions and look for a Stop. Mirrors the encoder's
  // empty-stack short-circuit.
  bool stop_legal = false;
  if (!state.pending_stack.empty()) {
    for (const auto& a : legal_actions(state)) {
      if (std::holds_alternative<Stop>(a)) {
        stop_legal = true;
        break;
      }
    }
  }
  out[base + 7] = stop_legal ? 1.0f : 0.0f;
}

// --- candidate per-player block (58 features) -------------------------------
// = the v2 block with begging (v2 idx 29) dropped + 5 features appended. Built
// atop write_player_block (so the shared crop/cap/etc. logic never drifts).
void write_player_block_candidate(float* out, int base, const GameState& state,
                                  const PlayerState& p, int player_idx) {
  std::array<float, kEncodedDim> v2{};
  write_player_block(v2.data(), 0, state, p, player_idx);
  for (int i = 0; i < 29; ++i) out[base + i] = v2[i];        // 0..28 unchanged
  for (int i = 30; i < 54; ++i) out[base + (i - 1)] = v2[i];  // drop begging(29)

  // running_score_excl_begging: total minus the (-3*count) begging penalty.
  out[base + 53] =
      static_cast<float>(score(state, player_idx) + 3 * p.begging_markers);

  // turns_until_next_feeding: family_left + people_total*(next_harvest - rn).
  static const std::array<int, 6> kHarvestRounds = {4, 7, 9, 11, 13, 14};
  int rn = state.round_number, next_h = -1;
  for (int h : kHarvestRounds)
    if (h >= rn && (next_h < 0 || h < next_h)) next_h = h;
  int family_left = state.phase == Phase::WORK ? p.people_home : 0;
  out[base + 54] = next_h < 0 ? 0.0f
                              : static_cast<float>(
                                    family_left + p.people_total * (next_h - rn));

  // capability bits.
  int n_rooms = 0;
  for (const auto& row : p.farmyard.grid)
    for (const auto& cell : row)
      if (cell.cell_type == CellType::ROOM) ++n_rooms;
  const Resources& r = p.resources;
  out[base + 55] = (p.house_material == HouseMaterial::WOOD && r.clay >= n_rooms &&
                    r.reed >= 1)
                       ? 1.0f
                       : 0.0f;  // can_renovate_to_clay
  out[base + 56] = ((p.house_material == HouseMaterial::WOOD ||
                     p.house_material == HouseMaterial::CLAY) &&
                    r.stone >= n_rooms && r.reed >= 1)
                       ? 1.0f
                       : 0.0f;  // can_renovate_to_stone
  out[base + 57] = n_rooms > p.people_total ? 1.0f : 0.0f;  // can_grow_family
}

}  // namespace

std::optional<int> encoder_decider_of(const GameState& state) {
  if (state.pending_stack.empty()) return state.current_player;
  return frame_player_idx(state.pending_stack.back());
}

std::array<float, kEncodedDim> encode(const GameState& state, int player_idx) {
  std::array<float, kEncodedDim> out{};
  write_player_block(out.data(), 0, state, state.players[player_idx], player_idx);
  write_player_block(out.data(), 54, state, state.players[1 - player_idx],
                     1 - player_idx);
  write_shared_block(out.data(), 108, state, player_idx);
  write_midaction_block(out.data(), 162, state);

  if (state.phase == Phase::BEFORE_SCORING) {
    // Terminal zeroing (§4.5): force the next-decision features to 0 AFTER the
    // blocks are written. game_end_indicator (shared+53 = idx 161) stays 1.
    // Names -> indices (from feature_names() ordering):
    //   own/opp family_left (27/81), food_owed (28/82), has_fed (52/106),
    //   future_food (53/107); current_player_is_own (109), in_harvest (110),
    //   rounds_until_next_harvest (111); stop_is_legal (169);
    //   subaction_avail_* (162-168).
    static const std::array<int, 11> kZero = {27,  81,  28,  82,  52,  106,
                                              53,  107, 109, 110, 111};
    for (int i : kZero) out[i] = 0.0f;
    out[169] = 0.0f;             // stop_is_legal
    for (int i = 162; i <= 168; ++i) out[i] = 0.0f;  // subaction_avail_*
  }
  return out;
}

std::array<float, kEncodedDimCandidate> encode_candidate(const GameState& state,
                                                         int player_idx) {
  std::array<float, kEncodedDimCandidate> out{};
  write_player_block_candidate(out.data(), 0, state,
                               state.players[player_idx], player_idx);
  write_player_block_candidate(out.data(), 58, state,
                               state.players[1 - player_idx], 1 - player_idx);
  write_shared_block(out.data(), 116, state, player_idx);
  write_midaction_block(out.data(), 170, state);

  if (state.phase == Phase::BEFORE_SCORING) {
    // Candidate terminal zeroing (_TERMINAL_ZERO_NAMES_CANDIDATE). own/opp:
    // family_left (27/85), food_owed (28/86), has_fed (51/109),
    // future_food (52/110), turns_until_next_feeding (54/112),
    // can_renovate_to_clay (55/113), can_renovate_to_stone (56/114),
    // can_grow_family (57/115); current_player_is_own (117), in_harvest (118),
    // rounds_until_next_harvest (119); stop_is_legal (177); subaction (170-176).
    // running_score_excl_begging (53/111) stays LIVE.
    static const std::array<int, 19> kZero = {
        27, 85, 28, 86, 51, 109, 52, 110, 54, 112,
        55, 113, 56, 114, 57, 115, 117, 118, 119};
    for (int i : kZero) out[i] = 0.0f;
    out[177] = 0.0f;                                  // stop_is_legal
    for (int i = 170; i <= 176; ++i) out[i] = 0.0f;   // subaction_avail_*
  }
  return out;
}

double begging_margin(const GameState& state, int perspective) {
  int own = state.players[perspective].begging_markers;
  int opp = state.players[1 - perspective].begging_markers;
  return -3.0 * static_cast<double>(own - opp);
}

// --- Encoder registry --------------------------------------------------------
namespace {
void encode_v2_into(const GameState& s, int p, std::vector<float>& out) {
  std::array<float, kEncodedDim> a = encode(s, p);
  out.assign(a.begin(), a.end());
}
void encode_candidate_into(const GameState& s, int p, std::vector<float>& out) {
  std::array<float, kEncodedDimCandidate> a = encode_candidate(s, p);
  out.assign(a.begin(), a.end());
}

// THE registry. Add a row to register a future encoder (its encode fn + dim +
// whether its value target was begging-stripped). Nothing else changes.
const EncoderSpec kEncoders[] = {
    {"v2", kEncodedDim, false, &encode_v2_into},
    {"cand_feat178_v1", kEncodedDimCandidate, true, &encode_candidate_into},
};
}  // namespace

const EncoderSpec& encoder_for_tag(const std::string& tag) {
  const std::string t = tag.empty() ? "v2" : tag;  // pre-registry exports = v2
  for (const auto& e : kEncoders)
    if (t == e.tag) return e;
  throw std::runtime_error("encoder_for_tag: unknown encoder tag '" + t + "'");
}

}  // namespace agricola
