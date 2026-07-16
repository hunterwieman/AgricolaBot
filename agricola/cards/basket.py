"""Basket (minor improvement, A56; Base Revised; cost 1 reed).

Card text: "Immediately after each time you use a wood accumulation space, you can
exchange 2 wood for 3 food. If you do, place those 2 wood on the accumulation
space." No prerequisite, no printed VPs.

Category 10 (bounded-hook conversion). Identical shape to Mushroom Collector at a
better rate (2 wood -> 3 food) with the same faithful wood-return-to-space clause.
On-play is a no-op. See CARD_IMPLEMENTATION_PLAN.md Category 10.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_action_space_hook
from agricola.constants import WOOD_ACCUMULATION_SPACES
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space, with_space

CARD_ID = "basket"

_WOOD_IN = 2
_FOOD_OUT = 3


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:
        return False
    top = state.pending_stack[-1]
    return top.space_id in WOOD_ACCUMULATION_SPACES and state.players[idx].resources.wood >= _WOOD_IN


def _apply(state: GameState, idx: int) -> GameState:
    space_id = state.pending_stack[-1].space_id
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=-_WOOD_IN, food=_FOOD_OUT))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    sp = get_space(state.board, space_id)
    sp = fast_replace(sp, accumulated=sp.accumulated + Resources(wood=_WOOD_IN))
    return fast_replace(state, board=with_space(state.board, space_id, sp))


register_minor(CARD_ID, cost=Cost(resources=Resources(reed=1)))
register("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, WOOD_ACCUMULATION_SPACES)
