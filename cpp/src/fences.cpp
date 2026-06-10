#include "agricola/fences.hpp"

namespace agricola {

int popcount(std::uint32_t x) {
  int n = 0;
  while (x) { x &= x - 1; ++n; }
  return n;
}

std::uint32_t pack_fences_h(const Farmyard& fy) {
  std::uint32_t bm = 0;
  for (int r = 0; r < kFenceRows + 1; ++r)
    for (int c = 0; c < kFenceCols; ++c)
      if (fy.horizontal_fences[r][c]) bm |= 1u << (r * kFenceCols + c);
  return bm;
}

std::uint32_t pack_fences_v(const Farmyard& fy) {
  std::uint32_t bm = 0;
  for (int r = 0; r < kFenceRows; ++r)
    for (int c = 0; c < kFenceCols + 1; ++c)
      if (fy.vertical_fences[r][c]) bm |= 1u << (r * (kFenceCols + 1) + c);
  return bm;
}

NewFenceEdges compute_new_fence_edges(const Farmyard& fy,
                                      std::uint32_t cells_bm) {
  // Look the entry up in the RESTRICTED table (the active universe). The Python
  // helper keys ENTRIES_BY_BM off UNIVERSE_FULL, but every cells_bm that
  // reaches here in Family-game play comes from a RESTRICTED CommitBuildPasture.
  const PastureCandidate* entry = nullptr;
  for (const auto& e : restricted_universe_entries()) {
    if (e.cells_bm == cells_bm) { entry = &e; break; }
  }
  NewFenceEdges out;
  if (entry == nullptr) return out;  // unknown shape -> 0 cost (defensive)
  std::uint32_t h_fences = pack_fences_h(fy);
  std::uint32_t v_fences = pack_fences_v(fy);
  out.h_new_bm = entry->h_boundary_bm & ~h_fences;
  out.v_new_bm = entry->v_boundary_bm & ~v_fences;
  out.wood_cost = popcount(out.h_new_bm) + popcount(out.v_new_bm);
  return out;
}

std::array<std::array<bool, kFenceCols>, kFenceRows + 1> apply_fence_edges_h(
    const std::array<std::array<bool, kFenceCols>, kFenceRows + 1>& fences,
    std::uint32_t new_bm) {
  auto out = fences;
  for (int r = 0; r < kFenceRows + 1; ++r)
    for (int c = 0; c < kFenceCols; ++c)
      if (new_bm & (1u << (r * kFenceCols + c))) out[r][c] = true;
  return out;
}

std::array<std::array<bool, kFenceCols + 1>, kFenceRows> apply_fence_edges_v(
    const std::array<std::array<bool, kFenceCols + 1>, kFenceRows>& fences,
    std::uint32_t new_bm) {
  auto out = fences;
  for (int r = 0; r < kFenceRows; ++r)
    for (int c = 0; c < kFenceCols + 1; ++c)
      if (new_bm & (1u << (r * (kFenceCols + 1) + c))) out[r][c] = true;
  return out;
}

}  // namespace agricola
