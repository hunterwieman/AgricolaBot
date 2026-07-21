"""Cattle Farm (minor improvement, C12; Corbarius Expansion; Farm Planner).

Card text (verbatim): "For each pasture you have, you can keep 1 cattle on this
card."
Cost: 1 Wood. Prerequisite: none. VPs: none (printed).

A typed (species-specific) card holder: pure standing capacity that exists while
the card sits in the tableau. Animals are not location-tracked, so there is no
placement decision — the capacity simply exists once the card is owned. The number
of slots is DYNAMIC: one cattle slot per pasture the player currently has.

Implemented as a per-species (cattle-only) slot count via
`register_typed_slots("cattle_farm", _slots)` (capacity_mods.py), consumed by the
GREEDY STRIP in `helpers.py` (`_typed_slot_strip`, and the ownership-aware entry
points `helpers.accommodates` / `pareto_frontier` / `breeding_frontier`):

- **"1 cattle per pasture"** is a cattle-ONLY slot count, so it cannot ride
  `num_flexible` (an any-type slot). It rides the typed-slot registry instead:
  `_slots(p) -> Animals(cattle=<pasture count>)`. The strip is exact by dominance,
  per type independently — parking a cattle on a cattle-only slot never constrains
  the other animals, so the owner's accommodation problem equals the standard one
  with the parked cattle removed and added back to every answer. This composes with
  every other capacity fold (real pastures, house pet, other holders) and keeps the
  frontier caches honest (the strip changes the memoized internals' ARGUMENTS, never
  a hidden input).

- **The pasture count** is derived from `p.farmyard.pastures` (the cached pasture
  decomposition), NEVER from `cell_type` — an empty fenced pasture cell reads as
  `EMPTY`, so counting `cell_type` would undercount (CARD_AUTHORING_GUIDE §2, "A
  pasture is not a CellType"). `len(p.farmyard.pastures)` is the pasture count.

- **This card is not a pasture.** It adds cattle capacity but is never itself a
  pasture: pasture count and pasture scoring (`scoring._score_pastures` over
  `farmyard.pastures`) and every pasture-referencing card effect read farmyard
  geometry, never this slot count. A holder card therefore never adds to the
  pasture count.

Monotonicity — no eviction path (user ruling 2026-07-21, the typed-slot fold
direction): the slot count equals the pasture count, and pastures are PERMANENT
(fences can never be demolished), so the count is monotone non-decreasing over a
game. Card capacity therefore never DROPS, and no situation can arise where a
housed cattle must be evicted because the card lost a slot. (Building a new stable
inside an existing pasture raises that pasture's own capacity but does not change
the pasture COUNT, so it does not change this card's slot count either.)

Cost 1 wood; no printed VP; no on-play effect; no prerequisite.

Family fast path: empty registry — `typed_slot_counts` returns `Animals()` when the
card is not owned, so `extract_slots` / the strip are byte-identical to the pre-card
engine and the C++ family gates are untouched.
"""
from __future__ import annotations

from agricola.cards.capacity_mods import register_typed_slots
from agricola.cards.specs import register_minor
from agricola.resources import Animals, Cost, Resources
from agricola.state import PlayerState

CARD_ID = "cattle_farm"


def _slots(player_state: PlayerState) -> Animals:
    """One cattle slot per pasture the player currently has (from the cached
    pasture decomposition, never `cell_type`)."""
    return Animals(cattle=len(player_state.farmyard.pastures))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register_typed_slots(CARD_ID, _slots)
