"""Tasting (minor improvement, B63; Bubulcus Expansion; players -).

Card text: "Each time you use a "Lessons" action space, before paying the occupation cost,
you can exchange 1 grain for 4 food."

Cost 2 wood, 1 printed VP, no prerequisite, not passing.

An optional `before_play_occupation` trigger: each time you play an occupation (via Lessons,
Scholar, or any future route), BEFORE paying its cost, you MAY exchange 1 grain for 4 food.
The play-occupation host's before-phase already surfaces `before_play_occupation` triggers
(`_eligible_fire_triggers` in `legality.py`), so no new firing machinery is needed. Triggers
fire only for OWNED cards, and `_owns` covers minor improvements as well as occupations, so an
owned minor fires here exactly like the occupation Paper Maker. Once per play ("each time you
use Lessons", and a Lessons placement plays exactly one occupation) via the host's
`triggers_resolved`. The trade is gated on having >= 1 grain to exchange.

Because firing it produces food usable for the occupation's food cost, it ALSO registers an
OCCUPATION_FOOD_SOURCE: the affordability gate (`_legal_lessons_cards` / Scholar) consults it
via `_payable_occupation` (which checks `occupations | minor_improvements`, so minors qualify)
so an occupation payable only by firing Tasting first is still offered (else you'd never reach
the frame to fire it). The play-occupation enumerator's commit gate (`_payable(top.cost)`) then
withholds the commit until Tasting is fired, so there is no empty-frontier dead state.

It is NOT folded into a food-payment frame: grain liquidates to food at a fixed 1:1 rate (no
cooking improvement makes grain worth more), so 1 grain -> 4 food is a strict 4x value trade
that is never Pareto-dominated and must be offered even when you already have enough food
(exactly Paper Maker's "pure value trade" rationale). The source declares its input (1 grain)
so the gate's simulated liquidation reserves it. See PAY_FOOD_PLOW_CARDS.md /
FOOD_PAYMENT_DESIGN.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor, register_occupation_food_source
from agricola.cards.triggers import register
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "tasting"


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # Optional, offered when owned + not yet fired this play + you have a grain to exchange.
    return CARD_ID not in triggers_resolved and state.players[idx].resources.grain >= 1


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=(p.resources - Resources(grain=1) + Resources(food=4)))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _food_source(state: GameState, idx: int):
    """For the occupation-affordability gate: (food produced, inputs consumed) when firing is
    possible, else None. Used by `_payable_occupation` to simulate firing Tasting."""
    if state.players[idx].resources.grain < 1:
        return None
    return (4, Resources(grain=1))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2)), vps=1)
register("before_play_occupation", CARD_ID, _eligible, _apply)
register_occupation_food_source(CARD_ID, _food_source)
