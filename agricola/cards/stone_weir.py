"""Stone Weir (minor improvement, deck E #55; Ephipparius; cost 1 stone).

Card text: "Each time you use the \"Fishing\" accumulation space, if there are
0/1/2/3 food on the space, you get an additional 4/3/2/1 food from the general
supply." Prerequisite: 2 occupations. Printed 1 VP.

Category 3 (action-space hook, automatic income) on the atomic Fishing space.
The bonus is 4 minus the food currently on Fishing, floored at 0 (0 food -> +4,
1 -> +3, 2 -> +2, 3 -> +1, 4+ -> +0). It is read in the BEFORE window (fired at
the host push): the food sitting on Fishing has NOT been swept yet, so reading
its scalar `accumulated_amount` now gives the printed threshold. Because Fishing
is atomic, the space must be explicitly hosted via `register_action_space_hook`
or no frame is pushed and the auto never fires. Played via an improvement space;
its effect is the hook, so on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space

CARD_ID = "stone_weir"
SPACES = frozenset({"fishing"})


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in SPACES


def _apply(state: GameState, idx: int) -> GameState:
    on_space = get_space(state.board, "fishing").accumulated_amount
    bonus = max(0, 4 - on_space)
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=bonus))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(stone=1)),
               min_occupations=2, vps=1)
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
