"""Wood Workshop (minor improvement, B75; Bubulcus Expansion; cost 1 clay,
1 Occupation prerequisite).

Card text: "Each time before you play or build an improvement, you get 1 wood."

Clarification: "You are able to pay for the improvement with just the wood given
by this card."

A mandatory, choice-free income grant (register_auto) that fires in the BEFORE
phase of an improvement play/build — so the +1 wood lands in hand *before* the
cost is charged and can fund that very improvement, with any surplus banking (a
real grant, not a cost reduction floored at 0). "Improvement" = a MAJOR or MINOR
improvement only — NOT rooms or renovation — so it registers on exactly
`before_build_major` and `before_play_minor`, mirroring Lumber Mill's scope. (See
COST_MODIFIER_DESIGN.md / CARD_IMPLEMENTATION_PLAN.md.)

Why the BEFORE phase, and on the sub-action events (not the composite host): the
engine fires `before_build_major` / `before_play_minor` at the moment
`ChooseSubAction` pushes the PendingBuildMajor / PendingPlayMinor leaf
(engine._fire_subaction_before_auto), which is strictly before the
CommitBuildMajor / CommitPlayMinor that charges the cost. Hooking the leaf events
rather than the `major_minor_improvement` composite host makes it fire uniformly
across every entry point (the Major/Minor Improvement space, House Redevelopment,
Basic Wish for Children, Meeting Place).

Self-firing is avoided structurally: `apply_auto_effects` gates on ownership
(`_owns`), and Wood Workshop only enters `minor_improvements` at CommitPlayMinor —
*after* its own `before_play_minor` would have fired — so playing Wood Workshop
itself never grants its owner the wood.

It is a MINOR with a structured definition: cost 1 clay and the occupation-count
prerequisite "1 Occupation" (`min_occupations=1`). No printed victory points, not
passing. Its only effect is the before-phase wood grant (no on-play effect — the
default no-op).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "wood_workshop"


def _eligible(state: GameState, idx: int) -> bool:
    # Unconditional: the before-auto seam (`engine._fire_subaction_before_auto`) is
    # depth-guarded to fire exactly once, at the leaf's push — a per-card phase gate
    # used to be needed here to block a re-fire from `_execute_play_minor`'s trailing
    # seam call, but that guard now lives in the seam itself.
    return True


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(wood=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(clay=1)),
    min_occupations=1,
)

# "Improvement" = MAJOR or MINOR improvement only (NOT rooms / renovation).
register_auto("before_build_major", CARD_ID, _eligible, _apply)
register_auto("before_play_minor", CARD_ID, _eligible, _apply)
