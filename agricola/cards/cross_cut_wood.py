"""Cross-Cut Wood (minor improvement, D4; Dulcinaria Expansion; kept).

Card text: "You immediately get a number of wood equal to the number of stone
in your supply."

Cost 1 food. Prerequisite: "3 Occupations" (a have-check, ``min_occupations=3``).
No printed VPs. Not a passing card — it stays in front of the player.

Category 2 (on-play one-shot). The reward is read from the CURRENT supply at play
time: wood gained = the owner's stone count at the moment the card is played. The
stone is NOT spent (it is only a multiplier); the card only ADDS that many wood. If
the player holds 0 stone, nothing is gained. The 1-food cost and 3-occupation
prerequisite are independent of this stone-count read.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "cross_cut_wood"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    # Read the stone count fresh from the current supply; the stone is not consumed.
    n = p.resources.stone
    p = fast_replace(p, resources=p.resources + Resources(wood=n))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=1)),
    min_occupations=3,
    on_play=_on_play,
)
