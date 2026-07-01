"""Civic Facade (minor improvement, D48; Dulcinaria Expansion; players -).

Card text: "Before the start of each round, if you have more occupations than
improvements in your hand, you get 1 food."

Cost 1 clay; prerequisite 3 rooms (a HAVE-check at play time).

Category 7 (start-of-round phase hook). "Before the start of each round" is exactly
the `start_of_round` hook: by the time these autos fire, `_complete_preparation` has
already incremented `round_number` to the round being entered. The food grant is
round-independent, so firing after the increment is fine.

The income is MANDATORY and choice-free → an automatic effect (`register_auto` on the
`start_of_round` event), fired at the preparation push for the owner.

The eligibility condition is unusual: it compares the player's UNPLAYED HAND — strictly
"more occupations than improvements IN YOUR HAND" — i.e. `len(hand_occupations) >
len(hand_minors)`, NOT the played `occupations` / `minor_improvements` tableaus. The
hand contains exactly occupation + minor-improvement cards (no majors are ever in hand),
so "improvements in your hand" = the minor-improvement hand cards. The inequality is
STRICT (a tie grants nothing). Eligibility is re-evaluated every round, so as the player
plays cards out of hand the grant naturally turns on or off.

See CARD_IMPLEMENTATION_PLAN.md Category 7.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto, register_start_of_round_hook
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, PlayerState

CARD_ID = "civic_facade"


def _num_rooms(p: PlayerState) -> int:
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if p.farmyard.grid[r][c].cell_type == CellType.ROOM
    )


def _prereq(state: GameState, idx: int) -> bool:
    # "3 Rooms" is a HAVE-check at play time.
    return _num_rooms(state.players[idx]) >= 3


def _eligible(state: GameState, idx: int) -> bool:
    # STRICT >: strictly more occupations than improvements among the UNPLAYED hand cards.
    p = state.players[idx]
    return len(p.hand_occupations) > len(p.hand_minors)


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(resources=Resources(clay=1)), prereq=_prereq)
register_auto("start_of_round", CARD_ID, _eligible, _apply)
register_start_of_round_hook(CARD_ID)
