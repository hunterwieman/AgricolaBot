// Pasture flood-fill — a faithful port of
// agricola/pasture.py:compute_pastures_from_arrays (CPP_ENGINE_PLAN.md §4).
//
// 3-pass: (1) flood-fill "outside" through open edges, (2) enclosed = complement,
// (3) connected components among enclosed cells. Output sorted by min(cells)
// lexicographically — load-bearing for Farmyard equality/hashing.
#pragma once

#include "agricola/types.hpp"

namespace agricola {

// Recompute the canonical pasture decomposition from a farmyard's grid + fences
// (ignores any existing farmyard.pastures).
std::vector<Pasture> compute_pastures(const Farmyard& fy);

}  // namespace agricola
