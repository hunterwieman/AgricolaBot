"""Chophouse (minor improvement, B43; Bubulcus Expansion).

Card text: "Each time you use the 'Grain/Vegetable Seed' action space, place 1 food
on each of the next 3/2 round spaces. At the start of these rounds, you get the
food."
Cost: 2 Wood / 2 Clay. Prerequisite: none. VPs: 1. Not passing.

Category 8 (deferred goods) on action-space hooks — the same shape as Herring Pot
(Fishing) but on the TWO atomic seed spaces, with a per-space schedule length:
`grain_seeds` schedules the next 3 round spaces, `vegetable_seeds` the next 2. The
single `_apply` branches on `pending_stack[-1].space_id` to pick N (a naive
Herring-Pot copy would hardcode one N).

"Each time you use [space]" → the `before_action_space` event, per the
Trigger-Timing ruling (a bare "each time you use [space]" fires BEFORE the space's
own effect — the same phase as Corn Scoop / Herring Pot). Because the food is
scheduled onto FUTURE round spaces (not collected this turn), the end state is
before/after-identical; the ruling fixes the phase regardless of observability.

Both seed spaces are ATOMIC (in ATOMIC_HANDLERS), so they do NOT self-host — the
host frame is pushed on placement only via `register_action_space_hook` (the same
index Corn Scoop uses for `grain_seeds`). The effect schedules 1 food onto rounds
R+1..R+N of `future_resources` per use; `schedule_resources` clamps slots outside
1..14, so late-game uses silently drop out-of-range round spaces ("each REMAINING
round space"). On-play is a no-op (the schedule is the per-use hook).

The card's clarifications field only cross-references "the errata for Swagman A129",
which governs Swagman (a 3+ player occupation) and has no bearing on Chophouse.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "chophouse"
SPACES = frozenset({"grain_seeds", "vegetable_seeds"})


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in SPACES


def _apply(state: GameState, idx: int) -> GameState:
    R = state.round_number
    sid = state.pending_stack[-1].space_id
    n = 3 if sid == "grain_seeds" else 2
    return schedule_resources(state, idx, range(R + 1, R + 1 + n), Resources(food=1))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2, clay=2)), vps=1)
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
