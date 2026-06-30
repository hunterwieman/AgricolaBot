"""Corn Schnapps Distillery (minor improvement, C64; Corbarius Expansion; players -).

Card text: "Once per round, you can pay 1 grain to place 1 food on each of the next 4
round spaces. At the start of these rounds, you get the food."
Cost: 1 Wood, 2 Clay. Prerequisite: none. VPs: 1. Not passing.

Category 7 (start-of-round phase hook) + Category 8 (deferred goods). The recurring
clause is an OPTIONAL, once-per-round paid grant — "you CAN pay" is the player's choice,
so it is a declinable `register` trigger (NOT a choiceless `register_auto`); declining is
simply not firing it (the PendingPreparation host's Proceed). There is no on-play effect;
the whole card is the round-start trigger, hosted every round via
`register_start_of_round_hook` (like Plow Driver / Groom — a persistent every-round host,
NOT a schedule-gated single host).

Firing it (`_apply`) pays 1 grain, latches `used_this_round` (II.3, so it fires at most
once per round), and schedules 1 food onto each of the NEXT 4 round spaces via
`schedule_resources(... range(R+1, R+5) ...)` — the food rides on the player's
`future_resources` slots and is collected at the START of each of those rounds by
`engine._complete_preparation` step 2 ("At the start of these rounds, you get the food").
Rounds past 14 are silently dropped by `schedule_resources`'s clamp ("each of the next 4
round spaces" that still exist).

The "once per round" latch resets automatically: `engine._complete_preparation` clears
`used_this_round` (step 3) BEFORE `_fire_preparation_hook` surfaces this round's
`start_of_round` triggers (step 5), so the grant is available again each round.

Cost is plain grain (a real `Resources` field), so `_apply` debits `Resources(grain=1)`
directly — no `PendingFoodPayment` liquidation path (unlike Plow Driver's food cost).
Eligibility requires `grain >= 1` so the trigger is never offered as a dead-end. Played
via Lessons / a minor-improvement entry point; card-only (the schedule fields are
unrestricted-default skip-fields), so the Family game is byte-identical. See
CARD_IMPLEMENTATION_PLAN.md Category 7 / Category 8 and agricola/cards/schedules.py.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_start_of_round_hook
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "corn_schnapps_distillery"
_GRAIN_COST = 1
_FOOD_PER_ROUND = Resources(food=1)
_N_ROUNDS = 4


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    p = state.players[idx]
    return (CARD_ID not in p.used_this_round
            and p.resources.grain >= _GRAIN_COST)


def _apply(state: GameState, idx: int) -> GameState:
    # Pay 1 grain, latch once-per-round, schedule 1 food onto the next 4 round spaces
    # (rounds R+1..R+4; rounds past 14 are dropped by schedule_resources's clamp).
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources - Resources(grain=_GRAIN_COST),
        used_this_round=p.used_this_round | {CARD_ID},
    )
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    R = state.round_number
    return schedule_resources(
        state, idx, range(R + 1, R + 1 + _N_ROUNDS), _FOOD_PER_ROUND)


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1, clay=2)),
    vps=1,
)  # no on-play effect — the recurring effect is the start_of_round trigger
register("start_of_round", CARD_ID, _eligible, _apply)
register_start_of_round_hook(CARD_ID)
