"""Throwing Axe (minor improvement, A52; Artifex Expansion).

Card text: "Each time you use a wood accumulation space while there is at least
1 wild boar on the 'Pig Market' accumulation space, you also get 2 food."
Cost: 1 Wood. Prerequisite: Play in Round 7 or Later. VPs: none. Not passing.

Category 3 (action-space hook, automatic income). "A wood accumulation space"
resolves to exactly ONE space — the `forest` space (the only entry in
BUILDING_ACCUMULATION_RATES whose accumulated resource is wood, Resources(wood=3));
it does NOT fire on clay_pit / the quarries / reed_bank. "Each time you use [space]"
fires in the BEFORE phase per the Trigger-Timing ruling (matching Canoe / Herring
Pot), so the +2 food is a `before_action_space` automatic effect. `forest` is an
ATOMIC space, so it must be hosted (register_action_space_hook) for a frame to exist.

The condition reads the BOAR sitting on the Pig Market accumulation space —
get_space(board, "pig_market").accumulated_amount (an int, since pig_market is a
food/animal accumulation space) >= 1 — NOT the player's owned boar. The +2 food is
mandatory, choiceless, and has no downside, so it is a register_auto effect.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.constants import WOOD_ACCUMULATION_SPACES
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space

CARD_ID = "throwing_axe"


def _prereq(state: GameState, idx: int) -> bool:
    return state.round_number >= 7


def _eligible(state: GameState, idx: int) -> bool:
    return (state.pending_stack[-1].space_id in WOOD_ACCUMULATION_SPACES
            and get_space(state.board, "pig_market").accumulated_amount >= 1)


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(food=2))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), prereq=_prereq, vps=0)
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, WOOD_ACCUMULATION_SPACES)
