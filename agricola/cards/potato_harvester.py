"""Potato Harvester (occupation, C106; Consul Dirigens Expansion; players 1+).

Card text: "When you play this card, you immediately get 3 food. For each
vegetable you get from your fields during the field phase of the harvest, you get
1 additional food."

Category 2 on-play (+3 food) + Category 6 (harvest-field hook). The harvest clause
only COUNTS the mechanical veg take rather than modifying the fields — it awards 1
food per vegetable harvested from the player's fields during the field phase.

The mechanical take (`_resolve_harvest_field`) removes exactly 1 crop from each
planted field, with grain taking precedence over veg: `if cell.grain > 0` takes a
grain, `elif cell.veg > 0` takes a veg. So a field yields a vegetable this harvest
exactly when it has no grain and has veg (`grain == 0 and veg > 0`), and yields at
most 1 veg per field (one crop per field per harvest). "For each vegetable you get
from your fields" therefore equals the count of such veg-bearing fields, and the
food bonus is that count.

Implemented as an automatic effect (register_auto on `harvest_field`), fired by
`_resolve_harvest_field` BEFORE the mechanical crop take. Firing first is required
for cards that DEPLETE fields (e.g. Scythe Worker); for Potato Harvester it is
immaterial because `_apply` only READS the fields (it counts veg-fields and credits
food, never mutating the grid), so the count is identical pre- and post-take. The
firing happens while the fields are still fully sown, which is the natural place to
count them.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto, register_harvest_field_hook
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "potato_harvester"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=3))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _veg_fields(state: GameState, idx: int) -> int:
    """Number of fields that will yield a vegetable in this harvest's mechanical
    take: a field with no grain (grain takes precedence in the take) and veg > 0.
    Each such field yields exactly 1 veg, so this count equals the vegetables the
    player gets from their fields — and hence the additional food awarded."""
    return sum(
        1
        for row in state.players[idx].farmyard.grid
        for cell in row
        if cell.cell_type == CellType.FIELD and cell.grain == 0 and cell.veg > 0
    )


def _eligible(state: GameState, idx: int) -> bool:
    return _veg_fields(state, idx) > 0


def _apply(state: GameState, idx: int) -> GameState:
    """Award 1 food per vegetable the mechanical take will harvest from the player's
    fields this harvest. Reads the grid only — no field mutation; the normal take
    removes the veg afterward."""
    food = _veg_fields(state, idx)
    if food == 0:
        return state
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=food))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, _on_play)
register_auto("harvest_field", CARD_ID, _eligible, _apply)
register_harvest_field_hook(CARD_ID)
