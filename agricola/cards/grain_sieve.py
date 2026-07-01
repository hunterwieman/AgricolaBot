"""Grain Sieve (minor improvement, D65; Dulcinaria Expansion; players -).

Card text: "In the field phase of each harvest, if you harvest at least 2 grain,
you get 1 additional grain from the general supply."

Cost: 1 wood. On-play is a no-op.

Category 6 (harvest-field hook). The effect fires in the field phase of every
harvest, gated on harvesting "at least 2 grain". A pure goods grant with no
downside, so it is modeled as a mandatory/choice-free automatic effect
(`register_auto` on `harvest_field`) — no optional FireTrigger.

Counting "at least 2 grain" — the ordering subtlety. The `harvest_field` hook
fires in `_resolve_harvest_field` BEFORE the mechanical crop take, while the grid
is still fully sown. The mechanical take then removes EXACTLY ONE grain from each
grain-bearing field this harvest (precedence: grain over veg). So the amount of
grain you harvest this field phase equals the NUMBER of FIELD cells holding grain,
NOT the total grain sitting on those fields: a single field sown to 3 grain
harvests only 1 grain this phase (it stays at 2). The eligibility test is
therefore "at least 2 FIELD cells with grain > 0", and we must NOT sum `cell.grain`
(see `agricola/cards/scythe_worker.py` for the same firing-order constraint, and
the spec's ordering note).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto, register_harvest_field_hook
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "grain_sieve"


def _grain_field_count(state: GameState, idx: int) -> int:
    """Number of FIELD cells holding grain. Each such field gives exactly 1 grain
    to the upcoming mechanical take, so this equals the grain this player harvests
    in the field phase (the hook fires before the take, grid still fully sown)."""
    return sum(
        1
        for row in state.players[idx].farmyard.grid
        for cell in row
        if cell.cell_type == CellType.FIELD and cell.grain > 0
    )


def _eligible(state: GameState, idx: int) -> bool:
    return _grain_field_count(state, idx) >= 2


def _apply(state: GameState, idx: int) -> GameState:
    """Grant 1 additional grain from the general supply."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(grain=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(Resources(wood=1)))  # no on-play effect
register_auto("harvest_field", CARD_ID, _eligible, _apply)
register_harvest_field_hook(CARD_ID)
