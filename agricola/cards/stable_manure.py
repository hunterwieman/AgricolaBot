"""Stable Manure (minor improvement, D72; Dulcinaria Expansion; Crop Provider).

Card text (verbatim): "In the field phase of each harvest, you can harvest 1
additional good from a number of fields equal to the number of unfenced stables
you have."

No cost (free), no printed VPs, not a passing card. Prerequisite: "At Most 1
Occupation" — modeled as `max_occupations=1` on the minor spec (a HAVE-check at
play time, never spent).

Category 6 (harvest-field hook), the field phase's first surfaced CHOICE (user
ruling 2026-07): "you can" is a real decision — WHICH fields take the extra
harvest (and whether to take fewer than the maximum) shapes future harvests,
since a benefited field is depleted by 2 this harvest (1 here + 1 in the
mechanical take). So the card is an OPTIONAL play-variant TRIGGER on the
`harvest_field` event, surfaced at the per-player `PendingHarvestField` choice
host that `_resolve_harvest_field` pushes before the mechanical crop take
(declining = the host's Proceed).

THE OPTION SET (user-ruled shortcut): fields are interchangeable within a group
keyed by (crop kind, crops remaining) — taking the extra from one 3-grain field
is identical to taking it from another — so instead of enumerating field
subsets, each variant is a COUNT VECTOR over groups: take `k_g` extra goods from
group `g`, with `0 <= k_g <= |g|` and `1 <= sum(k_g) <= N`, where N is the
number of unfenced stables. Only fields with >= 2 of their crop form groups: a
1-crop field's sole good goes to the normal take either way, so including it
changes nothing (loss-less restriction). The empty vector is not enumerated —
declining lives at the host's Proceed, per the no-dead-option convention.

Variant encoding: `"grain2:1|veg3:2"` = 1 extra from a (grain, 2-remaining)
field and 2 extra from (veg, 3-remaining) fields, groups sorted by key. The
apply parses the vector and takes the first `k_g` matching fields in scan
order (within a group any field is equivalent, so scan order is canonical).

`_variants` reads the LIVE grid at enumeration (after the `harvest_field` autos
fired at the transient host), so it composes with e.g. Scythe Worker depleting
a field first. Once fired, the host's `triggers_resolved` gives once-per-harvest.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.stable_architect import count_unfenced_stables
from agricola.cards.triggers import (
    register,
    register_harvest_field_hook,
    register_play_variant_trigger,
)
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "stable_manure"


def _cap(state: GameState, idx: int) -> int:
    """N = the number of unfenced stables — the maximum number of additional
    goods this card may harvest this field phase."""
    return count_unfenced_stables(state.players[idx].farmyard)


def _groups(state: GameState, idx: int) -> dict[str, int]:
    """The donor-field groups: {(crop kind + remaining) key: field count}, for
    fields holding >= 2 of their crop (a 1-crop field can spare nothing)."""
    out: dict[str, int] = {}
    for row in state.players[idx].farmyard.grid:
        for cell in row:
            if cell.cell_type != CellType.FIELD:
                continue
            if cell.grain >= 2:
                key = f"grain{cell.grain}"
            elif cell.veg >= 2:
                key = f"veg{cell.veg}"
            else:
                continue
            out[key] = out.get(key, 0) + 1
    return out


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Eligible iff there is at least one unfenced stable (a non-zero cap) AND at
    least one field that can spare an additional good (>= 2 of a single crop)."""
    return _cap(state, idx) > 0 and bool(_groups(state, idx))


def _variants(state: GameState, idx: int) -> list[str]:
    """Every legal count vector over the donor groups, encoded
    `"key:count|key:count"` (sorted keys, zero counts omitted), with
    1 <= total <= the unfenced-stable cap."""
    cap = _cap(state, idx)
    groups = sorted(_groups(state, idx).items())
    if cap <= 0 or not groups:
        return []
    vectors: list[list[int]] = [[]]
    for _key, size in groups:
        vectors = [v + [k] for v in vectors for k in range(min(size, cap) + 1)]
    out = []
    for v in vectors:
        if 1 <= sum(v) <= cap:
            out.append("|".join(f"{key}:{k}"
                                for (key, _size), k in zip(groups, v) if k))
    return out


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Take the chosen extras: for each `key:count` part, decrement `count`
    fields of that (crop, remaining) group in scan order and credit the supply.
    Fires before the mechanical take, which then removes the remaining 1 per
    sown field — so a benefited field is depleted by 2 total."""
    want = {}
    for part in variant.split("|"):
        key, _, count = part.partition(":")
        want[key] = int(count)
    p = state.players[idx]
    new_grid = []
    taken = Resources()
    for row in p.farmyard.grid:
        new_row = []
        for cell in row:
            key = None
            if cell.cell_type == CellType.FIELD:
                if cell.grain >= 2:
                    key = f"grain{cell.grain}"
                elif cell.veg >= 2:
                    key = f"veg{cell.veg}"
            if key is not None and want.get(key, 0) > 0:
                want[key] -= 1
                if cell.grain >= 2:
                    new_row.append(fast_replace(cell, grain=cell.grain - 1))
                    taken = taken + Resources(grain=1)
                else:
                    new_row.append(fast_replace(cell, veg=cell.veg - 1))
                    taken = taken + Resources(veg=1)
            else:
                new_row.append(cell)
        new_grid.append(tuple(new_row))
    assert not any(want.values()), (
        f"stable_manure variant {variant!r} names more fields than exist: {want}")
    # Fields never lie inside pastures, so the pasture cache rides along on the
    # grid fast_replace (mirrors _resolve_harvest_field's mechanical take).
    new_fy = fast_replace(p.farmyard, grid=tuple(new_grid))
    p = fast_replace(p, farmyard=new_fy, resources=p.resources + taken)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


# Free minor; prereq "At Most 1 Occupation" → max_occupations=1.
register_minor(CARD_ID, max_occupations=1)
register("harvest_field", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
register_harvest_field_hook(CARD_ID)
