"""Farm Building (minor improvement, C43; Corbarius Expansion; cost 1 clay + 1 reed).

Card text: "Each time you build a major improvement, place 1 food on each of the
next 3 round spaces. At the start of these rounds, you get the food." Printed 1 VP.

Category 8 (deferred-goods) driven by a Category-5-style improvement-build hook.
"Each time you build a major improvement" is the major-only event
`after_build_major`, fired once per major build by `_execute_build_major`'s
`_enter_after_phase` (NOT `after_build_improvement`, which also fires for minors).
The effect is mandatory and choice-free → an automatic effect (`register_auto`),
gated on ownership by `apply_auto_effects` so the eligibility fn is always-True.

"next 3 round spaces" = rounds R+1, R+2, R+3 (1-indexed `range(R+1, R+4)`), placed
via `schedule_resources` onto `future_resources` and collected at the start of each
scheduled round by `engine._complete_preparation` (the same plumbing the Well uses).
`schedule_resources` clamps rounds outside 1..14, so a late-game major (round 13 →
only round 14 gets food; round 14 → nothing) correctly degrades to "each REMAINING
round space". See CARD_IMPLEMENTATION_PLAN.md Category 8 / Category 5.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "farm_building"


def _always_eligible(state: GameState, idx: int) -> bool:
    return True


def _apply(state: GameState, idx: int) -> GameState:
    # "next 3 round spaces" = rounds R+1..R+3 (1-indexed). schedule_resources does
    # slot = rnd - 1 internally and drops rounds outside 1..14.
    R = state.round_number
    return schedule_resources(state, idx, range(R + 1, R + 4), Resources(food=1))


register_minor(CARD_ID, cost=Cost(resources=Resources(clay=1, reed=1)), vps=1)
register_auto("after_build_major", CARD_ID, _always_eligible, _apply)
