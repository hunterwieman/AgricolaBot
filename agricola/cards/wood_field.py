"""Wood Field (minor improvement, D75; Consul Dirigens).

Card text: "You can plant wood on this card as though it were 2 fields, but
it is considered 1 field. Sow and harvest wood on this card as you would
grain."
ERRATA (verbatim): ERRATA: add "You can plant only wood on this card."
Clarifications (verbatim): "You may plant 2 wood at once with 1 trigger of
the Chief Forester A115.  Planted wood may not be spent during scoring for
the Joinery 8 / 18."
Cost: 1 Food. Prerequisite: 1 Occupation. VPs: 1. Not passing.

A pure card-field registration — the shared machinery
(`agricola/cards/card_fields.py`) does everything once the spec row exists:
two stacks, sowable with wood only (the errata), wood-as-grain planting
3 per sow (the "as you would grain" clause: 1 supply wood -> 3 on the
stack); the field-phase take harvests 1 wood from each non-empty stack.
No effect code of its own.

Governing rulings (all user rulings, CARD_DEFERRED_PLANS.md):

- Ruling 45 (2026-07-12): a card-field counts as a FIELD, never a field
  TILE (ruling 32, 2026-07-06) — it joins every field-count reader, and
  per-TILE readers exclude it.
- Ruling 47 (2026-07-12): "as though it were 2 fields" = 2 independently-
  sowable STACKS; the take harvests 1 from EACH non-empty stack;
  "considered 1 field" scopes the field-count readers (the card counts as
  exactly 1 field).
- Ruling 48 (2026-07-12): the whole card consumes ONE field-unit of a
  capped generic sow, filling any subset of its stacks; a crops-explicit
  grant ("sow crops" — Fodder Planter) may not plant here at all
  (`PendingSow.crops_only`).

On the printed clarifications: Chief Forester (A115) is UNIMPLEMENTED — the
2-wood-at-once reading it confirms is already the machinery's ruling-48 cap
accounting (one trigger's single field-unit may fill both stacks), so
nothing card-specific waits on it. The Joinery clarification is STRUCTURAL:
card-planted goods live in the owner's CardStore, never in the player's
supply, and the Joinery craft bonus spends supply wood only — no code
needed.
"""
from __future__ import annotations

from agricola.cards.card_fields import register_card_field
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources

CARD_ID = "wood_field"

register_card_field(CARD_ID, stacks=2, sow_amounts=(("wood", 3),))

register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=1)),
    min_occupations=1,
    vps=1,
)
