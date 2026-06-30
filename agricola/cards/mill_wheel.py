"""Mill Wheel (minor improvement, B64; Bubulcus Expansion; cost 2 wood, 1 VP).

Card text: "Each time you use the 'Grain Utilization' action space while the
'Fishing' accumulation space is occupied, you get an additional 2 food."

Category 3 (action-space hook, automatic income) with a CONDITIONAL eligibility
clause (Fishing occupied). The +2 food is not optional — it is an automatic
effect gated by the condition, not a FireTrigger — so it registers as a
`before_action_space` auto-effect. On-play is a no-op.

Grain Utilization is a NON-atomic space, so unlike an atomic-space hook
(e.g. Pitchfork on Grain Seeds) this card does NOT call
`register_action_space_hook`: `_initiate_grain_utilization` always pushes the
PendingGrainUtilization host frame and fires the before-automatics at the push,
so the grant lands the moment the worker is placed (before any sow/bake
sub-action). A bare "each time you use" fires in the BEFORE phase per the
trigger-timing ruling. See CARD_IMPLEMENTATION_PLAN.md Category 3.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space

CARD_ID = "mill_wheel"
SPACES = frozenset({"grain_utilization"})


def _eligible(state: GameState, idx: int) -> bool:
    if state.pending_stack[-1].space_id not in SPACES:
        return False
    # Conditional: only pays out when the Fishing accumulation space is occupied
    # (by anyone). A direct workers-tuple check — NOT `_is_available`, which also
    # returns False on an unrevealed space and would mis-fire.
    return get_space(state.board, "fishing").workers != (0, 0)


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(food=2))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2)), vps=1)
register_auto("before_action_space", CARD_ID, _eligible, _apply)
