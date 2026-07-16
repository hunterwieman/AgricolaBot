"""Syrup Tap (minor improvement, deck E #47; Ephipparius; cost 1 wood + 1 stone).

Card text: "Each time you get at least 1 wood from an action space, place 1 food
on the next round space. At the start of that round, you get the food." Printed
1 VP.

User ruling (2026-07-15): the ACTION SPACE ITSELF must provide the wood -- like
Kindling Gatherer, which detects food supplied BY the space and ignores food a
card deposits during the turn. Wood produced by a CARD effect during the turn
(e.g. Legworker) does NOT trigger this; only wood physically sitting on the space
being used counts.

Category 3 (action-space hook) on the wood-bearing accumulation spaces. Modeled
as an after_action_space auto: eligible when the acting player took at least 1 wood
from the space, read off the host frame's `taken` (the Resources delta stamped
across the take at Proceed). Because `taken` measures only the space's own take, it
captures exactly "the space itself supplied the wood" and ignores wood a card grants
elsewhere in the turn -- honoring the ruling. Forest is the normal activator (it
accumulates wood each round); the clay/reed/stone spaces are hooked too because a
card can deposit wood onto them -- the `taken.wood >= 1` gate keeps the auto silent
unless the take actually included wood. On a qualifying use, place a flat 1 food
(regardless of how much wood was taken) on the NEXT round space via the deferred-goods
schedule; the engine pays it out at that round's start. Because these spaces are
atomic, they must be explicitly hosted via `register_action_space_hook` or no
frame is pushed and the auto never fires. Played via an improvement space; its
effect is the hook, so on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "syrup_tap"
# Every accumulation space where wood could sit: Forest accumulates it normally;
# the others are hooked because a card can deposit wood onto them (the
# `.accumulated.wood >= 1` gate keeps the auto silent unless wood is present).
SPACES = frozenset(
    {"forest", "clay_pit", "reed_bank", "western_quarry", "eastern_quarry"})


def _eligible(state: GameState, idx: int) -> bool:
    top = state.pending_stack[-1]
    if top.space_id not in SPACES:
        return False
    return top.taken.wood >= 1


def _apply(state: GameState, idx: int) -> GameState:
    # Flat 1 food onto the next round space (1-indexed round_number + 1),
    # collected at that round's start.
    return schedule_resources(
        state, idx, [state.round_number + 1], Resources(food=1))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1, stone=1)), vps=1)
register_auto("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
