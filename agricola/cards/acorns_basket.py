"""Acorns Basket (minor improvement, B84; Base Revised; cost 1 reed).

Card text: "Place 1 wild boar on each of the 2 round spaces. At the start of these
rounds, you get the wild boar."
Cost: 1 Reed. Prerequisite: 3 Occupations. VPs: none. Not passing.

The "2 round spaces" are the NEXT 2 round spaces — rounds R+1 and R+2 (confirmed with
the maintainer, 2026-06-30). Category 8 (deferred goods), the ANIMAL variant: the boar
ride on the card-only `future_rewards` tuple (a `FutureReward.animals` slot per round),
and are collected + auto-accommodated at the start of each scheduled round by
`engine._collect_future_rewards` — the SAME `pareto_frontier`/`can_accommodate`
machinery the animal markets use (so 1 boar onto a default farm fits the house-pet
slot; an over-capacity grant would be trimmed deterministically, decision-free, as
preparation is decision-free). The whole effect runs at play (`on_play`).

The boar ride via the shared `schedule_animals` helper (the animal sibling of
`schedule_resources`), additive into the round R+1 and R+2 slots. See FutureReward in
state.py and CARD_AUTHORING_GUIDE.md §4 (deferred animals).
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_animals
from agricola.cards.specs import register_minor
from agricola.resources import Animals, Cost, Resources
from agricola.state import GameState

CARD_ID = "acorns_basket"


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    return schedule_animals(state, idx, (R + 1, R + 2), Animals(boar=1))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(reed=1)),
    min_occupations=3,          # "3 Occupations" prerequisite
    on_play=_on_play,
)
