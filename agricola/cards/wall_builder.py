"""Wall Builder (occupation, A111; Base Revised; players 1+).

Card text: "Each time you build at least 1 room, you can place 1 food on each of
the next 4 round spaces. At the start of these rounds, you get the food."

Category 8 (deferred goods on round spaces). "Each time you build at least 1 room"
→ the `after_build_rooms` event, which fires ONCE per build-rooms session at the
session-ending Stop (so "at least 1 room" is satisfied exactly when the hook fires
at all). The effect schedules 1 food onto the next 4 round spaces (rounds R+1..R+4)
of `future_resources`, collected at the start of each. The printed "you can" is the
no-downside option a rational agent always takes (free food), so it is modeled as
an automatic effect (register_auto), not an optional FireTrigger.

Played via Lessons; its on-play is a no-op. See CARD_IMPLEMENTATION_PLAN.md
Category 8.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "wall_builder"


def _always(state: GameState, idx: int) -> bool:
    return True


def _apply(state: GameState, idx: int) -> GameState:
    # "next 4 round spaces" = rounds R+1..R+4 (1-indexed); schedule_resources
    # clamps any round > 14 away ("each of the next 4", remaining ones).
    R = state.round_number
    return schedule_resources(state, idx, range(R + 1, R + 5), Resources(food=1))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("after_build_rooms", CARD_ID, _always, _apply)
