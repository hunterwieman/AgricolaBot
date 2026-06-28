// C++ Action types — a faithful mirror of the 17 dataclasses in
// agricola/actions.py (CPP_ENGINE_PLAN.md §4 row 3). A std::variant tagged
// union with defaulted operator== for structural equality.
//
// Serialization to the {type, params} form (matching
// agents/nn/trace_replay.action_to_params) lives in action_canonical.cpp.
#pragma once

#include <optional>
#include <string>
#include <utility>
#include <variant>
#include <vector>

#include "agricola/types.hpp"  // Coord

namespace agricola {

struct PlaceWorker {
  std::string space;
  bool operator==(const PlaceWorker&) const = default;
  auto operator<=>(const PlaceWorker&) const = default;
};
struct ChooseSubAction {
  std::string name;
  bool operator==(const ChooseSubAction&) const = default;
  auto operator<=>(const ChooseSubAction&) const = default;
};
struct CommitSow {
  int grain = 0;
  int veg = 0;
  bool operator==(const CommitSow&) const = default;
  auto operator<=>(const CommitSow&) const = default;
};
struct CommitBake {
  int grain = 0;
  bool operator==(const CommitBake&) const = default;
  auto operator<=>(const CommitBake&) const = default;
};
struct CommitPlow {
  int row = 0;
  int col = 0;
  bool operator==(const CommitPlow&) const = default;
  auto operator<=>(const CommitPlow&) const = default;
};
struct CommitBuildStable {
  int row = 0;
  int col = 0;
  bool operator==(const CommitBuildStable&) const = default;
  auto operator<=>(const CommitBuildStable&) const = default;
};
struct CommitBuildRoom {
  int row = 0;
  int col = 0;
  bool operator==(const CommitBuildRoom&) const = default;
  auto operator<=>(const CommitBuildRoom&) const = default;
};
// A non-resource payment route: pay for a build by returning a major improvement
// you own (Family's only instance is Cooking Hearth via returning a Fireplace).
// Mirror of agricola/cost.py ReturnImprovement.
struct ReturnImprovement {
  int improvement_idx = 0;
  bool operator==(const ReturnImprovement&) const = default;
  auto operator<=>(const ReturnImprovement&) const = default;
};
// The unit of payment carried by a wide commit: a Resources vector (the printed /
// reduced cost) OR a non-resource route. Mirror of agricola/cost.py PaymentOption.
using PaymentOption = std::variant<Resources, ReturnImprovement>;

struct CommitBuildMajor {
  int major_idx = 0;
  PaymentOption payment{};  // Resources (printed cost) or ReturnImprovement (Cooking Hearth)
  bool operator==(const CommitBuildMajor&) const = default;
  auto operator<=>(const CommitBuildMajor&) const = default;
};
struct CommitRenovate {
  Resources payment{};  // base renovate cost (Family: num_rooms of next material + 1 reed)
  bool operator==(const CommitRenovate&) const = default;
  auto operator<=>(const CommitRenovate&) const = default;
};
struct CommitAccommodate {
  int sheep = 0;
  int boar = 0;
  int cattle = 0;
  bool operator==(const CommitAccommodate&) const = default;
  auto operator<=>(const CommitAccommodate&) const = default;
};
struct CommitBuildPasture {
  // frozenset[tuple[int,int]] in Python; sorted cell list here.
  std::vector<Coord> cells;
  bool operator==(const CommitBuildPasture&) const = default;
  auto operator<=>(const CommitBuildPasture&) const = default;
};
struct CommitHarvestConversion {
  std::string conversion_id;
  bool operator==(const CommitHarvestConversion&) const = default;
  auto operator<=>(const CommitHarvestConversion&) const = default;
};
struct CommitConvert {
  int grain = 0;
  int veg = 0;
  int sheep = 0;
  int boar = 0;
  int cattle = 0;
  bool operator==(const CommitConvert&) const = default;
  auto operator<=>(const CommitConvert&) const = default;
};
struct CommitBreed {
  int sheep = 0;
  int boar = 0;
  int cattle = 0;
  bool operator==(const CommitBreed&) const = default;
  auto operator<=>(const CommitBreed&) const = default;
};
struct FireTrigger {
  std::string card_id;
  bool operator==(const FireTrigger&) const = default;
  auto operator<=>(const FireTrigger&) const = default;
};
struct Stop {
  bool operator==(const Stop&) const = default;
  auto operator<=>(const Stop&) const = default;
};
// Proceed: the work-complete boundary for the atomic / Proceed-host action-space
// frames (SPACE_HOST_REFACTOR.md). In the Family game it appears at the five
// Proceed-host parents (Grain Util, Cultivation, Farm Expansion, House/Farm
// Redev), flipping the host to its after-phase.
struct Proceed {
  bool operator==(const Proceed&) const = default;
  auto operator<=>(const Proceed&) const = default;
};
struct RevealCard {
  std::string card;
  bool operator==(const RevealCard&) const = default;
  auto operator<=>(const RevealCard&) const = default;
};

using Action = std::variant<
    PlaceWorker, ChooseSubAction, CommitSow, CommitBake, CommitPlow,
    CommitBuildStable, CommitBuildRoom, CommitBuildMajor, CommitRenovate,
    CommitAccommodate, CommitBuildPasture, CommitHarvestConversion,
    CommitConvert, CommitBreed, FireTrigger, Stop, Proceed, RevealCard>;

// Serialize an action to its canonical {type, params} JSON string. The type is
// the Python class name; params mirror action_to_params (cells -> sorted
// [[r,c],...]). Defined in action_canonical.cpp.
std::string action_to_json(const Action& action);

// Inverse of action_to_json: parse a {type, params} JSON string into an Action.
// All 17 types; CommitBuildPasture.cells from [[r,c],...] -> sorted cell list;
// the wide commits' `payment` from the tagged route dict. Defined in
// action_canonical.cpp.
Action action_from_json(const std::string& text);

}  // namespace agricola
