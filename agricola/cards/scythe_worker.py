"""Scythe Worker (occupation, A112; Base Revised; players 1+).

Card text: "When you play this card, you immediately get 1 grain. In the field
phase of each harvest, you can harvest 1 additional grain from each of your grain
fields."

Category 2 on-play (+1 grain) + a field-phase take-MODIFIER. The field-phase
clause harvests one ADDITIONAL grain from each grain field — taken FROM the field,
at the same time as the mechanical take (user ruling 11, 2026-07-05: all
field-phase harvesting is ONE simultaneous event; there is no separate
during-phase harvesting occasion). Implemented as an AUTO take fold-in
(`register_take_modifier`, no variants): `_fold` contributes +1 extra unit per
grain field with >= 2 grain to `resolution.field_take`'s per-cell extras, so the
field is depleted by 2 in the one event (1 base + 1 extra) and the take
occasion's manifest entry carries `amount=2` — occasion consumers see the extra
as part of the take (Grain Sieve counts it toward "at least 2 grain", per the
ruling). A 1-grain field gives its single grain to the base take with none to
spare. Being printed "of each harvest", the fold-in applies only to a real
harvest's take (ruling 12) — a card-played field phase (Bumper Crop) runs bare.

DELIBERATELY DEFERRED — the choice. The card reads "you CAN harvest 1 additional
grain from each of your grain fields": it is OPTIONAL because taking the extra
grain depletes the field (trading future-harvest yield for grain now). With the
*current* card set, taking it on every eligible field is strictly optimal, so we
model it as mandatory-take-the-maximum and skip the choice machinery (YAGNI).
When a later card makes partial use meaningful, surface the choice by making
this a CHOICE-BEARING take-modifier — supply a `variants_fn` enumerating the
per-field-count options and move the fold into the variant-keyed `fold_fn`,
exactly the Stable Manure shape (`CommitFieldTake(modifiers=...)` variants at
the PendingFieldPhase host). Do NOT invent harvest-flow structure — the earlier
planned "wide trigger on the PendingHarvestField host" upgrade path is obsolete
(that host and the separate-occasion model were superseded by the harvest-window
machinery + ruling 11).
"""
from __future__ import annotations

from agricola.cards.harvest_windows import (
    register_harvest_window_hook,
    register_take_modifier,
)
from agricola.cards.specs import register_occupation
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


def _fold(state: GameState, idx: int, variant) -> dict:
    """+1 extra grain from each grain field that can spare one beyond the base
    take (>= 2 grain) — the documented mandatory-max simplification of the
    card's "you can"."""
    assert variant is None   # auto fold-in: no variants
    return {
        (r, c): 1
        for r, row in enumerate(state.players[idx].farmyard.grid)
        for c, cell in enumerate(row)
        if cell.cell_type == CellType.FIELD and cell.grain >= 2
    }


register_occupation(CARD_ID, _on_play)
register_take_modifier(CARD_ID, _fold)
register_harvest_window_hook(CARD_ID, "field_phase")
