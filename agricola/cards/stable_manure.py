"""Stable Manure (minor improvement, D72; Dulcinaria Expansion; Crop Provider).

Card text (verbatim): "In the field phase of each harvest, you can harvest 1
additional good from a number of fields equal to the number of unfenced stables
you have."

No cost (free), no printed VPs, not a passing card. Prerequisite: "At Most 1
Occupation" — modeled as `max_occupations=1` on the minor spec (a HAVE-check at
play time, never spent).

Category 6 (harvest-field hook). The field-phase clause harvests one ADDITIONAL
good (grain OR vegetable, whichever the field holds) taken FROM the field — so a
benefited field is depleted by 2 this harvest (1 here + 1 in the mechanical take),
not 1 — but it is CAPPED: the bonus applies to at most N fields, where N is the
number of unfenced stables in the farmyard. Implemented as an automatic effect
(`register_auto` on the `harvest_field` event), fired by `_resolve_harvest_field`
BEFORE the mechanical crop take so the additional goods are removed while the
fields are still fully sown.

Only a field with >= 2 of its crop can spare an additional good: a field holding a
single good gives that good to the normal take with none to spare. The cap counts
goods TAKEN, not fields scanned, and stops once N have been taken. Field selection
among eligible fields is value-neutral at fire time (every eligible field yields
exactly +1 of its own crop), so a deterministic first-N-eligible scan order is
correct — no grain-vs-veg priority is meaningful.

DELIBERATELY DEFERRED — the choice. The card reads "you CAN harvest" and is
OPTIONAL (taking the extra depletes the field, trading future yield for goods now).
With the current card set taking the maximum is strictly optimal, so it is modeled
as mandatory-take-the-maximum (the same convention as Scythe Worker), skipping the
choice machinery (YAGNI). When a later card makes partial use meaningful, surface
the choice via the planned `PendingHarvestField` host — do NOT invent harvest-flow
structure here.

`_apply` reads the LIVE grid at fire time (no pre-snapshot), so it composes
correctly with any other `harvest_field` card that fired earlier and depleted a
field (e.g. Scythe Worker reducing a 2-grain field to 1 — that field can then no
longer spare an extra good for the cap).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.stable_architect import count_unfenced_stables
from agricola.cards.triggers import register_auto, register_harvest_field_hook
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "stable_manure"


def _cap(state: GameState, idx: int) -> int:
    """N = the number of unfenced stables — the maximum number of additional
    goods this card may harvest this field phase."""
    return count_unfenced_stables(state.players[idx].farmyard)


def _eligible(state: GameState, idx: int) -> bool:
    """Eligible iff there is at least one unfenced stable (a non-zero cap) AND at
    least one field that can spare an additional good (>= 2 of a single crop)."""
    if _cap(state, idx) <= 0:
        return False
    return any(
        cell.cell_type == CellType.FIELD and (cell.grain >= 2 or cell.veg >= 2)
        for row in state.players[idx].farmyard.grid
        for cell in row
    )


def _apply(state: GameState, idx: int) -> GameState:
    """Take 1 additional good FROM up to N eligible fields (N = unfenced stables):
    decrement the field's crop and credit supply, counting goods taken and stopping
    once N have been taken. Fires before the mechanical take, which then removes the
    remaining 1 per sown field — so a benefited field is depleted by 2 total."""
    p = state.players[idx]
    cap = count_unfenced_stables(p.farmyard)
    if cap <= 0:
        return state
    new_grid = []
    taken = Resources()
    n_taken = 0
    for row in p.farmyard.grid:
        new_row = []
        for cell in row:
            if n_taken < cap and cell.cell_type == CellType.FIELD and cell.grain >= 2:
                new_row.append(fast_replace(cell, grain=cell.grain - 1))
                taken = taken + Resources(grain=1)
                n_taken += 1
            elif n_taken < cap and cell.cell_type == CellType.FIELD and cell.veg >= 2:
                new_row.append(fast_replace(cell, veg=cell.veg - 1))
                taken = taken + Resources(veg=1)
                n_taken += 1
            else:
                new_row.append(cell)
        new_grid.append(tuple(new_row))
    if n_taken == 0:
        return state
    # Fields never lie inside pastures, so the pasture cache rides along on the
    # grid fast_replace (mirrors _resolve_harvest_field's mechanical take).
    new_fy = fast_replace(p.farmyard, grid=tuple(new_grid))
    p = fast_replace(p, farmyard=new_fy, resources=p.resources + taken)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


# Free minor; prereq "At Most 1 Occupation" → max_occupations=1.
register_minor(CARD_ID, max_occupations=1)
register_auto("harvest_field", CARD_ID, _eligible, _apply)
register_harvest_field_hook(CARD_ID)
