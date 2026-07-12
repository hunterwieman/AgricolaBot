"""Bale of Straw (minor improvement, D61; Dulcinaria Expansion; players -).

Card text: "At the start of each harvest, if you have at least 3 grain fields
(including field cards with planted grain), you get 2 food."

Cost: none (free). Printed VPs: 0. No prerequisite, kept (not passing).
Category: Food Provider.

Harvest-window auto. The printed timing is "At the start of each harvest", which
maps to harvest window #2, `start_of_harvest` (the window that opens the whole
harvest, before the field phase). A MANDATORY, choice-free income → an automatic
effect (`register_auto` on the `start_of_harvest` window event), fired by the
harvest walk (`_process_simple_window`) per owner, window-major, starting player
first. This window is BEFORE the field phase's crop take, so `_eligible`/`_apply`
read the STILL-SOWN grid — exactly when "you have at least 3 grain fields" should
be evaluated, since the field phase has not yet removed any grain. (This matched
the old pre-take `harvest_field`-event home too; the migration moves the read to
the earlier printed instant with no change in what it sees, since no grain is
taken before either position.)

"Grain fields" = your own FIELD cells that currently have grain planted on them
(`cell.grain > 0`) PLUS your card-fields currently holding grain
(`crop_card_field_count(p, "grain")`) — the parenthetical "(including field cards
with planted grain)" names exactly the card-field machinery
(agricola/cards/card_fields.py), now modeled, in the catalog's own words. Ruling
45 (2026-07-12), verbatim: '"field TILES" means the plowed fields on the farmyard
grid; "field" is the BROADER category and includes card-fields. So a card-field
counts for field-count readers — the Fields scoring category and any "you need N
fields" requirement — while per-TILE readers still exclude it (ruling 32
unchanged).' Per ruling 47 (2026-07-12) a multi-stack card-field counts exactly
once. The threshold is at least 3 such fields; the reward is a flat 2 food (not
per-field). See CARD_IMPLEMENTATION_PLAN.md Category 6.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "bale_of_straw"

_THRESHOLD = 3
_FOOD = 2


def _grain_fields(state: GameState, idx: int) -> int:
    """Count the player's grain fields: grid FIELD cells with grain planted,
    plus grain-holding card-fields — the printed "(including field cards with
    planted grain)" (ruling 45, 2026-07-12: "field" includes card-fields;
    ruling 47: each card counts exactly once)."""
    from agricola.cards.card_fields import crop_card_field_count  # local: load-order safe
    p = state.players[idx]
    return sum(
        1
        for row in p.farmyard.grid
        for cell in row
        if cell.cell_type == CellType.FIELD and cell.grain > 0
    ) + crop_card_field_count(p, "grain")


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
register_auto("start_of_harvest", CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, "start_of_harvest")
