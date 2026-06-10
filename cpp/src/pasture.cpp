#include "agricola/pasture.hpp"

#include <algorithm>
#include <array>
#include <deque>
#include <set>

namespace agricola {
namespace {

// Mirror of pasture.py:_are_connected — two orthogonally adjacent cells have no
// fence between them. Caller guarantees (r2,c2) is an orthogonal neighbour.
bool are_connected(const Farmyard& fy, int r1, int c1, int r2, int c2) {
  if (r2 == r1 + 1) return !fy.horizontal_fences[r1 + 1][c1];
  if (r2 == r1 - 1) return !fy.horizontal_fences[r1][c1];
  if (c2 == c1 + 1) return !fy.vertical_fences[r1][c1 + 1];
  // c2 == c1 - 1
  return !fy.vertical_fences[r1][c1];
}

}  // namespace

std::vector<Pasture> compute_pastures(const Farmyard& fy) {
  std::set<Coord> outside;
  std::deque<Coord> queue;

  auto try_enter = [&](int r, int c) {
    Coord cell{r, c};
    if (outside.find(cell) == outside.end()) {
      outside.insert(cell);
      queue.push_back(cell);
    }
  };

  // Seed: border cells whose outer edge is open.
  for (int c = 0; c < kCols; ++c) {
    if (!fy.horizontal_fences[0][c]) try_enter(0, c);        // top edge open
    if (!fy.horizontal_fences[kRows][c]) try_enter(kRows - 1, c);  // bottom open
  }
  for (int r = 0; r < kRows; ++r) {
    if (!fy.vertical_fences[r][0]) try_enter(r, 0);          // left edge open
    if (!fy.vertical_fences[r][kCols]) try_enter(r, kCols - 1);  // right open
  }

  static const std::array<Coord, 4> kNbrs{{{-1, 0}, {1, 0}, {0, -1}, {0, 1}}};

  while (!queue.empty()) {
    auto [r, c] = queue.front();
    queue.pop_front();
    for (const auto& [dr, dc] : kNbrs) {
      int nr = r + dr, nc = c + dc;
      if (nr >= 0 && nr < kRows && nc >= 0 && nc < kCols &&
          outside.find({nr, nc}) == outside.end() &&
          are_connected(fy, r, c, nr, nc)) {
        try_enter(nr, nc);
      }
    }
  }

  std::set<Coord> enclosed;
  for (int r = 0; r < kRows; ++r)
    for (int c = 0; c < kCols; ++c)
      if (outside.find({r, c}) == outside.end()) enclosed.insert({r, c});

  // Connected components among enclosed cells.
  std::set<Coord> visited;
  std::vector<Pasture> pastures;
  for (const Coord& start : enclosed) {
    if (visited.find(start) != visited.end()) continue;
    std::vector<Coord> component;
    std::deque<Coord> q{start};
    visited.insert(start);
    component.push_back(start);
    while (!q.empty()) {
      auto [r, c] = q.front();
      q.pop_front();
      for (const auto& [dr, dc] : kNbrs) {
        int nr = r + dr, nc = c + dc;
        Coord nb{nr, nc};
        if (enclosed.find(nb) != enclosed.end() &&
            visited.find(nb) == visited.end() &&
            are_connected(fy, r, c, nr, nc)) {
          visited.insert(nb);
          component.push_back(nb);
          q.push_back(nb);
        }
      }
    }
    std::sort(component.begin(), component.end());  // canonical cell order
    int num_stables = 0;
    for (const auto& [r, c] : component)
      if (fy.grid[r][c].cell_type == CellType::STABLE) ++num_stables;
    int capacity = 2 * static_cast<int>(component.size()) * (1 << num_stables);
    pastures.push_back(Pasture{std::move(component), num_stables, capacity});
  }

  // Canonical ordering: sort by min(cells) lexicographically. cells are sorted,
  // so cells.front() is the min.
  std::sort(pastures.begin(), pastures.end(),
            [](const Pasture& a, const Pasture& b) {
              return a.cells.front() < b.cells.front();
            });
  return pastures;
}

}  // namespace agricola
