"""Storehouse Steward (occupation, A146; Artifex Expansion; players 3+).

Card text: "Each time you take exactly 2/3/4/5 food from a food accumulation space, you
also get 1 stone/reed/clay/wood. (If you take 6 or more food, you do not get a bonus
good)."

Category 3 (action-space hook, automatic income). A mandatory, choice-free bonus good →
an automatic effect (`register_auto`) on the AFTER window: the amount you TAKE from a food
accumulation space is read off the host frame's `taken.food` (the Resources delta stamped
across the take at Proceed). Food lives inside Resources, so `taken.food` covers both a
swept pile (Fishing) and any fixed-food permanent uniformly. The bonus is banded by the
amount taken: 2→stone, 3→reed, 4→clay, 5→wood; nothing at 0/1 or at 6+.

The only food accumulation space in the 2-player card game is Fishing (Meeting Place gives
no goods in the card game — user ruling 2026-07-02 — so it is not a food accumulation space
there). Fishing is atomic, so `register_action_space_hook` hosts it when this card is
owned.

This is a [3+] occupation — not dealt in the 2-player game, but valid to implement and
unit-test now. Played via Lessons; on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.constants import FOOD_ACCUMULATION_SPACES
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "storehouse_steward"

# food taken -> the bonus good ("1 stone/reed/clay/wood" for "2/3/4/5").
_BONUS = {
    2: Resources(stone=1),
    3: Resources(reed=1),
    4: Resources(clay=1),
    5: Resources(wood=1),
}


def _food_taken(state: GameState) -> int:
    """The food the acting player took from the hosted food space — the host frame's
    `taken.food` (the Resources delta stamped across the take at Proceed)."""
    return state.pending_stack[-1].taken.food


def _eligible(state: GameState, idx: int) -> bool:
    return (getattr(state.pending_stack[-1], "space_id", None) in FOOD_ACCUMULATION_SPACES
            and _food_taken(state) in _BONUS)


def _apply(state: GameState, idx: int) -> GameState:
    bonus = _BONUS[_food_taken(state)]
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + bonus)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, FOOD_ACCUMULATION_SPACES)
