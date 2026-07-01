"""Churchyard (minor improvement, D47; Dulcinaria Expansion).

Card text: "Place 2 food on each remaining round space. At the start of these
rounds, you get the food. (*Occupations and Improvements)"
Clarification on card: "Cards must be Occupations and Improvements."

Cost: 1 Stone, 1 Reed (a genuine spendable debit). Prerequisite: "10 Cards in
Front of You" — where Cards = Occupations and Improvements (minor improvements
PLUS owned major improvements). VPs: 1. Not passing.

Category 8 (deferred goods). The effect places 2 food on each REMAINING round
space — rounds strictly after the current round (the current round's space was
already collected at this round's start) up through 14. The food rides on
`future_resources` and is collected at the start of each scheduled round in
`engine._complete_preparation`.

The prerequisite is a have-check evaluated at legality time, BEFORE the card is
added to `minor_improvements`, so it never counts itself: the count must reach 10
from the cards already in front of the player (the played Churchyard is the 11th).
Standard Agricola treats Major improvements as Improvements, so owned majors count
toward the 10 (mirroring Food Basket's improvements count).
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "churchyard"


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    remaining = range(R + 1, 15)  # rounds strictly after the current one, through 14
    return schedule_resources(state, idx, remaining, Resources(food=2))


def _has_ten_cards(state: GameState, idx: int) -> bool:
    """10 Cards (Occupations and Improvements) in front of player `idx`.

    Improvements = minor improvements PLUS owned majors (majors live on
    ``state.board.major_improvement_owners``, not on ``PlayerState``)."""
    p = state.players[idx]
    n_occ = len(p.occupations)
    n_minor = len(p.minor_improvements)
    n_major = sum(1 for o in state.board.major_improvement_owners if o == idx)
    return (n_occ + n_minor + n_major) >= 10


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(stone=1, reed=1)),  # genuine spendable debit
    prereq=_has_ten_cards,
    vps=1,
    on_play=_on_play,
)
