"""Drift-Net Boat (minor improvement, A51; Artifex Expansion; cost 1 wood + 1 reed).

Card text: "Each time you use the "Fishing" accumulation space, you get an
additional 2 food." Printed 1 VP.

Category 3 (action-space hook, automatic income) on the atomic Fishing space.
Mirrors Canoe (A78), differing only in cost and the granted good (+2 food).
The "each time you use" wording carries no "immediately after" qualifier, so per
the trigger-timing ruling it fires in the before_action_space phase. It is a
downside-free pure-goods grant, so it is a register_auto (mandatory, choice-free),
never surfaced as an optional FireTrigger. fishing is an atomic accumulation space,
so register_action_space_hook is required to host a frame for the before-phase to
fire on. See CARD_IMPLEMENTATION_PLAN.md Category 3.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "drift_net_boat"
SPACES = frozenset({"fishing"})


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in SPACES


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(food=2))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1, reed=1)), vps=1)
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
