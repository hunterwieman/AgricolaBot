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

**Card-fields (user rulings 45/46, 2026-07-12).** A card-field (Beanfield,
Crop Rotation Field, ...) is one of "your fields" (ruling 45), and per-FIELD
harvest modifiers reach card-fields (ruling 46) — so a card whose take-good is
a crop with >= 2 remaining (the same floor as the grid's) is a selectable
Scythe target. Each qualifying card is its OWN singleton group, keyed
`"cf_<card_id>"` (colon-free — nothing in this module's keys needs a
delimiter, but the key shape is shared with Stable Manure's, whose vector
encoding splits on ":"): a card-field is NOT interchangeable with a same-count
grid field, because harvesting from the card moves card state (the CardStore
stacks) and fires card-level readers (Crop Rotation Field's re-sow). The fold
addresses the card's stack by the take-target key ("card", card_id,
stack_idx) via `iter_card_field_units` and empties it — extras = count − 1 −
claimed — within the one event (grain-capable card-fields are single-stack,
so per-field = per-stack). Wood/stone card-fields (Wood Field, Rock Garden,
Cherry Orchard) NEVER qualify: the printed wording harvests "all the CROPS
planted in it", and wood/stone are not crops (contrast Stable Manure's
"1 additional GOOD", which they do satisfy). Unlike the grid groups' flexible
fold, the card group is RIGID: when earlier claims leave the stack no spare —
fully claimed, or replaced out of the take entirely (Grain Thief enters a
replaced target at its full count) — the fold returns None and the enumerator
drops that modifier combination as infeasible (the same-outcome combination
without Scythe is still offered, so nothing is lost).

KNOWN LIMITATION (pre-existing, shared with the grid — awaiting a user
decision; documented, not solved here): on a MIXED field (Heresy Teacher's
vegetable placed below 3+ grain — grid cell and card stack alike), the take
mechanism harvests only the take-precedence crop, so Scythe's "all the crops
planted in it" currently yields the grain and leaves the vegetable behind.
The card-field extension deliberately matches the existing grid behavior
(take-good only) rather than inventing new machinery for the card side alone.
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
    the field count in the group (used only to know the group is non-empty).

    Card-fields are selectable FIELDS too (user rulings 45/46, 2026-07-12).
    Each qualifying card is its OWN singleton group (key "cf_<card_id>" — not
    interchangeable with a same-count grid field: harvesting the card moves
    card state and fires card-level readers). The floor mirrors the grid's,
    on the stack's take-good: a CROP with >= 2 remaining. Wood/stone
    card-fields never qualify — the card reaps "all the CROPS planted in it",
    and wood/stone are not crops."""
    from agricola.cards.card_fields import (
        CROP_SOW_AMOUNTS,
        card_field_stacks,
        owned_card_fields,
        stack_take_good,
    )

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
    p = state.players[idx]
    for cid in owned_card_fields(p):
        if any(good in CROP_SOW_AMOUNTS and n >= 2
               for good, n in map(stack_take_good, card_field_stacks(p, cid))):
            out[f"cf_{cid}"] = 1
    return out


def _variants(state: GameState, idx: int) -> list[str]:
    """One variant per donor group — a single group key (e.g. "grain3", or
    "cf_<card_id>" for a card-field, rulings 45/46). "Select exactly one of
    your fields" is exactly one group choice; fields within a group are
    interchangeable, so the group key IS the choice. Empty when no field can
    spare an extra beyond the base take — then no CommitFieldTake variant
    carries this card and (absent another reason) the walk takes inline."""
    return sorted(_groups(state, idx))


def _fold(state: GameState, idx: int, variant: str, claimed) -> dict | None:
    """Map the chosen group to per-cell extra takes: empty ONE field of that
    (crop, remaining) group — its remaining spare beyond the base take's 1 and
    beyond extras other modifiers already claimed is the extra, so the field
    ends the one take event EMPTY ("harvest all the crops planted in it" is
    satisfied by the combined event whoever claimed which unit). Within a
    group any field is equivalent; among them the field with the MOST spare is
    chosen (the player's crops — take the most; ties break by scan order), so
    Scythe composes with a same-group Stable Manure claim by preferring an
    unclaimed sibling. Grid groups are flexible demand — never None (a
    fully-claimed group still satisfies "all the crops harvested" with a
    0-extra fold).

    A "cf_<card_id>" group (rulings 45/46, 2026-07-12) empties the card's
    crop stack, addressed by the take-target key ("card", card_id, stack_idx)
    — grain-capable card-fields are single-stack, so the card's one crop
    stack IS the field. The singleton card group is RIGID: when the claims
    leave no spare (fully claimed, or Grain-Thief-replaced at full count) the
    fold returns None and the combination is dropped as infeasible — there is
    no sibling field to redirect to, and the same outcome is reachable
    without Scythe."""
    from agricola.cards.card_fields import (
        CROP_SOW_AMOUNTS,
        iter_card_field_units,
    )

    if variant.startswith("cf_"):
        cid = variant[len("cf_"):]
        for key, good, count in iter_card_field_units(state, idx):
            if key[1] != cid or good not in CROP_SOW_AMOUNTS:
                continue
            spare = count - 1 - claimed.get(key, 0)
            return {key: spare} if spare > 0 else None
        raise AssertionError(
            f"scythe variant {variant!r} names a card with no crop to reap")
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
