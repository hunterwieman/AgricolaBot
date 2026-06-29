"""Hedge Keeper (occupation, A88; Base Revised; players 1+).

Card text: "Each time you take a 'Build Fences' action, you do not have to pay
wood for 3 of the fences you build."

Clarification: "You may spend 0 wood to build 1-3 fences. Mini Pasture, Overhaul,
and other fencing effects that are not the literal 'Build Fences' action, do not
trigger this card."

Mechanism — a per-action free-fence SEED (COST_MODIFIER_DESIGN.md §9.4 source 2,
the per-action free-fence budget). The seed function is the single source of truth
for the budget at every site it is needed: the frame's `free_fence_budget` is seeded
from it at push (resolution), the placement-time "is Build Fences available?" check
anticipates it through it (legality), and the during-building enumerator reads the
remaining budget off the frame. The deferred-tally settle (engine `_settle_build_fences`
/ `_execute_build_pasture` CARDS path) covers the first 3 paid edges of the whole action
for free; the budget dies with the frame, so the +3 is exactly per-action.

The LITERAL-ACTION GATE (the clarification): the seed is 3 ONLY when
`build_fences_action` is True — i.e. the Fencing space or Farm Redevelopment
("Overhaul" is a fence build but its `build_fences_action` is False), never a card
EFFECT that builds fences (Mini Pasture). A card-effect fence build pushes a frame
with `build_fences_action=False`, so the seed returns 0 and Hedge Keeper grants
nothing there. Hedge Keeper ignores the entry-point `space_id` (it applies to any
literal Build Fences action).

No on-play effect — Category 2 / passive cost-discount occupation. Card-only state
(the seeded budget lives on a CARDS-mode-only frame field), so the Family game is
byte-identical and the C++ gates are untouched. See COST_MODIFIER_DESIGN.md §9 and
CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_free_fence_seed
from agricola.cards.specs import register_occupation

CARD_ID = "hedge_keeper"

FREE_FENCES = 3   # "do not have to pay wood for 3 of the fences you build"


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_free_fence_seed(
    CARD_ID,
    lambda state, idx, *, build_fences_action, space_id: (
        FREE_FENCES if build_fences_action else 0
    ),
)
