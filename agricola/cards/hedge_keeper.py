"""Hedge Keeper (occupation, A88; Base Revised; players 1+).

Card text: "Each time you take a 'Build Fences' action, you do not have to pay
wood for 3 of the fences you build."

Clarification: "You may spend 0 wood to build 1-3 fences. Mini Pasture, Overhaul,
and other fencing effects that are not the literal 'Build Fences' action, do not
trigger this card."

Mechanism — a `before_build_fences` AUTOMATIC effect (COST_MODIFIER_DESIGN.md §9.4
source 2, the per-action free-fence budget). When the `PendingBuildFences` host is
pushed in its before-phase, this seeds `free_fence_budget += 3` on the frame; the
deferred-tally settle (engine `_execute_build_pasture` CARDS path) then covers the
first 3 paid edges of the whole action for free. The budget dies with the frame, so
the +3 is exactly per-action.

The LITERAL-ACTION GATE (the clarification): the seed applies ONLY when
`top.build_fences_action is True` — i.e. the Fencing space or Farm Redevelopment
("Overhaul" is a fence build but its `build_fences_action` is False), never a card
EFFECT that builds fences (Mini Pasture). A card-effect fence build pushes
`PendingBuildFences(build_fences_action=False)`, which this auto skips, so Hedge
Keeper grants nothing there.

No on-play effect — Category 2 / passive cost-discount occupation. Card-only state
(the seeded budget lives on a CARDS-mode-only frame field), so the Family game is
byte-identical and the C++ gates are untouched. See COST_MODIFIER_DESIGN.md §9 and
CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.pending import PendingBuildFences
from agricola.replace import fast_replace
from agricola.state import GameState

CARD_ID = "hedge_keeper"

FREE_FENCES = 3   # "do not have to pay wood for 3 of the fences you build"


def _eligible(state: GameState, idx: int) -> bool:
    """Seed the budget only on a LITERAL 'Build Fences' action (the clarification):
    the top frame must be a before-phase PendingBuildFences with
    `build_fences_action True` — never a card-effect fence build (Mini Pasture /
    Overhaul), which sets the flag False."""
    if not state.pending_stack:
        return False
    top = state.pending_stack[-1]
    return (
        isinstance(top, PendingBuildFences)
        and top.build_fences_action
        and top.phase == "before"
    )


def _seed_budget(state: GameState, idx: int) -> GameState:
    """before_build_fences: add 3 to this action's per-action free-fence budget."""
    top = state.pending_stack[-1]
    return fast_replace(
        state,
        pending_stack=state.pending_stack[:-1]
        + (fast_replace(top, free_fence_budget=top.free_fence_budget + FREE_FENCES),),
    )


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_build_fences", CARD_ID, _eligible, _seed_budget)
