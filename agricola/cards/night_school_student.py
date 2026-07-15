"""Night-School Student (occupation, A152; Artifex Expansion; players 4+).

Card text (verbatim): "Each returning home phase in which no player returns a
person from a 'Lessons' action space, you can play an occupation for an
occupation cost of 1 food."
No cost / prerequisite / passing / printed VPs.

TIMING — "Each returning home phase in which ..." anchors on the returning-home
phase → the round-end ladder's ``returning_home`` window (round_end.py position
3, ruling 49, 2026-07-12; the same rung Silage rides). That rung fires PRE-reset,
which is exactly what the condition needs: "no player returns a person from a
Lessons space" is read off the STILL-PLACED board — the Lessons space holds no
worker of either player (``sum(workers) == 0``) — which the reset (position 4)
would otherwise clear. The 2-player board has one Lessons space (this is a 4+
card); "no player returns a person from a Lessons space" is that space empty.

FIRING KIND — "you can play an occupation" is OPTIONAL → an optional trigger
(``register``, not ``register_auto``); not firing is the host's Proceed. A single
route (play an occupation), so no play-variant is needed — firing pushes the
existing ``PendingPlayOccupation`` with a flat 1-food cost (Scholar's occupation
route: ``cost=Resources(food=1)``, the play frame's executor debits it, raising
the food by liquidation if short). Once per returning-home phase via the window
frame's ``triggers_resolved``.

NEVER A DEAD HOST — eligibility also requires a playable hand occupation
(``playable_occupations``) and the 1-food affordable (``_payable_occupation``,
liquidation-aware and Paper-Maker-aware, exactly Scholar's gate), so the trigger
is only offered when a real occupation play can follow.

Card-game only (ownership-gated registry): the Family game is byte-identical and
the C++ gates are untouched. Played via Lessons; on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register
from agricola.legality import _payable_occupation, playable_occupations
from agricola.pending import PendingPlayOccupation, push
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "night_school_student"
_OCC_COST = Resources(food=1)   # the flat "occupation cost of 1 food"


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per phase
        return False
    # "no player returns a person from a Lessons space" — the space is empty.
    if sum(get_space(state.board, "lessons").workers) != 0:
        return False
    # Never a dead host: a playable occupation and the 1 food must both be there.
    return (bool(playable_occupations(state, idx))
            and _payable_occupation(state, idx, state.players[idx], _OCC_COST))


def _apply(state: GameState, idx: int) -> GameState:
    return push(state, PendingPlayOccupation(
        player_idx=idx, initiated_by_id="card:night_school_student",
        cost=_OCC_COST))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("returning_home", CARD_ID, _eligible, _apply)
