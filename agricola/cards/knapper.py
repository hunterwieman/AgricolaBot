"""Knapper (occupation, Artifex A124; players 1+).

Card text (verbatim): "Each time before you use an action space card on round
spaces 5 to 7, you get 1 stone."

"Round spaces 5 to 7" are the stage cards revealed for rounds 5/6/7, i.e. every
space with ``ActionSpaceState.revealed_round in {5, 6, 7}`` (the round whose
preparation revealed it — user decision 2026-07-15). Those are exactly the three
stage-2 cards (``STAGE_CARDS[2]``: Basic Wish for Children, House Redevelopment,
Western Quarry — stage 2 spans rounds 5–7). Using any of them gives 1 stone.

Timing / kind: "Each time BEFORE you use …" — an explicit before window, a flat
mandatory good gain → an automatic effect (``register_auto`` on
``before_action_space``), the Wood Cutter idiom. Eligibility reads the hosted
space's ``revealed_round`` off the top frame's ``space_id``.

``register_action_space_hook({"western_quarry"})``: Western Quarry is the one
ATOMIC space among the three (a building-resource accumulation space), so it must
be explicitly hosted for the before-window to exist. Basic Wish for Children
(self-hosting in the card game) and House Redevelopment (a non-atomic host) already
push a ``before_action_space`` frame, so they need no hook. Played via Lessons; its
on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "knapper"

# The round spaces this fires on ("round spaces 5 to 7").
_ROUNDS = frozenset({5, 6, 7})

# The lone ATOMIC round-5–7 space; the other two (basic_wish_for_children,
# house_redevelopment) are already hosted, so only this one needs a hook.
_HOOK_SPACES = frozenset({"western_quarry"})


def _eligible(state: GameState, idx: int) -> bool:
    space_id = state.pending_stack[-1].space_id
    return get_space(state.board, space_id).revealed_round in _ROUNDS


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(stone=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, _HOOK_SPACES)
