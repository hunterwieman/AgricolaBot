"""Wood Carrier (occupation, A117; Artifex Expansion; players 1+).

Card text: "When you play this card, you immediately get 1 wood for each
improvement in front of you."

"Improvements in front of you" = the player's minor improvements PLUS the major
improvements they own; it EXCLUDES occupations (an occupation is not an
improvement, so Wood Carrier never counts itself). Minor improvements live on
``PlayerState.minor_improvements`` (a frozenset); major improvements are owned on
the BOARD (``state.board.major_improvement_owners``, a length-10 tuple of
owner-idx-or-None), the established idiom in ``scoring.py``.

Wood is a building resource, so the grant bypasses any animal-accommodation
concern. If the player has no improvements yet, the grant is a harmless +0.

Category 2 (on-play one-shot). No stored state.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "wood_carrier"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    n_minor = len(p.minor_improvements)
    n_major = sum(1 for owner in state.board.major_improvement_owners if owner == idx)
    count = n_minor + n_major
    p = fast_replace(p, resources=p.resources + Resources(wood=count))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, _on_play)
