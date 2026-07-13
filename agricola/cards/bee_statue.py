"""Bee Statue (minor improvement, E40; Ephipparius Expansion; cost 2 clay).

Card text (verbatim): 'Pile (from bottom to top) 1 vegetable, 1 stone, 1 grain,
1 stone, 1 grain on this card. Each time you use the "Day Laborer" action space,
you get the top good.'
No prerequisite, no printed VPs.

A metered goods store consumed TOP-first. The pile, bottom -> top, is
[veg, stone, grain, stone, grain]; the TOP is the last placed, so the goods come
off in the order grain, stone, grain, stone, veg — one per use of the atomic
Day Laborer space, five in all, then the pile is empty. Modeled as a `CardStore`
counter (uses so far, 0..5) indexing a fixed dispense sequence — the Moldboard
Plow uses-left idiom; no per-card goods-STACK state is needed since the sequence
is constant.

Timing — "each time you use [Day Laborer]" fires in the BEFORE window (the
ruling), and the good is flat (counter-determined, not outcome-dependent), so a
`before_action_space` automatic effect (mandatory, pure goods — Corn Scoop's
shape) is correct. Day Laborer is atomic, so `register_action_space_hook` hosts
it. "You" = the owner's use only (an own-action hook).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "bee_statue"
SPACES = frozenset({"day_laborer"})

# The pile consumed top-first: grain, stone, grain, stone, veg.
_SEQUENCE = (
    Resources(grain=1),
    Resources(stone=1),
    Resources(grain=1),
    Resources(stone=1),
    Resources(veg=1),
)


def _eligible(state: GameState, idx: int) -> bool:
    return (state.pending_stack[-1].space_id in SPACES
            and state.players[idx].card_state.get(CARD_ID, 0) < len(_SEQUENCE))


def _apply(state: GameState, idx: int) -> GameState:
    n = state.players[idx].card_state.get(CARD_ID, 0)
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources + _SEQUENCE[n],
        card_state=p.card_state.set(CARD_ID, n + 1),
    )
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(clay=2)))
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
