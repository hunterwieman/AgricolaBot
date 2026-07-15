"""Hill Cultivator (occupation, E121; Ephipparius Expansion; 1+ players).

Card text: "Each time you use the \"Grain Seeds\" or \"Vegetable Seeds\" action
space, you also get 2 or 3 clay, respectively."

Category 3 (action-space hook, automatic income). "Each time you use [space]"
fires in the BEFORE window per the standing Trigger-Timing ruling (a flat,
outcome-independent reward — matching Corn Scoop / Throwing Axe), so the clay
is a `before_action_space` automatic effect. "Respectively" pairs the slash
lists in order: Grain Seeds -> 2 clay, Vegetable Seeds -> 3 clay. The grant is
mandatory, choiceless, and has no downside, so it is a register_auto effect
(no trigger). Both spaces are ATOMIC, so they must be hosted
(register_action_space_hook) for a frame to exist. No on-play effect.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "hill_cultivator"
# "respectively": Grain Seeds -> 2 clay; Vegetable Seeds -> 3 clay.
CLAY_BY_SPACE = {"grain_seeds": 2, "vegetable_seeds": 3}
SPACES = frozenset(CLAY_BY_SPACE)


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in SPACES


def _apply(state: GameState, idx: int) -> GameState:
    clay = CLAY_BY_SPACE[state.pending_stack[-1].space_id]
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(clay=clay))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
