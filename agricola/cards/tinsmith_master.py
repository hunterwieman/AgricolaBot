"""Tinsmith Master (occupation, deck B #115; Bubulcus Expansion; players 1+).

Card text: "You can hold 1 additional animal in each pasture without a stable. Each time
you sow in a field, you can place 1 additional crop of the respective type in that field."

Clarifications (printed on the card): "This effect places one extra crop on top of the
usual stack, not a second stack in each field. You may not add anything except grain or
vegetable. This does not add a condition to sowing."

User ruling (2026-07-15): the "+1 crop, you can" is MEANINGFULLY DECLINABLE per field —
"when we sow with it active we have to count not just counts of veggies and grain sowed,
but also counts of veggies and grain that use the Tinsmith Master effect."

Two standing effects, no on-play:

  1. CAPACITY — +1 animal in each pasture WITHOUT a stable. Registered on the
     per-pasture-conditioned capacity registry (capacity_mods.register_pasture_capacity_per
     — the conditional sibling of Drinking Trough's flat fold): the bonus fn inspects each
     pasture and grants +1 only when `pasture.num_stables == 0`. Applied by
     helpers.extract_slots to the final (post-stable-doubling) capacity — trivially so,
     since a qualifying pasture has no stables to double by. Flows into every accommodation
     consumer (markets, breeding, feeding) via extract_slots; cache-safe by construction
     (the accommodation caches key on extract_slots' outputs — see §5.4's contract in
     CARD_ENGINE_IMPLEMENTATION.md).

  2. SOW BOOST — each field sown may take 1 extra crop of the sown type, per field, at the
     sower's option (the user ruling above). Registered on legality.SOW_BOOST_CARDS: the
     sow enumerator expands each CommitSow over `boost_grain` / `boost_veg` (how many of
     the sown grain-/veg-fields take the +1; 0/0 = decline) and `boost_card_sows` (which
     sown grain/veg card-field stacks take it — card-fields are fields, ruling 45
     2026-07-12; wood/stone stacks are excluded per the clarification's "anything except
     grain or vegetable"). The executor plants 4 grain / 3 veg on a boosted field ("one
     extra crop on top of the usual stack") — the extra crop comes from the general supply
     like the stack's other non-seed crops, so the player's supply debit is unchanged, and
     "this does not add a condition to sowing" holds: the bare unboosted commits are always
     present.
"""
from __future__ import annotations

from agricola.cards.capacity_mods import register_pasture_capacity_per
from agricola.cards.specs import register_occupation
from agricola.legality import register_sow_boost

CARD_ID = "tinsmith_master"


def _on_play(state, idx):
    """No on-play effect — both effects are standing (the registered modifiers)."""
    return state


def _stableless_pasture_bonus(pasture) -> int:
    """+1 capacity for a pasture WITHOUT a stable; stabled pastures unchanged."""
    return 1 if pasture.num_stables == 0 else 0


register_occupation(CARD_ID, _on_play)
register_pasture_capacity_per(CARD_ID, _stableless_pasture_bonus)
register_sow_boost(CARD_ID)
