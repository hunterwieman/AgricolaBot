"""Canoe (minor improvement, A78; Base Revised; cost 2 wood, prereq 1 occupation).

Card text: "Each time you use the 'Fishing' accumulation space, you get an
additional 1 food and 1 reed." Printed 1 VP.

Category 3 (action-space hook, automatic income) on the atomic Fishing space.
See CARD_IMPLEMENTATION_PLAN.md Category 3.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "canoe"
SPACES = frozenset({"fishing"})


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in SPACES


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(food=1, reed=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2)),
               min_occupations=1, vps=1)
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
