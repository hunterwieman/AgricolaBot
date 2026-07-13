"""Misanthropy (minor improvement, E35; Ephipparius Expansion; cost 1 Wood).

Card text: "During scoring, if you have exactly 4/3/2 people, you get 2/3/5 bonus
points."

Category 1 (end-game scoring term). A "/"-correlated reward (§ card-timing "slashes"):
exactly one of the conditions holds at scoring, mapping people count -> bonus:
4 -> 2, 3 -> 3, 2 -> 5. A full family of 5 (or the impossible <2) scores 0. People are
read off `PlayerState.people_total`; at scoring every person is an adult (newborns
became adults in the returning-home phase before the round-14 harvest), so
`people_total` is the family size. No stored state.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "misanthropy"

_POINTS_BY_PEOPLE = {4: 2, 3: 3, 2: 5}


def _score(state: GameState, idx: int) -> int:
    return _POINTS_BY_PEOPLE.get(state.players[idx].people_total, 0)


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register_scoring(CARD_ID, _score)
