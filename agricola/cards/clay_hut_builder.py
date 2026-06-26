"""Clay Hut Builder (occupation, A120; Base Revised; players 1+).

Card text: "Once you no longer live in a wooden house, place 2 clay on each of the
next 5 round spaces. At the start of these rounds, you get the clay."

Category 8 (deferred goods) gated on a one-shot conditional latch
(CARD_IMPLEMENTATION_PLAN.md II.3 / §6). "Once you no longer live in a wooden
house" is the level-triggered condition `house_material != WOOD` (i.e. clay OR
stone) — true after a wood->clay (or clay->stone) renovate, or already true the
instant the card is played in a non-wooden house. `_fire_ready_one_shots` fires it
once per game (per-game `fired_once` latch). "Next 5 round spaces" = rounds
R+1..R+5 of `future_resources`.

Played via Lessons; on-play is a no-op (the schedule is the conditional fire). See
CARD_IMPLEMENTATION_PLAN.md Category 8.
"""
from __future__ import annotations

from agricola.constants import HouseMaterial
from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_conditional
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "clay_hut_builder"


def _condition(state: GameState, idx: int) -> bool:
    return state.players[idx].house_material != HouseMaterial.WOOD


def _apply(state: GameState, idx: int) -> GameState:
    # "next 5 round spaces" = rounds R+1..R+5 (1-indexed).
    R = state.round_number
    return schedule_resources(state, idx, range(R + 1, R + 6), Resources(clay=2))


register_occupation(CARD_ID, lambda state, idx: state)   # the effect is the latch fire
register_conditional(CARD_ID, _condition, _apply)
