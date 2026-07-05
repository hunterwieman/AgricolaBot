"""Scythe (minor improvement, E73; Ephipparius Expansion; Crop Provider).

Card text (verbatim): "During the field phase of each harvest, you can select
exactly one of your fields and harvest all the crops planted in it."

Cost: 1 Wood. No printed VPs, no prerequisite, not a passing card. On-play is a
no-op.

**Timing home — a CHOICE-BEARING take-MODIFIER folding into the one event
(user ruling 11, 2026-07-05).** All field-phase harvesting is ONE simultaneous
event: the crops this card reaps from the selected field are taken AT THE SAME
TIME as the mechanical take, never as a separate occasion. Scythe is the sibling
of Stable Manure and Scythe Worker — a `register_take_modifier` fold-in — and
differs only in WHAT it harvests: instead of "1 additional good from N fields"
(Stable Manure) it harvests ALL the remaining crops from exactly ONE chosen
field. "You can" with a real choice — WHICH field to empty — makes it a
CHOICE-BEARING modifier (`register_take_modifier` with a `variants_fn`): the
choice surfaces as a variant of the take commit itself,
`CommitFieldTake(modifiers=(("scythe", <group>),))`, at the per-player
`PendingFieldPhase` host (owning this card with a legal use is itself what hosts
the frame). Declining = committing the bare take. Being printed "of each
harvest", the modifier applies only to a real harvest's take (ruling 12) — a
card-played field phase (Bumper Crop) runs bare.

**The extra amount = count − 1.** The base take already harvests 1 crop from
every planted field, so "harvest ALL the crops planted in it" adds the REMAINING
`count - 1` units on the chosen field. The chosen field's per-cell entry rides
`field_take`'s `extra_takes`: it is depleted from `count` to 0 in the one event
(1 base + (count-1) extra), and the manifest entry carries the full `amount`
with `emptied=True` — so occasion consumers see one event with everything in it
(Grain Sieve counts the folded-in grain toward "at least 2 grain" per ruling 11;
Slurry Spreader reads the emptied flag and pays once for the field, +2/+1 food,
not per unit).

THE OPTION SET (the Stable Manure grouping shortcut): fields are interchangeable
within a group keyed by (crop kind, crops remaining) — emptying one 3-grain
field is identical to emptying another — so each variant is a single GROUP key,
and the fold empties the FIRST field of that group in scan order (canonical
within the group). "Select exactly ONE of your fields" caps the choice at a
single group per harvest — enforced structurally by the variant shape: a variant
names exactly one group, and the enumerator offers one commit per group (never a
multi-group combination). Only fields with >= 2 of their crop form groups: a
1-crop field's sole crop already goes to the base take, so "harvest all the
crops" reaps nothing extra there — it is not a meaningful selection and forms no
group (loss-less restriction). The empty selection is not enumerated — declining
is the bare `CommitFieldTake()`, per the no-dead-option convention.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import (
    register_harvest_window_hook,
    register_take_modifier,
)
from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "scythe"


def _groups(state: GameState, idx: int) -> dict[str, int]:
    """The donor-field groups keyed by (crop kind + remaining count), for fields
    holding >= 2 of their crop (a 1-crop field's crop already goes to the base
    take — emptying it reaps nothing extra, so it forms no group). The value is
    the field count in the group (used only to know the group is non-empty)."""
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
    """One variant per donor group — a single group key (e.g. "grain3"). "Select
    exactly one of your fields" is exactly one group choice; fields within a
    group are interchangeable, so the group key IS the choice. Empty when no
    field can spare an extra beyond the base take — then no CommitFieldTake
    variant carries this card and (absent another reason) the walk takes
    inline."""
    return sorted(_groups(state, idx))


def _fold(state: GameState, idx: int, variant: str, claimed) -> dict:
    """Map the chosen group to per-cell extra takes: empty ONE field of that
    (crop, remaining) group — its remaining spare beyond the base take's 1 and
    beyond extras other modifiers already claimed is the extra, so the field
    ends the one take event EMPTY ("harvest all the crops planted in it" is
    satisfied by the combined event whoever claimed which unit). Within a
    group any field is equivalent; among them the field with the MOST spare is
    chosen (the player's crops — take the most; ties break by scan order), so
    Scythe composes with a same-group Stable Manure claim by preferring an
    unclaimed sibling. Flexible demand — never None (a fully-claimed group
    still satisfies "all the crops harvested" with a 0-extra fold)."""
    best = None   # (spare, r, c)
    for r, row in enumerate(state.players[idx].farmyard.grid):
        for c, cell in enumerate(row):
            if cell.cell_type != CellType.FIELD:
                continue
            if cell.grain >= 2:
                key, count = f"grain{cell.grain}", cell.grain
            elif cell.veg >= 2:
                key, count = f"veg{cell.veg}", cell.veg
            else:
                continue
            if key == variant:
                spare = count - 1 - claimed.get((r, c), 0)
                if best is None or spare > best[0]:
                    best = (spare, r, c)
    assert best is not None, (
        f"scythe variant {variant!r} names a group with no matching field")
    spare, r, c = best
    return {(r, c): spare} if spare > 0 else {}


# Cost 1 Wood; no printed VPs, no prereq, not passing; no on-play effect.
register_minor(CARD_ID, cost=Cost(Resources(wood=1)))
register_take_modifier(CARD_ID, _fold, variants_fn=_variants)
register_harvest_window_hook(CARD_ID, "field_phase")
