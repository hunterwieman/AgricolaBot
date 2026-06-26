"""Manservant (occupation, B107; Base Revised; players 1+).

Card text: "Once you live in a stone house, place 3 food on each remaining round
space. At the start of these rounds, you get the food."

Category 8 (deferred goods) gated on a one-shot conditional latch
(CARD_IMPLEMENTATION_PLAN.md II.3 / §6). "Once you live in a stone house" is a
LEVEL-triggered, once-per-game condition: it can become true via a clay->stone
renovate, or already be true the instant Manservant is played (you renovated to
stone first). Both moments run `_fire_ready_one_shots` for the owner, which fires
this card exactly once (recorded in the per-game `fired_once` latch). "Each
remaining round space" = rounds R+1..14 of `future_resources`.

Played via Lessons; its on-play is a no-op (the schedule is the conditional fire,
not the play). See CARD_IMPLEMENTATION_PLAN.md Category 8.
"""
from __future__ import annotations

from agricola.constants import HouseMaterial
from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_conditional
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "manservant"


def _condition(state: GameState, idx: int) -> bool:
    return state.players[idx].house_material == HouseMaterial.STONE


def _apply(state: GameState, idx: int) -> GameState:
    # "each remaining round space" = rounds R+1..14 (1-indexed).
    R = state.round_number
    return schedule_resources(state, idx, range(R + 1, 15), Resources(food=3))


register_occupation(CARD_ID, lambda state, idx: state)   # the effect is the latch fire
register_conditional(CARD_ID, _condition, _apply)
