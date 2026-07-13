"""Grain Thief (occupation, E112; Ephipparius Expansion; players 1+; Crop
Provider).

Card text (verbatim): "Each time you would harvest a grain field, you can leave
the grain on the field and take 1 grain from the general supply instead."

Occupation (no cost beyond the play action's; no printed VPs); the on-play is a
no-op — the whole card is the standing replacement option.

**Timing home — a REPLACE-kind choice-bearing take-modifier.** All field-phase
harvesting is one simultaneous event (user ruling 11, 2026-07-05), and this card
modifies that event: for each planted grain field the owner would harvest, they
may instead leave the field untouched and take 1 grain from the general supply.
Registered via ``register_take_modifier`` with ``order=0`` — the replace kind
folds FIRST, so every later fold (Stable Manure's rigid demand, Scythe Worker's
auto extra) sees the replaced cells pre-claimed at their full crop count and can
take nothing from them. The per-field choice surfaces as variants of the take
commit itself — ``CommitFieldTake(modifiers=(("grain_thief", "<count
vector>"),))`` — at the per-player ``PendingFieldPhase`` host (owning this card
with >= 1 planted grain field is itself what hosts the frame). Declining is the
bare ``CommitFieldTake()``.

**Scope — user ruling 12 (2026-07-04, the harvest-verb lexicon):** unscoped
harvest-verb wording ("each time you would harvest a grain field" — no "of each
harvest" anchor) applies wherever the field-phase effect runs — a REAL harvest's
take AND a card-played field phase (Bumper Crop, ruling 4). Hence
``harvest_scoped=False``: at Bumper Crop the choice surfaces automatically as a
``PendingCardChoice`` over the feasible modifier combinations.

**A replaced field is NOT harvested — user ruling 2026-07-06** (proposed
2026-07-05, derived from "leave the grain on the field ... instead"; the user
ratified the reading). Under this ruling a replaced field emits
NO manifest entry: it is invisible to Grain Sieve's "at least 2 grain", to
Lynchet's harvested-tile count, and to Food Merchant's per-grain buys; it cannot
donate an "additional" good to Stable Manure, and Scythe Worker takes no
additional grain from it. The replacement's 1 grain comes from the general
supply and is likewise NOT harvested (it never appears in the manifest). Carried
by ``TakeFold(skipped=..., bonus=...)`` through ``resolution.field_take``.

THE OPTION SET (the Stable Manure count-vector idiom): the choice is per grain
field — each planted grain field may independently be replaced — and fields are
interchangeable within a group keyed by remaining grain count (replacing one
3-grain field is identical to replacing another). A variant is a count vector
over the groups: replace ``k_g`` fields of group ``g``, with ``0 <= k_g <= |g|``
and ``sum(k_g) >= 1``. Unlike Stable Manure's donor groups, a 1-grain field IS
eligible (its single grain is exactly what gets left behind); veg fields are not
grain fields and form no group. The empty vector is not enumerated — declining
is the bare ``CommitFieldTake()``, per the no-dead-option convention.

Variant encoding: ``"grain1:1|grain3:2"`` = replace 1 (grain, 1-remaining) field
and 2 (grain, 3-remaining) fields, groups sorted by key. The fold picks the
first ``k_g`` matching fields per group in scan order (within a group any field
is equivalent, so scan order is canonical), skipping any cell an earlier fold
already claimed (defensive — as order-0 nothing precedes it), and returns
``TakeFold(skipped=<cells>, bonus=Resources(grain=<fields replaced>))`` — 1
supply grain per replaced field, regardless of how much grain stays on it.
Returns None if the vector's demand cannot be met under the claims.

Family-inert: occupations exist only under ``GameMode.CARDS``, and every
registration here is ownership-gated — the Family game is byte-identical.
"""
from __future__ import annotations

import re

from agricola.cards.display import register_action_labeler
from agricola.cards.harvest_windows import (
    TakeFold,
    register_harvest_window_hook,
    register_take_modifier,
)
from agricola.cards.specs import register_occupation
from agricola.constants import CellType
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "grain_thief"


def _groups(state: GameState, idx: int) -> dict[str, int]:
    """The replaceable-field groups: {remaining-grain key: field count}, over
    every planted grain field (any count >= 1 — leaving 1 grain on a 1-grain
    field is a real replacement, unlike Stable Manure's >= 2 donor floor).

    A card-field holding grain is a grain field (user rulings 45/46,
    2026-07-12) and may be replaced like any other. Each is its OWN singleton
    group (key "cf_<card_id>", colon-free): not interchangeable with a
    same-count grid field — leaving the grain ON the card is card state.
    Grain-holding card-fields are always single-stack (the multi-stack cards
    grow only wood/stone)."""
    from agricola.cards.card_fields import iter_card_field_units

    out: dict[str, int] = {}
    for row in state.players[idx].farmyard.grid:
        for cell in row:
            if cell.cell_type == CellType.FIELD and cell.grain > 0:
                key = f"grain{cell.grain}"
                out[key] = out.get(key, 0) + 1
    for key, good, _count in iter_card_field_units(state, idx):
        if good == "grain":
            out[f"cf_{key[1]}"] = 1
    return out


def _variants(state: GameState, idx: int) -> list[str]:
    """Every legal count vector over the grain-field groups, encoded
    ``"key:count|key:count"`` (sorted keys, zero counts omitted), with total
    replacements >= 1. Empty when no grain field is planted — then no
    CommitFieldTake variant carries this card and (absent another reason) the
    walk takes inline."""
    groups = sorted(_groups(state, idx).items())
    if not groups:
        return []
    vectors: list[list[int]] = [[]]
    for _key, size in groups:
        vectors = [v + [k] for v in vectors for k in range(size + 1)]
    out = []
    for v in vectors:
        if sum(v) >= 1:
            out.append("|".join(f"{key}:{k}"
                                for (key, _size), k in zip(groups, v) if k))
    return out


def _fold(state: GameState, idx: int, variant: str, claimed) -> TakeFold | None:
    """Map the chosen count vector to the replacement: pick the chosen number
    of fields per (remaining-grain) group in scan order, skipping any cell
    already in ``claimed`` (defensive — this fold runs first at order 0, so in
    practice nothing precedes it), and return their cells as ``skipped`` plus
    1 general-supply grain per replaced field as ``bonus``. Returns None when
    the vector's demand cannot be met — the enumerator then drops that
    modifier combination as infeasible."""
    from agricola.cards.card_fields import iter_card_field_units

    want: dict[str, int] = {}
    for part in variant.split("|"):
        key, _, count = part.partition(":")
        want[key] = int(count)
    cells: list = []
    for r, row in enumerate(state.players[idx].farmyard.grid):
        for c, cell in enumerate(row):
            if cell.cell_type != CellType.FIELD or cell.grain <= 0:
                continue
            key = f"grain{cell.grain}"
            if want.get(key, 0) > 0 and not claimed.get((r, c), 0):
                want[key] -= 1
                cells.append((r, c))
    for key, good, _count in iter_card_field_units(state, idx):
        gkey = f"cf_{key[1]}"
        if (good == "grain" and want.get(gkey, 0) > 0
                and not claimed.get(key, 0)):
            want[gkey] -= 1
            cells.append(key)
    if any(want.values()):
        return None
    return TakeFold(skipped=frozenset(cells),
                    bonus=Resources(grain=len(cells)))


_GRID_PART_RE = re.compile(r"^grain(\d+):(\d+)$")


def _action_label(variant: str) -> str | None:
    """Web-UI label for a count vector (mechanical, terse): what happens — the
    grain stays on the replaced fields and 1 supply grain arrives per field —
    "grain1:2|grain2:1" -> "leave 2 1-grain fields + 1 2-grain field, +3 grain
    from supply". A "cf_<id>" group names its card (title-cased slug). The
    generic count-vector prettifier would misread this as extra harvesting."""
    parts: list[str] = []
    total = 0
    for part in variant.split("|"):
        if part.startswith("cf_"):
            key, _, count = part.partition(":")
            if not count.isdigit():
                return None
            k = int(count)
            name = key[len("cf_"):].replace("_", " ").title()
            parts.append(name if k == 1 else f"{k}x {name}")
            total += k
            continue
        m = _GRID_PART_RE.match(part)
        if m is None:
            return None
        n, k = int(m.group(1)), int(m.group(2))
        parts.append(f"{k} {n}-grain field" + ("" if k == 1 else "s"))
        total += k
    if not parts or total < 1:
        return None
    return "leave " + " + ".join(parts) + f", +{total} grain from supply"


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_take_modifier(CARD_ID, _fold, variants_fn=_variants,
                       order=0, harvest_scoped=False)
register_harvest_window_hook(CARD_ID, "field_phase")
register_action_labeler(CARD_ID, _action_label)
