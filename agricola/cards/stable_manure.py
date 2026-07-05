"""Stable Manure (minor improvement, D72; Dulcinaria Expansion; Crop Provider).

Card text (verbatim): "In the field phase of each harvest, you can harvest 1
additional good from a number of fields equal to the number of unfenced stables
you have."

No cost (free), no printed VPs, not a passing card. Prerequisite: "At Most 1
Occupation" — modeled as `max_occupations=1` on the minor spec (a HAVE-check at
play time, never spent).

**Timing home — a take-MODIFIER folding into the one event (user ruling 11,
2026-07-05).** All field-phase harvesting is ONE simultaneous event: the extra
goods this card harvests are taken AT THE SAME TIME as the mechanical take,
never as a separate occasion (the earlier free-order/own-occasion model is
superseded; so is the ruling-9 contrast with Scythe Worker — Grain Sieve counts
this card's extra grain exactly as it counts Scythe Worker's). "You can" with a
real choice — WHICH fields take the extra — makes it a CHOICE-BEARING
take-modifier (`register_take_modifier` with a `variants_fn`): the choice
surfaces as variants of the take commit itself, `CommitFieldTake(modifiers=
(("stable_manure", <vector>),))`, at the per-player `PendingFieldPhase` host
(owning this card with a legal use is itself what hosts the frame). Declining =
committing the bare take. The chosen extras ride `field_take`'s per-cell
`extra_takes`: a benefited field is depleted by 2 in the one event (1 base + 1
extra, so only fields with >= 2 of their crop are donors — the extra must be
ADDITIONAL to the base take's), the manifest entry carries the combined amount,
and `emptied` reflects the net result. Being printed "of each harvest", the
modifier applies only to a real harvest's take (ruling 12) — a card-played
field phase (Bumper Crop) runs bare.

THE OPTION SET (user-ruled shortcut): fields are interchangeable within a group
keyed by (crop kind, crops remaining) — taking the extra from one 3-grain field
is identical to taking it from another — so instead of enumerating field
subsets, each variant is a COUNT VECTOR over groups: take `k_g` extra goods from
group `g`, with `0 <= k_g <= |g|` and `1 <= sum(k_g) <= N`, where N is the
number of unfenced stables. Only fields with >= 2 of their crop form groups: a
1-crop field's sole good goes to the base take either way, so including it
changes nothing (loss-less restriction). The empty vector is not enumerated —
declining is the bare `CommitFieldTake()`, per the no-dead-option convention.

Variant encoding: `"grain2:1|veg3:2"` = 1 extra from a (grain, 2-remaining)
field and 2 extra from (veg, 3-remaining) fields, groups sorted by key. The
fold parses the vector and picks the first `k_g` matching fields in scan
order (within a group any field is equivalent, so scan order is canonical).
Variants are enumerated at the host BEFORE the take fires (the take commit is
what consumes them), so the groups always read the fully-sown pre-take grid.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import (
    register_harvest_window_hook,
    register_take_modifier,
)
from agricola.cards.specs import register_minor
from agricola.cards.stable_architect import count_unfenced_stables
from agricola.constants import CellType
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


def _variants(state: GameState, idx: int) -> list[str]:
    """Every legal count vector over the donor groups, encoded
    `"key:count|key:count"` (sorted keys, zero counts omitted), with
    1 <= total <= the unfenced-stable cap. Empty when the cap is 0 or no
    field can spare an extra — then no CommitFieldTake variant carries this
    card and (absent another reason) the walk takes inline."""
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


def _fold(state: GameState, idx: int, variant: str, claimed) -> dict | None:
    """Map the chosen count vector to per-cell extra takes: for each
    `key:count` part, the first `count` fields of that (crop, remaining) group
    in scan order WITH REMAINING SPARE (count − 1 base − extras other
    modifiers already claimed >= 1) each contribute +1 extra unit to the one
    take event. Returns None when the claims leave fewer spare-having fields
    than the vector demands — the enumerator then drops that modifier
    combination as infeasible (a rigid demand is met exactly or not at all)."""
    want = {}
    for part in variant.split("|"):
        key, _, count = part.partition(":")
        want[key] = int(count)
    extras: dict = {}
    for r, row in enumerate(state.players[idx].farmyard.grid):
        for c, cell in enumerate(row):
            if cell.cell_type != CellType.FIELD:
                continue
            if cell.grain >= 2:
                key, n = f"grain{cell.grain}", cell.grain
            elif cell.veg >= 2:
                key, n = f"veg{cell.veg}", cell.veg
            else:
                continue
            if (want.get(key, 0) > 0
                    and n - 1 - claimed.get((r, c), 0) >= 1):
                want[key] -= 1
                extras[(r, c)] = 1
    if any(want.values()):
        return None   # demand unmeetable under the claims -> combo infeasible
    return extras


# Free minor; prereq "At Most 1 Occupation" → max_occupations=1.
register_minor(CARD_ID, max_occupations=1)
register_take_modifier(CARD_ID, _fold, variants_fn=_variants)
register_harvest_window_hook(CARD_ID, "field_phase")
