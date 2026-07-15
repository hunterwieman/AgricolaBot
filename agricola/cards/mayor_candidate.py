"""Mayor Candidate (occupation, E124; Ephipparius Expansion; players 1+).

Card text: "You immediately get 2 wood and 2 stone. During scoring, you get 1
negative point for each wood and each stone in your supply. You can no longer
discard wood or stone."

Two live effects plus one inert clause:

  1. ON-PLAY (Category 2) — immediately gain 2 wood and 2 stone (the Consultant
     on-play-goods shape).

  2. END-GAME SCORING — a NEGATIVE term of one point per wood AND per stone still
     in the player's supply at scoring: `-(wood + stone)`. Registered via
     `register_scoring` (which ships signed terms — Lantern House's hand penalty
     is the negative-term precedent). Reads the DECIDER's OWN supply only;
     ownership-gated by `scoring.py` (`_owns`), so `_score` runs only for a Mayor
     Candidate owner.

  3. INERT — "You can no longer discard wood or stone." This engine has no action
     that discards wood or stone at will (a player cannot voluntarily dump goods),
     so the clause — whose purpose is to stop dumping wood/stone before scoring to
     dodge the penalty — has nothing to forbid. It is inert exactly as Lantern
     House's "you cannot discard cards from your hand unplayed" clause is inert. No
     discard action exists to gate.

No stored state — the penalty is derived from the supply at scoring time.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "mayor_candidate"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=2, stone=2))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    r = state.players[idx].resources
    return -(r.wood + r.stone)   # 1 negative point per wood AND per stone in supply


register_occupation(CARD_ID, _on_play)
register_scoring(CARD_ID, _score)
