"""Godmother (occupation, Ephipparius E113; players 1+).

Card text (verbatim): "Each time you take a "Family Growth" action, you also
get 1 vegetable."

A mandatory, choice-free flat reward -> an automatic effect (register_auto),
firing in the BEFORE window per the trigger-timing rule ("each time you take X"
fires before X; the reward reads nothing the growth produced). It rides TWO
registrations that are mutually exclusive by construction:

1. ``before_family_growth`` — every family growth that runs through the
   ``PendingFamilyGrowth`` primitive: the Basic Wish for Children space in
   cards mode (its mandatory first sub-action) and every card-granted growth
   (Autumn Mother, Bed in the Grain Field, ...; those push the frame with
   ``place_on_space=False``). The engine's single before-auto seam
   (``engine._fire_subaction_before_auto``) fires this exactly once per
   pushed growth frame.

2. ``before_action_space`` filtered to ``space_id ==
   "urgent_wish_for_children"`` — Urgent Wish for Children is an ATOMIC space
   in both modes: its resolver grows the family inline WITHOUT pushing a
   ``PendingFamilyGrowth`` frame, so registration 1 never fires there, yet
   taking it is unambiguously "a Family Growth action". The
   ``register_action_space_hook`` makes the atomic space hosted when this
   card is owned, so the before-auto fires at the placement. Because the
   atomic resolver pushes no growth frame, the two registrations can never
   both fire on one action (no double pay).

Own-action only (``any_player=False`` on both): "you take" — an opponent's
growth pays nothing. The effect only ADDS a vegetable, consuming nothing, so
no mandatory work can be stranded and no eligibility gate beyond the space
filter is needed. Played via Lessons; its on-play is a no-op. Card-only
registries are empty in the Family game, so the Family game is byte-identical
and the C++ differential gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "godmother"

# The one Family-Growth action space whose growth is atomic (no
# PendingFamilyGrowth frame) in both modes — hookable only when hosted.
_URGENT_WISH = "urgent_wish_for_children"


def _gain_veg(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(veg=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _urgent_wish_eligible(state: GameState, idx: int) -> bool:
    # Consulted at a before_action_space host frame; read the space uniformly
    # via the host frame's `space_id` (atomic and non-atomic hosts alike).
    return state.pending_stack[-1].space_id == _URGENT_WISH


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect

# Every frame-pushed growth: the Basic Wish sub-action + card-granted growths.
register_auto("before_family_growth", CARD_ID, lambda state, idx: True, _gain_veg)

# The atomic Urgent Wish path (no growth frame ever pushed there).
register_auto("before_action_space", CARD_ID, _urgent_wish_eligible, _gain_veg)
register_action_space_hook(CARD_ID, frozenset({_URGENT_WISH}))
