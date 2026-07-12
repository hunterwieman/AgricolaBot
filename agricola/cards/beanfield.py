"""Beanfield (minor improvement, B68; Base Revised).

Card text: "This card is a field that can only grow vegetables."
Cost: 1 Food. Prerequisite: 2 Occupations. VPs: 1. Not passing.

A pure card-field registration — the shared machinery
(`agricola/cards/card_fields.py`) does everything once the spec row exists:
one stack, sowable with vegetables only (1 supply vegetable plants 2, exactly
as on a board field), harvested by the field-phase take (1 vegetable per
harvest), reachable by the per-field take modifiers, and counted by scoring
and every field reader. No effect code of its own.

Governing ruling (user ruling 45, 2026-07-12): a card-field counts as a
FIELD, never a field TILE — it joins every field-count reader (the Fields
scoring category, "N fields" requirements, "vegetable field" tests), each
card as exactly 1 field, while per-TILE readers exclude it (ruling 32,
2026-07-06: tile counters filter to "cell:" harvest sources; this card's are
"card:beanfield").
"""
from __future__ import annotations

from agricola.cards.card_fields import register_card_field
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources

CARD_ID = "beanfield"

register_card_field(CARD_ID, stacks=1, sow_amounts=(("veg", 2),))

register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=1)),
    min_occupations=2,
    vps=1,
)
