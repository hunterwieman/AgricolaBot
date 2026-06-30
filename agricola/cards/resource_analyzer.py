"""Resource Analyzer (occupation, deck C #157; Corbarius Expansion; players 4+).

Card text: "Before the start of each round, if you have more building resources than
all other players of at least two types, you get 1 food."

Category 7 (start-of-round phase hook). A MANDATORY, choice-free income → an
automatic effect (`register_auto` on the `start_of_round` event), fired at the
`PendingPreparation` push for the owner. The eligibility is re-checked each round,
so the income comes and goes as the resource counts shift.

The four building-resource TYPES are {wood, clay, reed, stone}. The condition is that,
for AT LEAST TWO of those types, the owner holds STRICTLY MORE of that resource than
"all other players" — in the 2-player game, that single opponent. ("more ... than"
is strictly greater, ">"; "at least two types" counts the number of resource TYPES
satisfying the comparison, not a total quantity.) See CARD_IMPLEMENTATION_PLAN.md
Category 7 and tests/test_cards_category7.py (Small-scale Farmer is the template).
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto, register_start_of_round_hook
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "resource_analyzer"

# The four "building resource" types compared against the opponent.
_BUILDING_RESOURCES = ("wood", "clay", "reed", "stone")


def _eligible(state: GameState, idx: int) -> bool:
    me = state.players[idx].resources
    opp = state.players[1 - idx].resources   # 2-player: the single "other player"
    # Count the building-resource types where I hold strictly more than the opponent.
    surplus_types = sum(
        getattr(me, t) > getattr(opp, t) for t in _BUILDING_RESOURCES
    )
    return surplus_types >= 2


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("start_of_round", CARD_ID, _eligible, _apply)
register_start_of_round_hook(CARD_ID)
