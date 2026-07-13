#include "agricola/hash.hpp"

#include <cstdint>
#include <string>
#include <variant>
#include <vector>

#include "agricola/types.hpp"

namespace agricola {
namespace {

// boost-style 64-bit hash_combine mixer.
inline void mix(std::uint64_t& h, std::uint64_t v) {
  h ^= v + 0x9e3779b97f4a7c15ULL + (h << 6) + (h >> 2);
}

inline void hi(std::uint64_t& h, int v) { mix(h, static_cast<std::uint64_t>(static_cast<std::int64_t>(v))); }
inline void hi(std::uint64_t& h, bool v) { mix(h, v ? 1u : 0u); }
inline void hi(std::uint64_t& h, Phase v) { mix(h, static_cast<std::uint64_t>(v)); }
inline void hi(std::uint64_t& h, CellType v) { mix(h, static_cast<std::uint64_t>(v)); }
inline void hi(std::uint64_t& h, HouseMaterial v) { mix(h, static_cast<std::uint64_t>(v)); }
inline void hi(std::uint64_t& h, const std::string& s) {
  for (unsigned char c : s) mix(h, c);
  mix(h, s.size());
}
inline void hi(std::uint64_t& h, const std::optional<int>& v) {
  if (v) { mix(h, 1u); hi(h, *v); } else { mix(h, 0u); }
}

void hi(std::uint64_t& h, const Resources& r) {
  hi(h, r.wood); hi(h, r.clay); hi(h, r.reed); hi(h, r.stone);
  hi(h, r.food); hi(h, r.grain); hi(h, r.veg);
}
void hi(std::uint64_t& h, const Animals& a) { hi(h, a.sheep); hi(h, a.boar); hi(h, a.cattle); }
void hi(std::uint64_t& h, const Cell& c) { hi(h, c.cell_type); hi(h, c.grain); hi(h, c.veg); }
void hi(std::uint64_t& h, const Pasture& p) {
  for (const auto& [r, cc] : p.cells) { hi(h, r); hi(h, cc); }
  mix(h, p.cells.size());
  hi(h, p.num_stables); hi(h, p.capacity);
}
void hi(std::uint64_t& h, const Farmyard& f) {
  for (const auto& row : f.grid) for (const auto& c : row) hi(h, c);
  for (const auto& row : f.horizontal_fences) for (bool b : row) hi(h, b);
  for (const auto& row : f.vertical_fences) for (bool b : row) hi(h, b);
  for (const auto& p : f.pastures) hi(h, p);
  mix(h, f.pastures.size());
}
void hi(std::uint64_t& h, const ActionSpaceState& s) {
  hi(h, s.workers[0]); hi(h, s.workers[1]);
  hi(h, s.accumulated); hi(h, s.accumulated_amount); hi(h, s.revealed);
}
void hi(std::uint64_t& h, const PlayerState& p) {
  hi(h, p.resources); hi(h, p.animals); hi(h, p.farmyard); hi(h, p.house_material);
  hi(h, p.people_total); hi(h, p.people_home); hi(h, p.newborns); hi(h, p.begging_markers);
  for (const auto& r : p.future_resources) hi(h, r);
  for (const auto& s : p.minor_improvements) hi(h, s);
  mix(h, p.minor_improvements.size());
  for (const auto& s : p.occupations) hi(h, s);
  mix(h, p.occupations.size());
  for (const auto& s : p.harvest_conversions_used) hi(h, s);
  mix(h, p.harvest_conversions_used.size());
  hi(h, p.fences_in_supply);
}
void hi(std::uint64_t& h, const BoardState& b) {
  for (const auto& s : b.action_spaces) hi(h, s);
  for (const auto& o : b.major_improvement_owners) hi(h, o);
}
inline void hi(std::uint64_t& h, const std::vector<std::string>& v) {
  for (const auto& s : v) hi(h, s);
  mix(h, v.size());
}

// Field-wise pending-frame hashing. Replaces the previous round-trip through
// pending_to_canonical (build an nlohmann::json object, dump to a string, hash
// the string) — pure allocation/serialization overhead on a hot path. Hashing
// the fields directly mirrors how PlayerState/BoardState above are hashed. Every
// discriminating field is mixed in (matching the JSON's discrimination), so two
// states differing only in a pending flag still hash apart. Note this only needs
// to be a good bucketing key: the transposition table resolves true equality via
// GameState's defaulted operator==, so a collision costs a bucket walk, never
// correctness. The common prefix (player_idx + initiated_by_id) is shared.
inline void hpre(std::uint64_t& h, const std::optional<int>& pidx,
                 const std::string& id) {
  hi(h, pidx);
  hi(h, id);
}
inline void hf(std::uint64_t& h, const PendingGrainUtilization& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.sow_chosen); hi(h, f.bake_chosen);
  hi(h, f.phase); hi(h, f.triggers_resolved);
}
inline void hf(std::uint64_t& h, const PendingSow& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.phase); hi(h, f.triggers_resolved);
}
inline void hf(std::uint64_t& h, const PendingBakeBread& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.phase); hi(h, f.triggers_resolved);
}
inline void hf(std::uint64_t& h, const PendingPlow& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.phase); hi(h, f.triggers_resolved);
}
inline void hf(std::uint64_t& h, const PendingFarmExpansion& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.room_chosen); hi(h, f.stable_chosen);
  hi(h, f.phase); hi(h, f.triggers_resolved);
}
inline void hf(std::uint64_t& h, const PendingBuildStables& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.cost); hi(h, f.max_builds); hi(h, f.num_built);
  hi(h, f.phase); hi(h, f.triggers_resolved);
}
inline void hf(std::uint64_t& h, const PendingBuildRooms& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.max_builds); hi(h, f.num_built);
  hi(h, f.phase); hi(h, f.triggers_resolved);
}
inline void hf(std::uint64_t& h, const PendingBuildMajor& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.phase); hi(h, f.triggers_resolved);
}
inline void hf(std::uint64_t& h, const PendingRenovate& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.phase); hi(h, f.triggers_resolved);
}
inline void hf(std::uint64_t& h, const PendingSubActionSpace& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.subaction_complete);
  hi(h, f.phase); hi(h, f.triggers_resolved);
}
inline void hf(std::uint64_t& h, const PendingCultivation& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.plow_chosen); hi(h, f.sow_chosen);
  hi(h, f.phase); hi(h, f.triggers_resolved);
}
inline void hf(std::uint64_t& h, const PendingSideJob& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.stable_chosen); hi(h, f.bake_chosen); hi(h, f.triggers_resolved);
}
inline void hf(std::uint64_t& h, const PendingSheepMarket& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.gained); hi(h, f.phase); hi(h, f.triggers_resolved);
}
inline void hf(std::uint64_t& h, const PendingPigMarket& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.gained); hi(h, f.phase); hi(h, f.triggers_resolved);
}
inline void hf(std::uint64_t& h, const PendingCattleMarket& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.gained); hi(h, f.phase); hi(h, f.triggers_resolved);
}
inline void hf(std::uint64_t& h, const PendingMajorMinorImprovement& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.major_chosen); hi(h, f.minor_chosen);
  hi(h, f.phase); hi(h, f.triggers_resolved);
}
inline void hf(std::uint64_t& h, const PendingHouseRedevelopment& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.renovate_chosen); hi(h, f.improvement_chosen);
  hi(h, f.phase); hi(h, f.triggers_resolved);
}
inline void hf(std::uint64_t& h, const PendingClayOven& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.bake_chosen);
}
inline void hf(std::uint64_t& h, const PendingStoneOven& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.bake_chosen);
}
inline void hf(std::uint64_t& h, const PendingBuildFences& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.pastures_built); hi(h, f.fences_built);
  hi(h, f.subdivision_started); hi(h, f.phase); hi(h, f.triggers_resolved);
}
inline void hf(std::uint64_t& h, const PendingFarmRedevelopment& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.renovate_chosen); hi(h, f.build_fences_chosen);
  hi(h, f.phase); hi(h, f.triggers_resolved);
}
inline void hf(std::uint64_t& h, const PendingHarvestFeed& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.conversion_done);
}
inline void hf(std::uint64_t& h, const PendingHarvestBreed& f) {
  hpre(h, f.player_idx, f.initiated_by_id); hi(h, f.breed_chosen);
}
inline void hf(std::uint64_t& h, const PendingReveal& f) {
  hpre(h, f.player_idx, f.initiated_by_id);
}

}  // namespace

std::uint64_t state_hash(const GameState& s) {
  std::uint64_t h = 1469598103934665603ULL;  // FNV-1a 64-bit offset basis (seed)
  hi(h, s.round_number);
  hi(h, s.phase);
  hi(h, s.current_player);
  hi(h, s.starting_player);
  hi(h, s.players[0]);
  hi(h, s.players[1]);
  hi(h, s.board);
  // Pending frames: hash the variant index + every field of the active frame
  // (the hf overloads above), so flags/counters fully discriminate (avoids
  // transposition-table collisions between states differing only in a pending
  // flag). Done field-wise rather than via pending_to_canonical (build a JSON
  // object + dump to a string + hash the chars) — that round-trip was pure
  // allocation/serialization overhead on this hot path.
  for (const auto& frame : s.pending_stack) {
    mix(h, frame.index());
    std::visit([&](const auto& f) { hf(h, f); }, frame);
  }
  mix(h, s.pending_stack.size());
  // Mirrors GameState.__hash__: two states differing only in the harvest
  // virtual-walk cursor must hash apart (mid-FEED/BREED band passes carry it).
  hi(h, s.harvest_cursor);
  return h;
}

}  // namespace agricola
