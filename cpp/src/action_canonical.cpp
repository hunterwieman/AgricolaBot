// Action -> {type, params} JSON, matching agents/nn/trace_replay.action_to_params.
//
// The Python type name is the dataclass class name; params mirror the
// dataclass fields. Non-scalar fields: CommitBuildPasture.cells
// (frozenset[tuple] -> sorted [[r,c],...]) and the wide commits' `payment`
// (a PaymentOption -> tagged route dict, see payment_to_json).
//
// The differential gate normalizes both sides through json.loads + json.dumps
// (sort_keys), so key order is irrelevant; only the type string + param values
// matter.
#include <algorithm>
#include <stdexcept>

#include "agricola/actions.hpp"
#include "nlohmann/json.hpp"

namespace agricola {
namespace {
using json = nlohmann::json;

// HouseMaterial <-> enum-name string (CommitRenovate.to_material serializes as the
// bare enum NAME, e.g. "CLAY" — mirror of Python's `v.name` / `HouseMaterial[v]`).
const char* house_material_name(HouseMaterial m) {
  switch (m) {
    case HouseMaterial::WOOD: return "WOOD";
    case HouseMaterial::CLAY: return "CLAY";
    case HouseMaterial::STONE: return "STONE";
  }
  throw std::runtime_error("bad HouseMaterial");
}
HouseMaterial house_material_from_name(const std::string& n) {
  if (n == "WOOD") return HouseMaterial::WOOD;
  if (n == "CLAY") return HouseMaterial::CLAY;
  if (n == "STONE") return HouseMaterial::STONE;
  throw std::runtime_error("bad HouseMaterial name: " + n);
}

// Serialize a PaymentOption as the tagged dict Python's trace_replay._payment_to_json
// emits: a Resources is {"route":"resources", + 7 flat components}; a non-resource
// route is {"route":"return_improvement","improvement_idx":i}. NO __type__.
json payment_to_json(const Resources& r) {
  return json{{"route", "resources"}, {"wood", r.wood},   {"clay", r.clay},
              {"reed", r.reed},       {"stone", r.stone}, {"food", r.food},
              {"grain", r.grain},     {"veg", r.veg}};
}
json payment_to_json(const PaymentOption& pay) {
  if (const auto* r = std::get_if<Resources>(&pay)) return payment_to_json(*r);
  const auto& ri = std::get<ReturnImprovement>(pay);
  return json{{"route", "return_improvement"},
              {"improvement_idx", ri.improvement_idx}};
}
// Inverse of payment_to_json (mirror of _payment_from_json).
PaymentOption payment_from_json(const json& d) {
  if (d.value("route", std::string()) == "return_improvement")
    return ReturnImprovement{d.at("improvement_idx").get<int>()};
  return Resources{d.at("wood").get<int>(),  d.at("clay").get<int>(),
                   d.at("reed").get<int>(),  d.at("stone").get<int>(),
                   d.at("food").get<int>(),  d.at("grain").get<int>(),
                   d.at("veg").get<int>()};
}

json params_of(const PlaceWorker& a) {
  return json{{"space", a.space}};
}
json params_of(const ChooseSubAction& a) {
  return json{{"name", a.name}};
}
json params_of(const CommitSow& a) {
  return json{{"grain", a.grain}, {"veg", a.veg}};
}
json params_of(const CommitBake& a) {
  return json{{"grain", a.grain}};
}
json params_of(const CommitPlow& a) {
  return json{{"row", a.row}, {"col", a.col}};
}
json params_of(const CommitBuildStable& a) {
  return json{{"row", a.row}, {"col", a.col}};
}
json params_of(const CommitBuildRoom& a) {
  return json{{"row", a.row}, {"col", a.col}};
}
json params_of(const CommitBuildMajor& a) {
  return json{{"major_idx", a.major_idx}, {"payment", payment_to_json(a.payment)}};
}
json params_of(const CommitRenovate& a) {
  // Family renovate is always a Resources payment (no route); to_material is the
  // bare enum name.
  return json{{"payment", payment_to_json(a.payment)},
              {"to_material", house_material_name(a.to_material)}};
}
json params_of(const CommitAccommodate& a) {
  return json{{"sheep", a.sheep}, {"boar", a.boar}, {"cattle", a.cattle}};
}
json params_of(const CommitBuildPasture& a) {
  std::vector<Coord> cells = a.cells;
  std::sort(cells.begin(), cells.end());
  json arr = json::array();
  for (const auto& [r, c] : cells) arr.push_back(json::array({r, c}));
  return json{{"cells", arr}};
}
json params_of(const CommitHarvestConversion& a) {
  return json{{"conversion_id", a.conversion_id}};
}
json params_of(const CommitConvert& a) {
  return json{{"grain", a.grain}, {"veg", a.veg}, {"sheep", a.sheep},
              {"boar", a.boar}, {"cattle", a.cattle}};
}
json params_of(const CommitBreed& a) {
  return json{{"sheep", a.sheep}, {"boar", a.boar}, {"cattle", a.cattle}};
}
json params_of(const FireTrigger& a) {
  return json{{"card_id", a.card_id}};
}
json params_of(const Stop&) { return json::object(); }
json params_of(const Proceed&) { return json::object(); }
json params_of(const RevealCard& a) {
  return json{{"card", a.card}};
}

const char* type_name(const Action& a) {
  return std::visit(
      [](const auto& v) -> const char* {
        using T = std::decay_t<decltype(v)>;
        if constexpr (std::is_same_v<T, PlaceWorker>) return "PlaceWorker";
        else if constexpr (std::is_same_v<T, ChooseSubAction>) return "ChooseSubAction";
        else if constexpr (std::is_same_v<T, CommitSow>) return "CommitSow";
        else if constexpr (std::is_same_v<T, CommitBake>) return "CommitBake";
        else if constexpr (std::is_same_v<T, CommitPlow>) return "CommitPlow";
        else if constexpr (std::is_same_v<T, CommitBuildStable>) return "CommitBuildStable";
        else if constexpr (std::is_same_v<T, CommitBuildRoom>) return "CommitBuildRoom";
        else if constexpr (std::is_same_v<T, CommitBuildMajor>) return "CommitBuildMajor";
        else if constexpr (std::is_same_v<T, CommitRenovate>) return "CommitRenovate";
        else if constexpr (std::is_same_v<T, CommitAccommodate>) return "CommitAccommodate";
        else if constexpr (std::is_same_v<T, CommitBuildPasture>) return "CommitBuildPasture";
        else if constexpr (std::is_same_v<T, CommitHarvestConversion>) return "CommitHarvestConversion";
        else if constexpr (std::is_same_v<T, CommitConvert>) return "CommitConvert";
        else if constexpr (std::is_same_v<T, CommitBreed>) return "CommitBreed";
        else if constexpr (std::is_same_v<T, FireTrigger>) return "FireTrigger";
        else if constexpr (std::is_same_v<T, Stop>) return "Stop";
        else if constexpr (std::is_same_v<T, Proceed>) return "Proceed";
        else if constexpr (std::is_same_v<T, RevealCard>) return "RevealCard";
      },
      a);
}

}  // namespace

std::string action_to_json(const Action& action) {
  json j;
  j["type"] = type_name(action);
  j["params"] = std::visit([](const auto& v) { return params_of(v); }, action);
  return j.dump();
}

Action action_from_json(const std::string& text) {
  const json j = json::parse(text);
  const std::string t = j.at("type").get<std::string>();
  const json p = j.contains("params") ? j.at("params") : json::object();

  if (t == "PlaceWorker") return PlaceWorker{p.at("space").get<std::string>()};
  if (t == "ChooseSubAction")
    return ChooseSubAction{p.at("name").get<std::string>()};
  if (t == "CommitSow")
    return CommitSow{p.at("grain").get<int>(), p.at("veg").get<int>()};
  if (t == "CommitBake") return CommitBake{p.at("grain").get<int>()};
  if (t == "CommitPlow")
    return CommitPlow{p.at("row").get<int>(), p.at("col").get<int>()};
  if (t == "CommitBuildStable")
    return CommitBuildStable{p.at("row").get<int>(), p.at("col").get<int>()};
  if (t == "CommitBuildRoom")
    return CommitBuildRoom{p.at("row").get<int>(), p.at("col").get<int>()};
  if (t == "CommitBuildMajor")
    return CommitBuildMajor{p.at("major_idx").get<int>(),
                            payment_from_json(p.at("payment"))};
  if (t == "CommitRenovate")
    // Family renovate is always a Resources payment (no route); to_material is the
    // bare enum name.
    return CommitRenovate{
        std::get<Resources>(payment_from_json(p.at("payment"))),
        house_material_from_name(p.at("to_material").get<std::string>())};
  if (t == "CommitAccommodate")
    return CommitAccommodate{p.at("sheep").get<int>(), p.at("boar").get<int>(),
                             p.at("cattle").get<int>()};
  if (t == "CommitBuildPasture") {
    CommitBuildPasture a;
    for (const auto& c : p.at("cells"))
      a.cells.emplace_back(c.at(0).get<int>(), c.at(1).get<int>());
    std::sort(a.cells.begin(), a.cells.end());
    return a;
  }
  if (t == "CommitHarvestConversion")
    return CommitHarvestConversion{p.at("conversion_id").get<std::string>()};
  if (t == "CommitConvert")
    return CommitConvert{p.at("grain").get<int>(), p.at("veg").get<int>(),
                         p.at("sheep").get<int>(), p.at("boar").get<int>(),
                         p.at("cattle").get<int>()};
  if (t == "CommitBreed")
    return CommitBreed{p.at("sheep").get<int>(), p.at("boar").get<int>(),
                       p.at("cattle").get<int>()};
  if (t == "FireTrigger")
    return FireTrigger{p.at("card_id").get<std::string>()};
  if (t == "Stop") return Stop{};
  if (t == "Proceed") return Proceed{};
  if (t == "RevealCard") return RevealCard{p.at("card").get<std::string>()};
  throw std::runtime_error("action_from_json: unknown type " + t);
}

}  // namespace agricola
