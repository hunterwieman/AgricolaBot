"""Mushroom Collector (occupation, A108; Base Revised; players 1+).

Card text: "Immediately after each time you use a wood accumulation space, you can
exchange 1 wood for 2 food. If you do, place the wood on the accumulation space."

Category 10 (bounded-hook conversion, now-or-never). An OPTIONAL effect → a
FireTrigger (register, not register_auto) on the wood space's `after_action_space`
event. Because it can only convert right after a wood space, it never enters the
at-any-time affordability closure.

The "place the wood on the accumulation space" clause is implemented faithfully:
the spent wood goes back onto the space (Forest) it was used on — NOT to the
general supply — so it is there for whoever uses the space next. (By the after-
phase, Proceed has already swept the space, so this leaves 1 wood on it.) Played
via Lessons; on-play is a no-op. See CARD_IMPLEMENTATION_PLAN.md Category 10.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_action_space_hook
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space, with_space

CARD_ID = "mushroom_collector"
WOOD_SPACES = frozenset({"forest"})   # 2-player: Forest is the only wood accumulation space

_WOOD_IN = 1
_FOOD_OUT = 2


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # at most once per space-use
        return False
    top = state.pending_stack[-1]
    return top.space_id in WOOD_SPACES and state.players[idx].resources.wood >= _WOOD_IN


def _apply(state: GameState, idx: int) -> GameState:
    space_id = state.pending_stack[-1].space_id
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=-_WOOD_IN, food=_FOOD_OUT))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    # Place the exchanged wood back on the accumulation space (not general supply).
    sp = get_space(state.board, space_id)
    sp = fast_replace(sp, accumulated=sp.accumulated + Resources(wood=_WOOD_IN))
    return fast_replace(state, board=with_space(state.board, space_id, sp))


register_occupation(CARD_ID, lambda state, idx: state)
register("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, WOOD_SPACES)
