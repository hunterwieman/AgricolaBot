"""Rock Garden (minor improvement, E80; Ephipparius).

Card text: "You can only plant stone on this card. Plant as though it were
3 fields, but it is considered 1 field. Sow and harvest stone on this card
as you would vegetables."
No cost. No prerequisite. No printed VPs.

A pure card-field registration — the shared machinery
(`agricola/cards/card_fields.py`) does everything once the spec row exists:
three stacks, sowable with stone only, stone-as-vegetables planting 2 per
sow (the "as you would vegetables" clause: 1 supply stone -> 2 on the
stack); the field-phase take harvests 1 stone from each non-empty stack.
No effect code of its own.

Governing rulings (all user rulings, CARD_DEFERRED_PLANS.md):

- Ruling 45 (2026-07-12): a card-field counts as a FIELD, never a field
  TILE (ruling 32, 2026-07-06) — it joins every field-count reader, and
  per-TILE readers exclude it.
- Ruling 47 (2026-07-12): "as though it were 3 fields" = 3 independently-
  sowable STACKS; the take harvests 1 from EACH non-empty stack;
  "considered 1 field" scopes the field-count readers (the card counts as
  exactly 1 field).
- Ruling 48 (2026-07-12): the whole card consumes ONE field-unit of a
  capped generic sow, filling any subset of its stacks; a crops-explicit
  grant ("sow crops" — Fodder Planter) may not plant here at all
  (`PendingSow.crops_only`).
"""
from __future__ import annotations

from agricola.cards.card_fields import register_card_field
from agricola.cards.specs import register_minor

CARD_ID = "rock_garden"

register_card_field(CARD_ID, stacks=3, sow_amounts=(("stone", 2),))

register_minor(CARD_ID)
