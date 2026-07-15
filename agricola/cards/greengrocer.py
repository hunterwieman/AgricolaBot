"""Greengrocer (occupation, B142; Base Revised; players 3+).

Card text: "Each time you use the 'Grain Seeds' action space, you also get 1 vegetable."

Category 3 (action-space hook, automatic income) — the Corn Scoop shape in vegetable
instead of grain. A mandatory, choice-free effect → an automatic effect
(`register_auto`), not a FireTrigger. "Each time you use" → the BEFORE window of the
space (the trigger-timing ruling); a flat +1 veg does not read the space's own effect,
so before is correct. Grain Seeds is an atomic space, so `register_action_space_hook`
hosts it when this card is owned.

This is a [3+] occupation — not dealt in the 2-player game, but valid to implement and
unit-test now. Played via Lessons; on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "greengrocer"
SPACES = frozenset({"grain_seeds"})


def _eligible(state: GameState, idx: int) -> bool:
    return getattr(state.pending_stack[-1], "space_id", None) in SPACES


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(veg=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
