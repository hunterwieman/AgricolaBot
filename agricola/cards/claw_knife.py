"""Claw Knife (minor improvement, A46; Artifex Expansion).

Card text: "Each time you use the 'Sheep Market' accumulation space, place 1 food
on each of the next 2 round spaces. At the start of these rounds, you get the food."
Cost: 1 Wood. Prerequisite: Exactly 1 Pasture. VPs: none. Not passing.

Category 8 (deferred goods) on a non-atomic action-space hook — the same shape as
Herring Pot (Fishing) but on `sheep_market` and scheduling 2 rounds instead of 3.
"Each time you use Sheep Market" → the `before_action_space` event, per the
Trigger-Timing ruling (a bare "each time you use [space]" fires BEFORE the space's
own effect — the same phase as Milk Jug / Herring Pot). Sheep Market is non-atomic
and self-hosts: `_initiate_sheep_market` pushes PendingSheepMarket and then itself
calls `apply_auto_effects(state, "before_action_space", ap)`, so NO
`register_action_space_hook` is needed (that index only gates the conditional
hosting of ATOMIC spaces — verified against Milk Jug's Cattle Market precedent).

NO `any_player` — "each time YOU use" fires for the owner only.

The "Exactly 1 Pasture" prerequisite is a PLAY-TIME have-check (consumed via
`prereq_met` in legality.py), NOT a per-use trigger condition: once Claw Knife is
played, the Sheep Market hook fires unconditionally regardless of the owner's later
pasture count. The effect schedules 1 food onto the next 2 round spaces (rounds
R+1..R+2) of `future_resources` per use; `schedule_resources` clamps slots outside
1..14, so late-game uses silently drop out-of-range round spaces ("each REMAINING
round space"). On-play is a no-op (the schedule is the per-use hook).
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "claw_knife"


def _prereq(state: GameState, idx: int) -> bool:
    # Exactly 1 pasture (the canonical BFS-derived enclosed-component decomposition).
    return len(state.players[idx].farmyard.pastures) == 1


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id == "sheep_market"


def _apply(state: GameState, idx: int) -> GameState:
    R = state.round_number
    return schedule_resources(state, idx, range(R + 1, R + 3), Resources(food=1))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), prereq=_prereq)
register_auto("before_action_space", CARD_ID, _eligible, _apply)
