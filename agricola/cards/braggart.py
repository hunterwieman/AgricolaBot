"""Braggart (occupation, A133; Base Revised; players 3+).

Card text (verbatim): "During the scoring, you get 2/3/4/5/7/9 bonus points for
having at least 5/6/7/8/9/10 improvements in front of you."

A pure end-game scoring term — no on-play effect (played via Lessons; its on-play
is a no-op). "Improvements in front of you" are the player's IMPROVEMENTS: the
minor improvements in their tableau PLUS the major improvements they own. (In
Agricola "improvements" = majors + minors; occupations are NOT improvements, so
they are excluded from the count — contrast "cards in front of you", which would
include occupations.) Majors are not on `PlayerState`; ownership lives on
`state.board.major_improvement_owners`, so the count sums the minors frozenset with
the owned-major count (the `churchyard.py` idiom).

The tiered bonus is a step function over the improvement count `n`:
  n >= 10 -> 9,  >= 9 -> 7,  >= 8 -> 5,  >= 7 -> 4,  >= 6 -> 3,  >= 5 -> 2,  else 0.
The bands are "AT LEAST" thresholds, so a count of 11+ stays at the top band (9).

Category 1 (end-game scoring). No stored state — derived from the tableau at
scoring time. Card-only registries default empty, so the Family game is
byte-identical and the C++ differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "braggart"

# (threshold, bonus) bands, highest first — the first satisfied band wins.
_BANDS: tuple[tuple[int, int], ...] = (
    (10, 9),
    (9, 7),
    (8, 5),
    (7, 4),
    (6, 3),
    (5, 2),
)


def _improvement_count(state: GameState, idx: int) -> int:
    """Improvements in front of player `idx`: minors in the tableau + owned majors.

    Majors live on `state.board.major_improvement_owners` (an owner per major idx),
    not on `PlayerState`, so they are counted from the board."""
    p = state.players[idx]
    n_minor = len(p.minor_improvements)
    n_major = sum(1 for o in state.board.major_improvement_owners if o == idx)
    return n_minor + n_major


def _score(state: GameState, idx: int) -> int:
    n = _improvement_count(state, idx)
    for threshold, bonus in _BANDS:
        if n >= threshold:
            return bonus
    return 0


# Pure scoring occupation: played via Lessons, but its on-play effect is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)
register_scoring(CARD_ID, _score)
