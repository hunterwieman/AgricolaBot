"""Blighter (occupation, E101; Ephipparius Expansion; players 1+).

Card text: "When you play this card, you get 1 bonus point for each complete
stage left to play. You may not play any more occupations."
Category: Points Provider. No printed VPs.

TWO EFFECTS:

1. **The banked points** — "each complete stage left to play" counts the stages
   entirely after the one the current round belongs to: ``6 −
   stage_of_round(round_number)`` (the Big Country "complete rounds left"
   analogue, user-confirmed 2026-07-14 — played during stage 2 banks 4 points
   for stages 3–6; played in stage 6 banks 0). A play-time quantity, so
   ``on_play`` banks it in the per-card CardStore and a ``register_scoring``
   term reads it back at end-game (the Big Country idiom — a flat ``vps=``
   could not express it).

2. **The occupation lock** — "You may not play any more occupations" registers
   this card as an OCCUPATION-PLAY BLOCKER (``register_occupation_play_blocker``).
   ``legality.playable_occupations`` — the single chokepoint every
   occupation-play route (Lessons, Scholar, card grants) enumerates through —
   returns the empty set for a player who OWNS a blocker, so Lessons stops
   being a legal placement for them and no grant can offer a play. The block
   starts the instant Blighter enters the tableau (its own play already
   resolved) and — being ownership-gated — a Blighter still in hand blocks
   nothing.

Card-game only (ownership-gated registries; the Family game never registers),
so the Family trace and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import (
    register_occupation,
    register_occupation_play_blocker,
)
from agricola.constants import stage_of_round
from agricola.replace import fast_replace
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "blighter"


def _complete_stages_left(state: GameState) -> int:
    """Stages entirely after the current round's stage (the in-progress stage is
    not complete)."""
    return 6 - stage_of_round(state.round_number)


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(
        p, card_state=p.card_state.set(CARD_ID, _complete_stages_left(state)))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    return state.players[idx].card_state.get(CARD_ID, 0)


register_occupation(CARD_ID, _on_play)
register_occupation_play_blocker(CARD_ID)
register_scoring(CARD_ID, _score)
