"""Brewing Water (minor improvement, B60; Bubulcus Expansion).

Card text: "Each time you use the 'Fishing' accumulation space, you can pay 1 grain
to place 1 food on each of the next 6 round spaces. At the start of these rounds,
you get the food."
Cost: none. Prerequisite: none. VPs: none. Not passing.

A Herring Pot (B47) sibling — both bare "each time you use the Fishing accumulation
space" cards — but with an OPTIONAL, cost-bearing fire: it surfaces as a declinable
`FireTrigger` ("you CAN pay 1 grain"), not a forced automatic effect. Mechanically it
combines two shapes already in the codebase:

- The fishing action-space hook (Herring Pot): "each time you use [Fishing]" fires on
  the space's `before_action_space` event per the Trigger-Timing ruling (a bare "each
  time you use [space]", no "immediately after", is BEFORE the space's own effect).
  Fishing is an atomic space, so `register_action_space_hook` is required for the
  PendingActionSpace host frame to surface the trigger.
- The optional cost-bearing trigger (Ox Goad): the optionality IS the FireTrigger —
  declining is the host's Proceed (not firing). Once fired, the 1-grain pay is
  mandatory, so eligibility gates on grain >= 1 to never offer a dead-end, and on the
  engine's `triggers_resolved` for once-per-use. Grain is a plain resource (not food),
  so the debit is a direct subtraction — no PendingFoodPayment / resume needed.

The effect debits 1 grain, then schedules 1 food onto each of the NEXT 6 round spaces
(rounds R+1..R+6) of `future_resources`; `schedule_resources` silently clamps slots
past round 14, so "the next 6 round spaces" near game end is handled correctly. We
also skip the fire in the final round (no future rounds remain to place food on), so
the grain is never paid for zero food. See CARD_IMPLEMENTATION_PLAN.md Category 8.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_action_space_hook
from agricola.constants import NUM_ROUNDS
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "brewing_water"
SPACES = frozenset({"fishing"})


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                      # once per use
        return False
    if state.pending_stack[-1].space_id not in SPACES:
        return False
    if state.players[idx].resources.grain < 1:            # the pay is mandatory once fired
        return False
    # In the final round there are no future round spaces to place food on, so a fire
    # would spend 1 grain for 0 food — never offer it.
    return state.round_number < NUM_ROUNDS


def _apply(state: GameState, idx: int) -> GameState:
    # Pay 1 grain (a plain resource), then place 1 food on each of the next 6 round
    # spaces (rounds R+1..R+6); schedule_resources clamps any slot past round 14.
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources - Resources(grain=1))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    R = state.round_number
    return schedule_resources(state, idx, range(R + 1, R + 7), Resources(food=1))


register_minor(CARD_ID, cost=Cost())
register("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
