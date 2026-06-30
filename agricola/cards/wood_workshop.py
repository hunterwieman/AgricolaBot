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
    # Fire only in the host frame's BEFORE phase — i.e. the genuine "before you
    # play/build the improvement" moment, when the leaf is first pushed and its
    # cost has not yet been charged. This gate matters for `before_play_minor`:
    # `_execute_play_minor` ends by calling `_fire_subaction_before_auto` again (to
    # catch a sub-action leaf that a minor's `on_play` may have pushed, e.g. Shifting
    # Cultivation → PendingPlow). For a minor whose `on_play` pushes nothing, the top
    # at that second call is still the *same* PendingPlayMinor — but now flipped to
    # its AFTER phase by the preceding `_enter_after_phase`. Without this gate the
    # grant would fire a second time and hand out +2 wood per minor. Reading
    # `phase == "before"` fires exactly once, at the real before-payment moment. (For
    # `before_build_major`, `_execute_build_major` never re-fires, so this is a
    # harmless no-op there — the single fire is always in the before phase.)
    top = state.pending_stack[-1]
    return getattr(top, "phase", "before") == "before"


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
