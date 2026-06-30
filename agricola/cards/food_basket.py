"""Food Basket (minor improvement, A8; Artifex Expansion; traveling).

Card text: "You immediately get 1 grain and 1 vegetable."

Cost 1 reed. Prerequisite: "2 Occupations and 2 Improvements" — at least two
occupations played AND at least two improvements (minor improvements PLUS owned
major improvements) in front of you. No printed VPs. It is a TRAVELING (passing)
card — after the immediate effect it is passed to the opponent rather than kept.

Category 2 (on-play one-shot) + passing. The on-play effect (+1 grain, +1 veg)
fires whether the card is kept or passed; the prerequisite is a have-check
evaluated at legality time, so the card never counts toward its own prereq.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "food_basket"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(grain=1, veg=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _prereq(state: GameState, idx: int) -> bool:
    """At least 2 improvements: minor improvements PLUS owned majors.

    Majors live on ``state.board.major_improvement_owners`` (length-10 tuple of
    None / owner idx), not on ``PlayerState``. The "2 Occupations" half of the
    prerequisite is the ``min_occupations=2`` bound on the spec, applied
    separately by ``prereq_met``.
    """
    p = state.players[idx]
    n_minor = len(p.minor_improvements)
    n_major = sum(1 for o in state.board.major_improvement_owners if o == idx)
    return (n_minor + n_major) >= 2


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(reed=1)),
    min_occupations=2,
    prereq=_prereq,
    passing_left=True,
    on_play=_on_play,
)
