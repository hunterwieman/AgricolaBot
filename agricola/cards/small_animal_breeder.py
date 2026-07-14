"""Small Animal Breeder (occupation, C111; Corbarius Expansion; players 1+).

Card text: "Before the start of each round, if you have food equal to or higher
than the current round number (e.g., 8+ food in round 8), you get 1 food."
Printed VPs: none. No cost / prerequisite / passing.

"BEFORE the start of each round" → the preparation ladder's `before_round`
window (user ruling 2026-07-14): the ladder's FIRST rung, before the reveal,
before round-space collection, before `start_of_round`. A MANDATORY, choice-free
income gated on a food threshold → an automatic effect (`register_auto`), fired
mechanically by the walk for the owner. The condition is re-checked each round,
so the income switches on/off as the player's food rises and falls relative to
the advancing round number.

Round-number semantics: the `before_round` window fires BEFORE `__round_setup__`
increments, so `state.round_number` still names the JUST-COMPLETED round — "the
current round number" the card refers to (the round being entered, the printed
"8+ food in round 8") is `state.round_number + 1`. And because the window
precedes `__collect__`, the food total is the PRE-collection total: goods
promised on this round's round space (the Well, schedule cards) have NOT yet
landed — exactly what "before the start of the round" means, and the observable
reason this rung exists as its own instant.
See CARD_IMPLEMENTATION_PLAN.md Category 7.
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
    # Pre-increment window: the round being entered is round_number + 1.
    return state.players[idx].resources.food >= state.round_number + 1


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, _on_play)
# "Before the start of each round" — the before_round window (user ruling
# 2026-07-14), the ladder's first rung, distinct from start_of_round.
register_auto("before_round", CARD_ID, _eligible, _apply)
