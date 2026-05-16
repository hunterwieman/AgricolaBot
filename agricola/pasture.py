"""Pasture dataclass and the BFS that derives pastures from a farmyard's
fences and grid.

This module is intentionally kept independent of `agricola.state` so that
`Farmyard` (in state.py) can call `compute_pastures_from_arrays` from its
`__post_init__` without creating a circular import. The BFS reads
`grid[r][c].cell_type` via duck typing — it does not import `Cell`.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from agricola.constants import CellType


# ---------------------------------------------------------------------------
# Pasture dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Pasture:
    cells: frozenset        # frozenset of (row, col) tuples
    num_stables: int        # stables inside this pasture
    capacity: int           # 2 * num_cells * (2 ** num_stables)


# ---------------------------------------------------------------------------
# BFS flood-fill
# ---------------------------------------------------------------------------

def _are_connected(
    horizontal_fences: tuple,
    vertical_fences: tuple,
    r1: int,
    c1: int,
    r2: int,
    c2: int,
) -> bool:
    """Return True if two orthogonally adjacent cells have no fence between them."""
    if r2 == r1 + 1:
        # (r1,c1) above (r2,c2): separated by horizontal_fences[r1+1][c1]
        return not horizontal_fences[r1 + 1][c1]
    if r2 == r1 - 1:
        return not horizontal_fences[r1][c1]
    if c2 == c1 + 1:
        # (r1,c1) left of (r2,c2): separated by vertical_fences[r1][c1+1]
        return not vertical_fences[r1][c1 + 1]
    if c2 == c1 - 1:
        return not vertical_fences[r1][c1]
    raise ValueError("Cells are not orthogonally adjacent")


def compute_pastures_from_arrays(
    grid: tuple,
    horizontal_fences: tuple,
    vertical_fences: tuple,
) -> tuple[Pasture, ...]:
    """Derive all enclosed pastures from raw grid + fence arrays.

    Algorithm:
    1. Flood-fill from 'outside' to find all cells reachable without crossing a fence.
    2. Cells NOT reachable from outside are enclosed.
    3. Among enclosed cells, find connected components — each is one pasture.

    Returns a tuple of Pasture objects sorted by min(p.cells) lexicographically,
    so equivalent farmyards always produce equal `pastures` tuples (required for
    `Farmyard.__eq__` and hashing).
    """
    # Step 1 & 2: Determine enclosed cells via outside flood fill.
    outside: set = set()
    queue: deque = deque()

    def try_enter(r: int, c: int) -> None:
        if (r, c) not in outside:
            outside.add((r, c))
            queue.append((r, c))

    # Seed: border cells connected to outside
    for c in range(5):
        if not horizontal_fences[0][c]:   # top edge open
            try_enter(0, c)
        if not horizontal_fences[3][c]:   # bottom edge open
            try_enter(2, c)
    for r in range(3):
        if not vertical_fences[r][0]:     # left edge open
            try_enter(r, 0)
        if not vertical_fences[r][5]:     # right edge open
            try_enter(r, 4)

    # BFS through interior using cell-to-cell adjacency
    while queue:
        r, c = queue.popleft()
        for nr, nc in [(r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)]:
            if 0 <= nr < 3 and 0 <= nc < 5 and (nr, nc) not in outside:
                if _are_connected(horizontal_fences, vertical_fences, r, c, nr, nc):
                    try_enter(nr, nc)

    enclosed = {
        (r, c)
        for r in range(3)
        for c in range(5)
        if (r, c) not in outside
    }

    # Step 3: Find connected components among enclosed cells.
    visited: set = set()
    pastures: list[Pasture] = []

    for start in enclosed:
        if start in visited:
            continue
        component: set = set()
        q: deque = deque([start])
        component.add(start)
        visited.add(start)
        while q:
            r, c = q.popleft()
            for nr, nc in [(r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)]:
                if (nr, nc) in enclosed and (nr, nc) not in visited:
                    if _are_connected(horizontal_fences, vertical_fences, r, c, nr, nc):
                        visited.add((nr, nc))
                        component.add((nr, nc))
                        q.append((nr, nc))

        # Step 4: Compute pasture data
        num_stables = sum(
            1 for (r, c) in component
            if grid[r][c].cell_type == CellType.STABLE
        )
        capacity = 2 * len(component) * (2 ** num_stables)
        pastures.append(Pasture(
            cells=frozenset(component),
            num_stables=num_stables,
            capacity=capacity,
        ))

    # Canonical ordering: sort by min(cells) lexicographically.
    pastures.sort(key=lambda p: min(p.cells))
    return tuple(pastures)
