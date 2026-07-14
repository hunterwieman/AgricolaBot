"""Small Animal Breeder (occupation, C111; Corbarius Expansion; players 1+).

Card text: "Before the start of each round, if you have food equal to or higher
than the current round number (e.g., 8+ food in round 8), you get 1 food."
Printed VPs: none. No cost / prerequisite / passing.

Category 7 (start-of-round phase hook). The clause is a MANDATORY, choice-free
income gated on a food threshold → an automatic effect (`register_auto` on the
`start_of_round` event), fired mechanically by the preparation walk for the owner. The
condition is re-checked each round, so the income switches on/off as the player's
food rises and falls relative to the advancing round number.

Round-number semantics (verified in engine.py `_complete_preparation`): the
start-of-round autos fire AFTER `round_number` is incremented to the round being
entered AND after that round's `future_resources` are distributed (step 2). So at
firing time `state.round_number` IS "the current round number" the card refers to,
and the player's food total is the post-distribution total — exactly the food the
player has at the start of the round. The comparison is therefore `food >=
state.round_number` directly (no offset). See CARD_IMPLEMENTATION_PLAN.md Category 7.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "small_animal_breeder"


def _on_play(state: GameState, idx: int) -> GameState:
    """No on-play effect — the card's income is the start-of-round auto."""
    return state


def _eligible(state: GameState, idx: int) -> bool:
    return state.players[idx].resources.food >= state.round_number


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, _on_play)
register_auto("start_of_round", CARD_ID, _eligible, _apply)
