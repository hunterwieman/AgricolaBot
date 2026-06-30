"""Stew (minor improvement, C45; Corbarius Expansion; players -).

Card text: "Each time you use the 'Day Laborer' action space, also place 1 food on
each of the next 4 round spaces. At the start of these rounds, you get the food."
Cost: 1 Clay. Prerequisite: none. VPs: 0. Not passing.

Category 8 (deferred goods) on an action-space hook — the same shape as Chophouse
(seed spaces) / Herring Pot (Fishing) but on the single `day_laborer` space with a
fixed schedule length of 4. Each use schedules 1 food onto rounds R+1..R+4 of
`future_resources`; the engine pays each scheduled slot out at the start of that
round (`_complete_preparation`), so no start_of_round trigger is needed.

"Each time you use [space]" → the `before_action_space` event, per the
Trigger-Timing ruling (a bare "each time you use [space]" fires BEFORE the space's
own effect — the same phase as Corn Scoop / Herring Pot / Chophouse). Because the
food is scheduled onto FUTURE round spaces (not collected this turn), the end state
is before/after-identical; the ruling fixes the phase regardless of observability.
The effect is pure benefit (food onto future rounds, no cost or choice), so it is an
automatic effect (`register_auto`), choiceless and never surfaced as a FireTrigger.

`day_laborer` is ATOMIC (in `ATOMIC_HANDLERS`), so it does NOT self-host — the host
frame is pushed on placement only via `register_action_space_hook` (the same index
Cottager uses for `day_laborer`); without it the `before_action_space` frame is never
pushed and the effect would silently never fire. `schedule_resources` clamps slots
outside 1..14, so late-game uses silently drop out-of-range round spaces ("each
REMAINING round space"). On-play is a no-op (the schedule is the per-use hook).
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "stew"
SPACES = frozenset({"day_laborer"})
N_ROUNDS = 4


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in SPACES


def _apply(state: GameState, idx: int) -> GameState:
    R = state.round_number
    return schedule_resources(
        state, idx, range(R + 1, R + 1 + N_ROUNDS), Resources(food=1)
    )


register_minor(CARD_ID, cost=Cost(resources=Resources(clay=1)))
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
