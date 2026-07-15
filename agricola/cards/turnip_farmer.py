"""Turnip Farmer (occupation, A141; Artifex Expansion; players 3+).

Card text (verbatim): "At the start of the returning home phase of each round,
if both the 'Day Laborer' and 'Grain Seeds' action spaces are occupied, you get
1 vegetable."
No cost / prerequisite / passing / printed VPs.

TIMING — "At the start of the returning home phase of each round" → the
round-end ladder's ``start_of_returning_home`` window (round_end.py position 2,
ruling 49, 2026-07-12: "at the start of the/each returning home phase" is the
rung BEFORE the return-home reset). Firing pre-reset is exactly what the card
needs: the still-placed board is the event data, so "both spaces are occupied"
reads the live occupancy that the reset (position 4) would otherwise clear.

FIRING KIND — "you get 1 vegetable" is mandatory and choice-free → an automatic
effect (``register_auto``), fired frame-lessly by the walk for the owner (ruling
21: a mandatory choice-free effect is an AUTO, never a forced offer). The
condition is re-checked each round.

"both ... action spaces are occupied" — a space is occupied when it holds a
worker of EITHER player (occupancy is not a per-player property here), so the
test is ``sum(workers) > 0`` on each of ``day_laborer`` and ``grain_seeds`` (both
permanent, always revealed).

Card-game only (ownership-gated registry): the Family game is byte-identical and
the C++ gates are untouched. Played via Lessons; on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "turnip_farmer"
_SPACES = ("day_laborer", "grain_seeds")


def _occupied(state: GameState, space_id: str) -> bool:
    return sum(get_space(state.board, space_id).workers) > 0


def _eligible(state: GameState, idx: int) -> bool:
    return all(_occupied(state, s) for s in _SPACES)


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(veg=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("start_of_returning_home", CARD_ID, _eligible, _apply)
