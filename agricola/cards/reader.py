"""Reader (occupation, C136; Corbarius; players 1+).

Card text (verbatim): "As soon as you have 6 occupations in front of you (including
this one), this card provides room for one person. In the draft variant, you need 7
occupations to play this."

User ruling (2026-07-16): Reader has NO play prerequisite — it can be played at any
occupation count. Its capacity benefit is active if and only if the player has played
7 occupations. (This project plays only the DRAFT variant, so the printed threshold is
hardcoded to 7; the displayed card text is edited to "7".) A hand holds at most 7
occupations, so "== 7" and ">= 7" coincide; ">= 7" is used to match the printed
"as soon as you have N" threshold semantics — persistent, not a momentary equality.

A passive PEOPLE-capacity bonus of +1 while the owner has played 7 occupations
(registered via the housing-capacity registry, capacity_mods). Recomputed each time
the family-growth gate is read. No on-play effect.
"""
from __future__ import annotations

from agricola.cards.capacity_mods import register_housing_capacity
from agricola.cards.specs import register_occupation
from agricola.state import GameState

CARD_ID = "reader"

_OCCUPATION_THRESHOLD = 7


def _capacity_bonus(state: GameState, idx: int) -> int:
    return 1 if len(state.players[idx].occupations) >= _OCCUPATION_THRESHOLD else 0


def _on_play(state: GameState, idx: int) -> GameState:
    """No on-play effect — the capacity is the passive registered modifier."""
    return state


register_occupation(CARD_ID, _on_play)
register_housing_capacity(CARD_ID, _capacity_bonus)
