"""Fire Protection Pond (minor improvement, A45; Artifex Expansion; players -).

Card text: "Once you no longer live in a wooden house, place 1 food on each of the
next 6 round spaces. At the start of these rounds, you get the food."

cost: 1 Food. prereq: "Still in Wooden House" (== WOOD) — so it can only be PLAYED
while wooden. No printed VPs, not passing.

Category 8 (deferred goods) gated on a one-shot conditional latch
(CARD_IMPLEMENTATION_PLAN.md II.3 / §6). "Once you no longer live in a wooden
house" is the level-triggered condition `house_material != WOOD` (clay OR stone).
Because the prereq pins play to a WOODEN house, the condition is FALSE at play time,
so the latch never fires on play; it always fires LATER via a renovate, where
`_fire_ready_one_shots` (resolution.py) re-checks the owner's condition and fires
the card exactly once (recorded in the per-game `fired_once` latch).

The window is a FIXED 6 rounds — "the next 6 round spaces" = rounds R+1..R+6
(1-indexed), i.e. `range(R + 1, R + 7)`. `schedule_resources` silently drops any
slot past round 14, matching "next 6" clamped to the game length. The on-play is a
no-op (the schedule is the conditional fire, not the play).

Played via one of the minor-play entry points. See CARD_IMPLEMENTATION_PLAN.md
Category 8.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_conditional
from agricola.constants import HouseMaterial
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "fire_protection_pond"


def _prereq(state: GameState, idx: int) -> bool:
    # "Still in Wooden House" — playable only while the house is wooden.
    return state.players[idx].house_material == HouseMaterial.WOOD


def _condition(state: GameState, idx: int) -> bool:
    # "Once you no longer live in a wooden house" — clay or stone.
    return state.players[idx].house_material != HouseMaterial.WOOD


def _apply(state: GameState, idx: int) -> GameState:
    # "the next 6 round spaces" = rounds R+1..R+6 (1-indexed); slots past 14 dropped.
    R = state.round_number
    return schedule_resources(state, idx, range(R + 1, R + 7), Resources(food=1))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=1)),
    prereq=_prereq,
)
register_conditional(CARD_ID, _condition, _apply)
