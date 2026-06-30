"""Excursion to the Quarry (minor improvement, B6; Bubulcus; players 1+).

Card text: "You immediately get a number of stone equal to the number of people
you have."

Clarification: "A newborn is a person."

Cost 2 food, prerequisite 1 occupation, no printed VPs, kept (not passing).

Category 2 (on-play one-shot). The stone gained equals `people_total` — the
player's home + placed workers AND newborns (the `PlayerState.people_total` field
already includes newborns, matching the clarification, so no manual addition is
needed). Stone is a building resource (no accommodation concern).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "excursion_to_the_quarry"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(stone=p.people_total))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=2)),
    min_occupations=1,
    on_play=_on_play,
)
