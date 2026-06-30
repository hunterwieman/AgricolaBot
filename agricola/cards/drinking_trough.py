"""Drinking Trough (minor improvement, A12; Base Revised; players 1+).

Card text: "Each of your pastures (with or without a stable) can hold up to 2 more animals."
Clarification: "Cards holding animals are not pastures unless explicitly stated." (No
animal-holding card acts as a pasture in the implemented set, so this clause is a no-op
today; a future card that IS explicitly a pasture must opt in rather than be boosted here.)

A passive per-pasture capacity bonus: every pasture's capacity gains a flat +2, applied
AFTER the stable doubling ("with or without a stable" -> +2 to the FINAL capacity, NOT
(2*cells+2)*2^stables and NOT another doubling). Registered via the pasture-capacity
registry (capacity_mods); extract_slots adds it to each pasture's capacity, so it flows into
the two capacity-gated decisions (animal acquisition + breeding) and nowhere else. Cost 1
clay; no on-play effect, no prerequisite.
"""
from __future__ import annotations

from agricola.cards.capacity_mods import register_pasture_capacity
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources

CARD_ID = "drinking_trough"


def _bonus(player_state) -> int:
    return 2


register_minor(CARD_ID, cost=Cost(resources=Resources(clay=1)))
register_pasture_capacity(CARD_ID, _bonus)
