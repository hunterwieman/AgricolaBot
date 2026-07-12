"""Melon Patch (minor improvement, E69; Ephipparius Expansion; Crop Provider).

Card text (verbatim): "This card is a field that can only grow vegetables. Each
time you harvest the last vegetable from this card, you can plow 1 field."

Cost: none (free). Prerequisite: 2 Occupations. No printed VPs. Kept (not
passing).

THE FIELD. `register_card_field` (agricola/cards/card_fields.py) makes the card
a real field: sowable at any sow (1 vegetable from supply plants the standard 2,
RULES.md), harvested by the field-phase take (one `HarvestEntry` with source
"card:melon_patch"), reachable by the per-field take modifiers (ruling 46,
2026-07-12). "Can only grow vegetables" is the spec's sow whitelist —
``sow_amounts=(("veg", 2),)`` — so no sow ever puts grain on it. One stack
(ruling 47, 2026-07-12 — no "as though it were N fields" clause). For
field-COUNT readers (the Fields scoring category, "N fields" requirements) the
card counts as exactly 1 field (ruling 45, 2026-07-12); it is NEVER a field
TILE (ruling 32, 2026-07-06 — per-tile readers filter to "cell:" sources, and
this card's manifest entries carry "card:melon_patch").

THE PLOW GRANT — an UNSCOPED per-occasion optional trigger
(`register_harvest_occasion_trigger`, agricola/cards/harvest_windows.py).
Rulings 43/44 (2026-07-12) place the card-fields' own harvest reactions on the
take occasion's optional-trigger stretch, alongside Food Merchant — the
`PendingHarvestOccasion` host — and that is exactly where this trigger sits.

- OPTIONAL. "You can plow 1 field" grants a SUB-ACTION, and a granted
  sub-action must have a decline path; per the standing convention the
  optionality lives at the OFFER (no per-frame declinable flag, no
  SkipTrigger): declining = Proceed on the host without firing.
- ELIGIBILITY. This occasion harvested the card's last vegetable — an entry
  with ``source == "card:melon_patch"`` and ``crop == "veg"``, AND the
  post-take store holds 0 veg (``card_holds == 0``; the occasion fns run on
  the POST-take state) — AND a legal plow target exists
  (``legality._can_plow``: never offer a trigger whose fired frame would have
  no legal commit).
- APPLY. Push the standard single-shot `PendingPlow` with
  ``initiated_by_id="card:melon_patch"``; the player picks the cell through
  the normal CommitPlow flow (before-phase commit, after-phase Stop pops back
  to the host). "Plow 1 field" plows 1 farmyard field — a field, never a tile
  handed out (ruling 32's tile/field distinction cuts the other way here: the
  grant is the plow primitive itself, exactly as Farmland grants it).
- ONCE PER OCCASION rides the host's ``triggers_resolved``; with one stack the
  card can empty at most once per take anyway.

SCOPING (ruling 12, 2026-07-04 — the harvest-verb lexicon): "Each time you
harvest the last vegetable from this card" is bare harvest-verb wording with
no phase anchor, so the trigger is UNSCOPED — it fires on ANY harvesting
occasion that empties the card: a real harvest's field-phase take and a
card-played bare take (Bumper Crop's mid-WORK ``source="card:bumper_crop"``
occasion) alike. The gate is the occasion itself, never ``state.phase``. The
E-deck contrast is deliberate: E69's "harvest" (this card) vs E70 Crop
Rotation Field's "remove" — this trigger reads the HARVEST verb.

Card-only throughout (the card-field registry, the occasion-trigger registry,
and the CardStore stack are all ownership-gated and never constructed in the
Family game), so the Family game is byte-identical and the C++ gates are
untouched.
"""
from __future__ import annotations

from agricola.cards.card_fields import card_holds, register_card_field
from agricola.cards.harvest_windows import register_harvest_occasion_trigger
from agricola.cards.specs import register_minor
from agricola.legality import _can_plow
from agricola.pending import PendingPlow, push
from agricola.state import GameState

CARD_ID = "melon_patch"


def _eligible(state: GameState, idx: int, occasion) -> bool:
    """This occasion took the card's last vegetable (a card:melon_patch veg
    entry AND a post-take store holding 0 veg) and a legal plow target exists
    (never offer a grant whose fired frame would have no legal commit).
    Ownership is checked by the seam; unscoped — no phase/source gate
    (ruling 12, 2026-07-04)."""
    return (
        any(e.source == f"card:{CARD_ID}" and e.crop == "veg"
            for e in occasion.entries)
        and card_holds(state.players[idx], CARD_ID, "veg") == 0
        and _can_plow(state.players[idx])
    )


def _apply(state: GameState, idx: int, occasion) -> GameState:
    """Grant the plow: push the standard single-shot PendingPlow; the cell is
    picked through the normal CommitPlow flow."""
    return push(state, PendingPlow(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))


register_minor(CARD_ID, min_occupations=2)   # free, no printed VPs, no on-play
register_card_field(CARD_ID, stacks=1, sow_amounts=(("veg", 2),))
register_harvest_occasion_trigger(CARD_ID, _eligible, _apply)
