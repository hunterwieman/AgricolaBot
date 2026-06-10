// Fence-universe metadata + bitmap helpers — a faithful mirror of the relevant
// parts of agricola/fences.py (CPP_ENGINE_PLAN.md §4 row 6). The RESTRICTED
// universe table itself is generated (fence_universe_data.cpp) by
// cpp/gen/export_fence_universe.py — we do NOT port the enumeration logic.
#pragma once

#include <cstdint>
#include <utility>
#include <vector>

#include "agricola/types.hpp"

namespace agricola {

constexpr int kFenceRows = 3;  // NUM_ROWS
constexpr int kFenceCols = 5;  // NUM_COLS
constexpr int kNumCells = 15;

// One candidate pasture shape: cell-set bitmap + precomputed edge metadata.
// Mirrors fences.PastureCandidate.
struct PastureCandidate {
  std::uint32_t cells_bm = 0;       // 15-bit cell-set bitmap
  std::uint32_t h_boundary_bm = 0;  // 20-bit horizontal-edge boundary
  std::uint32_t v_boundary_bm = 0;  // 18-bit vertical-edge boundary
  std::uint32_t adjacency_bm = 0;   // 15-bit in-grid orthogonal neighbors
  std::vector<Coord> cells;         // sorted (r,c) cell list
};

// The RESTRICTED universe entries (generated; same order as Python).
const std::vector<PastureCandidate>& restricted_universe_entries();

// Bitmap pack helpers (Farmyard fence arrays -> bitmap).
std::uint32_t pack_fences_h(const Farmyard& fy);
std::uint32_t pack_fences_v(const Farmyard& fy);

// Cost helper: new edges + wood cost for placing cells_bm's boundary on top of
// the player's current fences. Mirrors compute_new_fence_edges.
struct NewFenceEdges {
  std::uint32_t h_new_bm = 0;
  std::uint32_t v_new_bm = 0;
  int wood_cost = 0;
};
NewFenceEdges compute_new_fence_edges(const Farmyard& fy,
                                      std::uint32_t cells_bm);

// Return the (4,5) horizontal / (3,6) vertical fence arrays with the bits in
// `new_bm` OR'd on (mirrors fences.apply_fence_edges_h / apply_fence_edges_v).
std::array<std::array<bool, kFenceCols>, kFenceRows + 1> apply_fence_edges_h(
    const std::array<std::array<bool, kFenceCols>, kFenceRows + 1>& fences,
    std::uint32_t new_bm);
std::array<std::array<bool, kFenceCols + 1>, kFenceRows> apply_fence_edges_v(
    const std::array<std::array<bool, kFenceCols + 1>, kFenceRows>& fences,
    std::uint32_t new_bm);

int popcount(std::uint32_t x);

}  // namespace agricola
