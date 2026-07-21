"""Brick Hammer (minor improvement, D80; Dulcinaria Expansion).

Card text: "Each time after you build an improvement costing at least 2 clay,
you get 1 stone."
Cost: 1 Wood / 1 Food (a printed ALTERNATIVE cost — pay ONE of them).
Prerequisite: none. Printed 0 VP. Not traveling. Category: Building Resource
Provider.

USER RULING (2026-07-20): "costing at least 2 clay" reads the PRINTED cost,
never the payment actually made. For an improvement with multiple printed
alternative costs, the benefit is paid if ANY alternative includes >=2 clay,
even when the player paid an alternative that does not. (Consequence: a Cooking
Hearth bought by returning a Fireplace still qualifies — its printed cost is
4/5 clay.)

Mechanism — an automatic effect on the coarse `after_build_improvement` event
(the Junk Room shape): fired at the build host's deferred after-flip with the
host frame on top, for both improvement kinds. The elig fn reads WHICH
improvement that frame built and checks its printed cost(s):

- `PendingPlayMinor` — `played_card_id` (stamped by the executor before the
  flip) → the `MinorSpec`'s printed alternatives `(cost,) + alt_costs`; a
  state-scaling `cost_fn` (never combined with alt_costs) is evaluated as the
  printed cost. Qualify iff any alternative's resources include >=2 clay.
- `PendingBuildMajor` — `built_major_idx`, stamped by `_execute_build_major`
  at the commit via the ownership-gated `register_build_major_identity` seam
  (this card is why the seam exists) → `MAJOR_IMPROVEMENT_COSTS[idx]`. The
  Cooking Hearths' printed RESOURCE cost (4/5 clay) qualifies; their
  return-a-Fireplace payment route is irrelevant per the ruling above.

"you build" = own builds only (`top.player_idx == owner`; the event already
routes to the acting player — the guard is belt-and-braces). On Brick Hammer's
own play the event fires with the card already in the tableau (the Junk Room
"including this one" firing point), but its own printed cost (1 wood / 1 food)
has no clay, so the predicate is False — no self-fire, with no special-casing.
"""
from __future__ import annotations

from agricola.cards.specs import MINORS, register_minor
from agricola.cards.triggers import register_auto, register_build_major_identity
from agricola.constants import MAJOR_IMPROVEMENT_COSTS
from agricola.pending import PendingBuildMajor, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "brick_hammer"


def _printed_costs_qualify(spec, state: GameState, idx: int) -> bool:
    """True iff any of the minor spec's PRINTED cost alternatives has >=2 clay
    (user ruling 2026-07-20 — printed cost, never the payment made)."""
    if spec.cost_fn is not None:
        # A scaling cost has no printed alternatives; its cost_fn IS the
        # printed cost, evaluated for the builder.
        return spec.cost_fn(state, idx).resources.clay >= 2
    return any(c.resources.clay >= 2 for c in (spec.cost,) + spec.alt_costs)


def _eligible(state: GameState, idx: int) -> bool:
    top = state.pending_stack[-1]
    if top.player_idx != idx:            # own builds only
        return False
    if isinstance(top, PendingPlayMinor) and top.played_card_id is not None:
        return _printed_costs_qualify(MINORS[top.played_card_id], state, idx)
    if isinstance(top, PendingBuildMajor) and top.built_major_idx is not None:
        return MAJOR_IMPROVEMENT_COSTS[top.built_major_idx].clay >= 2
    return False


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(stone=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# Cost is "1 Wood / 1 Food" — an ALTERNATIVE ("/") cost: pay EITHER 1 wood OR
# 1 food, not both (the Chophouse idiom).
register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1)),
    alt_costs=(Cost(resources=Resources(food=1)),),
)
register_auto("after_build_improvement", CARD_ID, _eligible, _apply)
register_build_major_identity(CARD_ID)
