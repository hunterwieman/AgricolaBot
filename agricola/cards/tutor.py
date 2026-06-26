"""Tutor (occupation, B99; Base Revised; players 1+).

Card text: "During scoring, you get 1 bonus point for each occupation played after
this one."

Category 1 (end-game scoring), but unlike the pure-derived scoring cards (Stable
Architect, Manger) the score depends on WHEN the card was played: occupations
played AFTER Tutor count, those before do not. The engine tracks only the
aggregate `occupations` frozenset, with no play order — so Tutor snapshots the
occupation count AT PLAY TIME into the per-card CardStore (II.7) and the scoring
term reports how many MORE occupations the player has now.

`on_play` stores `len(occupations)` — the count INCLUDING Tutor itself (it is moved
to the tableau before on_play runs, see _execute_play_occupation). The scoring term
returns `len(occupations) − 1 − snapshot`: the `−1` excludes Tutor itself from the
"current" count, leaving exactly the occupations played strictly after it. Played
via Lessons. See CARD_IMPLEMENTATION_PLAN.md Category 1 / II.7.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.replace import fast_replace
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "tutor"


def _on_play(state: GameState, idx: int) -> GameState:
    # Snapshot the occupation count at play time (Tutor itself is already in the
    # tableau here, so this count includes it). Stored as an int in the CardStore.
    p = state.players[idx]
    snapshot = len(p.occupations)
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, snapshot))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    p = state.players[idx]
    snapshot = p.card_state.get(CARD_ID, len(p.occupations))
    # Occupations played strictly after Tutor: current count, minus Tutor itself,
    # minus everything already in the tableau when Tutor was played. Never negative.
    return max(0, len(p.occupations) - 1 - snapshot)


register_occupation(CARD_ID, _on_play)
register_scoring(CARD_ID, _score)
