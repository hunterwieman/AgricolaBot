"""Soldier (occupation, C133; Corbarius Expansion; players 3+).

Card text: "During scoring, you get 1 bonus point for each stone-wood pair in
your supply. You cannot score additional points for the resources scored with
this card."

A pure end-game scoring term — no on-play effect (it is still played via
Lessons; its on-play is a no-op). The bonus is the number of stone-wood PAIRS in
the supply, i.e. ``min(wood, stone)`` — NOT ``wood + stone``.

The "you cannot score additional points for the resources scored with this card"
clause is a no-op in this engine: base scoring (scoring.py) never awards points
for raw wood/stone sitting in the supply (it scores fields, pastures, animals,
rooms, people, majors, craft-building bonuses, and begging penalties). The craft
bonuses (Joinery/Pottery/Basketmaker's) reward resources CONSUMED into built
buildings, not the raw pile, so there is no double-count path for this clause to
suppress.

Category 1 (end-game scoring). No stored state — derived from the supply.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "soldier"


def _score(state: GameState, idx: int) -> int:
    """1 VP per stone-wood pair in supply = min(wood, stone)."""
    r = state.players[idx].resources
    return min(r.wood, r.stone)


# Pure scoring occupation: played via Lessons, but its on-play effect is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)
register_scoring(CARD_ID, _score)
