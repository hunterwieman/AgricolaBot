"""Collier (occupation, B144; Bubulcus Expansion; players 3+).

Card text: "Each time after you use the 'Clay Pit' or 'Hollow' accumulation
space, you get 1 wood. On 'Clay Pit' you also get 1 additional reed."
Clarification: "Note that this card is a 3+ player card."

'Hollow' is a 3+/4-player board-extension accumulation space (the clay analog of
Wood Cutter's Copse/Grove — never on the 2-player board), so this card only ever
fires on the 'Clay Pit'. There both halves of the reward apply: +1 wood AND +1
additional reed.

The text says "each time AFTER you use" EXPLICITLY, so this is an
``after_action_space`` automatic effect (contrast the bare "each time you use"
that fires BEFORE). The reward is flat (+1 wood +1 reed, independent of the clay
taken), so it needs no post-outcome read — but the printed "after" governs the
phase regardless (an explicit "after" is honored even when the outcome coincides
either way; CARD_AUTHORING_GUIDE.md §2). The +1 wood/reed is mandatory and
choiceless → an automatic effect (register_auto), not a FireTrigger; owner-gated
("you").

Clay Pit is ATOMIC (agricola/resolution.py ATOMIC_HANDLERS), so it must be HOSTED
via register_action_space_hook for a before/after phase to exist; the after-autos
fire at the host's work-complete flip (_enter_after_phase), after the clay is
taken. On-play is a no-op. Card-game only (ownership-gated registries), so the
Family trace and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "collier"

# 'Hollow' is a 3+/4-player board space absent from this engine, so only Clay Pit.
COLLIER_SPACES = frozenset({"clay_pit"})


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in COLLIER_SPACES


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=1, reed=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, COLLIER_SPACES)
