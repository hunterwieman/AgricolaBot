"""Bohemian (occupation, A157; Artifex Expansion; players 4+).

Card text (verbatim): "At the start of each returning home phase, if at least
one 'Lessons' action space is unoccupied, you get 1 food."
No cost / prerequisite / passing / printed VPs.

TIMING — "At the start of each returning home phase" → the round-end ladder's
``start_of_returning_home`` window (round_end.py position 2, ruling 49,
2026-07-12), the rung BEFORE the return-home reset. Firing pre-reset lets the
condition read the live board occupancy that the reset (position 4) would clear.

FIRING KIND — "you get 1 food" is mandatory and choice-free → an automatic
effect (``register_auto``), re-checked each round.

"at least one 'Lessons' action space is unoccupied" — the 2-player board has a
single Lessons space (the 3+/4+ boards add more; this occupation is a 4+ card),
so "at least one unoccupied" is satisfied exactly when that space holds no
worker of either player: ``sum(workers) == 0``. (Lessons is a permanent space,
always revealed; in the 2-player game it is only usable under the card rules.)

Card-game only (ownership-gated registry): the Family game is byte-identical and
the C++ gates are untouched. Played via Lessons; on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "bohemian"


def _eligible(state: GameState, idx: int) -> bool:
    # "at least one Lessons space unoccupied" — the single 2-player Lessons space
    # holds no worker of either player.
    return sum(get_space(state.board, "lessons").workers) == 0


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("start_of_returning_home", CARD_ID, _eligible, _apply)
