"""Wildlife Reserve (minor improvement, C11; Consul Dirigens Expansion; Farm
Planner).

Card text (verbatim): "This card can hold up to 1 sheep, 1 wild boar, and 1
cattle."
Clarification (verbatim): "This card does not count as a pasture."
Cost: 2 Wood. Prerequisite: 2 Occupations. VPs: 1 (printed).

One effect — a per-species typed holder registered as a plain modifier row
(agricola/cards/capacity_mods.py) with no engine edits:

- **Per-species card slots** (`register_typed_slots`, sheep=1/boar=1/cattle=1):
  "can hold up to 1 sheep, 1 wild boar, and 1 cattle" is pure capacity —
  animals are not location-tracked, so the slots are realized by the GREEDY
  STRIP applied at the ownership-aware accommodation entry points
  (`helpers.accommodates`, `pareto_frontier`, `breeding_frontier` via
  `_typed_slot_strip`). The strip is exact by dominance, per type
  INDEPENDENTLY (user ruling 2026-07-21, the typed-slot fold direction): a
  typed slot can hold only its own species, so parking that species there
  never constrains any other animal — the owner's accommodation problem equals
  the standard one with the parked animals removed and added back to every
  answer. This is the multi-species sibling of Dolly's Mother's single sheep
  slot (agricola/cards/dollys_mother.py), which pioneered the strip.

- **"Does not count as a pasture"** holds STRUCTURALLY, with no code: pasture
  count/scoring and every pasture-referencing card effect read
  `farmyard.pastures` (real farmyard geometry), never the typed-slot registry.
  The slot lives purely in the accommodation solver's answers. Verified by a
  test (a no-pasture farm still scores the no-pasture value with the card in
  play), not coded.

The prerequisite "2 Occupations" is `min_occupations=2` (a HAVE-check at play
time, never spent). Printed 1 VP -> `vps=1` (a kept minor's ordinary printed
points).

Family fast path: empty registry -> `typed_slot_counts` returns Animals(), the
strip is a no-op, and every accommodation formula reduces to its previous text;
the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.capacity_mods import register_typed_slots
from agricola.cards.specs import register_minor
from agricola.resources import Animals, Cost, Resources

CARD_ID = "wildlife_reserve"


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=2)),
    min_occupations=2,
    vps=1,
)
register_typed_slots(CARD_ID, lambda p: Animals(sheep=1, boar=1, cattle=1))
