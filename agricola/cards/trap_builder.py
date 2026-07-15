"""Trap Builder (occupation, D147; Dulcinaria Expansion; players 3+; Livestock
Provider).

Card text (verbatim): "Each time you use the "Day Laborer" action space, place 1
food, 1 food, and 1 wild boar on the next 3 round spaces, respectively. At the
start of these rounds, you get the good."
No clarifications / errata printed.

Category 8 (deferred goods) triggered by using an action space. "Each time you use
[the space]" fires in the BEFORE phase of the space (the standard Trigger-Timing
ruling) — and the effect is flat (a fixed schedule, independent of what Day
Laborer yields), so `before_action_space` is correct. It is MANDATORY and
choice-free ("place ... on the next 3 round spaces") → an automatic effect
(`register_auto`), filtered to the Day Laborer space via the host frame's
`space_id`.

Day Laborer is an ATOMIC space (no host frame by default), so
`register_action_space_hook(CARD_ID, {"day_laborer"})` makes it hosted while this
card is owned — exactly the Wood Cutter / Bee Statue idiom. The schedule places,
onto the next three round spaces (R+1, R+2, R+3) respectively:
  - R+1: 1 food, R+2: 1 food  -> `schedule_resources` (they ride future_resources)
  - R+3: 1 wild boar          -> `schedule_animals` (rides future_rewards,
                                 grant_animals-accommodated at round start)
`schedule_*` clamp any target past round 14 to nothing (Day Laborer used in the
last rounds schedules only the still-existing spaces).

Played via Lessons; no on-play effect. The registries / schedules are empty in the
Family game, so it stays byte-identical and the C++ gates are untouched. See
bee_statue.py / wood_cutter.py (the atomic `before_action_space` hook) and
acorns_basket.py (schedule_animals).
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_animals, schedule_resources
from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.resources import Animals, Resources
from agricola.state import GameState

CARD_ID = "trap_builder"
_SPACE = "day_laborer"


def _eligible(state: GameState, idx: int) -> bool:
    """Fire only on a Day Laborer use — read the space uniformly via the host
    frame's `space_id`."""
    return state.pending_stack[-1].space_id == _SPACE


def _apply(state: GameState, idx: int) -> GameState:
    """Schedule 1 food, 1 food, 1 wild boar onto rounds R+1, R+2, R+3 respectively."""
    R = state.round_number
    state = schedule_resources(state, idx, (R + 1, R + 2), Resources(food=1))
    return schedule_animals(state, idx, (R + 3,), Animals(boar=1))


register_occupation(CARD_ID, _noop_on_play)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, {_SPACE})
