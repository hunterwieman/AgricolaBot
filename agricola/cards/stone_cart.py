"""Stone Cart (minor improvement, C79; Consul Dirigens Expansion).

Card text: "Place 1 stone on each remaining even-numbered round space. At the start
of these rounds, you get the stone."
Cost: 2 Wood. Prerequisite: 2 Occupations. VPs: none. Not passing.

Category 8 (deferred goods), the Sack Cart shape: on play, +1 stone is scheduled
onto each remaining EVEN-numbered round space — rounds {2, 4, 6, 8, 10, 12, 14}
strictly after the current round. "Remaining" means only the ones strictly after the
current round (a round already entered has had its round-space goods collected), so
the filter is `r > R` (NOT `>=`): scheduling while sitting on round R excludes round
R itself, matching Sack Cart's `> R` filter exactly.

The stone rides on `PlayerState.future_resources` and is collected at the start of
each scheduled round by `engine._complete_preparation`. `schedule_resources` writes
slot `r-1` (the engine's Well index convention) and silently drops any round outside
1..14, so no manual bounds check is needed. Stone always fits (no accommodation), so
there is no capacity concern.

The "2 Occupations" prerequisite is a play-time HAVE-check on the owner's occupation
count (`min_occupations=2`), never spent — distinct from the 2-wood cost.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "stone_cart"
_EVEN_ROUNDS = (2, 4, 6, 8, 10, 12, 14)


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    remaining = [rnd for rnd in _EVEN_ROUNDS if rnd > R]
    return schedule_resources(state, idx, remaining, Resources(stone=1))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=2)),
    min_occupations=2,
    on_play=_on_play,
)
