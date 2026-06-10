#include "agricola/hash.hpp"

#include <cstdint>
#include <string>
#include <variant>

#include "agricola/canonical.hpp"

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
}
void hi(std::uint64_t& h, const BoardState& b) {
  for (const auto& s : b.action_spaces) hi(h, s);
  for (const auto& o : b.major_improvement_owners) hi(h, o);
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
  // Pending frames: hash the variant index + the frame's full canonical form so
  // flags/counters fully discriminate (avoids transposition-table collisions
  // between states that differ only in a pending flag). Frames are small and the
  // stack is usually short, so this is cheap — far cheaper than serializing the
  // whole state, which is what state_hash used to do.
  for (const auto& frame : s.pending_stack) {
    mix(h, frame.index());
    hi(h, pending_to_canonical(frame));
  }
  mix(h, s.pending_stack.size());
  return h;
}

}  // namespace agricola
