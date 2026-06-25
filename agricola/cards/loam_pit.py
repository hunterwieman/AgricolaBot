"""Loam Pit (minor improvement, B77; Base Revised; cost 1 food, prereq 3 occupations).

Card text: "Each time you use the 'Day Laborer' action space, you also get 3 clay."
Printed 1 VP.

Category 3 (action-space hook, automatic income) on the atomic Day Laborer space.
A mandatory, choice-free effect → an automatic effect (register_auto). The
3-occupations prerequisite is the dominant occupation-count shape (min_occupations).
See CARD_IMPLEMENTATION_PLAN.md Category 3.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "loam_pit"
SPACES = frozenset({"day_laborer"})


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in SPACES


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(clay=3))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(food=1)),
               min_occupations=3, vps=1)
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
