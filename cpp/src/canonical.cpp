#include "agricola/canonical.hpp"

#include <algorithm>
#include <stdexcept>

#include "nlohmann/json.hpp"

namespace agricola {
namespace {

using json = nlohmann::ordered_json;

// --- enum name maps ---------------------------------------------------------
const char* phase_name(Phase p) {
  switch (p) {
    case Phase::WORK: return "WORK";
    case Phase::RETURN_HOME: return "RETURN_HOME";
    case Phase::PREPARATION: return "PREPARATION";
    case Phase::HARVEST_FIELD: return "HARVEST_FIELD";
    case Phase::HARVEST_FEED: return "HARVEST_FEED";
    case Phase::HARVEST_BREED: return "HARVEST_BREED";
    case Phase::BEFORE_SCORING: return "BEFORE_SCORING";
  }
  throw std::runtime_error("bad Phase");
}
Phase phase_from_name(const std::string& n) {
  if (n == "WORK") return Phase::WORK;
  if (n == "RETURN_HOME") return Phase::RETURN_HOME;
  if (n == "PREPARATION") return Phase::PREPARATION;
  if (n == "HARVEST_FIELD") return Phase::HARVEST_FIELD;
  if (n == "HARVEST_FEED") return Phase::HARVEST_FEED;
  if (n == "HARVEST_BREED") return Phase::HARVEST_BREED;
  if (n == "BEFORE_SCORING") return Phase::BEFORE_SCORING;
  throw std::runtime_error("bad Phase name: " + n);
}
const char* cell_type_name(CellType t) {
  switch (t) {
    case CellType::EMPTY: return "EMPTY";
    case CellType::ROOM: return "ROOM";
    case CellType::FIELD: return "FIELD";
    case CellType::STABLE: return "STABLE";
  }
  throw std::runtime_error("bad CellType");
}
CellType cell_type_from_name(const std::string& n) {
  if (n == "EMPTY") return CellType::EMPTY;
  if (n == "ROOM") return CellType::ROOM;
  if (n == "FIELD") return CellType::FIELD;
  if (n == "STABLE") return CellType::STABLE;
  throw std::runtime_error("bad CellType name: " + n);
}
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

// --- node builders ----------------------------------------------------------
json enum_node(const char* cls, const char* name) {
  json j;
  j["__enum__"] = cls;
  j["name"] = name;
  return j;
}
json opt_int_node(const std::optional<int>& v) {
  return v.has_value() ? json(*v) : json(nullptr);
}
json str_set_node(std::vector<std::string> v) {
  std::sort(v.begin(), v.end());
  json arr = json::array();
  for (auto& s : v) arr.push_back(s);
  json j;
  j["__set__"] = std::move(arr);
  return j;
}
json coord_set_node(std::vector<Coord> cells) {
  std::sort(cells.begin(), cells.end());
  json arr = json::array();
  for (const auto& [r, c] : cells) arr.push_back(json::array({r, c}));
  json j;
  j["__set__"] = std::move(arr);
  return j;
}

std::optional<int> read_opt_int(const json& j) {
  return j.is_null() ? std::nullopt : std::optional<int>(j.get<int>());
}
std::vector<std::string> read_str_set(const json& j) {
  std::vector<std::string> out;
  for (const auto& e : j.at("__set__")) out.push_back(e.get<std::string>());
  return out;
}

// --- to_canonical (tc) ------------------------------------------------------
json tc(const Resources& r) {
  json j;
  j["__type__"] = "Resources";
  j["wood"] = r.wood;  j["clay"] = r.clay;  j["reed"] = r.reed;
  j["stone"] = r.stone;  j["food"] = r.food;  j["grain"] = r.grain;
  j["veg"] = r.veg;
  return j;
}
json tc(const Animals& a) {
  json j;
  j["__type__"] = "Animals";
  j["sheep"] = a.sheep;  j["boar"] = a.boar;  j["cattle"] = a.cattle;
  return j;
}
json tc(const Cell& c) {
  json j;
  j["__type__"] = "Cell";
  j["cell_type"] = enum_node("CellType", cell_type_name(c.cell_type));
  j["grain"] = c.grain;  j["veg"] = c.veg;
  return j;
}
json tc(const Pasture& p) {
  json j;
  j["__type__"] = "Pasture";
  j["cells"] = coord_set_node(p.cells);
  j["num_stables"] = p.num_stables;
  j["capacity"] = p.capacity;
  return j;
}
json tc(const Farmyard& f) {
  json j;
  j["__type__"] = "Farmyard";
  json grid = json::array();
  for (const auto& row : f.grid) {
    json jrow = json::array();
    for (const auto& cell : row) jrow.push_back(tc(cell));
    grid.push_back(std::move(jrow));
  }
  j["grid"] = std::move(grid);
  json hf = json::array();
  for (const auto& row : f.horizontal_fences) {
    json jrow = json::array();
    for (bool b : row) jrow.push_back(b);
    hf.push_back(std::move(jrow));
  }
  j["horizontal_fences"] = std::move(hf);
  json vf = json::array();
  for (const auto& row : f.vertical_fences) {
    json jrow = json::array();
    for (bool b : row) jrow.push_back(b);
    vf.push_back(std::move(jrow));
  }
  j["vertical_fences"] = std::move(vf);
  json pastures = json::array();
  for (const auto& p : f.pastures) pastures.push_back(tc(p));
  j["pastures"] = std::move(pastures);
  return j;
}
json tc(const ActionSpaceState& s) {
  json j;
  j["__type__"] = "ActionSpaceState";
  j["workers"] = json::array({s.workers[0], s.workers[1]});
  j["accumulated"] = tc(s.accumulated);
  j["accumulated_amount"] = s.accumulated_amount;
  j["revealed"] = s.revealed;
  return j;
}
json tc(const PlayerState& p) {
  json j;
  j["__type__"] = "PlayerState";
  j["resources"] = tc(p.resources);
  j["animals"] = tc(p.animals);
  j["farmyard"] = tc(p.farmyard);
  j["house_material"] =
      enum_node("HouseMaterial", house_material_name(p.house_material));
  j["people_total"] = p.people_total;
  j["people_home"] = p.people_home;
  j["newborns"] = p.newborns;
  j["begging_markers"] = p.begging_markers;
  json fr = json::array();
  for (const auto& r : p.future_resources) fr.push_back(tc(r));
  j["future_resources"] = std::move(fr);
  j["minor_improvements"] = str_set_node(p.minor_improvements);
  j["occupations"] = str_set_node(p.occupations);
  j["harvest_conversions_used"] = str_set_node(p.harvest_conversions_used);
  return j;
}
json tc(const BoardState& b) {
  json j;
  j["__type__"] = "BoardState";
  json spaces = json::array();
  for (const auto& s : b.action_spaces) spaces.push_back(tc(s));
  j["action_spaces"] = std::move(spaces);
  json owners = json::array();
  for (const auto& o : b.major_improvement_owners) owners.push_back(opt_int_node(o));
  j["major_improvement_owners"] = std::move(owners);
  return j;
}

// Pending frames. Helper to start a frame with the common leading fields.
json pframe(const char* type, const std::optional<int>& player_idx,
            const std::string& initiated_by_id) {
  json j;
  j["__type__"] = type;
  j["player_idx"] = opt_int_node(player_idx);
  j["initiated_by_id"] = initiated_by_id;
  return j;
}
json tc(const PendingGrainUtilization& p) {
  json j = pframe("PendingGrainUtilization", p.player_idx, p.initiated_by_id);
  j["sow_chosen"] = p.sow_chosen;  j["bake_chosen"] = p.bake_chosen;
  return j;
}
json tc(const PendingSow& p) {
  json j = pframe("PendingSow", p.player_idx, p.initiated_by_id);
  j["phase"] = p.phase;
  j["triggers_resolved"] = str_set_node(p.triggers_resolved);
  return j;
}
json tc(const PendingBakeBread& p) {
  json j = pframe("PendingBakeBread", p.player_idx, p.initiated_by_id);
  j["phase"] = p.phase;
  j["triggers_resolved"] = str_set_node(p.triggers_resolved);
  return j;
}
json tc(const PendingPlow& p) {
  json j = pframe("PendingPlow", p.player_idx, p.initiated_by_id);
  j["phase"] = p.phase;
  j["triggers_resolved"] = str_set_node(p.triggers_resolved);
  return j;
}
json tc(const PendingFarmExpansion& p) {
  json j = pframe("PendingFarmExpansion", p.player_idx, p.initiated_by_id);
  j["room_chosen"] = p.room_chosen;  j["stable_chosen"] = p.stable_chosen;
  return j;
}
json tc(const PendingBuildStables& p) {
  json j = pframe("PendingBuildStables", p.player_idx, p.initiated_by_id);
  j["cost"] = tc(p.cost);  j["max_builds"] = opt_int_node(p.max_builds);
  j["num_built"] = p.num_built;
  return j;
}
json tc(const PendingBuildRooms& p) {
  json j = pframe("PendingBuildRooms", p.player_idx, p.initiated_by_id);
  j["cost"] = tc(p.cost);  j["max_builds"] = opt_int_node(p.max_builds);
  j["num_built"] = p.num_built;
  return j;
}
json tc(const PendingBuildMajor& p) {
  json j = pframe("PendingBuildMajor", p.player_idx, p.initiated_by_id);
  j["phase"] = p.phase;
  j["triggers_resolved"] = str_set_node(p.triggers_resolved);
  return j;
}
json tc(const PendingRenovate& p) {
  json j = pframe("PendingRenovate", p.player_idx, p.initiated_by_id);
  j["cost"] = tc(p.cost);
  j["phase"] = p.phase;
  j["triggers_resolved"] = str_set_node(p.triggers_resolved);
  return j;
}
json tc(const PendingFarmland& p) {
  json j = pframe("PendingFarmland", p.player_idx, p.initiated_by_id);
  j["plow_chosen"] = p.plow_chosen;
  j["triggers_resolved"] = str_set_node(p.triggers_resolved);
  return j;
}
json tc(const PendingCultivation& p) {
  json j = pframe("PendingCultivation", p.player_idx, p.initiated_by_id);
  j["plow_chosen"] = p.plow_chosen;  j["sow_chosen"] = p.sow_chosen;
  j["triggers_resolved"] = str_set_node(p.triggers_resolved);
  return j;
}
json tc(const PendingSideJob& p) {
  json j = pframe("PendingSideJob", p.player_idx, p.initiated_by_id);
  j["stable_chosen"] = p.stable_chosen;  j["bake_chosen"] = p.bake_chosen;
  j["triggers_resolved"] = str_set_node(p.triggers_resolved);
  return j;
}
json tc(const PendingSheepMarket& p) {
  json j = pframe("PendingSheepMarket", p.player_idx, p.initiated_by_id);
  j["gained"] = p.gained;
  j["phase"] = p.phase;
  j["triggers_resolved"] = str_set_node(p.triggers_resolved);
  return j;
}
json tc(const PendingPigMarket& p) {
  json j = pframe("PendingPigMarket", p.player_idx, p.initiated_by_id);
  j["gained"] = p.gained;
  j["phase"] = p.phase;
  j["triggers_resolved"] = str_set_node(p.triggers_resolved);
  return j;
}
json tc(const PendingCattleMarket& p) {
  json j = pframe("PendingCattleMarket", p.player_idx, p.initiated_by_id);
  j["gained"] = p.gained;
  j["phase"] = p.phase;
  j["triggers_resolved"] = str_set_node(p.triggers_resolved);
  return j;
}
json tc(const PendingMajorMinorImprovement& p) {
  json j = pframe("PendingMajorMinorImprovement", p.player_idx, p.initiated_by_id);
  j["major_chosen"] = p.major_chosen;  j["minor_chosen"] = p.minor_chosen;
  j["triggers_resolved"] = str_set_node(p.triggers_resolved);
  return j;
}
json tc(const PendingHouseRedevelopment& p) {
  json j = pframe("PendingHouseRedevelopment", p.player_idx, p.initiated_by_id);
  j["renovate_chosen"] = p.renovate_chosen;
  j["improvement_chosen"] = p.improvement_chosen;
  j["triggers_resolved"] = str_set_node(p.triggers_resolved);
  return j;
}
json tc(const PendingClayOven& p) {
  json j = pframe("PendingClayOven", p.player_idx, p.initiated_by_id);
  j["bake_chosen"] = p.bake_chosen;
  return j;
}
json tc(const PendingStoneOven& p) {
  json j = pframe("PendingStoneOven", p.player_idx, p.initiated_by_id);
  j["bake_chosen"] = p.bake_chosen;
  return j;
}
json tc(const PendingFencing& p) {
  json j = pframe("PendingFencing", p.player_idx, p.initiated_by_id);
  j["build_fences_chosen"] = p.build_fences_chosen;
  j["triggers_resolved"] = str_set_node(p.triggers_resolved);
  return j;
}
json tc(const PendingBuildFences& p) {
  json j = pframe("PendingBuildFences", p.player_idx, p.initiated_by_id);
  j["pastures_built"] = p.pastures_built;  j["fences_built"] = p.fences_built;
  j["subdivision_started"] = p.subdivision_started;
  j["triggers_resolved"] = str_set_node(p.triggers_resolved);
  return j;
}
json tc(const PendingFarmRedevelopment& p) {
  json j = pframe("PendingFarmRedevelopment", p.player_idx, p.initiated_by_id);
  j["renovate_chosen"] = p.renovate_chosen;
  j["build_fences_chosen"] = p.build_fences_chosen;
  j["triggers_resolved"] = str_set_node(p.triggers_resolved);
  return j;
}
json tc(const PendingHarvestFeed& p) {
  json j = pframe("PendingHarvestFeed", p.player_idx, p.initiated_by_id);
  j["conversion_done"] = p.conversion_done;
  return j;
}
json tc(const PendingHarvestBreed& p) {
  json j = pframe("PendingHarvestBreed", p.player_idx, p.initiated_by_id);
  j["breed_chosen"] = p.breed_chosen;
  return j;
}
json tc(const PendingReveal& p) {
  return pframe("PendingReveal", p.player_idx, p.initiated_by_id);
}
json tc(const PendingDecision& pd) {
  return std::visit([](const auto& p) { return tc(p); }, pd);
}
json tc(const GameState& s) {
  json j;
  j["__type__"] = "GameState";
  j["round_number"] = s.round_number;
  j["phase"] = enum_node("Phase", phase_name(s.phase));
  j["current_player"] = s.current_player;
  j["starting_player"] = s.starting_player;
  json players = json::array();
  players.push_back(tc(s.players[0]));
  players.push_back(tc(s.players[1]));
  j["players"] = std::move(players);
  j["board"] = tc(s.board);
  json stack = json::array();
  for (const auto& f : s.pending_stack) stack.push_back(tc(f));
  j["pending_stack"] = std::move(stack);
  return j;
}

// --- from_canonical (fc) ----------------------------------------------------
Resources resources_from(const json& j) {
  return Resources{j.at("wood"), j.at("clay"), j.at("reed"), j.at("stone"),
                   j.at("food"), j.at("grain"), j.at("veg")};
}
Animals animals_from(const json& j) {
  return Animals{j.at("sheep"), j.at("boar"), j.at("cattle")};
}
Cell cell_from(const json& j) {
  return Cell{cell_type_from_name(j.at("cell_type").at("name")),
              j.at("grain"), j.at("veg")};
}
Pasture pasture_from(const json& j) {
  Pasture p;
  for (const auto& c : j.at("cells").at("__set__"))
    p.cells.emplace_back(c.at(0).get<int>(), c.at(1).get<int>());
  std::sort(p.cells.begin(), p.cells.end());
  p.num_stables = j.at("num_stables");
  p.capacity = j.at("capacity");
  return p;
}
Farmyard farmyard_from(const json& j) {
  Farmyard f;
  const auto& grid = j.at("grid");
  for (int r = 0; r < kRows; ++r)
    for (int c = 0; c < kCols; ++c) f.grid[r][c] = cell_from(grid.at(r).at(c));
  const auto& hf = j.at("horizontal_fences");
  for (int r = 0; r < kRows + 1; ++r)
    for (int c = 0; c < kCols; ++c) f.horizontal_fences[r][c] = hf.at(r).at(c);
  const auto& vf = j.at("vertical_fences");
  for (int r = 0; r < kRows; ++r)
    for (int c = 0; c < kCols + 1; ++c) f.vertical_fences[r][c] = vf.at(r).at(c);
  for (const auto& p : j.at("pastures")) f.pastures.push_back(pasture_from(p));
  return f;
}
ActionSpaceState action_space_from(const json& j) {
  ActionSpaceState s;
  s.workers = {j.at("workers").at(0).get<int>(), j.at("workers").at(1).get<int>()};
  s.accumulated = resources_from(j.at("accumulated"));
  s.accumulated_amount = j.at("accumulated_amount");
  s.revealed = j.at("revealed");
  return s;
}
PlayerState player_from(const json& j) {
  PlayerState p;
  p.resources = resources_from(j.at("resources"));
  p.animals = animals_from(j.at("animals"));
  p.farmyard = farmyard_from(j.at("farmyard"));
  p.house_material = house_material_from_name(j.at("house_material").at("name"));
  p.people_total = j.at("people_total");
  p.people_home = j.at("people_home");
  p.newborns = j.at("newborns");
  p.begging_markers = j.at("begging_markers");
  for (const auto& r : j.at("future_resources"))
    p.future_resources.push_back(resources_from(r));
  p.minor_improvements = read_str_set(j.at("minor_improvements"));
  p.occupations = read_str_set(j.at("occupations"));
  p.harvest_conversions_used = read_str_set(j.at("harvest_conversions_used"));
  return p;
}
BoardState board_from(const json& j) {
  BoardState b;
  for (const auto& s : j.at("action_spaces"))
    b.action_spaces.push_back(action_space_from(s));
  for (const auto& o : j.at("major_improvement_owners"))
    b.major_improvement_owners.push_back(read_opt_int(o));
  return b;
}
PendingDecision pending_from(const json& j) {
  const std::string t = j.at("__type__");
  auto pid = read_opt_int(j.at("player_idx"));
  std::string iby = j.at("initiated_by_id");
  if (t == "PendingGrainUtilization")
    return PendingGrainUtilization{pid, iby, j.at("sow_chosen"), j.at("bake_chosen")};
  if (t == "PendingSow")
    return PendingSow{pid, iby, j.value("phase", std::string("before")),
                      read_str_set(j.at("triggers_resolved"))};
  if (t == "PendingBakeBread")
    return PendingBakeBread{pid, iby, j.value("phase", std::string("before")),
                            read_str_set(j.at("triggers_resolved"))};
  if (t == "PendingPlow")
    return PendingPlow{pid, iby, j.value("phase", std::string("before")),
                       read_str_set(j.at("triggers_resolved"))};
  if (t == "PendingFarmExpansion")
    return PendingFarmExpansion{pid, iby, j.at("room_chosen"), j.at("stable_chosen")};
  if (t == "PendingBuildStables")
    return PendingBuildStables{pid, iby, resources_from(j.at("cost")),
                               read_opt_int(j.at("max_builds")), j.at("num_built")};
  if (t == "PendingBuildRooms")
    return PendingBuildRooms{pid, iby, resources_from(j.at("cost")),
                             read_opt_int(j.at("max_builds")), j.at("num_built")};
  if (t == "PendingBuildMajor")
    return PendingBuildMajor{pid, iby, j.value("phase", std::string("before")),
                             read_str_set(j.at("triggers_resolved"))};
  if (t == "PendingRenovate")
    return PendingRenovate{pid, iby, resources_from(j.at("cost")),
                           j.value("phase", std::string("before")),
                           read_str_set(j.at("triggers_resolved"))};
  if (t == "PendingFarmland")
    return PendingFarmland{pid, iby, j.at("plow_chosen"),
                           read_str_set(j.at("triggers_resolved"))};
  if (t == "PendingCultivation")
    return PendingCultivation{pid, iby, j.at("plow_chosen"), j.at("sow_chosen"),
                              read_str_set(j.at("triggers_resolved"))};
  if (t == "PendingSideJob")
    return PendingSideJob{pid, iby, j.at("stable_chosen"), j.at("bake_chosen"),
                          read_str_set(j.at("triggers_resolved"))};
  if (t == "PendingSheepMarket")
    return PendingSheepMarket{pid, iby, j.at("gained"),
                              j.value("phase", std::string("before")),
                              read_str_set(j.at("triggers_resolved"))};
  if (t == "PendingPigMarket")
    return PendingPigMarket{pid, iby, j.at("gained"),
                            j.value("phase", std::string("before")),
                            read_str_set(j.at("triggers_resolved"))};
  if (t == "PendingCattleMarket")
    return PendingCattleMarket{pid, iby, j.at("gained"),
                               j.value("phase", std::string("before")),
                               read_str_set(j.at("triggers_resolved"))};
  if (t == "PendingMajorMinorImprovement")
    return PendingMajorMinorImprovement{pid, iby, j.at("major_chosen"),
                                        j.at("minor_chosen"),
                                        read_str_set(j.at("triggers_resolved"))};
  if (t == "PendingHouseRedevelopment")
    return PendingHouseRedevelopment{pid, iby, j.at("renovate_chosen"),
                                     j.at("improvement_chosen"),
                                     read_str_set(j.at("triggers_resolved"))};
  if (t == "PendingClayOven")
    return PendingClayOven{pid, iby, j.at("bake_chosen")};
  if (t == "PendingStoneOven")
    return PendingStoneOven{pid, iby, j.at("bake_chosen")};
  if (t == "PendingFencing")
    return PendingFencing{pid, iby, j.at("build_fences_chosen"),
                          read_str_set(j.at("triggers_resolved"))};
  if (t == "PendingBuildFences")
    return PendingBuildFences{pid, iby, j.at("pastures_built"), j.at("fences_built"),
                              j.at("subdivision_started"),
                              read_str_set(j.at("triggers_resolved"))};
  if (t == "PendingFarmRedevelopment")
    return PendingFarmRedevelopment{pid, iby, j.at("renovate_chosen"),
                                    j.at("build_fences_chosen"),
                                    read_str_set(j.at("triggers_resolved"))};
  if (t == "PendingHarvestFeed")
    return PendingHarvestFeed{pid, iby, j.at("conversion_done")};
  if (t == "PendingHarvestBreed")
    return PendingHarvestBreed{pid, iby, j.at("breed_chosen")};
  if (t == "PendingReveal") return PendingReveal{pid, iby};
  throw std::runtime_error("unknown pending __type__: " + t);
}
GameState game_state_from(const json& j) {
  GameState s;
  s.round_number = j.at("round_number");
  s.phase = phase_from_name(j.at("phase").at("name"));
  s.current_player = j.at("current_player");
  s.starting_player = j.at("starting_player");
  s.players[0] = player_from(j.at("players").at(0));
  s.players[1] = player_from(j.at("players").at(1));
  s.board = board_from(j.at("board"));
  for (const auto& f : j.at("pending_stack")) s.pending_stack.push_back(pending_from(f));
  return s;
}

}  // namespace

std::string to_canonical_string(const GameState& state) {
  return tc(state).dump();
}

GameState game_state_from_string(const std::string& text) {
  return game_state_from(json::parse(text));
}

std::string pending_to_canonical(const PendingDecision& frame) {
  return tc(frame).dump();
}

}  // namespace agricola
