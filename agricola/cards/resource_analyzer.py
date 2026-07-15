"""Resource Analyzer (occupation, C157; Corbarius Expansion; players 4+).

Card text (verbatim): "Before the start of each round, if you have more building
resources than all other players of at least two types, you get 1 food."
No cost / prerequisite / passing / printed VPs.

TIMING — "Before the start of each round" → the preparation ladder's
``before_round`` window (preparation.py position 0, user ruling 2026-07-14:
the ladder's FIRST rung, before the reveal, round-space collection, and
``start_of_round``). Small Animal Breeder is the exemplar of this rung. Firing
pre-collection is harmless here — the comparison reads current holdings, and any
round-space goods have not yet landed.

FIRING KIND — "you get 1 food" is mandatory and choice-free → an automatic
effect (``register_auto``), re-checked each round.

THE CONDITION — "more building resources than all other players of at least two
types". Building resources are wood, clay, reed, and stone (food/grain/vegetable
are not building resources). For at least two of those four types the owner must
hold STRICTLY more than every other player; in the 2-player engine "all other
players" is the single opponent, so the test counts the types among
{wood, clay, reed, stone} where ``owner > opponent`` and fires when that count is
>= 2.

Card-game only (ownership-gated registry): the Family game is byte-identical and
the C++ gates are untouched. Played via Lessons; on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "resource_analyzer"
_BUILDING = ("wood", "clay", "reed", "stone")


def _types_ahead(state: GameState, idx: int) -> int:
    """Count building-resource types where the owner strictly leads the (single)
    opponent."""
    mine = state.players[idx].resources
    theirs = state.players[1 - idx].resources
    return sum(1 for t in _BUILDING if getattr(mine, t) > getattr(theirs, t))


def _eligible(state: GameState, idx: int) -> bool:
    return _types_ahead(state, idx) >= 2


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_round", CARD_ID, _eligible, _apply)
