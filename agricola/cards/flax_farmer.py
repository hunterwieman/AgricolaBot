"""Flax Farmer (occupation, E137; Ephipparius Expansion; players 3+).

Card text: "Each time you use the 'Reed Bank' accumulation space, you also get 1
grain. Each time you use the 'Grain Seeds' action space, you also get 1 reed."

Two bare "each time you use" grants → the BEFORE phase (the Trigger-Timing
ruling; CARD_AUTHORING_GUIDE.md §2). Both rewards are flat (+1 grain on Reed
Bank, +1 reed on Grain Seeds — each independent of what the space yields), so
before-timing is correct. Mandatory and choiceless → automatic effects
(register_auto), owner-gated ("you").

Reed Bank and Grain Seeds are both ATOMIC (agricola/resolution.py
ATOMIC_HANDLERS), so both are hosted via register_action_space_hook. On-play is a
no-op. Card-game only (ownership-gated registries), so the Family trace and the
C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "flax_farmer"

_GRAIN_SPACE = "reed_bank"     # using Reed Bank also grants 1 grain
_REED_SPACE = "grain_seeds"    # using Grain Seeds also grants 1 reed
FLAX_SPACES = frozenset({_GRAIN_SPACE, _REED_SPACE})


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in FLAX_SPACES


def _apply(state: GameState, idx: int) -> GameState:
    sid = state.pending_stack[-1].space_id
    bonus = Resources(grain=1) if sid == _GRAIN_SPACE else Resources(reed=1)
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + bonus)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, FLAX_SPACES)
