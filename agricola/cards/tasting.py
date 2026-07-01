"""Tasting (minor improvement, B63; Bubulcus Expansion; players -).

Card text: "Each time you use a "Lessons" action space, before paying the occupation cost,
you can exchange 1 grain for 4 food."

Cost 2 wood, 1 printed VP, no prerequisite, not passing.

An OPTIONAL trigger scoped to the LESSONS action space: each time you USE the Lessons
action space, before the occupation cost is paid, you MAY exchange 1 grain for 4 food.

WHY `before_action_space`, NOT `before_play_occupation`. The text scopes the exchange to
"a 'Lessons' action space" — it fires per *use of Lessons*, not per occupation played. The
card was originally registered on the generic `before_play_occupation` event, which fires
at the before-phase of EVERY `PendingPlayOccupation` frame no matter what created it: not
only Lessons, but also Scholar (a start-of-round occupation play), Teacher's Desk (an
occupation played off the Major Improvement / House Redevelopment spaces), and Writing Desk.
That over-fired the card on non-Lessons plays, granting a grain->food exchange the card does
not entitle. The fix models it as a Lessons-scoped action-space trigger.

Lessons is a NON-atomic space already hosted by a Delegating `PendingSubActionSpace`
(`initiated_by_id="space:lessons"`, so `space_id == "lessons"`); its before-phase enumerator
(`_enumerate_pending_subactionspace`) surfaces `before_action_space` triggers ahead of the
mandatory `ChooseSubAction("play_occupation")` that computes and pays the occupation cost.
So a single `register("before_action_space", ...)` gated on the host frame's
`space_id == "lessons"` fires exactly once per Lessons use, before the cost — matching the
text — and the same host is NOT reached by Scholar / Teacher's Desk / Writing Desk (those
push a `PendingPlayOccupation` directly, never the Lessons host), so the over-fire is gone.
Because Lessons is already hosted, NO `register_action_space_hook` is needed (that is for
atomic spaces that must be given a host to be hookable; contrast Cottager, which hosts the
atomic Day Laborer space). This mirrors Teacher's Desk (`agricola/cards/teachers_desk.py`),
which gates the identical way on its two spaces.

OPTIONAL (`register`, not `register_auto`) — "you can exchange". The decline path is simply
NOT firing: the player takes the host's mandatory `ChooseSubAction("play_occupation")`
instead, which closes the before-window (no SkipTrigger; optionality lives at the parent
host). Once-per-use is enforced by the host frame's `triggers_resolved` (checked in
`_eligible`). The trade is gated on having >= 1 grain to exchange.

Because firing it produces food usable for the occupation's food cost, it ALSO registers an
OCCUPATION_FOOD_SOURCE: the Lessons affordability gate (`_legal_lessons_cards`) consults it
via `_payable_occupation` (which checks `occupations | minor_improvements`, so minors qualify),
so an occupation payable only by firing Tasting first is still offered at placement time (else
you'd never reach the space to fire it). That registration is timing-agnostic — it simulates
the exchange to decide affordability — so it is unchanged by moving the trigger to the Lessons
host.

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

# The action-space host this card fires on, keyed by the host frame's `space_id`.
_SPACES = frozenset({"lessons"})


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # Scoped to the Lessons host (not the generic play-occupation before-phase). Optional,
    # offered when: it is the Lessons action-space host + not yet fired this use (the host's
    # `triggers_resolved`) + you have a grain to exchange.
    if CARD_ID in triggers_resolved:
        return False
    if getattr(state.pending_stack[-1], "space_id", None) not in _SPACES:
        return False
    return state.players[idx].resources.grain >= 1


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
register("before_action_space", CARD_ID, _eligible, _apply)
register_occupation_food_source(CARD_ID, _food_source)
