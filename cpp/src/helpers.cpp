// Level-0 baselines of agricola/helpers.py — set-identical to the optimized
// paths. We compute the same candidate sets and Pareto-filter them; only the
// SET matters for the legality gate (order is not required cross-language).
#include "agricola/helpers.hpp"

#include <cmath>

namespace agricola {

int fences_in_supply(const Farmyard& fy) {
  int built = 0;
  for (const auto& row : fy.horizontal_fences)
    for (bool b : row) built += b ? 1 : 0;
  for (const auto& row : fy.vertical_fences)
    for (bool b : row) built += b ? 1 : 0;
  return 15 - built;
}

int stables_in_supply(const Farmyard& fy) {
  int built = 0;
  for (int r = 0; r < 3; ++r)
    for (int c = 0; c < 5; ++c)
      if (fy.grid[r][c].cell_type == CellType::STABLE) ++built;
  return 4 - built;
}

std::array<int, 4> cooking_rates(const GameState& state, int player_idx) {
  const auto& owners = state.board.major_improvement_owners;
  auto owns = [&](int i) {
    return owners[i].has_value() && *owners[i] == player_idx;
  };
  bool has_hearth = owns(2) || owns(3);
  bool has_fireplace = owns(0) || owns(1);
  if (has_hearth) return {2, 3, 4, 3};
  if (has_fireplace) return {2, 2, 3, 2};
  return {0, 0, 0, 1};
}

std::set<Coord> enclosed_cells(const Farmyard& fy) {
  std::set<Coord> result;
  for (const auto& p : fy.pastures)
    for (const auto& c : p.cells) result.insert(c);
  return result;
}

std::pair<std::vector<int>, int> extract_slots(const PlayerState& p) {
  std::vector<int> caps;
  int stables_in_pastures = 0;
  for (const auto& past : p.farmyard.pastures) {
    caps.push_back(past.capacity);
    stables_in_pastures += past.num_stables;
  }
  int total_stables_built = 4 - stables_in_supply(p.farmyard);
  int standalone_stables = total_stables_built - stables_in_pastures;
  int num_flexible = standalone_stables + 1;  // +1 house pet
  return {caps, num_flexible};
}

bool can_accommodate(const std::vector<int>& caps, int num_flexible, int sheep,
                     int boar, int cattle) {
  const std::array<int, 3> counts{sheep, boar, cattle};
  int n = static_cast<int>(caps.size());
  // Enumerate all assignments of pasture -> {0 empty, 1 sheep, 2 boar, 3 cattle}.
  // 4^n configs.
  long total = 1;
  for (int i = 0; i < n; ++i) total *= 4;
  for (long mask = 0; mask < total; ++mask) {
    std::array<int, 3> dedicated{0, 0, 0};
    long m = mask;
    for (int i = 0; i < n; ++i) {
      int t = static_cast<int>(m & 3);
      m >>= 2;
      if (t > 0) dedicated[t - 1] += caps[i];
    }
    int overflow = 0;
    for (int t = 0; t < 3; ++t) {
      int o = counts[t] - dedicated[t];
      if (o > 0) overflow += o;
    }
    if (overflow <= num_flexible) return true;
  }
  return false;
}

namespace {
bool dom3(const std::array<int, 3>& a, const std::array<int, 3>& b) {
  // a dominates b: >= in every component, strictly > in at least one.
  return a[0] >= b[0] && a[1] >= b[1] && a[2] >= b[2] && a != b;
}
}  // namespace

std::vector<std::pair<std::array<int, 3>, int>> pareto_frontier(
    const PlayerState& p, const Animals& gained, std::array<int, 3> rates) {
  auto [caps, num_flexible] = extract_slots(p);
  int s_av = p.animals.sheep + gained.sheep;
  int b_av = p.animals.boar + gained.boar;
  int c_av = p.animals.cattle + gained.cattle;
  std::vector<std::array<int, 3>> feasible;
  for (int s = 0; s <= s_av; ++s)
    for (int b = 0; b <= b_av; ++b)
      for (int c = 0; c <= c_av; ++c)
        if (can_accommodate(caps, num_flexible, s, b, c))
          feasible.push_back({s, b, c});

  std::vector<std::pair<std::array<int, 3>, int>> frontier;
  for (const auto& cand : feasible) {
    bool dominated = false;
    for (const auto& other : feasible)
      if (dom3(other, cand)) { dominated = true; break; }
    if (!dominated) {
      int food = (s_av - cand[0]) * rates[0] + (b_av - cand[1]) * rates[1] +
                 (c_av - cand[2]) * rates[2];
      frontier.push_back({cand, food});
    }
  }
  return frontier;
}

namespace {
int breeding_food_gained(const Animals& pre, const std::array<int, 3>& post,
                         const std::array<int, 3>& rates) {
  int s = pre.sheep, b = pre.boar, c = pre.cattle;
  int sF = post[0], bF = post[1], cF = post[2];
  int sR = rates[0], bR = rates[1], cR = rates[2];
  int food_s = (s >= 2 && sF >= 3) ? (s + 1 - sF) * sR : (s - sF) * sR;
  int food_b = (b >= 2 && bF >= 3) ? (b + 1 - bF) * bR : (b - bF) * bR;
  int food_c = (c >= 2 && cF >= 3) ? (c + 1 - cF) * cR : (c - cF) * cR;
  return food_s + food_b + food_c;
}
}  // namespace

std::vector<std::pair<std::array<int, 3>, int>> breeding_frontier(
    const PlayerState& p, std::array<int, 3> rates) {
  int s = p.animals.sheep, b = p.animals.boar, c = p.animals.cattle;
  int s_des = s >= 2 ? s + 1 : s;
  int b_des = b >= 2 ? b + 1 : b;
  int c_des = c >= 2 ? c + 1 : c;
  auto [caps, num_flexible] = extract_slots(p);
  std::vector<std::array<int, 3>> feasible;
  for (int sF = 0; sF <= s_des; ++sF)
    for (int bF = 0; bF <= b_des; ++bF)
      for (int cF = 0; cF <= c_des; ++cF)
        if (can_accommodate(caps, num_flexible, sF, bF, cF))
          feasible.push_back({sF, bF, cF});

  Animals pre = p.animals;
  std::vector<std::pair<std::array<int, 3>, int>> frontier;
  for (const auto& cand : feasible) {
    bool dominated = false;
    for (const auto& other : feasible)
      if (dom3(other, cand)) { dominated = true; break; }
    if (!dominated)
      frontier.push_back({cand, breeding_food_gained(pre, cand, rates)});
  }
  return frontier;
}

namespace {
int ceil_div(int a, int b) { return (a + b - 1) / b; }

bool dom5(const std::array<int, 5>& a, const std::array<int, 5>& b) {
  bool ge_all = true, gt_any = false;
  for (int i = 0; i < 5; ++i) {
    if (a[i] < b[i]) ge_all = false;
    if (a[i] > b[i]) gt_any = true;
  }
  return ge_all && gt_any;
}

bool dom6(const std::array<int, 6>& a, const std::array<int, 6>& b) {
  bool ge_all = true, gt_any = false;
  for (int i = 0; i < 6; ++i) {
    if (a[i] < b[i]) ge_all = false;
    if (a[i] > b[i]) gt_any = true;
  }
  return ge_all && gt_any;
}

// Level-0 food_payment_frontier baseline: REMAINING 5-tuples that FULLY pay
// food_owed, Pareto-filtered.
std::vector<std::array<int, 5>> food_payment_frontier(const PlayerState& p,
                                                      int food_owed,
                                                      std::array<int, 4> rates) {
  int sR = rates[0], bR = rates[1], cR = rates[2], vR = rates[3];
  int grain_max = p.resources.grain;
  int veg_max = p.resources.veg;
  int sheep_max = p.animals.sheep;
  int boar_max = p.animals.boar;
  int cattle_max = p.animals.cattle;

  if (food_owed == 0)
    return {{grain_max, veg_max, sheep_max, boar_max, cattle_max}};

  int grain_cap = std::min(grain_max, food_owed);
  int veg_cap = vR > 0 ? std::min(veg_max, ceil_div(food_owed, vR)) : 0;
  int sheep_cap = sR > 0 ? std::min(sheep_max, ceil_div(food_owed, sR)) : 0;
  int boar_cap = bR > 0 ? std::min(boar_max, ceil_div(food_owed, bR)) : 0;
  int cattle_cap = cR > 0 ? std::min(cattle_max, ceil_div(food_owed, cR)) : 0;

  std::vector<std::array<int, 5>> candidates;
  for (int g = 0; g <= grain_cap; ++g)
    for (int v = 0; v <= veg_cap; ++v)
      for (int s = 0; s <= sheep_cap; ++s)
        for (int b = 0; b <= boar_cap; ++b)
          for (int c = 0; c <= cattle_cap; ++c) {
            int food = g + v * vR + s * sR + b * bR + c * cR;
            if (food < food_owed) continue;
            candidates.push_back({grain_max - g, veg_max - v, sheep_max - s,
                                  boar_max - b, cattle_max - c});
          }

  std::vector<std::array<int, 5>> frontier;
  for (size_t i = 0; i < candidates.size(); ++i) {
    bool dominated = false;
    for (size_t j = 0; j < candidates.size(); ++j)
      if (j != i && dom5(candidates[j], candidates[i])) {
        dominated = true;
        break;
      }
    if (!dominated) frontier.push_back(candidates[i]);
  }
  return frontier;
}
}  // namespace

std::vector<std::pair<std::array<int, 5>, int>> harvest_feed_frontier(
    const PlayerState& p, int food_owed, std::array<int, 4> rates) {
  int sR = rates[0], bR = rates[1], cR = rates[2], vR = rates[3];
  int grain_max = p.resources.grain;
  int veg_max = p.resources.veg;
  int sheep_max = p.animals.sheep;
  int boar_max = p.animals.boar;
  int cattle_max = p.animals.cattle;

  if (food_owed == 0)
    return {{{grain_max, veg_max, sheep_max, boar_max, cattle_max}, 0}};

  // Aggregate candidates from each paid level, admitting each config at the paid
  // level matching its natural fit (= min(food_generated, food_owed)).
  std::vector<std::pair<std::array<int, 5>, int>> candidates;
  for (int paid = 0; paid <= food_owed; ++paid) {
    for (const auto& rem : food_payment_frontier(p, paid, rates)) {
      int food_generated = (grain_max - rem[0]) + (veg_max - rem[1]) * vR +
                           (sheep_max - rem[2]) * sR + (boar_max - rem[3]) * bR +
                           (cattle_max - rem[4]) * cR;
      int natural = std::min(food_generated, food_owed);
      if (paid == natural) candidates.push_back({rem, food_owed - paid});
    }
  }

  // Pareto-filter on (5 goods, -begging).
  std::vector<std::array<int, 6>> ends;
  ends.reserve(candidates.size());
  for (const auto& [rem, beg] : candidates)
    ends.push_back({rem[0], rem[1], rem[2], rem[3], rem[4], -beg});

  std::vector<std::pair<std::array<int, 5>, int>> frontier;
  for (size_t i = 0; i < candidates.size(); ++i) {
    bool dominated = false;
    for (size_t j = 0; j < candidates.size(); ++j)
      if (j != i && dom6(ends[j], ends[i])) {
        dominated = true;
        break;
      }
    if (!dominated) frontier.push_back(candidates[i]);
  }
  return frontier;
}

}  // namespace agricola
