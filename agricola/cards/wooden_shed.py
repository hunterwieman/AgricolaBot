"""Wooden Shed (minor improvement, D9; Dulcinaria).

Card text (verbatim): "This card can only be played via a \"Major Improvement\" action.
It provides room for one person. You may no longer renovate."
Clarifications: "May not be played on the \"House Redevelopment\" action space, as the
\"Renovate\" action is mandatory and comes before the improvement action.  May be played
through the effect of a card, such as Angler A095."
Cost: 2 wood, 1 reed.  Prerequisite: Still in Wooden House.

Three effects:

1. A PEOPLE-capacity bonus of +1 (housing-capacity registry) — "provides room for one
   person" — permanent while owned. (The card does not count as a room; it is pure
   housing capacity, exactly like the other capacity cards.)

2. A PLAY-ORIGIN restriction: "can only be played via a Major or Minor Improvement
   action" (the phrase "Major Improvement action" is the informal name for it). It is
   registered as a COMPOSITE_ONLY_MINOR, so `playable_minors` offers it only when the
   play-minor frame is the composite host's child (`initiated_by_id ==
   "major_minor_improvement"` — the Major Improvement space, House Redevelopment, and
   card grants like Angler), never via the bare "Minor Improvement" action of Meeting
   Place / Basic Wish / bare grants. The House-Redevelopment exclusion in the
   clarification needs no origin code: House Redevelopment renovates FIRST (mandatory),
   so by the improvement step the player is no longer in a wooden house and the prereq
   below already fails. Angler grants the composite action, so it works — per the
   clarification.

3. "You may no longer renovate": registered in the renovate-forbid registry (legality),
   which drives `_legal_renovate_targets` to [] for the owner — forbidding renovation on
   every path (House/Farm Redevelopment via `_can_renovate`, and any card-granted
   renovation). The same seam Mantlepiece uses.

No on-play effect.
"""
from __future__ import annotations

from agricola.cards.capacity_mods import register_housing_capacity
from agricola.cards.specs import register_minor
from agricola.constants import HouseMaterial
from agricola.legality import register_composite_only_minor, register_renovate_forbid
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "wooden_shed"


def _capacity_bonus(state: GameState, idx: int) -> int:
    return 1


def _prereq(state: GameState, idx: int) -> bool:
    """Still in Wooden House."""
    return state.players[idx].house_material == HouseMaterial.WOOD


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2, reed=1)), prereq=_prereq)
register_housing_capacity(CARD_ID, _capacity_bonus)
register_composite_only_minor(CARD_ID)
register_renovate_forbid(CARD_ID)
