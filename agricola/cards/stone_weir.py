"""Stone Weir (minor improvement, deck E #55; Ephipparius; cost 1 stone).

Card text: "Each time you use the \"Fishing\" accumulation space, if there are
0/1/2/3 food on the space, you get an additional 4/3/2/1 food from the general
supply." Prerequisite: 2 occupations. Printed 1 VP.

Category 3 (action-space hook, automatic income) on the atomic Fishing space.
The bonus is 4 minus the food that was on Fishing, floored at 0 (0 food -> +4,
1 -> +3, 2 -> +2, 3 -> +1, 4+ -> +0). It is read in the AFTER window (Refactor A):
Fishing sweeps its whole pile into the player at the take, so the food that WAS on
the space equals the host frame's `taken.food` (the Resources delta stamped across
the take), and the inverse bonus reads that. Reading the pre-take scalar in the
after window would be wrong — the space is zeroed by then — which is exactly why
this keys on `taken`, not `accumulated_amount`. Because Fishing is atomic, the space
must be explicitly hosted via `register_action_space_hook` or no frame is pushed and
the auto never fires. Played via an improvement space; its effect is the hook, so
on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "stone_weir"
SPACES = frozenset({"fishing"})


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in SPACES


def _apply(state: GameState, idx: int) -> GameState:
    taken_food = state.pending_stack[-1].taken.food   # fishing swept its whole pile
    bonus = max(0, 4 - taken_food)
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=bonus))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(stone=1)),
               min_occupations=2, vps=1)
register_auto("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
