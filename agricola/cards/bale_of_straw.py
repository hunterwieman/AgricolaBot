"""Bale of Straw (minor improvement, D61; Dulcinaria Expansion; players -).

Card text: "At the start of each harvest, if you have at least 3 grain fields
(including field cards with planted grain), you get 2 food."

Cost: none (free). Printed VPs: 0. No prerequisite, kept (not passing).
Category: Food Provider.

Category 6 (harvest-field hook). A MANDATORY, choice-free income at the start of
each harvest → an automatic effect (`register_auto` on the `harvest_field`
event), which `_resolve_harvest_field` fires (via `_fire_harvest_field_hook`)
BEFORE the mechanical crop take. So `_eligible`/`_apply` read the STILL-SOWN
grid — exactly when "you have at least 3 grain fields" should be evaluated, since
the field phase has not yet removed any grain.

"Grain fields" = your own FIELD cells that currently have grain planted on them
(`cell.grain > 0`). The parenthetical "(including field cards with planted
grain)" refers to expansion field-card mechanics not modeled in this engine, so
it adds nothing here. The threshold is at least 3 such fields; the reward is a
flat 2 food (not per-field). See CARD_IMPLEMENTATION_PLAN.md Category 6.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto, register_harvest_field_hook
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "bale_of_straw"

_THRESHOLD = 3
_FOOD = 2


def _grain_fields(state: GameState, idx: int) -> int:
    """Count the player's FIELD cells that currently have grain planted."""
    return sum(
        1
        for row in state.players[idx].farmyard.grid
        for cell in row
        if cell.cell_type == CellType.FIELD and cell.grain > 0
    )


def _eligible(state: GameState, idx: int) -> bool:
    return _grain_fields(state, idx) >= _THRESHOLD


def _apply(state: GameState, idx: int) -> GameState:
    """+2 food at the start of the harvest when the grain-field threshold is met.

    Reads the still-sown grid (the hook fires before the mechanical take) and
    only credits food — it never touches the grid, so it does NOT alter the
    crops the mechanical take then harvests."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=_FOOD))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID)
register_auto("harvest_field", CARD_ID, _eligible, _apply)
register_harvest_field_hook(CARD_ID)
