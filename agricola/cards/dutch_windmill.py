"""Dutch Windmill (minor improvement, A63; Base Revised; cost 2 wood + 2 stone,
2 VP).

Card text: "Each time you take a 'Bake Bread' action in a round immediately
following a harvest, you get 3 additional food."

Category 5 (bake-bread hook, automatic income). A mandatory, choice-free effect →
an automatic effect (register_auto) on `after_bake_bread`. The harvest rounds are
{4, 7, 9, 11, 13, 14}, so the rounds immediately following a harvest are
{5, 8, 10, 12, 14} (round 13's harvest is followed by round 14; round 14's final
harvest has no following round). Stateless: the only gate is `round_number`. +3
food. See CARD_IMPLEMENTATION_PLAN.md Category 5.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "dutch_windmill"

# Rounds immediately following a harvest round ({4,7,9,11,13,14} + 1, capped at 14).
_POST_HARVEST_ROUNDS = frozenset({5, 8, 10, 12, 14})


def _eligible(state: GameState, idx: int) -> bool:
    return state.round_number in _POST_HARVEST_ROUNDS


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(food=3))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2, stone=2)), vps=2)
register_auto("after_bake_bread", CARD_ID, _eligible, _apply)
