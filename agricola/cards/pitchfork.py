"""Pitchfork (minor improvement, B62; Base Revised; cost 1 wood).

Card text: "Each time you use the 'Grain Seeds' action space, if the 'Farmland'
action space is occupied you also get 3 food." No prerequisite, no printed VPs.

Category 3 (action-space hook, automatic income) with a CONDITIONAL eligibility
clause (Farmland occupied). The payout is not optional — it is an automatic
effect gated by the condition, not a FireTrigger. On-play is a no-op.
See CARD_IMPLEMENTATION_PLAN.md Category 3.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space

CARD_ID = "pitchfork"
SPACES = frozenset({"grain_seeds"})


def _eligible(state: GameState, idx: int) -> bool:
    if state.pending_stack[-1].space_id not in SPACES:
        return False
    # Conditional: only pays out when the Farmland space is occupied (by anyone).
    return get_space(state.board, "farmland").workers != (0, 0)


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(food=3))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
