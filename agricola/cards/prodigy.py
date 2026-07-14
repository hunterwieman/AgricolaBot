"""Prodigy (occupation, E98; Ephipparius Expansion; players 1+).

Card text: "If this is your 1st occupation, you immediately get 1 bonus point
for each improvement you have. (This will not apply to improvements played
after this card.)"
Category: Points Provider. No printed VPs.

ON-PLAY BANKING (the Big Country idiom): "your 1st occupation" — the executor
moves the card into ``occupations`` BEFORE ``on_play`` runs
(``_execute_play_occupation``), so the gate is ``len(occupations) == 1``
(Prodigy itself and nothing before it; Tutor's counting convention). If it
holds, bank 1 point per improvement owned AT THIS INSTANT — minor improvements
(``p.minor_improvements``) plus majors (owned slots of
``board.major_improvement_owners``, the Education Bonus / Food Basket count) —
in the per-card CardStore; a ``register_scoring`` term reads the bank at
end-game. The parenthetical is exactly why the count is FROZEN at play time
(banked, never re-derived): later improvements must not raise it. User
confirmed 2026-07-14: "improvement" = majors + minors; "1st occupation" =
literally the first occupation played all game, by any route.

Played as anything but the 1st occupation, on_play banks nothing (no CardStore
entry, scores 0). A traveling minor passed away before Prodigy is played was
still an improvement PLAYED by this player, but "each improvement you HAVE"
counts holdings, not history — a passed traveler is not held, and majors/minors
in the tableau are; the read below is exactly current holdings.

Card-game only (ownership-gated registries), so the Family trace and the C++
gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.replace import fast_replace
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "prodigy"


def _improvements_owned(state: GameState, idx: int) -> int:
    """Minors in the tableau + majors owned on the board (the Education Bonus /
    Food Basket improvements count)."""
    p = state.players[idx]
    n_major = sum(1 for o in state.board.major_improvement_owners if o == idx)
    return len(p.minor_improvements) + n_major


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    if len(p.occupations) != 1:      # Prodigy is already in the tableau here
        return state
    banked = _improvements_owned(state, idx)
    if banked == 0:
        return state
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, banked))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    return state.players[idx].card_state.get(CARD_ID, 0)


register_occupation(CARD_ID, _on_play)
register_scoring(CARD_ID, _score)
