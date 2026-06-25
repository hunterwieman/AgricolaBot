"""Geologist (occupation, B121; Base Revised; players 1+).

Card text: "Each time you use the 'Forest' or 'Reed Bank' accumulation space, you
also get 1 clay. In games with 3 or more players, this also applies to the
'Clay Pit'." This engine is 2-player, so the Clay Pit clause never applies.

Category 3 (action-space hook, automatic income) — fires on two atomic spaces,
exercising the multi-space hook. Played via Lessons; on-play is a no-op.
See CARD_IMPLEMENTATION_PLAN.md Category 3.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "geologist"

# 2-player: Forest + Reed Bank (the Clay Pit clause is 3+ players only).
GEOLOGIST_SPACES = frozenset({"forest", "reed_bank"})


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in GEOLOGIST_SPACES


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(clay=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, GEOLOGIST_SPACES)
