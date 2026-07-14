"""Civic Facade (minor improvement, D48; Dulcinaria Expansion; players -).

Card text: "Before the start of each round, if you have more occupations than
improvements in your hand, you get 1 food."

Cost 1 clay; prerequisite 3 rooms (a HAVE-check at play time).

"BEFORE the start of each round" → the preparation ladder's `before_round`
window (user ruling 2026-07-14): the ladder's FIRST rung, before the reveal,
before round-space collection, before `start_of_round`. The eligibility reads
only the player's hand counts, which nothing earlier in the round boundary
touches, so the rung placement is about fidelity, not observability (contrast
Small Animal Breeder, whose food read makes the pre-collection instant
observable). `round_number` still names the just-completed round at this window;
the food grant is round-independent, so no offset is needed.

The income is MANDATORY and choice-free → an automatic effect (`register_auto`),
fired mechanically by the walk for the owner.

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
from agricola.cards.triggers import register_auto
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
# "Before the start of each round" — the before_round window (user ruling
# 2026-07-14), the ladder's first rung, distinct from start_of_round.
register_auto("before_round", CARD_ID, _eligible, _apply)
