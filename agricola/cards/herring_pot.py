"""Herring Pot (minor improvement, B47; Base Revised).

Card text: "Each time you use the 'Fishing' accumulation space, place 1 food on
each of the next 3 round spaces. At the start of these rounds, you get the food."
Cost: 1 Clay. Prerequisite: none. VPs: none. Not passing.

Category 8 (deferred goods) on an action-space hook. "Each time you use Fishing"
→ the `before_action_space` event on the `fishing` space, per the Trigger-Timing
ruling (a bare "each time you use [space]" fires BEFORE the space's own effect —
the same phase as Milk Jug / Wood Cutter / Corn Scoop). The schedule's food lands on
future round spaces and is independent of fishing's own catch, so the end state would
coincide either way — but the phase is fixed by the ruling, not by observability. The
host frame is pushed on that placement (register_action_space_hook). The effect
schedules 1 food onto the next 3 round spaces (rounds R+1..R+3) of `future_resources`
PER USE. Played via an improvement space; the play itself is a no-op (the schedule is
the per-use hook), so on_play is the default.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "herring_pot"
SPACES = frozenset({"fishing"})


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in SPACES


def _apply(state: GameState, idx: int) -> GameState:
    R = state.round_number
    return schedule_resources(state, idx, range(R + 1, R + 4), Resources(food=1))


register_minor(CARD_ID, cost=Cost(resources=Resources(clay=1)))
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
