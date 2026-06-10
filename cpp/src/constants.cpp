#include "agricola/constants.hpp"

#include <stdexcept>

namespace agricola {

// PERMANENT_ACTION_SPACES then stage cards in stage order — exactly the Python
// SPACE_IDS construction (constants.py). Stage cards order: stage 1 [4], stage 2
// [3], stage 3 [2], stage 4 [2], stage 5 [2], stage 6 [1] = 11 + 14 = 25.
const std::array<std::string, 25> SPACE_IDS{
    // permanents (11)
    "farm_expansion", "meeting_place", "grain_seeds", "farmland", "lessons",
    "day_laborer", "forest", "clay_pit", "reed_bank", "fishing", "side_job",
    // stage 1 (4)
    "major_improvement", "fencing", "grain_utilization", "sheep_market",
    // stage 2 (3)
    "basic_wish_for_children", "house_redevelopment", "western_quarry",
    // stage 3 (2)
    "vegetable_seeds", "pig_market",
    // stage 4 (2)
    "cattle_market", "eastern_quarry",
    // stage 5 (2)
    "urgent_wish_for_children", "cultivation",
    // stage 6 (1)
    "farm_redevelopment",
};

int space_index(const std::string& space_id) {
  for (int i = 0; i < static_cast<int>(SPACE_IDS.size()); ++i)
    if (SPACE_IDS[i] == space_id) return i;
  return -1;
}

Resources room_cost(HouseMaterial material) {
  Resources r;
  r.reed = 2;
  switch (material) {
    case HouseMaterial::WOOD: r.wood = 5; break;
    case HouseMaterial::CLAY: r.clay = 5; break;
    case HouseMaterial::STONE: r.stone = 5; break;
  }
  return r;
}

namespace {
Resources mk(int wood = 0, int clay = 0, int reed = 0, int stone = 0) {
  Resources r;
  r.wood = wood;
  r.clay = clay;
  r.reed = reed;
  r.stone = stone;
  return r;
}
}  // namespace

const std::array<Resources, 10> MAJOR_IMPROVEMENT_COSTS{
    mk(0, 2, 0, 0),  // 0: Fireplace (cheap)
    mk(0, 3, 0, 0),  // 1: Fireplace (expensive)
    mk(0, 4, 0, 0),  // 2: Cooking Hearth (cheap)
    mk(0, 5, 0, 0),  // 3: Cooking Hearth (expensive)
    mk(1, 0, 0, 3),  // 4: Well
    mk(0, 3, 0, 1),  // 5: Clay Oven
    mk(0, 1, 0, 3),  // 6: Stone Oven
    mk(2, 0, 0, 2),  // 7: Joinery
    mk(0, 2, 0, 2),  // 8: Pottery
    mk(0, 0, 2, 2),  // 9: Basketmaker's Workshop
};

std::optional<BakingSpec> baking_spec_for_major(int major_idx) {
  switch (major_idx) {
    case 0: return BakingSpec{std::nullopt, 2};
    case 1: return BakingSpec{std::nullopt, 2};
    case 2: return BakingSpec{std::nullopt, 3};
    case 3: return BakingSpec{std::nullopt, 3};
    case 5: return BakingSpec{std::optional<int>(1), 5};
    case 6: return BakingSpec{std::optional<int>(2), 4};
    default: return std::nullopt;
  }
}

bool major_is_baking(int major_idx) {
  return baking_spec_for_major(major_idx).has_value();
}

const std::array<std::vector<std::string>, 7> STAGE_CARDS{{
    {},                                                                       // 0 unused
    {"major_improvement", "fencing", "grain_utilization", "sheep_market"},    // 1
    {"basic_wish_for_children", "house_redevelopment", "western_quarry"},      // 2
    {"vegetable_seeds", "pig_market"},                                         // 3
    {"cattle_market", "eastern_quarry"},                                       // 4
    {"urgent_wish_for_children", "cultivation"},                               // 5
    {"farm_redevelopment"},                                                    // 6
}};

int stage_of_round(int round_number) {
  // rounds 1-4 -> 1, 5-7 -> 2, 8-9 -> 3, 10-11 -> 4, 12-13 -> 5, 14 -> 6.
  // Derived from STAGE_CARDS sizes (4,3,2,2,2,1).
  int r = round_number;
  if (r >= 1 && r <= 4) return 1;
  if (r >= 5 && r <= 7) return 2;
  if (r >= 8 && r <= 9) return 3;
  if (r >= 10 && r <= 11) return 4;
  if (r >= 12 && r <= 13) return 5;
  if (r == 14) return 6;
  throw std::runtime_error("stage_of_round: round out of range");
}

bool is_harvest_round(int round_number) {
  switch (round_number) {
    case 4: case 7: case 9: case 11: case 13: case 14: return true;
    default: return false;
  }
}

}  // namespace agricola
