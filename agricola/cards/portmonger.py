"""Portmonger (occupation, A103; Artifex Expansion; deck A #103; players 1+).

Card text: "Each time you take 1/2/3+ food from a food accumulation space, you
also get 1 vegetable/grain/reed."

A banded / single-tier reward (REVIEWER CORRECTION 2026-06-30): the take falls in
exactly ONE band and yields exactly ONE good —
    take 1 food  → 1 vegetable
    take 2 food  → 1 grain
    take 3+ food → 1 reed
This matches the codebase's own slash-tier precedent (Loom, Gift Basket, Milking
Parlor all read "N/M/K → a/b/c" as a single-tier select, not an accumulation), and
the open "3+" band implies one top-tier reward.

Implemented as a `before_action_space` automatic effect on the food accumulation
spaces, hosted via `register_action_space_hook`. Firing happens in the BEFORE
phase, while the food is still sitting on the space, so `accumulated_amount` is the
amount about to be taken (the atomic `fishing` handler zeroes it only later, at the
host's Proceed). The eligibility `accumulated_amount >= 1` guard means an empty
space yields nothing.

In the card game (the only mode this occupation plays in) `fishing` is the sole
food accumulation space — Meeting Place pays food ONLY in the Family game and
accumulates nothing here, so it is NOT a food accumulation space for this card and
is deliberately NOT hooked. (Hooking it would be inert per the guard above, but the
mere registration makes the engine HOST Meeting Place — `should_host_space` reads
registrations, not eligibility — which collides with Meeting Place's pushing card
handler and soft-locks the turn.)

No cost / prereq / vps / passing (pure occupation; played via Lessons — the whole
effect is the hook).
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "portmonger"
# The card-game food accumulation spaces: just `fishing` (meeting_place pays food
# only in Family, which this occupation never sees — see the module docstring).
SPACES = frozenset({"fishing"})


def _eligible(state: GameState, idx: int) -> bool:
    top = state.pending_stack[-1]
    return (top.space_id in SPACES
            and get_space(state.board, top.space_id).accumulated_amount >= 1)


def _apply(state: GameState, idx: int) -> GameState:
    space_id = state.pending_stack[-1].space_id
    n = get_space(state.board, space_id).accumulated_amount
    if n == 1:
        reward = Resources(veg=1)
    elif n == 2:
        reward = Resources(grain=1)
    else:  # n >= 3
        reward = Resources(reed=1)
    p = fast_replace(state.players[idx], resources=state.players[idx].resources + reward)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)  # no on-play; effect is the hook
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
