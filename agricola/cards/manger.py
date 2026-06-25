"""Manger (minor improvement, A32; Base Revised; cost 2 wood).

Card text: "During scoring, if your pastures cover at least 6/7/8/10 farmyard
spaces, you get 1/2/3/4 bonus points." No prerequisite, no printed VPs.

Category 1 (end-game scoring) — a pure derived read of pasture coverage (total
cells enclosed by pastures), like Stable Architect. Kept in the tableau when
played; the scoring term fires for the owner. See CARD_IMPLEMENTATION_PLAN.md
Category 1.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "manger"


def _pasture_coverage(state: GameState, idx: int) -> int:
    return sum(len(past.cells) for past in state.players[idx].farmyard.pastures)


def _score(state: GameState, idx: int) -> int:
    cov = _pasture_coverage(state, idx)
    if cov >= 10:
        return 4
    if cov >= 8:
        return 3
    if cov >= 7:
        return 2
    if cov >= 6:
        return 1
    return 0


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2)))
register_scoring(CARD_ID, _score)
