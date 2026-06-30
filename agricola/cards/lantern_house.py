"""Lantern House (minor improvement, C35; Consul Dirigens; players -).

Card text: "During scoring, you get 1 negative point for each card left in your
hand. You cannot discard cards from your hand unplayed. If you already have, you
cannot play this card."

Cost 1 Wood. Prerequisite: "No Occupations" (you may not have played any
occupation). Printed 7 VP (the yellow circle), kept when this minor is in the
tableau.

Category 1 (end-game scoring). No stored state — the penalty is derived at
scoring time from the player's own hand size.

Three precise points:
  (1) The 7 printed victory points come through `MinorSpec.vps` (scoring.py's
      kept-minor vps loop), NOT through the scoring term. Putting +7 in `_score`
      would double-count it against that loop.
  (2) The scoring term is NEGATIVE: one point of penalty per card still in the
      player's hand at scoring — `-(len(hand_occupations) + len(hand_minors))`.
      It counts the DECIDER's OWN hand only, never the opponent's. (Lantern
      House itself is in `minor_improvements`, not the hand, once played, so it
      never counts itself.)
  (3) The two remaining text clauses are inert here:
      - "You cannot discard cards from your hand unplayed" — this engine never
        discards hand cards unplayed; there is no such action surface.
      - "If you already have, you cannot play this card" — cards are unique
        within a pool, so a duplicate Lantern House can never be drawn or
        played; no guard is needed.

The `register_scoring` term is gated by card ownership in `scoring.py`
(`_owns`), so `_score` only ever runs for a player who actually has Lantern
House in their tableau; no ownership check is needed inside `_score`.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "lantern_house"


def _score(state: GameState, idx: int) -> int:
    ps = state.players[idx]
    hand_size = len(ps.hand_occupations) + len(ps.hand_minors)
    return -hand_size


# Cost 1 wood; prereq "No Occupations" => at most 0 occupations played;
# printed 7 VP via the kept-minor vps loop (do NOT also add it in _score).
register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1)),
    max_occupations=0,
    vps=7,
)
register_scoring(CARD_ID, _score)
