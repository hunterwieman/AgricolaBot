"""Sculptor (occupation, Dulcinaria D105; players 1+).

Card text: "Each time you use a clay accumulation space, you also get 1 food.
Each time you use a stone accumulation space, you also get 1 grain."

Two mandatory, choice-free effects -> automatic effects (register_auto), both
riding the `before_action_space` window per the standing Trigger-Timing ruling
("each time you use [space]" = before). In the 2-player game the clay
accumulation space is Clay Pit and the stone accumulation spaces are the
Western and Eastern Quarries. All three are atomic spaces, so they must be
hosted via register_action_space_hook or the automatics would never fire.

3-4 player note: larger games add more clay accumulation spaces (e.g. Hollow)
to the board; when the 4-player work lands, this card's space sets must be
extended. Played via Lessons; its on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.constants import CLAY_ACCUMULATION_SPACES, STONE_ACCUMULATION_SPACES
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "sculptor"


def _eligible_clay(state: GameState, idx: int) -> bool:
    # Consulted at a before_action_space host frame; read the space uniformly
    # via the host frame's `space_id`.
    return state.pending_stack[-1].space_id in CLAY_ACCUMULATION_SPACES


def _apply_clay(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(food=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _eligible_stone(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in STONE_ACCUMULATION_SPACES


def _apply_stone(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(grain=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible_clay, _apply_clay)
register_auto("before_action_space", CARD_ID, _eligible_stone, _apply_stone)
register_action_space_hook(CARD_ID, CLAY_ACCUMULATION_SPACES | STONE_ACCUMULATION_SPACES)
