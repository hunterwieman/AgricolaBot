"""Recount (minor improvement, E6; Ephipparius Expansion; traveling).

Card text: "You immediately get 1 building resource of each type of which you
have 4 or more resources in your supply already."

No cost, no prerequisite, no printed VPs; a TRAVELING (passing) card — after the
immediate effect it passes to the opponent rather than being kept.

Category 2 (on-play one-shot) + passing. The four BUILDING resources are wood,
clay, reed, and stone (food / grain / vegetable are crops/food, not building
resources — the card category "Building Resource Provider" confirms the scope).
For each building-resource type the player already holds >= 4 of, gain exactly 1
of that type. Reads the DECIDER's OWN supply only. No stored state.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "recount"

# The four building resources (the card's scope). Crops/food are excluded.
_BUILDING = ("wood", "clay", "reed", "stone")


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    r = p.resources
    gain = Resources(**{t: 1 for t in _BUILDING if getattr(r, t) >= 4})
    p = fast_replace(p, resources=r + gain)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    passing_left=True,
    on_play=_on_play,
)
