"""Fodder Chamber (minor improvement, D35; Dulcinaria Expansion; cost 3 stone + 3 grain).

Card text: "During scoring in a game with 1/2/3/4+ players, you get 1 bonus point
for every 7th/5th/4th/3rd animal on your farm." Printed 2 victory points.

This engine is the 2-player game, so the threshold is the *5th-animal* tier: the
bonus is `floor(total_animals / 5)` — one bonus point per complete group of 5
animals on the farm.

Category 1 (end-game scoring) — a pure derived read of the player's farm-total
animal count, like Manger / Stable Architect. Kept in the tableau when played;
the scoring term fires for the owner. The printed 2 VPs ride on the
`register_minor(vps=2)` registration and are summed separately in `score()`, so
`_score` must return ONLY the per-5-animals bonus (returning it again here would
double-count).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "fodder_chamber"


def _total_animals(state: GameState, idx: int) -> int:
    """All animals on the player's farm — `PlayerState.animals` is the canonical
    farm-total (collected + accommodated across pastures, stables, and the
    house), exactly what `score()` reads for animal scoring."""
    a = state.players[idx].animals
    return a.sheep + a.boar + a.cattle


def _score(state: GameState, idx: int) -> int:
    # 2-player game: 1 bonus point for every 5th animal on the farm.
    return _total_animals(state, idx) // 5


register_minor(CARD_ID, cost=Cost(resources=Resources(stone=3, grain=3)), vps=2)
register_scoring(CARD_ID, _score)
