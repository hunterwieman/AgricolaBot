// Scoring + tiebreaker — a faithful port of agricola/scoring.py (Stage 3).
// 15 scoring categories + craft bonus; the tiebreaker subtracts the craft spend
// recomputed independently (CPP_ENGINE_PLAN.md §5.4).
#include "agricola/scoring.hpp"

#include <algorithm>
#include <array>
#include <set>

#include "agricola/types.hpp"

namespace agricola {
namespace {

const std::array<int, 10> MAJOR_IMPROVEMENT_POINTS{1, 1, 1, 1, 4,
                                                   2, 3, 2, 2, 2};

int score_field_tiles(int n) {
  if (n <= 1) return -1;
  if (n == 2) return 1;
  if (n == 3) return 2;
  if (n == 4) return 3;
  return 4;
}
int score_pastures(int n) {
  if (n == 0) return -1;
  return std::min(n, 4);
}
int score_grain(int n) {
  if (n == 0) return -1;
  if (n <= 3) return 1;
  if (n <= 5) return 2;
  if (n <= 7) return 3;
  return 4;
}
int score_veg(int n) {
  if (n == 0) return -1;
  return std::min(n, 4);
}
int score_sheep(int n) {
  if (n == 0) return -1;
  if (n <= 3) return 1;
  if (n <= 5) return 2;
  if (n <= 7) return 3;
  return 4;
}
int score_boar(int n) {
  if (n == 0) return -1;
  if (n <= 2) return 1;
  if (n <= 4) return 2;
  if (n <= 6) return 3;
  return 4;
}
int score_cattle(int n) {
  if (n == 0) return -1;
  if (n == 1) return 1;
  if (n <= 3) return 2;
  if (n <= 5) return 3;
  return 4;
}

// Craft building bonus points + resources consumed to earn them.
// _CRAFT_BONUSES: 7 Joinery (wood), 8 Pottery (clay), 9 Basketmaker's (reed).
struct CraftSpend {
  int bonus = 0;
  int wood = 0;
  int clay = 0;
  int reed = 0;
};

CraftSpend craft_bonus_spending(const GameState& state, int player_idx) {
  const Resources& res = state.players[static_cast<size_t>(player_idx)].resources;
  int wood = res.wood, clay = res.clay, reed = res.reed;
  const auto& owners = state.board.major_improvement_owners;
  auto owns = [&](int i) {
    return owners[static_cast<size_t>(i)].has_value() &&
           *owners[static_cast<size_t>(i)] == player_idx;
  };
  CraftSpend out;
  // Joinery (idx 7, wood) thresholds (7,3),(5,2),(3,1) highest first.
  if (owns(7)) {
    if (wood >= 7) { out.bonus += 3; out.wood += 7; }
    else if (wood >= 5) { out.bonus += 2; out.wood += 5; }
    else if (wood >= 3) { out.bonus += 1; out.wood += 3; }
  }
  // Pottery (idx 8, clay) thresholds (7,3),(5,2),(3,1).
  if (owns(8)) {
    if (clay >= 7) { out.bonus += 3; out.clay += 7; }
    else if (clay >= 5) { out.bonus += 2; out.clay += 5; }
    else if (clay >= 3) { out.bonus += 1; out.clay += 3; }
  }
  // Basketmaker's (idx 9, reed) thresholds (5,3),(4,2),(2,1).
  if (owns(9)) {
    if (reed >= 5) { out.bonus += 3; out.reed += 5; }
    else if (reed >= 4) { out.bonus += 2; out.reed += 4; }
    else if (reed >= 2) { out.bonus += 1; out.reed += 2; }
  }
  return out;
}

}  // namespace

int score(const GameState& state, int player_idx) {
  const PlayerState& ps = state.players[static_cast<size_t>(player_idx)];
  const Farmyard& fy = ps.farmyard;
  const auto& grid = fy.grid;
  const auto& pastures = fy.pastures;

  int num_fields = 0, total_grain_field = 0, total_veg_field = 0;
  for (int r = 0; r < kRows; ++r)
    for (int c = 0; c < kCols; ++c) {
      const Cell& cell = grid[static_cast<size_t>(r)][static_cast<size_t>(c)];
      if (cell.cell_type == CellType::FIELD) {
        ++num_fields;
        total_grain_field += cell.grain;
        total_veg_field += cell.veg;
      }
    }

  int pts = 0;
  pts += score_field_tiles(num_fields);
  pts += score_pastures(static_cast<int>(pastures.size()));
  pts += score_grain(ps.resources.grain + total_grain_field);
  pts += score_veg(ps.resources.veg + total_veg_field);
  pts += score_sheep(ps.animals.sheep);
  pts += score_boar(ps.animals.boar);
  pts += score_cattle(ps.animals.cattle);

  // Enclosed cells.
  std::set<Coord> enclosed;
  for (const auto& p : pastures)
    for (const auto& cell : p.cells) enclosed.insert(cell);

  // Unused empty farmyard spaces (not enclosed). Always <= 0.
  int unused = 0;
  for (int r = 0; r < kRows; ++r)
    for (int c = 0; c < kCols; ++c) {
      const Cell& cell = grid[static_cast<size_t>(r)][static_cast<size_t>(c)];
      if (cell.cell_type == CellType::EMPTY &&
          enclosed.find({r, c}) == enclosed.end())
        ++unused;
    }
  pts += -unused;

  // Fenced stables: stables inside any pasture.
  int fenced_stables = 0;
  for (const auto& p : pastures)
    for (const auto& [r, c] : p.cells)
      if (grid[static_cast<size_t>(r)][static_cast<size_t>(c)].cell_type ==
          CellType::STABLE)
        ++fenced_stables;
  pts += std::min(fenced_stables, 4);

  // Clay / stone rooms.
  int num_rooms = 0;
  for (int r = 0; r < kRows; ++r)
    for (int c = 0; c < kCols; ++c)
      if (grid[static_cast<size_t>(r)][static_cast<size_t>(c)].cell_type ==
          CellType::ROOM)
        ++num_rooms;
  if (ps.house_material == HouseMaterial::CLAY)
    pts += num_rooms * 1;
  else if (ps.house_material == HouseMaterial::STONE)
    pts += num_rooms * 2;

  // People, begging.
  pts += ps.people_total * 3;
  pts += ps.begging_markers * -3;

  // Major improvement points.
  for (int i = 0; i < 10; ++i)
    if (state.board.major_improvement_owners[static_cast<size_t>(i)]
            .has_value() &&
        *state.board.major_improvement_owners[static_cast<size_t>(i)] ==
            player_idx)
      pts += MAJOR_IMPROVEMENT_POINTS[static_cast<size_t>(i)];

  // Craft bonus.
  pts += craft_bonus_spending(state, player_idx).bonus;
  return pts;
}

int tiebreaker(const GameState& state, int player_idx) {
  const Resources& res = state.players[static_cast<size_t>(player_idx)].resources;
  CraftSpend spent = craft_bonus_spending(state, player_idx);
  return (res.wood - spent.wood) + (res.clay - spent.clay) +
         (res.reed - spent.reed) + res.stone;
}

}  // namespace agricola
