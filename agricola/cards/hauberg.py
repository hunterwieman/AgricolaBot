"""Hauberg (minor improvement, B41; Bubulcus Expansion; Goods Provider).

Card text (verbatim): "Alternate placing 2 wood and 1 wild boar on the next 4
round spaces. You decide what to start with. At the start of these rounds, you
get the goods."
Cost: 3 Food. Prerequisite: 3 Occupations. No printed VPs.

Category 8 (deferred goods) with a play-time ORDER choice. The next 4 round
spaces (R+1..R+4) alternate between "2 wood" and "1 wild boar"; the player
decides which to start with. Per the user (2026-07-13) that choice is surfaced
WIDE — two plays at the improvement-space selection, "Hauberg (wood first)" /
"Hauberg (boar first)" — via `register_play_minor_variant`. Both variants carry a
ZERO surcharge: the 3-food cost is the card's ordinary (cost-modifier-visible)
base cost; the variant only picks the schedule ordering.

The wood rides on `future_resources` (`schedule_resources`); the boar on the
card-only `future_rewards` (`schedule_animals`), collected at each round's start
and reconciled by the accommodation barrier if it overflows (the Acorns Basket
boar pattern). Round spaces beyond round 14 are dropped by the helpers ("the next
4", remaining ones).
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_animals, schedule_resources
from agricola.cards.specs import register_minor, register_play_minor_variant
from agricola.resources import Animals, Cost, Resources
from agricola.state import GameState

CARD_ID = "hauberg"


def _variants(state: GameState, idx: int) -> list:
    return [("wood_first", Resources()), ("boar_first", Resources())]


def _on_play(state: GameState, idx: int, variant: str) -> GameState:
    R = state.round_number
    wood_first = variant == "wood_first"
    for offset, rnd in enumerate(range(R + 1, R + 5)):
        # offset 0,2 hold the "start" good; 1,3 the other. So the start good is
        # wood iff wood_first, alternating each step.
        place_wood = ((offset % 2 == 0) == wood_first)
        if place_wood:
            state = schedule_resources(state, idx, (rnd,), Resources(wood=2))
        else:
            state = schedule_animals(state, idx, (rnd,), Animals(boar=1))
    return state


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=3)),
    min_occupations=3,
    on_play=_on_play,
)
register_play_minor_variant(CARD_ID, _variants)
