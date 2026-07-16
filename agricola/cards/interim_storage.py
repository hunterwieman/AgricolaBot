"""Interim Storage (minor improvement, A81; Artifex Expansion; cost 2 food).

Card text: "Each time you use a clay/reed/stone accumulation space, place 1
wood/clay/reed on this card. At the start of rounds 7, 11, and 14, move all the
goods on this card to your supply."
Printed VPs: none. Prerequisite: none. Not a passing minor.

Two halves:

ACCUMULATE — a `before_action_space` automatic effect on the clay / reed / stone
accumulation spaces (`clay_pit`, `reed_bank`, and the two quarries at 2 players).
"Each time you use [a space]" is the BEFORE-phase hook (the Geologist precedent),
and the timing relative to the space's own take is irrelevant since the placed
good comes from the supply onto the card, not from the space. The card-to-good
mapping is PARALLEL, each good one tier DOWN from what the space yields: a clay
space → 1 WOOD, a reed space → 1 CLAY, a stone space → 1 REED. The good the space
yields is read from `BUILDING_ACCUMULATION_RATES`, so the deposit is derived from
the space's good type — identical at 2p and correct for any 4p clay/reed/stone
space. The running total of placed goods is held in this card's CardStore slot as
a `Resources`.

RELEASE — a `start_of_round` automatic effect: when round 7, 11, or 14 begins,
move all goods held on the card to the owner's supply and reset the card to empty,
so accumulation restarts for the next window. By the time `start_of_round` autos
fire, `_complete_preparation` has already incremented `round_number` to the new
round, so the gate is `state.round_number in {7, 11, 14}`.

See CARD_IMPLEMENTATION_PLAN.md Categories 3 (action-space hook) + 7
(start-of-round phase hook).
"""
from __future__ import annotations

from agricola.constants import (
    BUILDING_ACCUMULATION_RATES,
    CLAY_ACCUMULATION_SPACES,
    REED_ACCUMULATION_SPACES,
    STONE_ACCUMULATION_SPACES,
)
from agricola.cards.specs import register_minor
from agricola.cards.triggers import (
    register_action_space_hook,
    register_auto,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "interim_storage"

# The clay / reed / stone accumulation spaces this card hooks. Derived from the
# named constants so the "active list" lives in one place and grows at 4 players.
_HOOK_SPACES = (
    CLAY_ACCUMULATION_SPACES | REED_ACCUMULATION_SPACES | STONE_ACCUMULATION_SPACES
)

# Rounds at whose start the held goods are released to the owner's supply.
RELEASE_ROUNDS = frozenset({7, 11, 14})


def _deposit_for(space_id: str) -> Resources:
    """The good placed on the card when `space_id` is used — one tier DOWN from
    what the space yields: a clay space → 1 wood, a reed space → 1 clay, a stone
    space → 1 reed. The space's yielded good is read from BUILDING_ACCUMULATION_RATES
    (which of clay/reed/stone is > 0), so this is correct for any 4p clay/reed/stone
    accumulation space, not just the four 2p spaces."""
    rate = BUILDING_ACCUMULATION_RATES[space_id]
    if rate.clay:
        return Resources(wood=1)
    if rate.reed:
        return Resources(clay=1)
    if rate.stone:
        return Resources(reed=1)
    return Resources()   # unreachable: only clay/reed/stone spaces are hooked


def _eligible_accum(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in _HOOK_SPACES


def _apply_accum(state: GameState, idx: int) -> GameState:
    gain = _deposit_for(state.pending_stack[-1].space_id)
    p = state.players[idx]
    held = p.card_state.get(CARD_ID, Resources())
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, held + gain))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible_release(state: GameState, idx: int) -> bool:
    return state.round_number in RELEASE_ROUNDS and bool(
        state.players[idx].card_state.get(CARD_ID, Resources())
    )


def _apply_release(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    held = p.card_state.get(CARD_ID, Resources())
    p = fast_replace(
        p,
        resources=p.resources + held,
        card_state=p.card_state.set(CARD_ID, Resources()),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(resources=Resources(food=2)))

# Accumulate half: hook the clay/reed/stone accumulation spaces; on each use, place
# the mapped good on the card.
register_action_space_hook(CARD_ID, _HOOK_SPACES)
register_auto("before_action_space", CARD_ID, _eligible_accum, _apply_accum)

# Release half: at the start of rounds 7/11/14, move all held goods to supply.
register_auto("start_of_round", CARD_ID, _eligible_release, _apply_release)
