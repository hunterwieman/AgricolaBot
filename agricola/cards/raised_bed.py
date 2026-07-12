"""Raised Bed (minor improvement, E61; Ephipparius Expansion; players -).

Card text: "At the start of each harvest, you get 4 food."

Cost: 2 Clay, 2 Stone. Printed VPs: 1. Prerequisite: "2 Grain Fields". Kept (not
passing). Category: Food Provider.

Harvest-window auto. The printed timing "At the start of each harvest" maps to
harvest window #2, `start_of_harvest` (the window that opens the whole harvest,
before the field phase). The income is UNCONDITIONAL and choice-free ("you get",
not "you can" / not "if …") -> an automatic effect (`register_auto` on the
`start_of_harvest` window event), fired by the harvest walk
(`_process_simple_window`) per owner, window-major, starting player first. No
eligibility condition, so `_eligible` is always True; the auto simply credits a
flat 4 food and never touches the grid, so the field-phase take is unaffected.

Prerequisite "2 Grain Fields" is a HAVE-check at PLAY time: at least two grain
fields, counting the player's own grain-holding FIELD cells (`cell.grain > 0`)
— the same definition Sleeping Corner / Bale of Straw / Gardener's Knife use
for a "grain field" — PLUS the player's grain-holding card-fields (ruling 45,
2026-07-12; verbatim quote in `_prereq`). A prerequisite is checked, never
spent (distinct from the cost).
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "raised_bed"

_FOOD = 4


def _prereq(state: GameState, idx: int) -> bool:
    """2 Grain Fields — at least two grain fields: FIELD cells that currently
    hold grain plus grain-holding card-fields. Ruling 45 (2026-07-12),
    verbatim: ""field TILES" means the plowed fields on the farmyard grid;
    "field" is the BROADER category and includes card-fields. So a card-field
    counts for field-count readers — the Fields scoring category and any "you
    need N fields" requirement — while per-TILE readers still exclude it
    (ruling 32 unchanged)." Each grain-holding card counts exactly once
    (ruling 47, 2026-07-12); a veg- or wood-holding card-field is not a grain
    field."""
    from agricola.cards.card_fields import crop_card_field_count
    p = state.players[idx]
    grid = p.farmyard.grid
    grain_fields = sum(
        1
        for row in grid
        for cell in row
        if cell.cell_type == CellType.FIELD and cell.grain > 0
    ) + crop_card_field_count(p, "grain")
    return grain_fields >= 2


def _eligible(state: GameState, idx: int) -> bool:
    # Unconditional income — the card names no condition.
    return True


def _apply(state: GameState, idx: int) -> GameState:
    """+4 food at the start of the harvest (unconditional). Credits food only;
    never touches the grid, so the mechanical field-phase take is unaffected."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=_FOOD))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(clay=2, stone=2)),
    prereq=_prereq,
    vps=1,
)
register_auto("start_of_harvest", CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, "start_of_harvest")
