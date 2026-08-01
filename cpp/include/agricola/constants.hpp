// Game constants — a faithful mirror of agricola/constants.py (Stage 2).
//
// SPACE_IDS / SPACE_INDEX, room/major/baking cost tables, accumulation-space
// metadata, the stage-card grouping + stage_of_round, and harvest rounds. Pull
// exact values from constants.py; the legality port reads these.
#pragma once

#include <array>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "agricola/types.hpp"

namespace agricola {

// Canonical 25-entry action-space ordering (PERMANENT_ACTION_SPACES then stage
// cards in stage order). Indexes BoardState.action_spaces.
extern const std::array<std::string, 25> SPACE_IDS;

// space_id -> canonical index. -1 if unknown.
int space_index(const std::string& space_id);

// Room costs by current house material.
Resources room_cost(HouseMaterial material);

// Major improvement costs, indexed by major_idx (0-9).
extern const std::array<Resources, 10> MAJOR_IMPROVEMENT_COSTS;

// Per-action Bake Bread specs by major_idx: (max_grain_per_action, food_per_grain).
// max_grain_per_action == nullopt means "any amount" (Fireplace / Cooking Hearth).
struct BakingSpec {
  std::optional<int> max_grain;  // nullopt = uncapped
  int food_per_grain;
};
// Returns the baking spec for a given major_idx, or nullopt if that major has
// no baking ability. (Mirrors BAKING_IMPROVEMENT_SPECS keys {0,1,2,3,5,6}.)
std::optional<BakingSpec> baking_spec_for_major(int major_idx);
bool major_is_baking(int major_idx);  // idx in BAKING_IMPROVEMENTS

// Fireplace / cooking-hearth major indices.
constexpr std::array<int, 2> FIREPLACE_INDICES{0, 1};
constexpr std::array<int, 2> COOKING_HEARTH_INDICES{2, 3};

// Stage cards grouped by stage (1-6), in canonical within-stage order.
extern const std::array<std::vector<std::string>, 7> STAGE_CARDS;  // index 1..6

// Stage (1-6) that round_number (1-14) belongs to.
int stage_of_round(int round_number);

// Harvest rounds.
bool is_harvest_round(int round_number);

constexpr int NUM_ROUNDS = 14;
constexpr int NUM_MAJOR_IMPROVEMENTS = 10;

// Harvest virtual-walk cursor anchors (ruling 40, 2026-07-12 — FEED/BREED
// banding). GameState.harvest_cursor indexes the 24-position 2-player VIRTUAL
// walk of the harvest-window ladder (agricola/cards/harvest_windows.py: the
// raw window ladder with the FIELD/FEED/BREED bands each repeated once per
// player, starting player's pass — "pass 0" — first). The C++ engine is
// Family-only: every window between the payment/breeding frames is a
// cards-only no-op, so the walk collapses to a fixed state machine over the
// anchors below. Each CURSOR_AFTER_* value is the position just PAST a band
// pass's frame push (Python: sentinel_position("<after-window>", pass)) — the
// value carried while that pass's frame is up.
//
// RENUMBERED by ruling 88 (2026-08-01): the `start_of_feeding` rung was deleted
// from the ladder, so the FEED band is two rungs and the walk is 24 positions
// (was 26). Every anchor at or after the FEED band shifted; these values MUST
// stay equal to the Python sentinel_position() results or the canonical JSON
// diverges mid-feed/mid-breed and the differential gates fail. The has_fed
// anchor keeps its MEANING (the second player's FEED pass begins) — that instant
// is now the `feeding` sentinel rather than the deleted rung, and the encoder
// output was verified bit-identical across the change.
constexpr int CURSOR_AFTER_FEEDING_PASS0 = 13;    // SP's payment frame up
constexpr int CURSOR_START_FEEDING_PASS1 = 14;    // 2nd FEED pass begins (encoder's has_fed boundary)
constexpr int CURSOR_AFTER_FEEDING_PASS1 = 15;    // other player's payment frame up
constexpr int CURSOR_AFTER_BREEDING_PASS0 = 18;   // SP's breeding frame up
constexpr int CURSOR_AFTER_BREEDING_PASS1 = 21;   // other player's breeding frame up

}  // namespace agricola
