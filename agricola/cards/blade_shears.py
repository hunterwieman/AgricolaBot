"""Blade Shears (minor improvement, C7; Corbarius Expansion; players -).

Card text: "You immediately get your choice of 3 food or 1 food for each sheep
you have. (Keep the sheep.)"
Clarification: "Choose exactly 3 food, or food equal to your sheep."

Cost 1 wood. Prerequisite: "1 Pasture" — at least one enclosed pasture in front
of the player (a have-check at legality time, not a cost). No printed VPs, not a
passing card.

Category 2 (on-play one-shot). The "3 food OR 1 food per sheep" choice is not a
real decision frame: food is a pure free good with no downside, so the rational
and only sensible choice is always whichever is larger. We therefore collapse the
choice to a deterministic ``max(3, sheep)`` food grant rather than pushing a
``PendingCardChoice``. The sheep are kept ("Keep the sheep.") — they are never
spent or subtracted.

The prerequisite reads the BFS-derived enclosed-pasture decomposition
(``farmyard.pastures``); a pasture is not its own ``CellType``, so "1 Pasture"
means ``len(farmyard.pastures) >= 1``. The card never counts toward its own
prereq (the prerequisite is evaluated at legality time, before the card is owned).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "blade_shears"


def _prereq(state: GameState, idx: int) -> bool:
    """Playable iff the player has at least one enclosed pasture."""
    return len(state.players[idx].farmyard.pastures) >= 1


def _on_play(state: GameState, idx: int) -> GameState:
    """Gain ``max(3, sheep)`` food; keep the sheep."""
    p = state.players[idx]
    gain = max(3, p.animals.sheep)
    p = fast_replace(p, resources=p.resources + Resources(food=gain))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1)),
    prereq=_prereq,
    on_play=_on_play,
)
