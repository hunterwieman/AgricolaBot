"""Forest Lake Hut (minor improvement, A42; Artifex Expansion; cost 2 clay).

Card text: "Each time you use the "Fishing"/"Forest" accumulation space, you also
get 1 wood/food." Printed 1 VP.

The paired-slash text is a CROSSED mapping: using Fishing grants +1 WOOD, using
Forest grants +1 FOOD (not Fishing->food / Forest->wood). So the only deviation
from Canoe (A78) is that the granted good depends on which space was used.

Category 3 (action-space hook, automatic income) on the atomic Fishing/Forest
spaces. The "each time you use" wording carries no "immediately after" qualifier,
so per the trigger-timing ruling it fires in the before_action_space phase. The
grant is a downside-free pure-goods income, so it is a register_auto (mandatory,
choice-free), never surfaced as an optional FireTrigger. Both fishing and forest
are atomic accumulation spaces, so register_action_space_hook is required to host
a frame for the before-phase to fire on. See CARD_IMPLEMENTATION_PLAN.md Category 3.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "forest_lake_hut"
SPACES = frozenset({"fishing", "forest"})


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in SPACES


def _apply(state: GameState, idx: int) -> GameState:
    sid = state.pending_stack[-1].space_id
    # Crossed mapping: Fishing -> +1 wood, Forest -> +1 food.
    delta = Resources(wood=1) if sid == "fishing" else Resources(food=1)
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + delta)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(clay=2)), vps=1)
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
