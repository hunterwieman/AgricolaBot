"""Crack Weeder (minor improvement, B58; Bubulcus Expansion; players -).

Card text: "When you play this card, you immediately get 1 food. For each
vegetable you take from a field in the field phase of a harvest, you also get
1 food."

Category 2 on-play (+1 food) + Category 6 (harvest-field hook). Cost 1 wood; no
prerequisite, no printed VPs, kept (not passing).

The field-phase clause earns 1 food for each vegetable taken from a field this
harvest. The mechanical field-phase take in `_resolve_harvest_field` removes
exactly 1 crop per planted field, taking grain if present else (the `elif veg`
branch) one vegetable from a veg-sown field. So "each vegetable you take from a
field" is exactly one vegetable per field that is veg-sown (veg > 0) this
harvest — at most one per field regardless of how many vegetables the field
holds (a 2-veg field still yields only 1 vegetable per harvest, hence +1 food,
not +2).

Implemented as an automatic effect (`register_auto` on `harvest_field`) that
fires BEFORE the mechanical crop take (`_fire_harvest_field_hook` runs first in
`_resolve_harvest_field`), so it reads the still-sown grid. Unlike Scythe Worker
this card does NOT take any extra crop from the fields — it only adds food
alongside the normal mechanical take, so it never mutates the grid. Counting
veg-sown fields (veg > 0) exactly mirrors which fields the mechanical take's
`elif veg` branch will harvest a vegetable from, since a field is sown grain XOR
veg (so veg > 0 implies grain == 0).

See CARD_BATCH_TRIAGE.md (B58).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto, register_harvest_field_hook
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "crack_weeder"


def _on_play(state: GameState, idx: int) -> GameState:
    """Immediate +1 food when the card is played."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible(state: GameState, idx: int) -> bool:
    # Some veg-sown field will yield a vegetable to the mechanical take this
    # harvest (grain XOR veg at sow, so veg > 0 implies grain == 0 — exactly the
    # `elif veg` branch of _resolve_harvest_field).
    return any(
        cell.cell_type == CellType.FIELD and cell.veg > 0
        for row in state.players[idx].farmyard.grid
        for cell in row
    )


def _apply(state: GameState, idx: int) -> GameState:
    """+1 food per veg-sown field (one vegetable taken per field this harvest).

    Reads the still-sown grid (the hook fires before the mechanical take) and
    only credits food — it never touches the grid, so it does NOT deplete the
    fields the mechanical take then harvests."""
    p = state.players[idx]
    food = sum(
        1
        for row in p.farmyard.grid
        for cell in row
        if cell.cell_type == CellType.FIELD and cell.veg > 0
    )
    if food == 0:
        return state
    p = fast_replace(p, resources=p.resources + Resources(food=food))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), on_play=_on_play)
register_auto("harvest_field", CARD_ID, _eligible, _apply)
register_harvest_field_hook(CARD_ID)
