"""Scythe Worker (occupation, A112; Base Revised; players 1+).

Card text: "When you play this card, you immediately get 1 grain. In the field
phase of each harvest, you can harvest 1 additional grain from each of your grain
fields."

Category 2 on-play (+1 grain) + Category 6 (harvest-field hook). The field-phase
clause is a MANDATORY, choice-free income — 1 extra grain per grain field — so it
is an automatic effect (register_auto on the `harvest_field` event), fired by
`_resolve_harvest_field` BEFORE the mechanical crop take. Firing before the take
matters: the eligibility/amount reads the grain fields while they are still sown
(a field with grain > 0 is a grain field). The card's "you can" is the standard
beneficial wording — never a reason to forgo free grain — so it is automatic, not
an optional FireTrigger. See CARD_IMPLEMENTATION_PLAN.md Category 6.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto, register_harvest_field_hook
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "scythe_worker"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(grain=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _grain_fields(state: GameState, idx: int) -> int:
    return sum(
        1
        for row in state.players[idx].farmyard.grid
        for cell in row
        if cell.cell_type == CellType.FIELD and cell.grain > 0
    )


def _eligible(state: GameState, idx: int) -> bool:
    return _grain_fields(state, idx) > 0


def _apply(state: GameState, idx: int) -> GameState:
    extra = _grain_fields(state, idx)   # +1 grain per grain field
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(grain=extra))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, _on_play)
register_auto("harvest_field", CARD_ID, _eligible, _apply)
register_harvest_field_hook(CARD_ID)
