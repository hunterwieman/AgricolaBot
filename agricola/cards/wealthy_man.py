"""Wealthy Man (occupation, D153; Dulcinaria Expansion; players 4+).

Card text (verbatim): "At the start of each of the 1st/2nd/3rd/4th/5th/6th harvest,
if you have at least 1/2/3/4/5/6 grain fields, you get 1 bonus point."

At the start of harvest N (N = 1..6, the six harvests falling on rounds
4/7/9/11/13/14), if the owner has at least N grain fields they bank 1 bonus point.
The threshold rises with the harvest ordinal, so a point is earned each harvest only
while the owner keeps pace (1 grain field by the 1st harvest, 2 by the 2nd, ...).
Points accumulate across the game and are read at scoring.

- **Timing — `start_of_harvest`.** "At the start of each ... harvest" is the harvest
  ladder's `start_of_harvest` window (#2, opening the whole harvest before the field
  phase). The grant is MANDATORY and choice-free -> an automatic effect
  (`register_auto`), hosted by the window hook (`register_harvest_window_hook`) — the
  `dentist.py` feeding-auto / `social_benefits.py` shape.

- **The ordinal.** Which harvest (1..6) is derived from `round_number`: the sorted
  harvest rounds give ordinal = index + 1 (round 4 -> 1st, round 14 -> 6th). The
  window only fires during a real harvest (round in `HARVEST_ROUNDS`); a defensive
  guard returns not-eligible for any other round.

- **"Grain fields"** are FIELD cells currently sown with grain (`grain > 0`).

- **Banking, round-keyed.** The auto accumulates into a `(last_scored_round,
  banked_points)` CardStore tuple, guarded by the harvest round so a re-entry never
  double-counts (the window fires once per harvest; the guard is defensive).

The CardStore tuple is empty in the Family game -> byte-identical, C++ gates
untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.constants import HARVEST_ROUNDS, CellType
from agricola.replace import fast_replace
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "wealthy_man"
WINDOW_ID = "start_of_harvest"

# round_number -> harvest ordinal (1..6): round 4 is the 1st harvest, 14 the 6th.
_HARVEST_ORDINAL: dict[int, int] = {
    r: i + 1 for i, r in enumerate(sorted(HARVEST_ROUNDS))
}


def _entry(state: GameState, idx: int) -> tuple[int, int]:
    """This owner's (last_scored_round, banked_points), default (0, 0)."""
    return state.players[idx].card_state.get(CARD_ID, (0, 0))


def _grain_fields(state: GameState, idx: int) -> int:
    """FIELD cells currently sown with grain (grain > 0)."""
    grid = state.players[idx].farmyard.grid
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD and grid[r][c].grain > 0
    )


def _eligible(state: GameState, idx: int) -> bool:
    ordinal = _HARVEST_ORDINAL.get(state.round_number)
    if ordinal is None:                       # not a harvest round (defensive)
        return False
    if _entry(state, idx)[0] == state.round_number:
        return False                          # already banked this harvest
    return _grain_fields(state, idx) >= ordinal


def _apply(state: GameState, idx: int) -> GameState:
    _last, banked = _entry(state, idx)
    p = state.players[idx]
    p = fast_replace(
        p, card_state=p.card_state.set(CARD_ID, (state.round_number, banked + 1))
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    return _entry(state, idx)[1]


# Pure recurring occupation: played via Lessons, on-play is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)
register_auto(WINDOW_ID, CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, WINDOW_ID)
register_scoring(CARD_ID, _score)
