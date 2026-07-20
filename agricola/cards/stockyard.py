"""Stockyard (minor improvement, B12; Bubulcus Expansion; Farm Planner).

Card text (verbatim): "This card can hold up to 3 animals of the same type. (It
is not considered a pasture)."
Cost: 1 Wood + 1 Stone. Prerequisite: none. VPs: 1 (printed).

A pasture-LIKE animal holder: pure standing capacity that exists while the card
sits in the tableau. Animals are not location-tracked, so there is no placement
decision — the capacity simply exists once the card is owned.

Implemented as a single extra ANONYMOUS single-type capacity bin (user design
direction 2026-07-20 — fold pasture-like holders into the accommodation solver's
capacity list as anonymous bins, keeping them distinct wherever card effects
distinguish them):

- **"up to 3 animals of the same type"** is exactly the accommodation solver's
  one-type-per-bin semantics: a bin of capacity 3 holds up to 3 animals of a
  single type. Registered via `register_animal_cap_slots` (capacity_mods.py);
  `helpers.extract_slots` appends the bin to the capacity list AFTER every
  pasture-only fold (the per-pasture bonuses, the reserved-empty drop), so
  nothing that treats real pastures as distinct can ever touch the card bin.
  Consumed by the two capacity-gated decisions — animal acquisition
  (`pareto_frontier`) and breeding (`breeding_frontier`) — and by
  `helpers.accommodates`, and nowhere else.

- **"(It is not considered a pasture)"** holds STRUCTURALLY: pasture count and
  pasture scoring (`scoring._score_pastures` over `farmyard.pastures`) and every
  pasture-referencing card effect read farmyard geometry, never this anonymous
  capacity list. A holder card therefore never adds to the pasture count nor is
  it ever reserved/boosted as a pasture.

Cost 1 wood + 1 stone; printed 1 VP -> `vps=1`; no on-play effect, no
prerequisite.

Family fast path: empty registry — `extra_animal_caps` returns () when the card
is not owned, so `extract_slots` is byte-identical to the pre-card engine and the
C++ family gates are untouched.
"""
from __future__ import annotations

from agricola.cards.capacity_mods import register_animal_cap_slots
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources

CARD_ID = "stockyard"


def _caps(player_state) -> tuple:
    """One anonymous single-type bin of capacity 3 (any owner, any farm state)."""
    return (3,)


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1, stone=1)), vps=1)
register_animal_cap_slots(CARD_ID, _caps)
