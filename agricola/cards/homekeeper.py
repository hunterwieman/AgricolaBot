"""Homekeeper (occupation, A85; Artifex; players 1+).

Card text (verbatim): "Exactly one clay or stone room in your house can hold an
additional person if the room is adjacent to both a field and a pasture."
Clarifications: "Field cards may not count as adjacent.  If the room later loses
adjacency to the field and/or pasture, the capacity for an additional person is
lost (e.g. after playing Overhaul C001)."

A passive PEOPLE-capacity bonus of +1 (registered via the housing-capacity registry,
capacity_mods): when the player lives in a clay or stone house (all rooms share one
material) AND at least one ROOM cell is orthogonally adjacent to BOTH a FIELD cell
AND a cell belonging to some pasture, the house holds one more person than its room
count. "Exactly one" room qualifies, so the bonus is capped at +1 no matter how many
rooms satisfy the adjacency.

The bonus is a pure function of current state (house material + farmyard geometry),
so it is recomputed each time the family-growth gate is read — which is exactly the
memoryless "lose adjacency, lose the capacity" behaviour the clarification describes.
Only farmyard FIELD tiles count as adjacent (the grid's own cells); a field granted
by a card is not a farmyard cell, so it cannot count (per the clarification). No
on-play effect.
"""
from __future__ import annotations

from agricola.cards.capacity_mods import register_housing_capacity
from agricola.cards.specs import register_occupation
from agricola.constants import CellType, HouseMaterial
from agricola.state import GameState

CARD_ID = "homekeeper"

_NEIGHBORS = [(-1, 0), (1, 0), (0, -1), (0, 1)]


def _capacity_bonus(state: GameState, idx: int) -> int:
    p = state.players[idx]
    if p.house_material not in (HouseMaterial.CLAY, HouseMaterial.STONE):
        return 0
    grid = p.farmyard.grid
    pasture_cells: set = set()
    for past in p.farmyard.pastures:
        pasture_cells |= past.cells
    if not pasture_cells:
        return 0
    for r in range(3):
        for c in range(5):
            if grid[r][c].cell_type != CellType.ROOM:
                continue
            neigh = [(r + dr, c + dc) for dr, dc in _NEIGHBORS]
            adj_field = any(
                0 <= nr < 3 and 0 <= nc < 5
                and grid[nr][nc].cell_type == CellType.FIELD
                for nr, nc in neigh
            )
            adj_pasture = any((nr, nc) in pasture_cells for nr, nc in neigh)
            if adj_field and adj_pasture:
                return 1          # "Exactly one" room — the bonus is capped at +1
    return 0


def _on_play(state: GameState, idx: int) -> GameState:
    """No on-play effect — the capacity is the passive registered modifier."""
    return state


register_occupation(CARD_ID, _on_play)
register_housing_capacity(CARD_ID, _capacity_bonus)
