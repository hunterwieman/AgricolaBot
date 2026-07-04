"""Stable Manure (minor improvement, D72; Dulcinaria Expansion; Crop Provider).

Card text (verbatim): "In the field phase of each harvest, you can harvest 1
additional good from a number of fields equal to the number of unfenced stables
you have."

No cost (free), no printed VPs, not a passing card. Prerequisite: "At Most 1
Occupation" — modeled as `max_occupations=1` on the minor spec (a HAVE-check at
play time, never spent).

**Timing home (HARVEST_WINDOWS_DESIGN.md §4a, user ruling 2026-07-03).** This is
a during-window ("field_phase", harvest window #5) **class-(a) free-ordered
independent trigger**: an additional-harvest effect that is legal at any point in
the field-phase window — BEFORE or AFTER the mandatory crop take (`CommitFieldTake`),
in the player-chosen order. (Its previous home fired it strictly before the take;
the free order is the intended new semantics.) "You can" is a real decision —
WHICH fields take the extra harvest (and whether to take fewer than the maximum)
shapes future harvests, since a benefited field is depleted this harvest by the
extra plus, if the field is still planted at take time, the mechanical take. So it
is an OPTIONAL play-variant TRIGGER (`register("field_phase", …)` +
`register_play_variant_trigger`) surfaced at the per-player `PendingFieldPhase`
host; declining = the host's take-then-Proceed. Once fired, the frame's
`triggers_resolved` gives once-per-field-phase.

**Its extra goods are their OWN harvesting occasion (user ruling 5, 2026-07-03).**
The card-granted harvest is a separate occasion from the take: after moving the
goods, `_apply` builds a `HarvestOccasion(source="card:stable_manure", …)` naming
the benefited field cells and calls `resolution.emit_harvest_occasion`, which
records it on the host frame's manifest and fires the per-occasion autos — so
consequence cards see this card's harvest as its own event, distinct from the
take.

THE OPTION SET (user-ruled shortcut): fields are interchangeable within a group
keyed by (crop kind, crops remaining) — taking the extra from one 3-grain field
is identical to taking it from another — so instead of enumerating field
subsets, each variant is a COUNT VECTOR over groups: take `k_g` extra goods from
group `g`, with `0 <= k_g <= |g|` and `1 <= sum(k_g) <= N`, where N is the
number of unfenced stables. Only fields with >= 2 of their crop form groups: a
1-crop field's sole good goes to the normal take either way, so including it
changes nothing (loss-less restriction). The empty vector is not enumerated —
declining lives at the host (take + Proceed), per the no-dead-option convention.

Variant encoding: `"grain2:1|veg3:2"` = 1 extra from a (grain, 2-remaining)
field and 2 extra from (veg, 3-remaining) fields, groups sorted by key. The
apply parses the vector and takes the first `k_g` matching fields in scan
order (within a group any field is equivalent, so scan order is canonical).

`_variants` reads the LIVE grid at enumeration time — the current grid, which
after the take differs from before it. Firing AFTER the take means a field the
take emptied can no longer spare a crop and so is no longer a legal variant
(correct free-order behavior); firing BEFORE the take sees the full pre-take
grid. This is also what lets the card compose with any pre-take effect (e.g.
Scythe Worker depleting a field first).
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_minor
from agricola.cards.stable_architect import count_unfenced_stables
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.constants import CellType
from agricola.pending import HarvestEntry, HarvestOccasion
from agricola.replace import fast_replace
from agricola.resolution import emit_harvest_occasion
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
    1 <= total <= the unfenced-stable cap. Computed from the CURRENT grid, so
    the offered options differ before vs. after the take (fields the take
    emptied drop out of the donor groups — correct free-order behavior)."""
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
    """Take the chosen extras as this card's own harvesting occasion: for each
    `key:count` part, decrement `count` fields of that (crop, remaining) group in
    scan order and credit the supply, then emit a
    `HarvestOccasion(source="card:stable_manure", …)` naming the benefited cells
    (per-cell `HarvestEntry`, `emptied` true when the extra took the field's last
    crop) via `resolution.emit_harvest_occasion` — which records it on the host
    frame's manifest and fires the per-occasion autos (design doc §4a/§4d,
    ruling 5, 2026-07-03). A separate occasion from the mechanical take."""
    want = {}
    for part in variant.split("|"):
        key, _, count = part.partition(":")
        want[key] = int(count)
    p = state.players[idx]
    new_grid = []
    taken = Resources()
    entries: list[HarvestEntry] = []
    for r, row in enumerate(p.farmyard.grid):
        new_row = []
        for c, cell in enumerate(row):
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
                    entries.append(HarvestEntry(
                        source=f"cell:{r},{c}", crop="grain", amount=1,
                        emptied=(cell.grain - 1 == 0)))
                else:
                    new_row.append(fast_replace(cell, veg=cell.veg - 1))
                    taken = taken + Resources(veg=1)
                    entries.append(HarvestEntry(
                        source=f"cell:{r},{c}", crop="veg", amount=1,
                        emptied=(cell.veg - 1 == 0)))
            else:
                new_row.append(cell)
        new_grid.append(tuple(new_row))
    assert not any(want.values()), (
        f"stable_manure variant {variant!r} names more fields than exist: {want}")
    # Fields never lie inside pastures, so the pasture cache rides along on the
    # grid fast_replace (mirrors field_take's mechanical take).
    new_fy = fast_replace(p.farmyard, grid=tuple(new_grid))
    p = fast_replace(p, farmyard=new_fy, resources=p.resources + taken)
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    # The extras are their own harvesting occasion (ruling 5): record it on the
    # host frame's manifest and fire the per-occasion autos.
    occasion = HarvestOccasion(source=f"card:{CARD_ID}", entries=tuple(entries))
    return emit_harvest_occasion(state, idx, occasion)


# Free minor; prereq "At Most 1 Occupation" → max_occupations=1.
register_minor(CARD_ID, max_occupations=1)
register("field_phase", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
register_harvest_window_hook(CARD_ID, "field_phase")
