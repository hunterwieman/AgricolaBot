// legal_actions — port of agricola/legality.py. Mirrors every placement
// predicate, shared helper, and per-pending enumerator. Cards are deferred, so
// the only card-touching behaviors (FireTrigger at PendingBakeBread, the
// Potter-Ceramics bake-bread extension) are omitted: in Family play no player
// owns potter_ceramics, so both are always inert -> set-identical to Python.
#include "agricola/legality.hpp"

#include <algorithm>
#include <array>
#include <stdexcept>

#include "agricola/constants.hpp"
#include "agricola/fences.hpp"
#include "agricola/helpers.hpp"

namespace agricola {
namespace {

constexpr int R = 3;  // grid rows
constexpr int C = 5;  // grid cols
constexpr std::array<std::pair<int, int>, 4> kOrth{
    {{-1, 0}, {1, 0}, {0, -1}, {0, 1}}};

const ActionSpaceState& get_space(const GameState& s, const std::string& id) {
  return s.board.action_spaces[space_index(id)];
}

bool is_available(const GameState& s, const std::string& space) {
  const auto& sp = get_space(s, space);
  bool unoccupied = sp.workers[0] == 0 && sp.workers[1] == 0;
  return unoccupied && sp.revealed;
}

int num_rooms(const PlayerState& p) {
  int n = 0;
  for (int r = 0; r < R; ++r)
    for (int c = 0; c < C; ++c)
      if (p.farmyard.grid[r][c].cell_type == CellType::ROOM) ++n;
  return n;
}

int player_index(const GameState& s, const PlayerState& p) {
  return (&p == &s.players[0]) ? 0 : 1;
}

bool owns_baker(const GameState& s, const PlayerState& p) {
  int pid = player_index(s, p);
  const auto& owners = s.board.major_improvement_owners;
  for (int i = 0; i < 10; ++i)
    if (major_is_baking(i) && owners[i].has_value() && *owners[i] == pid)
      return true;
  return false;
}

bool can_bake_bread(const GameState& s, const PlayerState& p) {
  // Base check only; the Potter-Ceramics extension is inert in Family play.
  return owns_baker(s, p) && p.resources.grain >= 1;
}

bool can_sow(const PlayerState& p) {
  const auto& g = p.farmyard.grid;
  bool has_empty_field = false;
  for (int r = 0; r < R && !has_empty_field; ++r)
    for (int c = 0; c < C; ++c)
      if (g[r][c].cell_type == CellType::FIELD && g[r][c].grain == 0 &&
          g[r][c].veg == 0) {
        has_empty_field = true;
        break;
      }
  bool has_seed = p.resources.grain >= 1 || p.resources.veg >= 1;
  return has_empty_field && has_seed;
}

std::vector<Coord> legal_plow_cells(const PlayerState& p) {
  const auto& g = p.farmyard.grid;
  std::set<Coord> enclosed = enclosed_cells(p.farmyard);
  std::vector<Coord> field_cells;
  for (int r = 0; r < R; ++r)
    for (int c = 0; c < C; ++c)
      if (g[r][c].cell_type == CellType::FIELD) field_cells.push_back({r, c});
  std::vector<Coord> empty_unenclosed;
  for (int r = 0; r < R; ++r)
    for (int c = 0; c < C; ++c)
      if (g[r][c].cell_type == CellType::EMPTY && !enclosed.count({r, c}))
        empty_unenclosed.push_back({r, c});
  if (field_cells.empty()) return empty_unenclosed;
  std::set<Coord> adjacent;
  for (const auto& [r, c] : field_cells)
    for (const auto& [dr, dc] : kOrth) adjacent.insert({r + dr, c + dc});
  std::vector<Coord> out;
  for (const auto& cell : empty_unenclosed)
    if (adjacent.count(cell)) out.push_back(cell);
  return out;
}

bool can_plow(const PlayerState& p) { return !legal_plow_cells(p).empty(); }

std::vector<Coord> legal_stable_cells(const PlayerState& p) {
  const auto& g = p.farmyard.grid;
  std::vector<Coord> out;
  for (int r = 0; r < R; ++r)
    for (int c = 0; c < C; ++c)
      if (g[r][c].cell_type == CellType::EMPTY) out.push_back({r, c});
  return out;
}

bool can_afford(const PlayerState& p, const Resources& cost) {
  const auto& r = p.resources;
  return r.wood >= cost.wood && r.clay >= cost.clay && r.reed >= cost.reed &&
         r.stone >= cost.stone && r.food >= cost.food && r.grain >= cost.grain &&
         r.veg >= cost.veg;
}

bool can_build_stable(const PlayerState& p, const Resources& cost) {
  return stables_in_supply(p.farmyard) >= 1 && !legal_stable_cells(p).empty() &&
         can_afford(p, cost);
}

bool can_afford_room(const PlayerState& p) {
  return can_afford(p, room_cost(p.house_material));
}

std::vector<Coord> legal_room_cells(const PlayerState& p) {
  const auto& g = p.farmyard.grid;
  std::set<Coord> enclosed = enclosed_cells(p.farmyard);
  std::vector<Coord> room_cells;
  for (int r = 0; r < R; ++r)
    for (int c = 0; c < C; ++c)
      if (g[r][c].cell_type == CellType::ROOM) room_cells.push_back({r, c});
  std::vector<Coord> empty_unenclosed;
  for (int r = 0; r < R; ++r)
    for (int c = 0; c < C; ++c)
      if (g[r][c].cell_type == CellType::EMPTY && !enclosed.count({r, c}))
        empty_unenclosed.push_back({r, c});
  std::set<Coord> adjacent;
  for (const auto& [r, c] : room_cells)
    for (const auto& [dr, dc] : kOrth) adjacent.insert({r + dr, c + dc});
  std::vector<Coord> out;
  for (const auto& cell : empty_unenclosed)
    if (adjacent.count(cell)) out.push_back(cell);
  return out;
}

bool has_room_placement(const PlayerState& p) {
  return !legal_room_cells(p).empty();
}

bool can_build_room(const PlayerState& p) {
  return can_afford_room(p) && has_room_placement(p);
}

bool can_renovate(const PlayerState& p) {
  if (p.house_material == HouseMaterial::STONE) return false;
  int nr = num_rooms(p);
  const auto& res = p.resources;
  if (p.house_material == HouseMaterial::WOOD)
    return res.clay >= nr && res.reed >= 1;
  return res.stone >= nr && res.reed >= 1;  // CLAY
}

bool can_afford_major(const GameState& s, const PlayerState& p, int idx) {
  int pid = player_index(s, p);
  const auto& res = p.resources;
  const auto& owns = s.board.major_improvement_owners;
  auto fp_owned = [&](int i) {
    return owns[i].has_value() && *owns[i] == pid;
  };
  bool owns_fireplace = fp_owned(0) || fp_owned(1);
  switch (idx) {
    case 0: return res.clay >= 2;
    case 1: return res.clay >= 3;
    case 2: return res.clay >= 4 || owns_fireplace;
    case 3: return res.clay >= 5 || owns_fireplace;
    case 4: return res.stone >= 3 && res.wood >= 1;
    case 5: return res.clay >= 3 && res.stone >= 1;
    case 6: return res.clay >= 1 && res.stone >= 3;
    case 7: return res.wood >= 2 && res.stone >= 2;
    case 8: return res.clay >= 2 && res.stone >= 2;
    case 9: return res.reed >= 2 && res.stone >= 2;
    default: return false;
  }
}

bool can_afford_any_major(const GameState& s, const PlayerState& p) {
  const auto& owners = s.board.major_improvement_owners;
  for (int i = 0; i < 10; ++i)
    if (!owners[i].has_value() && can_afford_major(s, p, i)) return true;
  return false;
}

// --- fence-action helpers (port of legality.py _check_entry_legal etc.) ------

std::uint32_t enclosable_cells_bm(const Farmyard& fy) {
  std::uint32_t bm = 0;
  for (int r = 0; r < kFenceRows; ++r)
    for (int c = 0; c < kFenceCols; ++c) {
      auto ct = fy.grid[r][c].cell_type;
      if (ct == CellType::EMPTY || ct == CellType::STABLE)
        bm |= 1u << (r * kFenceCols + c);
    }
  return bm;
}

std::uint32_t cells_bm_of_pasture(const Pasture& p) {
  std::uint32_t bm = 0;
  for (const auto& [r, c] : p.cells) bm |= 1u << (r * kFenceCols + c);
  return bm;
}

int lowest_bit_length(std::uint32_t bm) {
  // (bm & -bm).bit_length(): position (1-based) of the lowest set bit.
  if (bm == 0) return 0;
  std::uint32_t low = bm & (~bm + 1);
  int len = 0;
  while (low) { ++len; low >>= 1; }
  return len;
}

struct FenceScanCtx {
  std::uint32_t enclosable_bm;
  std::vector<std::uint32_t> pasture_bms;
  std::uint32_t existing_pasture_cells_bm;
  bool has_existing_pastures;
  bool subdivision_started;
  std::uint32_t h_fences_bm;
  std::uint32_t v_fences_bm;
  int wood;
  int fences_left;
};

bool universe_contains_bm(std::uint32_t bm) {
  for (const auto& e : restricted_universe_entries())
    if (e.cells_bm == bm) return true;
  return false;
}

// Returns true iff this entry is a legal pasture commit under ctx.
bool check_entry_legal(const PastureCandidate& entry, const FenceScanCtx& ctx) {
  std::uint32_t bm = entry.cells_bm;

  // 1. Enclosable cells only.
  if (bm & ~ctx.enclosable_bm) return false;

  // 2. Subdivision vs new-pasture.
  bool is_subdivision = false;
  std::uint32_t parent_bm = 0;
  if (bm & ctx.existing_pasture_cells_bm) {
    for (std::uint32_t P_bm : ctx.pasture_bms)
      if ((bm & P_bm) == bm) {
        is_subdivision = true;
        parent_bm = P_bm;
        break;
      }
    if (!is_subdivision) return false;  // straddles multiple pastures
  }

  // 2b. Builds-before-subdivisions ordering rule.
  if (!is_subdivision && ctx.subdivision_started) return false;

  // 3. Adjacency for new pasture (when existing pastures present).
  if (!is_subdivision && ctx.has_existing_pastures)
    if (!(entry.adjacency_bm & ctx.existing_pasture_cells_bm)) return false;

  // 4. Affordability + supply + at-least-one-new-fence.
  std::uint32_t h_new = entry.h_boundary_bm & ~ctx.h_fences_bm;
  std::uint32_t v_new = entry.v_boundary_bm & ~ctx.v_fences_bm;
  int new_count = popcount(h_new) + popcount(v_new);
  if (new_count < 1) return false;
  if (new_count > ctx.wood) return false;
  if (new_count > ctx.fences_left) return false;

  // 5. Subdivision canonicalization.
  if (is_subdivision) {
    std::uint32_t complement_bm = parent_bm & ~bm;
    if (universe_contains_bm(complement_bm)) {
      int lo_self = lowest_bit_length(bm);
      int lo_comp = lowest_bit_length(complement_bm);
      if (lo_comp < lo_self) return false;
    }
  }
  return true;
}

FenceScanCtx make_ctx(const Farmyard& fy, int wood, bool subdivision_started) {
  FenceScanCtx ctx;
  ctx.enclosable_bm = enclosable_cells_bm(fy);
  ctx.existing_pasture_cells_bm = 0;
  for (const auto& past : fy.pastures) {
    std::uint32_t b = cells_bm_of_pasture(past);
    ctx.pasture_bms.push_back(b);
    ctx.existing_pasture_cells_bm |= b;
  }
  ctx.has_existing_pastures = !ctx.pasture_bms.empty();
  ctx.subdivision_started = subdivision_started;
  ctx.h_fences_bm = pack_fences_h(fy);
  ctx.v_fences_bm = pack_fences_v(fy);
  ctx.wood = wood;
  ctx.fences_left = fences_in_supply(fy);
  return ctx;
}

bool any_legal_pasture_commit(const PlayerState& p) {
  FenceScanCtx ctx = make_ctx(p.farmyard, p.resources.wood, false);
  for (const auto& entry : restricted_universe_entries())
    if (check_entry_legal(entry, ctx)) return true;
  return false;
}

// --- placement predicates ---------------------------------------------------

const PlayerState& cur(const GameState& s) {
  return s.players[s.current_player];
}

bool accum_has_resources(const ActionSpaceState& sp) {
  // bool(Resources(...)) is True iff any component is non-zero.
  const auto& a = sp.accumulated;
  return a.wood || a.clay || a.reed || a.stone || a.food || a.grain || a.veg;
}

bool legal_atomic(const GameState& s, const std::string& space) {
  if (space == "day_laborer") return is_available(s, "day_laborer");
  if (space == "grain_seeds") return is_available(s, "grain_seeds");
  if (space == "meeting_place") return is_available(s, "meeting_place");
  if (space == "vegetable_seeds") return is_available(s, "vegetable_seeds");
  if (space == "fishing")
    return is_available(s, "fishing") &&
           get_space(s, "fishing").accumulated_amount > 0;
  if (space == "forest")
    return is_available(s, "forest") &&
           accum_has_resources(get_space(s, "forest"));
  if (space == "clay_pit")
    return is_available(s, "clay_pit") &&
           accum_has_resources(get_space(s, "clay_pit"));
  if (space == "reed_bank")
    return is_available(s, "reed_bank") &&
           accum_has_resources(get_space(s, "reed_bank"));
  if (space == "western_quarry")
    return is_available(s, "western_quarry") &&
           accum_has_resources(get_space(s, "western_quarry"));
  if (space == "eastern_quarry")
    return is_available(s, "eastern_quarry") &&
           accum_has_resources(get_space(s, "eastern_quarry"));
  if (space == "basic_wish_for_children") {
    if (!is_available(s, "basic_wish_for_children")) return false;
    const auto& p = cur(s);
    return p.people_total < 5 && p.people_total < num_rooms(p);
  }
  if (space == "urgent_wish_for_children") {
    if (!is_available(s, "urgent_wish_for_children")) return false;
    return cur(s).people_total < 5;
  }
  return false;
}

bool legal_non_atomic(const GameState& s, const std::string& space) {
  if (space == "farm_expansion") {
    if (!is_available(s, "farm_expansion")) return false;
    const auto& p = cur(s);
    Resources cost; cost.wood = 2;
    return can_build_room(p) || can_build_stable(p, cost);
  }
  if (space == "farmland") {
    if (!is_available(s, "farmland")) return false;
    return can_plow(cur(s));
  }
  if (space == "side_job") {
    if (!is_available(s, "side_job")) return false;
    const auto& p = cur(s);
    Resources cost; cost.wood = 1;
    return can_build_stable(p, cost) || can_bake_bread(s, p);
  }
  if (space == "grain_utilization") {
    if (!is_available(s, "grain_utilization")) return false;
    const auto& p = cur(s);
    return can_sow(p) || can_bake_bread(s, p);
  }
  if (space == "sheep_market")
    // No emptiness gate (user ruling 2026-07-14; unreachable today) — mirrors Python.
    return is_available(s, "sheep_market");
  if (space == "pig_market")
    // No emptiness gate (user ruling 2026-07-14; unreachable today) — mirrors Python.
    return is_available(s, "pig_market");
  if (space == "cattle_market")
    // No emptiness gate (user ruling 2026-07-14; unreachable today) — mirrors Python.
    return is_available(s, "cattle_market");
  if (space == "major_improvement") {
    if (!is_available(s, "major_improvement")) return false;
    return can_afford_any_major(s, cur(s));
  }
  if (space == "house_redevelopment") {
    if (!is_available(s, "house_redevelopment")) return false;
    return can_renovate(cur(s));
  }
  if (space == "cultivation") {
    if (!is_available(s, "cultivation")) return false;
    const auto& p = cur(s);
    return can_plow(p) || can_sow(p);
  }
  if (space == "farm_redevelopment") {
    if (!is_available(s, "farm_redevelopment")) return false;
    return can_renovate(cur(s));
  }
  if (space == "fencing") {
    if (!is_available(s, "fencing")) return false;
    const auto& p = cur(s);
    if (p.resources.wood < 1) return false;
    if (fences_in_supply(p.farmyard) < 1) return false;
    return any_legal_pasture_commit(p);
  }
  return false;
}

// ALL_LEGALITY order: atomic first (in its insertion order), then non-atomic.
// `lessons` is omitted entirely. Order doesn't matter for the gate (set
// comparison), but we mirror it for clarity.
const std::array<std::string, 12> kAtomicSpaces{
    "day_laborer", "fishing", "forest", "clay_pit", "reed_bank", "grain_seeds",
    "meeting_place", "western_quarry", "vegetable_seeds", "eastern_quarry",
    "basic_wish_for_children", "urgent_wish_for_children"};
const std::array<std::string, 12> kNonAtomicSpaces{
    "farm_expansion", "farmland", "side_job", "grain_utilization",
    "sheep_market", "pig_market", "cattle_market", "major_improvement",
    "house_redevelopment", "cultivation", "farm_redevelopment", "fencing"};

std::vector<Action> legal_placements(const GameState& s) {
  std::vector<Action> out;
  if (s.players[s.current_player].people_home < 1) return out;
  for (const auto& sp : kAtomicSpaces)
    if (legal_atomic(s, sp)) out.push_back(PlaceWorker{sp});
  for (const auto& sp : kNonAtomicSpaces)
    if (legal_non_atomic(s, sp)) out.push_back(PlaceWorker{sp});
  return out;
}

// --- per-pending enumerators ------------------------------------------------

const PlayerState& frame_player(const GameState& s, std::optional<int> pid) {
  return s.players[*pid];
}

std::vector<Action> enum_grain_utilization(const GameState& s,
                                           const PendingGrainUtilization& pd) {
  // Proceed-host (and/or; SPACE_HOST_REFACTOR.md §4.3). after-phase: Stop (the
  // Family after-window has no triggers). before-phase: the legal
  // ChooseSubActions + Proceed once a sub-action has run.
  if (pd.phase == "after") return {Stop{}};
  const auto& p = frame_player(s, pd.player_idx);
  std::vector<Action> a;
  if (!pd.bake_chosen && can_bake_bread(s, p))
    a.push_back(ChooseSubAction{"bake_bread"});
  if (!pd.sow_chosen && can_sow(p)) a.push_back(ChooseSubAction{"sow"});
  if (pd.sow_chosen || pd.bake_chosen) a.push_back(Proceed{});
  return a;
}

std::vector<Action> enum_sow(const GameState& s, const PendingSow& pd) {
  if (pd.phase == "after") return {Stop{}};  // after-phase: triggers (none in Family) + Stop
  const auto& p = frame_player(s, pd.player_idx);
  int empty_fields = 0;
  const auto& g = p.farmyard.grid;
  for (int r = 0; r < R; ++r)
    for (int c = 0; c < C; ++c)
      if (g[r][c].cell_type == CellType::FIELD && g[r][c].grain == 0 &&
          g[r][c].veg == 0)
        ++empty_fields;
  std::vector<Action> a;
  for (int gr = 0; gr <= p.resources.grain; ++gr)
    for (int v = 0; v <= p.resources.veg; ++v) {
      if (gr + v == 0) continue;
      if (gr + v > empty_fields) continue;
      a.push_back(CommitSow{gr, v});
    }
  return a;
}

// baking_specs_for_player: collect (max_grain, food_per_grain) for owned
// baking majors (extensions are card-only, deferred).
std::vector<BakingSpec> baking_specs(const GameState& s, int pid) {
  std::vector<BakingSpec> specs;
  const auto& owners = s.board.major_improvement_owners;
  for (int i = 0; i < 10; ++i) {
    auto spec = baking_spec_for_major(i);
    if (spec && owners[i].has_value() && *owners[i] == pid) specs.push_back(*spec);
  }
  return specs;
}

std::vector<Action> enum_bake_bread(const GameState& s,
                                    const PendingBakeBread& pd) {
  if (pd.phase == "after") return {Stop{}};  // after-phase: triggers (none in Family) + Stop
  const auto& p = frame_player(s, pd.player_idx);
  std::vector<Action> a;
  // FireTrigger options: cards deferred, none ever eligible -> omitted.
  auto specs = baking_specs(s, *pd.player_idx);
  if (!specs.empty()) {
    int finite_cap = 0;
    bool uncapped_present = false;
    for (const auto& sp : specs) {
      if (sp.max_grain.has_value()) finite_cap += *sp.max_grain;
      else uncapped_present = true;
    }
    int max_grain =
        uncapped_present ? p.resources.grain
                         : std::min(p.resources.grain, finite_cap);
    for (int n = 1; n <= max_grain; ++n) a.push_back(CommitBake{n});
  }
  return a;
}

std::vector<Action> enum_plow(const GameState& s, const PendingPlow& pd) {
  if (pd.phase == "after") return {Stop{}};  // after-phase: triggers (none in Family) + Stop
  const auto& p = frame_player(s, pd.player_idx);
  std::vector<Action> a;
  for (const auto& [r, c] : legal_plow_cells(p)) a.push_back(CommitPlow{r, c});
  return a;
}

std::vector<Action> enum_build_stables(const GameState& s,
                                       const PendingBuildStables& pd) {
  // before/after host: after-phase = triggers (none in Family) + Stop.
  if (pd.phase == "after") return {Stop{}};
  const auto& p = frame_player(s, pd.player_idx);
  std::vector<Action> a;
  bool cap_ok = !pd.max_builds.has_value() || pd.num_built < *pd.max_builds;
  if (cap_ok && can_build_stable(p, pd.cost))
    for (const auto& [r, c] : legal_stable_cells(p))
      a.push_back(CommitBuildStable{r, c});
  if (pd.num_built >= 1) a.push_back(Proceed{});
  return a;
}

std::vector<Action> enum_build_rooms(const GameState& s,
                                     const PendingBuildRooms& pd) {
  // before/after host: after-phase = triggers (none in Family) + Stop.
  if (pd.phase == "after") return {Stop{}};
  const auto& p = frame_player(s, pd.player_idx);
  std::vector<Action> a;
  bool cap_ok = !pd.max_builds.has_value() || pd.num_built < *pd.max_builds;
  // Room cost recomputed (Family: singleton ROOM_COSTS), not read off the frame.
  if (cap_ok && can_afford(p, room_cost(p.house_material)))
    for (const auto& [r, c] : legal_room_cells(p))
      a.push_back(CommitBuildRoom{r, c});
  if (pd.num_built >= 1) a.push_back(Proceed{});
  return a;
}

std::vector<Action> enum_build_major(const GameState& s,
                                     const PendingBuildMajor& pd) {
  if (pd.phase == "after") return {Stop{}};  // was build_chosen; now phase
  const auto& owners = s.board.major_improvement_owners;
  const auto& p = frame_player(s, pd.player_idx);
  int pid = *pd.player_idx;
  std::vector<Action> a;
  for (int idx = 0; idx < 10; ++idx) {
    if (owners[idx].has_value()) continue;
    // Wide commit: one CommitBuildMajor per affordable PaymentOption — the printed
    // Resources cost (when affordable) + each owned-Fireplace return route for
    // Cooking Hearth. Same decision set as before, packaged as payments.
    if (can_afford(p, MAJOR_IMPROVEMENT_COSTS[idx]))
      a.push_back(CommitBuildMajor{idx, MAJOR_IMPROVEMENT_COSTS[idx]});
    // Cooking Hearth via Fireplace return.
    if (idx == 2 || idx == 3) {
      for (int fp : FIREPLACE_INDICES)
        if (owners[fp].has_value() && *owners[fp] == pid)
          a.push_back(CommitBuildMajor{idx, ReturnImprovement{fp}});
    }
  }
  return a;
}

std::vector<Action> enum_renovate(const GameState& s,
                                  const PendingRenovate& pd) {
  if (pd.phase == "after") return {Stop{}};  // after-phase: triggers (none in Family) + Stop
  // Payment = the base renovate cost (num_rooms of the next material + 1 reed):
  // WOOD->clay, CLAY->stone. Mirrors agricola/legality.py + renovate_cost().
  // to_material = the next tier (Family has no target extension — Conservator's
  // wood->stone route is card-only).
  const PlayerState& p = frame_player(s, pd.player_idx);
  int nr = num_rooms(p);
  bool wood = p.house_material == HouseMaterial::WOOD;
  Resources payment = wood ? Resources{0, nr, 1, 0, 0, 0, 0}   // clay=nr, reed=1
                           : Resources{0, 0, 1, nr, 0, 0, 0};  // stone=nr, reed=1
  HouseMaterial to_material =
      wood ? HouseMaterial::CLAY : HouseMaterial::STONE;
  return {CommitRenovate{payment, to_material}};
}

std::vector<Action> enum_farm_expansion(const GameState& s,
                                        const PendingFarmExpansion& pd) {
  // Proceed-host (and/or; SPACE_HOST_REFACTOR.md §4.3).
  if (pd.phase == "after") return {Stop{}};
  const auto& p = frame_player(s, pd.player_idx);
  std::vector<Action> a;
  if (!pd.room_chosen && can_build_room(p))
    a.push_back(ChooseSubAction{"build_rooms"});
  Resources cost; cost.wood = 2;
  if (!pd.stable_chosen && can_build_stable(p, cost))
    a.push_back(ChooseSubAction{"build_stables"});
  if (pd.room_chosen || pd.stable_chosen) a.push_back(Proceed{});
  return a;
}

// The single mandatory ChooseSubAction the generic Delegating space host offers
// in its before-phase, dispatched by space_id (SPACE_HOST_REFACTOR.md §4.2/§8).
// Returns whether a legal choice exists, writing it into `out`. (Family C++:
// "lessons" is card-only and never reached.)
static bool subactionspace_choice(const GameState& s,
                                  const PendingSubActionSpace& pd,
                                  ChooseSubAction& out) {
  const std::string sid = pd.space_id();
  const auto& p = frame_player(s, pd.player_idx);
  if (sid == "farmland") {
    if (can_plow(p)) { out = ChooseSubAction{"plow"}; return true; }
    return false;
  }
  if (sid == "fencing") { out = ChooseSubAction{"build_fences"}; return true; }
  if (sid == "major_improvement") {
    if (can_afford_any_major(s, p)) { out = ChooseSubAction{"improvement"}; return true; }
    return false;
  }
  throw std::runtime_error("Unknown sub-action space host " + sid);
}

std::vector<Action> enum_subactionspace(const GameState& s,
                                        const PendingSubActionSpace& pd) {
  // Generic Delegating space host (SPACE_HOST_REFACTOR.md §4.2). after-phase
  // (reached via the auto-advance once the child popped): Stop. before-phase: the
  // single mandatory ChooseSubAction (the child). The transient
  // subaction_complete && phase=="before" state is never enumerated — the
  // auto-advance flips it inside the same step.
  if (pd.phase == "after") return {Stop{}};
  std::vector<Action> a;
  ChooseSubAction choice{""};
  if (subactionspace_choice(s, pd, choice)) a.push_back(choice);
  return a;
}

std::vector<Action> enum_cultivation(const GameState& s,
                                     const PendingCultivation& pd) {
  // Proceed-host (and/or; SPACE_HOST_REFACTOR.md §4.3).
  if (pd.phase == "after") return {Stop{}};
  const auto& p = frame_player(s, pd.player_idx);
  std::vector<Action> a;
  if (!pd.plow_chosen && can_plow(p)) a.push_back(ChooseSubAction{"plow"});
  if (!pd.sow_chosen && can_sow(p)) a.push_back(ChooseSubAction{"sow"});
  if (pd.plow_chosen || pd.sow_chosen) a.push_back(Proceed{});
  return a;
}

std::vector<Action> enum_side_job(const GameState& s, const PendingSideJob& pd) {
  const auto& p = frame_player(s, pd.player_idx);
  std::vector<Action> a;
  Resources cost; cost.wood = 1;
  if (!pd.stable_chosen && can_build_stable(p, cost))
    a.push_back(ChooseSubAction{"build_stables"});
  if (!pd.bake_chosen && can_bake_bread(s, p))
    a.push_back(ChooseSubAction{"bake_bread"});
  if (pd.stable_chosen || pd.bake_chosen) a.push_back(Stop{});
  return a;
}

std::vector<Action> enum_animal_market(const GameState& s, int pid,
                                       const Animals& gained) {
  const auto& p = s.players[pid];
  auto cr = cooking_rates(s, pid);
  std::array<int, 3> rates3{cr[0], cr[1], cr[2]};
  auto frontier = pareto_frontier(p, gained, rates3);
  std::vector<Action> a;
  for (const auto& [cfg, food] : frontier)
    a.push_back(CommitAccommodate{cfg[0], cfg[1], cfg[2]});
  return a;
}

std::vector<Action> enum_major_minor(const GameState& s,
                                     const PendingMajorMinorImprovement& pd) {
  // Delegating host (SPACE_HOST_REFACTOR.md §4.2/§6). after-phase (reached via the
  // auto-advance once the child popped): Stop. before-phase: the exclusive
  // build_major / play_minor choice (Family: only build_major). The transient
  // subaction_complete state is never enumerated (the auto-advance flips it).
  if (pd.phase == "after") return {Stop{}};
  const auto& p = frame_player(s, pd.player_idx);
  std::vector<Action> a;
  if (!pd.major_chosen && can_afford_any_major(s, p))
    a.push_back(ChooseSubAction{"build_major"});
  return a;
}

std::vector<Action> enum_clay_oven(const GameState& s, const PendingClayOven& pd) {
  const auto& p = frame_player(s, pd.player_idx);
  std::vector<Action> a{Stop{}};
  if (!pd.bake_chosen && can_bake_bread(s, p))
    a.push_back(ChooseSubAction{"bake_bread"});
  return a;
}

std::vector<Action> enum_stone_oven(const GameState& s,
                                    const PendingStoneOven& pd) {
  const auto& p = frame_player(s, pd.player_idx);
  std::vector<Action> a{Stop{}};
  if (!pd.bake_chosen && can_bake_bread(s, p))
    a.push_back(ChooseSubAction{"bake_bread"});
  return a;
}

std::vector<Action> enum_house_redev(const GameState& s,
                                     const PendingHouseRedevelopment& pd) {
  // Proceed-host (and-then; SPACE_HOST_REFACTOR.md §4.3).
  if (pd.phase == "after") return {Stop{}};
  const auto& p = frame_player(s, pd.player_idx);
  std::vector<Action> a;
  if (!pd.renovate_chosen && can_renovate(p))
    a.push_back(ChooseSubAction{"renovate"});
  if (pd.renovate_chosen && !pd.improvement_chosen && can_afford_any_major(s, p))
    a.push_back(ChooseSubAction{"improvement"});
  if (pd.renovate_chosen) a.push_back(Proceed{});
  return a;
}

std::vector<Action> enum_build_fences(const GameState& s,
                                      const PendingBuildFences& pd) {
  // before/after host (mirrors enum_build_stables/_rooms): after-phase =
  // triggers (none in Family) + Stop; before-phase = pasture commits, then
  // Proceed (the multi-shot work-complete flip) once at least one is built.
  if (pd.phase == "after") return {Stop{}};
  const auto& p = frame_player(s, pd.player_idx);
  FenceScanCtx ctx =
      make_ctx(p.farmyard, p.resources.wood, pd.subdivision_started);
  std::vector<Action> a;
  for (const auto& entry : restricted_universe_entries())
    if (check_entry_legal(entry, ctx))
      a.push_back(CommitBuildPasture{entry.cells});
  if (pd.pastures_built >= 1) a.push_back(Proceed{});
  return a;
}

std::vector<Action> enum_farm_redev(const GameState& s,
                                    const PendingFarmRedevelopment& pd) {
  // Proceed-host (and-then; SPACE_HOST_REFACTOR.md §4.3).
  if (pd.phase == "after") return {Stop{}};
  const auto& p = frame_player(s, pd.player_idx);
  std::vector<Action> a;
  if (!pd.renovate_chosen && can_renovate(p))
    a.push_back(ChooseSubAction{"renovate"});
  if (pd.renovate_chosen && !pd.build_fences_chosen &&
      any_legal_pasture_commit(p))
    a.push_back(ChooseSubAction{"build_fences"});
  if (pd.renovate_chosen) a.push_back(Proceed{});
  return a;
}

// Harvest conversions: the 3 built-in crafts, in registry insertion order
// (joinery, pottery, basketmaker), mapped to majors 7/8/9.
struct HarvestConv {
  const char* id;
  Resources input_cost;
  int major_idx;
};
const std::array<HarvestConv, 3> kHarvestConvs{{
    {"joinery", [] { Resources r; r.wood = 1; return r; }(), 7},
    {"pottery", [] { Resources r; r.clay = 1; return r; }(), 8},
    {"basketmaker", [] { Resources r; r.reed = 1; return r; }(), 9},
}};

std::vector<Action> enum_harvest_feed(const GameState& s,
                                      const PendingHarvestFeed& pd) {
  const auto& p = frame_player(s, pd.player_idx);
  int pid = *pd.player_idx;
  std::vector<Action> a;
  if (pd.conversion_done) { a.push_back(Stop{}); return a; }

  // 1. Undecided owned + affordable conversions.
  const auto& owners = s.board.major_improvement_owners;
  for (const auto& hc : kHarvestConvs) {
    bool used = std::find(p.harvest_conversions_used.begin(),
                          p.harvest_conversions_used.end(),
                          std::string(hc.id)) !=
                p.harvest_conversions_used.end();
    if (used) continue;
    bool owned = owners[hc.major_idx].has_value() &&
                 *owners[hc.major_idx] == pid;
    if (!owned) continue;
    if (can_afford(p, hc.input_cost))
      a.push_back(CommitHarvestConversion{hc.id});
  }

  // 2. CommitConvert points from harvest_feed_frontier (consumed = pre - rem).
  auto rates = cooking_rates(s, pid);
  int need = 2 * p.people_total - p.newborns;
  int food_owed = std::max(0, need - p.resources.food);
  int grain_pre = p.resources.grain;
  int veg_pre = p.resources.veg;
  int sheep_pre = p.animals.sheep;
  int boar_pre = p.animals.boar;
  int cattle_pre = p.animals.cattle;
  for (const auto& [rem, beg] : harvest_feed_frontier(p, food_owed, rates)) {
    a.push_back(CommitConvert{grain_pre - rem[0], veg_pre - rem[1],
                              sheep_pre - rem[2], boar_pre - rem[3],
                              cattle_pre - rem[4]});
  }
  return a;
}

std::vector<Action> enum_harvest_breed(const GameState& s,
                                       const PendingHarvestBreed& pd) {
  const auto& p = frame_player(s, pd.player_idx);
  int pid = *pd.player_idx;
  std::vector<Action> a;
  if (pd.breed_chosen) { a.push_back(Stop{}); return a; }
  auto cr = cooking_rates(s, pid);
  std::array<int, 3> rates3{cr[0], cr[1], cr[2]};
  for (const auto& [cfg, food] : breeding_frontier(p, rates3))
    a.push_back(CommitBreed{cfg[0], cfg[1], cfg[2]});
  return a;
}

std::vector<Action> enum_reveal(const GameState& s, const PendingReveal&) {
  int stage = stage_of_round(s.round_number + 1);
  std::vector<Action> a;
  for (const auto& c : STAGE_CARDS[stage])
    if (!get_space(s, c).revealed) a.push_back(RevealCard{c});
  return a;
}

std::vector<Action> enumerate_pending(const GameState& s,
                                      const PendingDecision& top) {
  return std::visit(
      [&](const auto& pd) -> std::vector<Action> {
        using T = std::decay_t<decltype(pd)>;
        if constexpr (std::is_same_v<T, PendingGrainUtilization>)
          return enum_grain_utilization(s, pd);
        else if constexpr (std::is_same_v<T, PendingSow>)
          return enum_sow(s, pd);
        else if constexpr (std::is_same_v<T, PendingBakeBread>)
          return enum_bake_bread(s, pd);
        else if constexpr (std::is_same_v<T, PendingPlow>)
          return enum_plow(s, pd);
        else if constexpr (std::is_same_v<T, PendingBuildStables>)
          return enum_build_stables(s, pd);
        else if constexpr (std::is_same_v<T, PendingBuildRooms>)
          return enum_build_rooms(s, pd);
        else if constexpr (std::is_same_v<T, PendingBuildMajor>)
          return enum_build_major(s, pd);
        else if constexpr (std::is_same_v<T, PendingRenovate>)
          return enum_renovate(s, pd);
        else if constexpr (std::is_same_v<T, PendingFarmExpansion>)
          return enum_farm_expansion(s, pd);
        else if constexpr (std::is_same_v<T, PendingSubActionSpace>)
          return enum_subactionspace(s, pd);
        else if constexpr (std::is_same_v<T, PendingCultivation>)
          return enum_cultivation(s, pd);
        else if constexpr (std::is_same_v<T, PendingSideJob>)
          return enum_side_job(s, pd);
        else if constexpr (std::is_same_v<T, PendingSheepMarket>)
          return pd.phase == "after" ? std::vector<Action>{Stop{}}
                 : enum_animal_market(s, *pd.player_idx, Animals{pd.gained, 0, 0});
        else if constexpr (std::is_same_v<T, PendingPigMarket>)
          return pd.phase == "after" ? std::vector<Action>{Stop{}}
                 : enum_animal_market(s, *pd.player_idx, Animals{0, pd.gained, 0});
        else if constexpr (std::is_same_v<T, PendingCattleMarket>)
          return pd.phase == "after" ? std::vector<Action>{Stop{}}
                 : enum_animal_market(s, *pd.player_idx, Animals{0, 0, pd.gained});
        else if constexpr (std::is_same_v<T, PendingMajorMinorImprovement>)
          return enum_major_minor(s, pd);
        else if constexpr (std::is_same_v<T, PendingClayOven>)
          return enum_clay_oven(s, pd);
        else if constexpr (std::is_same_v<T, PendingStoneOven>)
          return enum_stone_oven(s, pd);
        else if constexpr (std::is_same_v<T, PendingHouseRedevelopment>)
          return enum_house_redev(s, pd);
        else if constexpr (std::is_same_v<T, PendingBuildFences>)
          return enum_build_fences(s, pd);
        else if constexpr (std::is_same_v<T, PendingFarmRedevelopment>)
          return enum_farm_redev(s, pd);
        else if constexpr (std::is_same_v<T, PendingHarvestFeed>)
          return enum_harvest_feed(s, pd);
        else if constexpr (std::is_same_v<T, PendingHarvestBreed>)
          return enum_harvest_breed(s, pd);
        else if constexpr (std::is_same_v<T, PendingReveal>)
          return enum_reveal(s, pd);
        else
          return {};
      },
      top);
}

}  // namespace

std::vector<Action> legal_actions(const GameState& state) {
  if (!state.pending_stack.empty())
    return enumerate_pending(state, state.pending_stack.back());
  if (state.phase == Phase::BEFORE_SCORING) return {};
  if (state.phase == Phase::WORK) return legal_placements(state);
  return {};  // other phases never surface to the agent
}

}  // namespace agricola
