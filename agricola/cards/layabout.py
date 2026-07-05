"""Layabout (occupation, C108; Consul Dirigens Expansion; players 1+).

Card text (verbatim): "When you play this card, you must skip the next
harvest. (You also do not have to feed your family that harvest.)"

"You must" — the skip is automatic at play: `_on_play` latches the NEXT
harvest's round (the first harvest round at or after the play round — a play
always precedes its own round's harvest, the Bed-in-the-Grain-Field
convention) in card_state; harvest rounds are unique, so the latch is inert
once that round passes.

**The cancellation is TOTAL — user ruling 14 (2026-07-05, superseding the
earlier contested ruling 2 and following the official online implementation,
which the user dislikes but rules to match):** every harvest-relative instant
is suppressed for the skipping player — immediately-before-harvest through
after-harvest, the outer boundaries included ("after each harvest" cards do
NOT fire for the skipper) — plus the feeding frames (no payment, no begging;
the printed parenthetical) and the breeding frames (no newborns). The
skipper's fields keep their crops; the opponent's harvest is untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_skip
from agricola.cards.specs import register_occupation
from agricola.constants import HARVEST_ROUNDS
from agricola.replace import fast_replace
from agricola.state import GameState

CARD_ID = "layabout"
_SKIP_ROUND_KEY = f"{CARD_ID}_skip_round"


def _on_play(state: GameState, idx: int) -> GameState:
    """Latch the next harvest (mandatory — "you must")."""
    target = min(r for r in HARVEST_ROUNDS if r >= state.round_number)
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(_SKIP_ROUND_KEY, target))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _skipped(state: GameState, idx: int, window_id: str) -> bool:
    # Ruling 14: TOTAL — every window id (the feeding/breeding sentinels
    # included) is suppressed during the latched round's harvest.
    return (state.players[idx].card_state.get(_SKIP_ROUND_KEY)
            == state.round_number)


register_occupation(CARD_ID, _on_play)
register_harvest_skip(CARD_ID, _skipped)
