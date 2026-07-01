"""Small Basket (minor improvement, D68; Dulcinaria Expansion; Crop Provider;
prereq 2 Occupations).

Card text: "Each time you use the "Reed Bank" accumulation space, you can pay 1
reed to get 1 vegetable. If you do in a game with 4+ players, place that 1 reed on
the accumulation space."

No printed cost. No printed VPs. Prerequisite: 2 Occupations.

An OPTIONAL action-space trigger hosted on the (atomic) Reed Bank accumulation
space. The bare "Each time you use [Reed Bank]" rides the `before_action_space`
event — the Wood Cutter / Brewery Pond ruling settles that a bare "each time you
use [space]" fires BEFORE the space's own reed pickup, not after (no "immediately
after"); the phase is immaterial here anyway, since paying 1 reed for 1 vegetable
is independent of the reed the space grants. Optionality lives in the FireTrigger:
spending a reed may be unwanted, so the grant is the player's CHOICE — declining is
simply the host's `Stop` (no SkipTrigger flag); hence `register` (optional), NEVER
`register_auto` (mandatory, choiceless).

Firing is a direct goods swap: −1 reed, +1 vegetable. A simple state edit, no
pending pushed (the Truffle Slicer / Brewery Pond shape).

The "place that 1 reed on the accumulation space" clause is gated to 4+-player
games, so in the 2-player engine it NEVER fires — the reed is simply spent, with no
`with_space` reed-return (this is the deliberate difference from Basket, whose
2-player text DOES return the wood). The card-text branch is inert here by player
count, not by simplification.

Eligibility never offers a dead-end (CARD_AUTHORING_GUIDE §2): it gates on the host
frame's space being Reed Bank AND on-hand `reed >= 1`. "Once per use" is automatic —
`_apply_fire_trigger` stamps `triggers_resolved | {card_id}` before applying, and
`_eligible` reads it, so the card fires at most once per Reed Bank use (but may be
used on every separate Reed Bank use over the game).

The "2 Occupations" prerequisite is a `min_occupations=2` have-check (NOT a cost).
Reed Bank is ATOMIC, so the host frame is pushed via `register_action_space_hook`.
Card-only state defaults canonically, so the Family game is byte-identical and the
C++ gates are untouched. See truffle_slicer.py / brewery_pond.py (the Reed Bank
before_action_space host) and CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_action_space_hook
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "small_basket"
SPACES = frozenset({"reed_bank"})


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    """Offer the pay-1-reed-for-1-vegetable exchange only on a Reed Bank use, when
    the player has a reed to pay, and it has not already fired this use. Never a
    dead-end."""
    if CARD_ID in triggers_resolved:                       # once per Reed Bank use
        return False
    if state.pending_stack[-1].space_id not in SPACES:
        return False
    return state.players[idx].resources.reed >= 1


def _apply(state: GameState, idx: int) -> GameState:
    """Pay 1 reed for 1 vegetable. A simple state edit — no pending pushed. The
    4+-player reed-return clause is inert in the 2-player engine, so no space
    reed-return."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(reed=-1, veg=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, min_occupations=2)   # cost=Cost() default; no printed VPs
register("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
