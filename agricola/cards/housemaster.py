"""Housemaster (occupation, B153; Bubulcus Expansion; players 4+).

Card text: "During scoring, total the point values of your major improvements. The
smallest value counts double. If the total is at least 5/7/9/11, you get 1/2/3/4
bonus points."

A pure scoring term. "Point value" is the PRINTED major VP from
`MAJOR_IMPROVEMENT_POINTS` (Fireplace/Cooking Hearth 1, Clay Oven 2, Stone Oven 3,
Well 4, Joinery/Pottery/Basketmaker 2 — the base values, user ruling 2026-07-15,
NOT including the earned craft-bonus points). Total = sum of the owned majors'
values plus the smallest again (it "counts double"); then >= 11/9/7/5 -> 4/3/2/1
bonus points, else 0. No majors owned -> total 0 -> 0.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.scoring import MAJOR_IMPROVEMENT_POINTS, register_scoring
from agricola.state import GameState

CARD_ID = "housemaster"


def _score(state: GameState, idx: int) -> int:
    owners = state.board.major_improvement_owners
    vals = [MAJOR_IMPROVEMENT_POINTS[i] for i in range(len(owners)) if owners[i] == idx]
    if not vals:
        return 0
    total = sum(vals) + min(vals)          # the smallest value counts double
    for threshold, pts in ((11, 4), (9, 3), (7, 2), (5, 1)):
        if total >= threshold:
            return pts
    return 0


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_scoring(CARD_ID, _score)
