"""Butler (occupation, C100; Corbarius Expansion; players 1+).

Card text: "If you play this card in round 11 or before, during scoring, you get 4
bonus points if you then have more rooms than people."

Category 1 (end-game scoring) with a play-TIME gate: the 4-point bonus is only
available at all if Butler was played in round 11 or earlier. That round number is a
play-time quantity — by the time scoring runs the round is 14 (terminal), so the gate
cannot be reconstructed during `_score`. So `on_play` snapshots whether the play round
was ≤ 11 into the per-card CardStore (II.7), and the scoring term reads it back.

The bonus itself ("more rooms than people") is a derived end-game read, evaluated at
scoring time: strictly MORE rooms than people (a strict `>`), where "people" is the
player's total people in play (`people_total`, home + placed), and "rooms" counts the
ROOM cells in the farmyard grid. The 4 points are all-or-nothing, not per-room. A never-
snapshotted state (the gate flag missing) scores 0 rather than awarding the bonus.
Played via Lessons; printed VPs are 0 (the 4 points are conditional). See
CARD_IMPLEMENTATION_PLAN.md Category 1 / II.7.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.scoring import register_scoring
from agricola.state import GameState, PlayerState

CARD_ID = "butler"


def _num_rooms(p: PlayerState) -> int:
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if p.farmyard.grid[r][c].cell_type == CellType.ROOM
    )


def _on_play(state: GameState, idx: int) -> GameState:
    # Snapshot the play-time gate: 1 if played in round 11 or before, else 0. This is
    # the only moment the play round is visible (scoring sees round 14), so it must be
    # captured now and read back at scoring.
    p = state.players[idx]
    gated_in = 1 if state.round_number <= 11 else 0
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, gated_in))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    p = state.players[idx]
    # Default 0 means "not gated in" — a state that never ran on_play scores nothing.
    if not p.card_state.get(CARD_ID, 0):
        return 0
    # "more rooms than people" — strict >, people = people_total (home + placed).
    return 4 if _num_rooms(p) > p.people_total else 0


register_occupation(CARD_ID, _on_play)
register_scoring(CARD_ID, _score)
