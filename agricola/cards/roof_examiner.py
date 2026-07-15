"""Roof Examiner (occupation, D145; Dulcinaria Expansion; players 3+).

Card text (verbatim): "When you play this card, if you have 1/2/3/4 major
improvements, you immediately get 2/3/4/5 reed."

Category 2 (on-play one-shot). The reed payout is a step function over the number
of major improvements the player owns:
  majors >= 4 -> 5 reed,  >= 3 -> 4 reed,  >= 2 -> 3 reed,  >= 1 -> 2 reed,  else 0.
The bands are read as "AT LEAST" thresholds (owning 5+ majors stays at the top band,
5 reed). Owning zero majors grants nothing. Majors are not on `PlayerState`;
ownership lives on `state.board.major_improvement_owners`, so the count is summed
from the board (the `churchyard.py` idiom). This is a pure goods gain (reed always
fits), so it is a plain `on_play` grant, mirroring `consultant.py`. "Immediately"
names the standard card-play instant.

No stored state. Card-only registries default empty -> Family byte-identical, C++
gates untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "roof_examiner"

# (threshold major count, reed) bands, highest first.
_BANDS: tuple[tuple[int, int], ...] = (
    (4, 5),
    (3, 4),
    (2, 3),
    (1, 2),
)


def _major_count(state: GameState, idx: int) -> int:
    """Number of major improvements owned by player `idx` (from the board)."""
    return sum(1 for o in state.board.major_improvement_owners if o == idx)


def _reed_for(majors: int) -> int:
    for threshold, reed in _BANDS:
        if majors >= threshold:
            return reed
    return 0


def _on_play(state: GameState, idx: int) -> GameState:
    reed = _reed_for(_major_count(state, idx))
    if reed == 0:
        return state
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(reed=reed))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, _on_play)
