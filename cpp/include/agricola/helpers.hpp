// Derived-quantity + frontier helpers — level-0 baselines of agricola/helpers.py
// (set-identical to the optimized paths). CPP_ENGINE_PLAN.md §4 row 8.
#pragma once

#include <array>
#include <set>
#include <tuple>
#include <vector>

#include "agricola/types.hpp"

namespace agricola {

int fences_in_supply(const Farmyard& fy);
int stables_in_supply(const Farmyard& fy);

// (sheep_rate, boar_rate, cattle_rate, veg_rate) for at-any-time conversion.
std::array<int, 4> cooking_rates(const GameState& state, int player_idx);

// Set of (r,c) cells inside any pasture.
std::set<Coord> enclosed_cells(const Farmyard& fy);

// (pasture_capacities, num_flexible).
std::pair<std::vector<int>, int> extract_slots(const PlayerState& p);

bool can_accommodate(const std::vector<int>& pasture_caps, int num_flexible,
                     int sheep, int boar, int cattle);

// Animal Pareto frontier after gaining (gained), with rates for food. Returns
// (Animals-as-(s,b,c), food).
std::vector<std::pair<std::array<int, 3>, int>> pareto_frontier(
    const PlayerState& p, const Animals& gained, std::array<int, 3> rates);

// Breeding Pareto frontier: (post-(s,b,c), food_gained).
std::vector<std::pair<std::array<int, 3>, int>> breeding_frontier(
    const PlayerState& p, std::array<int, 3> rates);

// Harvest-feed frontier: ((grain_rem,veg_rem,sheep_rem,boar_rem,cattle_rem),
// begging).
std::vector<std::pair<std::array<int, 5>, int>> harvest_feed_frontier(
    const PlayerState& p, int food_owed, std::array<int, 4> rates);

}  // namespace agricola
