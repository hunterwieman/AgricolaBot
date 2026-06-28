// The C++ Agricola state data model (CPP_ENGINE_PLAN.md §5).
//
// A faithful mirror of the Python frozen dataclasses (agricola/state.py,
// resources.py, pasture.py, pending.py, constants.py). Value-semantic structs;
// `operator==` is defaulted (C++20) so equality is structural — the
// transposition-table contract (§5.3). Fixed dimensions: grid 3x5, horizontal
// fences 4x5, vertical fences 3x6, future_resources 14, action_spaces 25,
// majors 10.
//
// Field DECLARATION ORDER here must match the Python dataclasses, because the
// canonical serializer (canonical.cpp) walks fields in order and the dump must
// be byte-identical to Python's.
#pragma once

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <utility>
#include <variant>
#include <vector>

namespace agricola {

// --- enums (serialized by member name) --------------------------------------
enum class Phase {
  WORK,
  RETURN_HOME,
  PREPARATION,
  HARVEST_FIELD,
  HARVEST_FEED,
  HARVEST_BREED,
  BEFORE_SCORING,
};

enum class CellType { EMPTY, ROOM, FIELD, STABLE };

enum class HouseMaterial { WOOD, CLAY, STONE };

// --- leaf value types -------------------------------------------------------
struct Resources {
  int wood = 0;
  int clay = 0;
  int reed = 0;
  int stone = 0;
  int food = 0;
  int grain = 0;
  int veg = 0;
  bool operator==(const Resources&) const = default;
  // Ordering so structs carrying a Resources (e.g. CommitRenovate.payment) keep
  // a working defaulted operator<=> (matches the action-struct convention).
  auto operator<=>(const Resources&) const = default;
};

struct Animals {
  int sheep = 0;
  int boar = 0;
  int cattle = 0;
  bool operator==(const Animals&) const = default;
};

struct Cell {
  CellType cell_type = CellType::EMPTY;
  int grain = 0;
  int veg = 0;
  bool operator==(const Cell&) const = default;
};

using Coord = std::pair<int, int>;  // (row, col)

struct Pasture {
  // Canonical: cells kept SORTED (lexicographic) so the vector mirrors the
  // Python frozenset's sorted serialization and gives set equality.
  std::vector<Coord> cells;
  int num_stables = 0;
  int capacity = 0;
  bool operator==(const Pasture&) const = default;
};

// --- farmyard ---------------------------------------------------------------
constexpr int kRows = 3;
constexpr int kCols = 5;

struct Farmyard {
  std::array<std::array<Cell, kCols>, kRows> grid{};            // (3,5)
  std::array<std::array<bool, kCols>, kRows + 1> horizontal_fences{};  // (4,5)
  std::array<std::array<bool, kCols + 1>, kRows> vertical_fences{};    // (3,6)
  std::vector<Pasture> pastures{};  // canonically ordered (see pasture.hpp)
  bool operator==(const Farmyard&) const = default;
};

// --- board ------------------------------------------------------------------
struct ActionSpaceState {
  std::array<int, 2> workers{0, 0};
  Resources accumulated{};
  int accumulated_amount = 0;
  bool revealed = false;
  bool operator==(const ActionSpaceState&) const = default;
};

struct BoardState {
  std::vector<ActionSpaceState> action_spaces;          // length 25
  std::vector<std::optional<int>> major_improvement_owners;  // length 10
  bool operator==(const BoardState&) const = default;
};

// --- player -----------------------------------------------------------------
struct PlayerState {
  Resources resources{};
  Animals animals{};
  Farmyard farmyard{};
  HouseMaterial house_material = HouseMaterial::WOOD;
  int people_total = 0;
  int people_home = 0;
  int newborns = 0;
  int begging_markers = 0;
  std::vector<Resources> future_resources;          // length 14
  std::vector<std::string> minor_improvements;      // frozenset[str], sorted
  std::vector<std::string> occupations;             // frozenset[str], sorted
  std::vector<std::string> harvest_conversions_used;  // frozenset[str], sorted
  bool operator==(const PlayerState&) const = default;
};

// --- pending frames (25-variant tagged union) -------------------------------
// Every frame carries player_idx (std::nullopt only for PendingReveal — the
// nature sentinel) and initiated_by_id, plus its own fields. triggers_resolved
// is a frozenset[str] (sorted vector) on the frames that declare it.

struct PendingGrainUtilization {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  bool sow_chosen = false;
  bool bake_chosen = false;
  std::string phase = "before";  // "before" | "after" (SPACE_HOST_REFACTOR Proceed-host)
  std::vector<std::string> triggers_resolved;
  bool operator==(const PendingGrainUtilization&) const = default;
};
struct PendingSow {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  std::string phase = "before";  // "before" | "after" (SUBACTION_HOOK_REFACTOR)
  std::vector<std::string> triggers_resolved;
  bool operator==(const PendingSow&) const = default;
};
struct PendingBakeBread {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  std::string phase = "before";  // "before" | "after"
  std::vector<std::string> triggers_resolved;
  bool operator==(const PendingBakeBread&) const = default;
};
struct PendingPlow {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  std::string phase = "before";  // "before" | "after"
  std::vector<std::string> triggers_resolved;
  bool operator==(const PendingPlow&) const = default;
};
struct PendingFarmExpansion {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  bool room_chosen = false;
  bool stable_chosen = false;
  std::string phase = "before";  // "before" | "after" (SPACE_HOST_REFACTOR Proceed-host)
  std::vector<std::string> triggers_resolved;
  bool operator==(const PendingFarmExpansion&) const = default;
};
struct PendingBuildStables {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  Resources cost{};
  std::optional<int> max_builds;
  int num_built = 0;
  std::string phase = "before";  // "before" | "after" (SPACE_HOST_REFACTOR before/after host)
  std::vector<std::string> triggers_resolved;
  bool operator==(const PendingBuildStables&) const = default;
};
struct PendingBuildRooms {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  std::optional<int> max_builds;
  int num_built = 0;
  std::string phase = "before";  // "before" | "after" (SPACE_HOST_REFACTOR before/after host)
  std::vector<std::string> triggers_resolved;
  bool operator==(const PendingBuildRooms&) const = default;
};
struct PendingBuildMajor {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  std::string phase = "before";  // "before" | "after" (replaces old build_chosen)
  std::vector<std::string> triggers_resolved;
  bool operator==(const PendingBuildMajor&) const = default;
};
struct PendingRenovate {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  std::string phase = "before";  // "before" | "after"
  std::vector<std::string> triggers_resolved;
  bool operator==(const PendingRenovate&) const = default;
};
// Generic Delegating action-space host (SPACE_HOST_REFACTOR.md §4.2/§5):
// replaces the old per-space PendingFarmland / PendingFencing. The specific
// child is dispatched by space_id (read off initiated_by_id = "space:<id>").
struct PendingSubActionSpace {
  std::optional<int> player_idx;
  std::string initiated_by_id;               // "space:<id>"
  bool subaction_complete = false;
  std::string phase = "before";              // "before" | "after"
  std::vector<std::string> triggers_resolved;
  // space_id = initiated_by_id after the "space:" prefix.
  std::string space_id() const {
    const std::string pfx = "space:";
    if (initiated_by_id.rfind(pfx, 0) == 0) return initiated_by_id.substr(pfx.size());
    return initiated_by_id;
  }
  bool operator==(const PendingSubActionSpace&) const = default;
};
struct PendingCultivation {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  bool plow_chosen = false;
  bool sow_chosen = false;
  std::string phase = "before";  // "before" | "after" (SPACE_HOST_REFACTOR Proceed-host)
  std::vector<std::string> triggers_resolved;
  bool operator==(const PendingCultivation&) const = default;
};
struct PendingSideJob {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  bool stable_chosen = false;
  bool bake_chosen = false;
  std::vector<std::string> triggers_resolved;
  bool operator==(const PendingSideJob&) const = default;
};
struct PendingSheepMarket {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  int gained = 0;
  std::string phase = "before";  // "before" | "after" (4b: non-auto-pop market)
  std::vector<std::string> triggers_resolved;
  bool operator==(const PendingSheepMarket&) const = default;
};
struct PendingPigMarket {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  int gained = 0;
  std::string phase = "before";
  std::vector<std::string> triggers_resolved;
  bool operator==(const PendingPigMarket&) const = default;
};
struct PendingCattleMarket {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  int gained = 0;
  std::string phase = "before";
  std::vector<std::string> triggers_resolved;
  bool operator==(const PendingCattleMarket&) const = default;
};
struct PendingMajorMinorImprovement {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  bool major_chosen = false;
  bool minor_chosen = false;
  std::string phase = "before";  // "before" | "after" (SPACE_HOST_REFACTOR Delegating host)
  std::vector<std::string> triggers_resolved;
  // Delegating work-complete signal (derived): a major built or a minor played.
  bool subaction_complete() const { return major_chosen || minor_chosen; }
  bool operator==(const PendingMajorMinorImprovement&) const = default;
};
struct PendingHouseRedevelopment {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  bool renovate_chosen = false;
  bool improvement_chosen = false;
  std::string phase = "before";  // "before" | "after" (SPACE_HOST_REFACTOR Proceed-host)
  std::vector<std::string> triggers_resolved;
  bool operator==(const PendingHouseRedevelopment&) const = default;
};
struct PendingClayOven {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  bool bake_chosen = false;
  bool operator==(const PendingClayOven&) const = default;
};
struct PendingStoneOven {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  bool bake_chosen = false;
  bool operator==(const PendingStoneOven&) const = default;
};
struct PendingBuildFences {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  int pastures_built = 0;
  int fences_built = 0;
  bool subdivision_started = false;
  std::string phase = "before";  // "before" | "after" (SPACE_HOST_REFACTOR before/after host)
  std::vector<std::string> triggers_resolved;
  bool operator==(const PendingBuildFences&) const = default;
};
struct PendingFarmRedevelopment {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  bool renovate_chosen = false;
  bool build_fences_chosen = false;
  std::string phase = "before";  // "before" | "after" (SPACE_HOST_REFACTOR Proceed-host)
  std::vector<std::string> triggers_resolved;
  bool operator==(const PendingFarmRedevelopment&) const = default;
};
struct PendingHarvestFeed {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  bool conversion_done = false;
  bool operator==(const PendingHarvestFeed&) const = default;
};
struct PendingHarvestBreed {
  std::optional<int> player_idx;
  std::string initiated_by_id;
  bool breed_chosen = false;
  bool operator==(const PendingHarvestBreed&) const = default;
};
struct PendingReveal {
  std::optional<int> player_idx;  // always std::nullopt (nature)
  std::string initiated_by_id = "phase:reveal";
  bool operator==(const PendingReveal&) const = default;
};

using PendingDecision = std::variant<
    PendingGrainUtilization, PendingSow, PendingBakeBread, PendingPlow,
    PendingBuildStables, PendingBuildRooms, PendingBuildMajor, PendingRenovate,
    PendingFarmExpansion, PendingSubActionSpace, PendingCultivation, PendingSideJob,
    PendingSheepMarket, PendingPigMarket, PendingCattleMarket,
    PendingMajorMinorImprovement, PendingHouseRedevelopment, PendingClayOven,
    PendingStoneOven, PendingBuildFences,
    PendingFarmRedevelopment, PendingHarvestFeed, PendingHarvestBreed,
    PendingReveal>;

// --- top-level state --------------------------------------------------------
struct GameState {
  int round_number = 0;
  Phase phase = Phase::WORK;
  int current_player = 0;
  int starting_player = 0;
  std::array<PlayerState, 2> players{};
  BoardState board{};
  std::vector<PendingDecision> pending_stack{};
  bool operator==(const GameState&) const = default;
};

}  // namespace agricola
