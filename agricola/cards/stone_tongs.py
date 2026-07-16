"""Stone Tongs (minor improvement, A80; Base Revised; cost 1 wood).

Card text: "Each time you use a stone accumulation space, you get 1 additional
stone." In the 2-player game the stone accumulation spaces are Western Quarry
and Eastern Quarry (both atomic). No prerequisite, no printed VPs.

Category 3 (action-space hook, automatic income). On-play is a no-op.
See CARD_IMPLEMENTATION_PLAN.md Category 3.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.constants import STONE_ACCUMULATION_SPACES
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "stone_tongs"


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in STONE_ACCUMULATION_SPACES


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(stone=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, STONE_ACCUMULATION_SPACES)
