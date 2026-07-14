// Resolution handlers — a faithful port of agricola/resolution.py (Stage 3).
//
// Atomic _resolve_<space>, non-atomic _initiate_<space> + _choose_subaction_*,
// and the _execute_<subaction> effect functions. Recomputes farmyard.pastures
// ONLY in build_stable + build_pasture (the two pasture-changing effects), per
// CPP_ENGINE_PLAN.md §5.4.
#include "agricola/resolution.hpp"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <variant>
#include <vector>

#include "agricola/constants.hpp"
#include "agricola/fences.hpp"
#include "agricola/helpers.hpp"
#include "agricola/pasture.hpp"
#include "agricola/state_ops.hpp"

namespace agricola {

// --- Resources / Animals arithmetic (mirrors Python __add__/__sub__) ---------
Resources operator+(const Resources& a, const Resources& b) {
  return Resources{a.wood + b.wood, a.clay + b.clay, a.reed + b.reed,
                   a.stone + b.stone, a.food + b.food, a.grain + b.grain,
                   a.veg + b.veg};
}
Resources operator-(const Resources& a, const Resources& b) {
  return Resources{a.wood - b.wood, a.clay - b.clay, a.reed - b.reed,
                   a.stone - b.stone, a.food - b.food, a.grain - b.grain,
                   a.veg - b.veg};
}

using Grid = std::array<std::array<Cell, kCols>, kRows>;

namespace {

// Replace grid[row][col] with `cell`, returning a new grid.
Grid grid_with_cell(const Grid& grid, int row, int col, const Cell& cell) {
  Grid out = grid;
  out[static_cast<size_t>(row)][static_cast<size_t>(col)] = cell;
  return out;
}

}  // namespace

// ===========================================================================
// Cross-cutting worker placement.
// ===========================================================================
GameState apply_worker_placement(const GameState& state_in,
                                 const std::string& space_id) {
  GameState state = state_in;
  int ap = state.current_player;
  const ActionSpaceState& sp = get_space_ref(state, space_id);
  ActionSpaceState ns = sp;
  ns.workers[static_cast<size_t>(ap)] += 1;
  state = with_space(state, space_id, ns);
  PlayerState p = state.players[static_cast<size_t>(ap)];
  p.people_home -= 1;
  return update_player(state, ap, p);
}

// ===========================================================================
// Atomic handlers.
// ===========================================================================
namespace {

GameState resolve_building_accum(const GameState& state, const std::string& id) {
  int ap = state.current_player;
  PlayerState p = state.players[static_cast<size_t>(ap)];
  const ActionSpaceState& sp = get_space_ref(state, id);
  p.resources = p.resources + sp.accumulated;
  GameState s = update_player(state, ap, p);
  ActionSpaceState ns = get_space_ref(s, id);
  ns.accumulated = Resources{};
  return with_space(s, id, ns);
}

GameState resolve_food_accum(const GameState& state, const std::string& id) {
  int ap = state.current_player;
  PlayerState p = state.players[static_cast<size_t>(ap)];
  const ActionSpaceState& sp = get_space_ref(state, id);
  p.resources = p.resources + Resources{0, 0, 0, 0, sp.accumulated_amount, 0, 0};
  GameState s = update_player(state, ap, p);
  ActionSpaceState ns = get_space_ref(s, id);
  ns.accumulated_amount = 0;
  return with_space(s, id, ns);
}

GameState resolve_day_laborer(const GameState& state) {
  int ap = state.current_player;
  PlayerState p = state.players[static_cast<size_t>(ap)];
  p.resources = p.resources + Resources{0, 0, 0, 0, 2, 0, 0};
  return update_player(state, ap, p);
}
GameState resolve_grain_seeds(const GameState& state) {
  int ap = state.current_player;
  PlayerState p = state.players[static_cast<size_t>(ap)];
  p.resources = p.resources + Resources{0, 0, 0, 0, 0, 1, 0};
  return update_player(state, ap, p);
}
GameState resolve_vegetable_seeds(const GameState& state) {
  int ap = state.current_player;
  PlayerState p = state.players[static_cast<size_t>(ap)];
  p.resources = p.resources + Resources{0, 0, 0, 0, 0, 0, 1};
  return update_player(state, ap, p);
}
GameState resolve_meeting_place(const GameState& state) {
  int ap = state.current_player;
  GameState s = resolve_food_accum(state, "meeting_place");
  s.starting_player = ap;
  return s;
}

GameState resolve_wish_for_children(const GameState& state,
                                    const std::string& id) {
  // Worker already placed (parent). Add the newborn's second worker on the
  // same space; bump people_total + newborns (NOT people_home for the newborn).
  int ap = state.current_player;
  ActionSpaceState ns = get_space_ref(state, id);
  ns.workers[static_cast<size_t>(ap)] += 1;
  GameState s = with_space(state, id, ns);
  PlayerState p = s.players[static_cast<size_t>(ap)];
  p.people_total += 1;
  p.newborns += 1;
  return update_player(s, ap, p);
}

}  // namespace

GameState resolve_atomic(const GameState& state, const std::string& space_id) {
  if (space_id == "day_laborer") return resolve_day_laborer(state);
  if (space_id == "fishing") return resolve_food_accum(state, "fishing");
  if (space_id == "forest") return resolve_building_accum(state, "forest");
  if (space_id == "clay_pit") return resolve_building_accum(state, "clay_pit");
  if (space_id == "reed_bank") return resolve_building_accum(state, "reed_bank");
  if (space_id == "grain_seeds") return resolve_grain_seeds(state);
  if (space_id == "meeting_place") return resolve_meeting_place(state);
  if (space_id == "western_quarry")
    return resolve_building_accum(state, "western_quarry");
  if (space_id == "vegetable_seeds") return resolve_vegetable_seeds(state);
  if (space_id == "eastern_quarry")
    return resolve_building_accum(state, "eastern_quarry");
  if (space_id == "basic_wish_for_children")
    return resolve_wish_for_children(state, "basic_wish_for_children");
  if (space_id == "urgent_wish_for_children")
    return resolve_wish_for_children(state, "urgent_wish_for_children");
  throw std::runtime_error("resolve_atomic: unknown space " + space_id);
}

bool is_atomic_space(const std::string& id) {
  return id == "day_laborer" || id == "fishing" || id == "forest" ||
         id == "clay_pit" || id == "reed_bank" || id == "grain_seeds" ||
         id == "meeting_place" || id == "western_quarry" ||
         id == "vegetable_seeds" || id == "eastern_quarry" ||
         id == "basic_wish_for_children" || id == "urgent_wish_for_children";
}

// ===========================================================================
// Non-atomic initiators (push the parent pending).
// ===========================================================================
GameState initiate_nonatomic(const GameState& state, const std::string& id) {
  int ap = state.current_player;
  if (id == "grain_utilization")
    return push(state,
                PendingGrainUtilization{ap, "space:grain_utilization"});
  if (id == "farmland")
    return push(state, PendingSubActionSpace{ap, "space:farmland"});
  if (id == "cultivation")
    return push(state, PendingCultivation{ap, "space:cultivation"});
  if (id == "side_job") return push(state, PendingSideJob{ap, "space:side_job"});
  if (id == "sheep_market") {
    int gained = get_space_ref(state, "sheep_market").accumulated_amount;
    ActionSpaceState ns = get_space_ref(state, "sheep_market");
    ns.accumulated_amount = 0;
    GameState s = with_space(state, "sheep_market", ns);
    PendingSheepMarket frame;
    frame.player_idx = ap;
    frame.initiated_by_id = "space:sheep_market";
    frame.gained = gained;
    return push(s, frame);
  }
  if (id == "pig_market") {
    int gained = get_space_ref(state, "pig_market").accumulated_amount;
    ActionSpaceState ns = get_space_ref(state, "pig_market");
    ns.accumulated_amount = 0;
    GameState s = with_space(state, "pig_market", ns);
    PendingPigMarket frame;
    frame.player_idx = ap;
    frame.initiated_by_id = "space:pig_market";
    frame.gained = gained;
    return push(s, frame);
  }
  if (id == "cattle_market") {
    int gained = get_space_ref(state, "cattle_market").accumulated_amount;
    ActionSpaceState ns = get_space_ref(state, "cattle_market");
    ns.accumulated_amount = 0;
    GameState s = with_space(state, "cattle_market", ns);
    PendingCattleMarket frame;
    frame.player_idx = ap;
    frame.initiated_by_id = "space:cattle_market";
    frame.gained = gained;
    return push(s, frame);
  }
  if (id == "major_improvement")
    return push(state,
                PendingSubActionSpace{ap, "space:major_improvement"});
  if (id == "house_redevelopment")
    return push(state,
                PendingHouseRedevelopment{ap, "space:house_redevelopment"});
  if (id == "farm_expansion")
    return push(state, PendingFarmExpansion{ap, "space:farm_expansion"});
  if (id == "fencing")
    return push(state, PendingSubActionSpace{ap, "space:fencing"});
  if (id == "farm_redevelopment")
    return push(state,
                PendingFarmRedevelopment{ap, "space:farm_redevelopment"});
  throw std::runtime_error("initiate_nonatomic: unknown space " + id);
}

bool is_nonatomic_space(const std::string& id) {
  return id == "grain_utilization" || id == "farmland" || id == "cultivation" ||
         id == "side_job" || id == "sheep_market" || id == "pig_market" ||
         id == "cattle_market" || id == "major_improvement" ||
         id == "house_redevelopment" || id == "farm_expansion" ||
         id == "fencing" || id == "farm_redevelopment";
}

// ===========================================================================
// Choose-sub-action handlers (dispatch on the top pending's variant index).
// ===========================================================================
namespace {

// PENDING_ID string for each parent pending (mirrors the ClassVar PENDING_ID;
// used as the inner pending's initiated_by_id).
template <typename T>
std::string pending_id();

template <>
std::string pending_id<PendingGrainUtilization>() { return "grain_utilization"; }
template <>
std::string pending_id<PendingCultivation>() { return "cultivation"; }
template <>
std::string pending_id<PendingSideJob>() { return "side_job"; }
template <>
std::string pending_id<PendingMajorMinorImprovement>() {
  return "major_minor_improvement";
}
template <>
std::string pending_id<PendingClayOven>() { return "clay_oven"; }
template <>
std::string pending_id<PendingStoneOven>() { return "stone_oven"; }
template <>
std::string pending_id<PendingHouseRedevelopment>() {
  return "house_redevelopment";
}
template <>
std::string pending_id<PendingFarmExpansion>() { return "farm_expansion"; }
template <>
std::string pending_id<PendingFarmRedevelopment>() {
  return "farm_redevelopment";
}

}  // namespace

GameState choose_subaction(const GameState& state, const ChooseSubAction& act) {
  const PendingDecision& top = state.pending_stack.back();
  const std::string& name = act.name;

  if (auto* g = std::get_if<PendingGrainUtilization>(&top)) {
    PendingGrainUtilization nt = *g;
    if (name == "sow") {
      nt.sow_chosen = true;
      GameState s = replace_top(state, nt);
      return push(s, PendingSow{nt.player_idx,
                                pending_id<PendingGrainUtilization>()});
    }
    if (name == "bake_bread") {
      nt.bake_chosen = true;
      GameState s = replace_top(state, nt);
      return push(s, PendingBakeBread{nt.player_idx,
                                      pending_id<PendingGrainUtilization>()});
    }
  } else if (auto* sas = std::get_if<PendingSubActionSpace>(&top)) {
    // Generic Delegating space host (SPACE_HOST_REFACTOR.md §4.2/§8): set
    // subaction_complete and push the single mandatory child, dispatched by
    // space_id. The child's initiated_by_id carries the space's id (not the
    // generic "action_space" PENDING_ID) so existing provenance is preserved
    // (e.g. PendingPlow.initiated_by_id == "farmland").
    PendingSubActionSpace nt = *sas;
    const std::string sid = nt.space_id();
    nt.subaction_complete = true;
    GameState s = replace_top(state, nt);
    if (sid == "farmland" && name == "plow")
      return push(s, PendingPlow{nt.player_idx, "farmland"});
    if (sid == "fencing" && name == "build_fences")
      return push(s, PendingBuildFences{nt.player_idx, "fencing"});
    if (sid == "major_improvement" && name == "improvement")
      // Preserve the composite host's provenance "space:major_improvement"
      // (the host's full initiated_by_id), distinct from the House-Redev path's
      // "house_redevelopment".
      return push(s, PendingMajorMinorImprovement{nt.player_idx,
                                                  nt.initiated_by_id});
    throw std::runtime_error("choose_subaction: unknown sub-action " + name +
                             " for space host " + sid);
  } else if (auto* c = std::get_if<PendingCultivation>(&top)) {
    PendingCultivation nt = *c;
    if (name == "plow") {
      nt.plow_chosen = true;
      GameState s = replace_top(state, nt);
      return push(
          s, PendingPlow{nt.player_idx, pending_id<PendingCultivation>()});
    }
    if (name == "sow") {
      nt.sow_chosen = true;
      GameState s = replace_top(state, nt);
      return push(
          s, PendingSow{nt.player_idx, pending_id<PendingCultivation>()});
    }
  } else if (auto* sj = std::get_if<PendingSideJob>(&top)) {
    PendingSideJob nt = *sj;
    if (name == "build_stables") {
      nt.stable_chosen = true;
      GameState s = replace_top(state, nt);
      PendingBuildStables frame;
      frame.player_idx = nt.player_idx;
      frame.initiated_by_id = pending_id<PendingSideJob>();
      frame.cost = Resources{1, 0, 0, 0, 0, 0, 0};  // wood=1
      frame.max_builds = 1;
      frame.num_built = 0;
      return push(s, frame);
    }
    if (name == "bake_bread") {
      nt.bake_chosen = true;
      GameState s = replace_top(state, nt);
      return push(s, PendingBakeBread{nt.player_idx,
                                      pending_id<PendingSideJob>()});
    }
  } else if (auto* mm = std::get_if<PendingMajorMinorImprovement>(&top)) {
    if (name == "build_major") {
      PendingMajorMinorImprovement nt = *mm;
      nt.major_chosen = true;
      GameState s = replace_top(state, nt);
      return push(s, PendingBuildMajor{nt.player_idx,
                                       pending_id<PendingMajorMinorImprovement>()});
    }
    // "play_minor" not in Family scope.
  } else if (auto* co = std::get_if<PendingClayOven>(&top)) {
    if (name == "bake_bread") {
      PendingClayOven nt = *co;
      nt.bake_chosen = true;
      GameState s = replace_top(state, nt);
      return push(s, PendingBakeBread{nt.player_idx,
                                      pending_id<PendingClayOven>()});
    }
  } else if (auto* so = std::get_if<PendingStoneOven>(&top)) {
    if (name == "bake_bread") {
      PendingStoneOven nt = *so;
      nt.bake_chosen = true;
      GameState s = replace_top(state, nt);
      return push(s, PendingBakeBread{nt.player_idx,
                                      pending_id<PendingStoneOven>()});
    }
  } else if (auto* hr = std::get_if<PendingHouseRedevelopment>(&top)) {
    PendingHouseRedevelopment nt = *hr;
    if (name == "renovate") {
      nt.renovate_chosen = true;
      GameState s = replace_top(state, nt);
      return push(s, PendingRenovate{nt.player_idx,
                                     pending_id<PendingHouseRedevelopment>()});
    }
    if (name == "improvement") {
      nt.improvement_chosen = true;
      GameState s = replace_top(state, nt);
      return push(s, PendingMajorMinorImprovement{
                         nt.player_idx,
                         pending_id<PendingHouseRedevelopment>()});
    }
  } else if (auto* fe = std::get_if<PendingFarmExpansion>(&top)) {
    PendingFarmExpansion nt = *fe;
    if (name == "build_rooms") {
      nt.room_chosen = true;
      GameState s = replace_top(state, nt);
      PendingBuildRooms frame;
      frame.player_idx = nt.player_idx;
      frame.initiated_by_id = pending_id<PendingFarmExpansion>();
      frame.max_builds = std::nullopt;
      frame.num_built = 0;
      return push(s, frame);
    }
    if (name == "build_stables") {
      nt.stable_chosen = true;
      GameState s = replace_top(state, nt);
      PendingBuildStables frame;
      frame.player_idx = nt.player_idx;
      frame.initiated_by_id = pending_id<PendingFarmExpansion>();
      frame.cost = Resources{2, 0, 0, 0, 0, 0, 0};  // wood=2
      frame.max_builds = std::nullopt;
      frame.num_built = 0;
      return push(s, frame);
    }
  } else if (auto* fr = std::get_if<PendingFarmRedevelopment>(&top)) {
    PendingFarmRedevelopment nt = *fr;
    if (name == "renovate") {
      nt.renovate_chosen = true;
      GameState s = replace_top(state, nt);
      return push(s, PendingRenovate{nt.player_idx,
                                     pending_id<PendingFarmRedevelopment>()});
    }
    if (name == "build_fences") {
      nt.build_fences_chosen = true;
      GameState s = replace_top(state, nt);
      return push(s, PendingBuildFences{nt.player_idx,
                                        pending_id<PendingFarmRedevelopment>()});
    }
  }
  throw std::runtime_error("choose_subaction: no handler for name=" + name);
}

// ===========================================================================
// _execute_* effect functions.
// ===========================================================================

// Flip the top frame to phase="after" (no pop) — the C++ mirror of Python's
// _enter_after_phase. C++ Family has no automatic effects, so this is only the
// phase flip; the trailing Stop pops. (SUBACTION_HOOK_REFACTOR.md)
static GameState enter_after_phase(const GameState& state) {
  PendingDecision nt = state.pending_stack.back();
  std::visit([](auto& f) {
    if constexpr (requires { f.phase; }) { f.phase = "after"; }
    if constexpr (requires { f.effect_initiated; }) { f.effect_initiated = false; }
  }, nt);
  return replace_top(state, nt);
}

// Deferred after-flip (user ruling 2026-07-14, mirroring Python's
// _mark_effect_initiated): the commit executor marks the work applied; the
// advance loop flips the host to its after-phase once it is back on top —
// i.e. after anything the effect pushed (the ovens' free-bake wrapper) has
// resolved. For an effect that pushes nothing the flip happens within the
// same step, observably identical to the old inline flip.
static GameState mark_effect_initiated(const GameState& state) {
  PendingDecision nt = state.pending_stack.back();
  std::visit([](auto& f) {
    if constexpr (requires { f.effect_initiated; }) { f.effect_initiated = true; }
  }, nt);
  return replace_top(state, nt);
}

GameState execute_sow(const GameState& state, int player_idx,
                      const CommitSow& commit) {
  PlayerState p = state.players[static_cast<size_t>(player_idx)];
  p.resources =
      p.resources - Resources{0, 0, 0, 0, 0, commit.grain, commit.veg};
  int g_rem = commit.grain, v_rem = commit.veg;
  Grid grid = p.farmyard.grid;
  for (int r = 0; r < kRows; ++r)
    for (int c = 0; c < kCols; ++c) {
      Cell& cell = grid[static_cast<size_t>(r)][static_cast<size_t>(c)];
      if (cell.cell_type == CellType::FIELD && cell.grain == 0 &&
          cell.veg == 0) {
        if (g_rem > 0) {
          cell.grain = 3;
          --g_rem;
        } else if (v_rem > 0) {
          cell.veg = 2;
          --v_rem;
        }
      }
    }
  p.farmyard.grid = grid;
  return mark_effect_initiated(update_player(state, player_idx, p));
}

GameState execute_bake(const GameState& state, int player_idx,
                       const CommitBake& commit) {
  // Collect (cap, rate) specs for owned baking majors; consume rate-descending.
  std::vector<std::pair<std::optional<int>, int>> specs;
  const auto& owners = state.board.major_improvement_owners;
  for (int i = 0; i < 10; ++i) {
    auto sp = baking_spec_for_major(i);
    if (sp && owners[static_cast<size_t>(i)].has_value() &&
        *owners[static_cast<size_t>(i)] == player_idx)
      specs.emplace_back(sp->max_grain, sp->food_per_grain);
  }
  std::sort(specs.begin(), specs.end(),
            [](const auto& a, const auto& b) { return a.second > b.second; });
  int grain_remaining = commit.grain;
  int food = 0;
  for (const auto& [cap, rate] : specs) {
    int used = cap.has_value() ? std::min(*cap, grain_remaining) : grain_remaining;
    food += used * rate;
    grain_remaining -= used;
    if (grain_remaining == 0) break;
  }
  PlayerState p = state.players[static_cast<size_t>(player_idx)];
  p.resources = p.resources + Resources{0, 0, 0, 0, food, -commit.grain, 0};
  return mark_effect_initiated(update_player(state, player_idx, p));
}

GameState execute_plow(const GameState& state, int player_idx,
                       const CommitPlow& commit) {
  PlayerState p = state.players[static_cast<size_t>(player_idx)];
  Cell field;
  field.cell_type = CellType::FIELD;
  p.farmyard.grid =
      grid_with_cell(p.farmyard.grid, commit.row, commit.col, field);
  return mark_effect_initiated(update_player(state, player_idx, p));
}

GameState execute_build_stable(const GameState& state, int player_idx,
                               const CommitBuildStable& commit) {
  const PendingBuildStables& top =
      std::get<PendingBuildStables>(state.pending_stack.back());
  PlayerState p = state.players[static_cast<size_t>(player_idx)];
  Cell stable;
  stable.cell_type = CellType::STABLE;
  p.farmyard.grid =
      grid_with_cell(p.farmyard.grid, commit.row, commit.col, stable);
  p.farmyard.pastures = compute_pastures(p.farmyard);  // pasture-changing
  p.resources = p.resources - top.cost;
  GameState s = update_player(state, player_idx, p);
  PendingBuildStables nt = top;
  nt.num_built += 1;
  return replace_top(s, nt);
}

GameState execute_build_room(const GameState& state, int player_idx,
                             const CommitBuildRoom& commit) {
  const PendingBuildRooms& top =
      std::get<PendingBuildRooms>(state.pending_stack.back());
  PlayerState p = state.players[static_cast<size_t>(player_idx)];
  Cell room;
  room.cell_type = CellType::ROOM;
  p.farmyard.grid =
      grid_with_cell(p.farmyard.grid, commit.row, commit.col, room);
  // Room cost recomputed at build time (Family: singleton ROOM_COSTS) rather
  // than read from a stale frame cache (COST_MODIFIER_DESIGN.md §3.3).
  p.resources = p.resources - room_cost(p.house_material);
  GameState s = update_player(state, player_idx, p);
  PendingBuildRooms nt = top;
  nt.num_built += 1;
  return replace_top(s, nt);
}

GameState execute_renovate(const GameState& state, int player_idx,
                           const CommitRenovate& commit) {
  // Assert the frame type (the payment now rides on the commit, not the frame).
  (void)std::get<PendingRenovate>(state.pending_stack.back());
  PlayerState p = state.players[static_cast<size_t>(player_idx)];
  if (p.house_material == HouseMaterial::STONE)
    throw std::runtime_error("CommitRenovate illegal on stone house");
  // Upgrade to the chosen target tier (Family: == the derived next tier).
  p.house_material = commit.to_material;
  p.resources = p.resources - commit.payment;
  return mark_effect_initiated(update_player(state, player_idx, p));
}

GameState execute_build_major(const GameState& state, int player_idx,
                              const CommitBuildMajor& commit) {
  GameState s = state;

  // 1. Pay via the chosen PaymentOption: a ReturnImprovement returns a Fireplace
  //    (Cooking Hearth only); otherwise debit the Resources payment (the printed
  //    cost now rides on the commit, not read from MAJOR_IMPROVEMENT_COSTS).
  if (const auto* ri = std::get_if<ReturnImprovement>(&commit.payment)) {
    s.board.major_improvement_owners[static_cast<size_t>(ri->improvement_idx)] =
        std::nullopt;
  } else {
    PlayerState p = s.players[static_cast<size_t>(player_idx)];
    p.resources = p.resources - std::get<Resources>(commit.payment);
    s = update_player(s, player_idx, p);
  }

  // 2. Assign the new major.
  s.board.major_improvement_owners[static_cast<size_t>(commit.major_idx)] =
      player_idx;

  // 3. Well (idx 4): +1 food on each of the next 5 future_resources slots.
  if (commit.major_idx == 4) {
    PlayerState p = s.players[static_cast<size_t>(player_idx)];
    int end = std::min(s.round_number + 5, 14);
    for (int r = s.round_number; r < end; ++r)
      p.future_resources[static_cast<size_t>(r)] =
          p.future_resources[static_cast<size_t>(r)] +
          Resources{0, 0, 0, 0, 1, 0, 0};
    s = update_player(s, player_idx, p);
  }

  // 4. DEFER the after-flip (user ruling 2026-07-14): mark the work applied;
  //    the advance loop flips this host once any oven wrapper pushed below has
  //    fully resolved — mirroring Python. When the wrapper pops back, the flip
  //    happens before the next enumeration, so the frame then offers its
  //    after-phase Stop exactly as before. `phase=="after"` still carries what
  //    `build_chosen` used to.
  s = mark_effect_initiated(s);

  // 5. Oven wrappers, else leave the after-phase frame for its trailing Stop.
  if (commit.major_idx == 5)
    return push(s, PendingClayOven{player_idx, "build_major"});
  if (commit.major_idx == 6)
    return push(s, PendingStoneOven{player_idx, "build_major"});
  return s;
}

GameState execute_build_pasture(const GameState& state, int player_idx,
                                const CommitBuildPasture& commit) {
  PlayerState p = state.players[static_cast<size_t>(player_idx)];
  Farmyard fy = p.farmyard;

  // 1. Pack cells to bitmap (bit = r*NUM_COLS + c).
  std::uint32_t cells_bm = 0;
  for (const auto& [r, c] : commit.cells)
    cells_bm |= 1u << (r * kCols + c);

  // 2. New-pasture vs subdivision (pre-commit farmyard).
  std::uint32_t existing_bm = 0;
  for (const auto& past : fy.pastures)
    for (const auto& [r, c] : past.cells) existing_bm |= 1u << (r * kCols + c);
  bool is_subdivision = (cells_bm & existing_bm) != 0;

  // 3. New-edge deltas + cost.
  NewFenceEdges edges = compute_new_fence_edges(fy, cells_bm);

  // 4. Apply fence updates.
  fy.horizontal_fences =
      apply_fence_edges_h(fy.horizontal_fences, edges.h_new_bm);
  fy.vertical_fences = apply_fence_edges_v(fy.vertical_fences, edges.v_new_bm);

  // 5. Recompute pasture decomposition (pasture-changing).
  fy.pastures = compute_pastures(fy);

  // 6 + 7. Debit wood + decrement fence supply + update player.
  p.farmyard = fy;
  p.resources = p.resources - Resources{edges.wood_cost, 0, 0, 0, 0, 0, 0};
  p.fences_in_supply -= edges.wood_cost;  // new fence edges drawn from supply
  GameState s = update_player(state, player_idx, p);

  // 8. Bump counters + ordering flag.
  PendingBuildFences nt = std::get<PendingBuildFences>(s.pending_stack.back());
  nt.pastures_built += 1;
  nt.fences_built += edges.wood_cost;
  nt.subdivision_started = nt.subdivision_started || is_subdivision;
  return replace_top(s, nt);
}

GameState execute_accommodate(const GameState& state, int player_idx,
                              const CommitAccommodate& commit) {
  const PendingDecision& pending = state.pending_stack.back();
  PlayerState p = state.players[static_cast<size_t>(player_idx)];
  auto rates = cooking_rates(state, player_idx);  // (s,b,c,v)

  int s_gained = 0, b_gained = 0, c_gained = 0;
  if (auto* sm = std::get_if<PendingSheepMarket>(&pending))
    s_gained = sm->gained;
  else if (auto* pm = std::get_if<PendingPigMarket>(&pending))
    b_gained = pm->gained;
  else if (auto* cm = std::get_if<PendingCattleMarket>(&pending))
    c_gained = cm->gained;

  int s_avail = p.animals.sheep + s_gained;
  int b_avail = p.animals.boar + b_gained;
  int c_avail = p.animals.cattle + c_gained;

  int food = (s_avail - commit.sheep) * rates[0] +
             (b_avail - commit.boar) * rates[1] +
             (c_avail - commit.cattle) * rates[2];

  p.animals = Animals{commit.sheep, commit.boar, commit.cattle};
  p.resources = p.resources + Resources{0, 0, 0, 0, food, 0, 0};
  GameState s = update_player(state, player_idx, p);
  // Mark the work applied (no pop); the advance loop flips the frame within
  // this same step (the accommodate pushes nothing) — the deferred after-flip,
  // mirroring Python. The trailing Stop pops.
  return mark_effect_initiated(s);
}

GameState execute_harvest_conversion(const GameState& state, int player_idx,
                                     const CommitHarvestConversion& commit) {
  // The three Family-content conversions: joinery 1 wood->2 food,
  // pottery 1 clay->2 food, basketmaker 1 reed->3 food.
  Resources input_cost{};
  int food_out = 0;
  if (commit.conversion_id == "joinery") {
    input_cost = Resources{1, 0, 0, 0, 0, 0, 0};
    food_out = 2;
  } else if (commit.conversion_id == "pottery") {
    input_cost = Resources{0, 1, 0, 0, 0, 0, 0};
    food_out = 2;
  } else if (commit.conversion_id == "basketmaker") {
    input_cost = Resources{0, 0, 1, 0, 0, 0, 0};
    food_out = 3;
  } else {
    throw std::runtime_error("unknown harvest conversion " +
                             commit.conversion_id);
  }
  PlayerState p = state.players[static_cast<size_t>(player_idx)];
  p.resources = p.resources - input_cost + Resources{0, 0, 0, 0, food_out, 0, 0};
  // Mark used (frozenset -> sorted vector; keep sorted/uniq).
  if (std::find(p.harvest_conversions_used.begin(),
                p.harvest_conversions_used.end(),
                commit.conversion_id) == p.harvest_conversions_used.end()) {
    p.harvest_conversions_used.push_back(commit.conversion_id);
    std::sort(p.harvest_conversions_used.begin(),
              p.harvest_conversions_used.end());
  }
  return update_player(state, player_idx, p);
  // No side_effect_fn for the three built-in crafts; stack untouched — the
  // dispatcher never pops, so the host stays on top (Stop pops it).
}

GameState execute_convert(const GameState& state, int player_idx,
                          const CommitConvert& commit) {
  PendingHarvestFeed top =
      std::get<PendingHarvestFeed>(state.pending_stack.back());
  PlayerState p = state.players[static_cast<size_t>(player_idx)];
  auto rates = cooking_rates(state, player_idx);  // (s,b,c,v)
  int sR = rates[0], bR = rates[1], cR = rates[2], vR = rates[3];

  int food_produced = commit.grain + commit.veg * vR + commit.sheep * sR +
                      commit.boar * bR + commit.cattle * cR;

  int need = 2 * p.people_total - p.newborns;
  int total_available = p.resources.food + food_produced;
  int food_paid = std::min(need, total_available);
  int food_remaining = total_available - food_paid;
  int begging_added = need - food_paid;

  p.resources = Resources{p.resources.wood,
                          p.resources.clay,
                          p.resources.reed,
                          p.resources.stone,
                          food_remaining,
                          p.resources.grain - commit.grain,
                          p.resources.veg - commit.veg};
  p.animals = Animals{p.animals.sheep - commit.sheep,
                      p.animals.boar - commit.boar,
                      p.animals.cattle - commit.cattle};
  p.begging_markers += begging_added;
  GameState s = update_player(state, player_idx, p);
  top.conversion_done = true;
  return replace_top(s, top);
}

GameState execute_breed(const GameState& state, int player_idx,
                        const CommitBreed& commit) {
  PendingHarvestBreed top =
      std::get<PendingHarvestBreed>(state.pending_stack.back());
  PlayerState p = state.players[static_cast<size_t>(player_idx)];
  auto rates = cooking_rates(state, player_idx);
  int sR = rates[0], bR = rates[1], cR = rates[2];
  int s = p.animals.sheep, b = p.animals.boar, c = p.animals.cattle;
  int sF = commit.sheep, bF = commit.boar, cF = commit.cattle;
  // breeding_food_gained (helpers.py): if pre>=2 and post>=3, removals=(pre+1-post);
  // else removals=(pre-post). All removals converted to food at the rate.
  int food_s = (s >= 2 && sF >= 3) ? (s + 1 - sF) * sR : (s - sF) * sR;
  int food_b = (b >= 2 && bF >= 3) ? (b + 1 - bF) * bR : (b - bF) * bR;
  int food_c = (c >= 2 && cF >= 3) ? (c + 1 - cF) * cR : (c - cF) * cR;
  int food_gained = food_s + food_b + food_c;

  p.animals = Animals{commit.sheep, commit.boar, commit.cattle};
  p.resources = p.resources + Resources{0, 0, 0, 0, food_gained, 0, 0};
  GameState ns = update_player(state, player_idx, p);
  top.breed_chosen = true;
  return replace_top(ns, top);
}

}  // namespace agricola
