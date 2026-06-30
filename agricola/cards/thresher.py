"""Thresher (occupation, C112; Consul Dirigens Expansion; players 1+).

Card text: "Immediately before each time you use the 'Grain Utilization',
'Farmland', or 'Cultivation' action space, you can buy 1 grain for 1 food."

Clarification: "This effect happens before using the space, and must happen
before effects such as Flail C026."

Category 4 (action-space hook). The buy is the player's choice → an OPTIONAL
trigger (register, not register_auto) whose apply_fn swaps 1 food for 1 grain
(the potter_ceramics goods-swap idiom). Fires on the BEFORE-phase of the three
named spaces: "each time you use [space]" fires before the space's own effect
(the Trigger-Timing ruling), and the card's own clarification restates this —
the grain bought here is therefore available to the subsequent Sow/space effect
(and resolves before a later Flail). Eligibility gates on food >= 1, so it never
offers a dead-end buy the player cannot pay; `triggers_resolved` scoping makes it
re-eligible on each new space use and limits it to at most once per use.

All three spaces (Grain Utilization, Farmland, Cultivation) are non-atomic and so
always hosted — no register_action_space_hook is needed. Played via Lessons; its
on-play is a no-op. See CARD_IMPLEMENTATION_PLAN.md Category 4 and the Threshing
Board / Assistant Tiller before_action_space templates.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "thresher"
SPACES = frozenset({"grain_utilization", "farmland", "cultivation"})


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    return (CARD_ID not in triggers_resolved
            and state.pending_stack[-1].space_id in SPACES
            and state.players[idx].resources.food >= 1)


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    new_player = fast_replace(p, resources=p.resources + Resources(food=-1, grain=1))
    new_players = tuple(
        new_player if i == idx else state.players[i]
        for i in range(len(state.players))
    )
    return fast_replace(state, players=new_players)


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("before_action_space", CARD_ID, _eligible, _apply)
