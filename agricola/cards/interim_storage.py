"""Interim Storage (minor improvement, A81; Artifex Expansion; cost 2 food).

Card text: "Each time you use a clay/reed/stone accumulation space, place 1
wood/clay/reed on this card. At the start of rounds 7, 11, and 14, move all the
goods on this card to your supply."
Printed VPs: none. Prerequisite: none. Not a passing minor.

Two halves:

ACCUMULATE — a `before_action_space` automatic effect on the four building
accumulation spaces (`clay_pit`, `reed_bank`, `western_quarry`, `eastern_quarry`).
"Each time you use [a space]" is the BEFORE-phase hook (the Geologist precedent),
and the timing relative to the space's own take is irrelevant since the placed
good comes from the supply onto the card, not from the space. The card-to-good
mapping is PARALLEL, each good one tier DOWN from what the space yields: the clay
space (`clay_pit`) → 1 WOOD, the reed space (`reed_bank`) → 1 CLAY, and the stone
spaces (`western_quarry`/`eastern_quarry`, the only two) → 1 REED. The running
total of placed goods is held in this card's CardStore slot as a `Resources`.

RELEASE — a `start_of_round` automatic effect: when round 7, 11, or 14 begins,
move all goods held on the card to the owner's supply and reset the card to empty,
so accumulation restarts for the next window. By the time `start_of_round` autos
fire, `_complete_preparation` has already incremented `round_number` to the new
round, so the gate is `state.round_number in {7, 11, 14}`.

See CARD_IMPLEMENTATION_PLAN.md Categories 3 (action-space hook) + 7
(start-of-round phase hook).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import (
    register_action_space_hook,
    register_auto,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "interim_storage"

# The four building accumulation spaces this card hooks, each mapped to the good
# placed on the card (one tier down from what the space itself yields).
ACCUMULATION_GAIN: dict[str, Resources] = {
    "clay_pit": Resources(wood=1),        # clay space → 1 wood
    "reed_bank": Resources(clay=1),       # reed space → 1 clay
    "western_quarry": Resources(reed=1),  # stone space → 1 reed
    "eastern_quarry": Resources(reed=1),  # stone space → 1 reed
}

# Rounds at whose start the held goods are released to the owner's supply.
RELEASE_ROUNDS = frozenset({7, 11, 14})


def _eligible_accum(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in ACCUMULATION_GAIN


def _apply_accum(state: GameState, idx: int) -> GameState:
    gain = ACCUMULATION_GAIN[state.pending_stack[-1].space_id]
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

# Accumulate half: hook the four building accumulation spaces; on each use, place
# the mapped good on the card.
register_action_space_hook(CARD_ID, frozenset(ACCUMULATION_GAIN))
register_auto("before_action_space", CARD_ID, _eligible_accum, _apply_accum)

# Release half: at the start of rounds 7/11/14, move all held goods to supply.
register_auto("start_of_round", CARD_ID, _eligible_release, _apply_release)
