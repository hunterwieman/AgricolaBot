"""Cesspit (minor improvement, D40; Dulcinaria Expansion; players -).

Card text: "Alternate placing 1 clay and 1 wild boar on each remaining round space,
starting with clay. At the start of these rounds, you get the respective good."
Cost: none. Prerequisite: 2 Fields and 1 Occupation. VPs: -1. Not passing.

Category 8 (deferred goods), combining the resource sibling (`schedule_resources`,
clay) and the animal sibling (`schedule_animals`, wild boar). On play, the goods are
spread over every REMAINING round space — rounds R+1 .. 14 — ALTERNATING clay, boar,
clay, boar, … with the FIRST remaining space (R+1) getting clay ("starting with clay").

The alternation is over the SEQUENCE of remaining round spaces, NOT over even/odd round
NUMBERS: the n-th remaining space (0-indexed) gets clay when n is even and a boar when n
is odd. So we key on the enumerate-index of `range(R + 1, 15)`, never on the round number's
own parity (R varies, so round-number parity would flip the assignment depending on when
the card is played).

- The clay rides on `PlayerState.future_resources` and is collected at the start of each
  scheduled round by `engine._complete_preparation` (`schedule_resources` writes slot
  `r-1`, the engine's Well index convention, and silently drops rounds > 14).
- The boar ride on `PlayerState.future_rewards` (the card-only animal slot) and are
  collected at the start of each scheduled round by `engine._collect_future_rewards`,
  which grants them via `helpers.grant_animals` — the same path Acorns Basket uses, so
  1 boar onto a default farm fits the house-pet slot. On a full farm the accommodation
  barrier surfaces a keep-which choice at the round's first worker placement.

`vps=-1` is the printed penalty (scored when the card is kept; cf. Brewery Pond / Mantlepiece).
The whole effect runs at play (`on_play`); no on-going trigger.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_animals, schedule_resources
from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.resources import Animals, Cost, Resources
from agricola.state import GameState

CARD_ID = "cesspit"


def _prereq_two_fields(state: GameState, idx: int) -> bool:
    """At least 2 FIELD cells (any field tiles; no crop required, unlike Ash Trees)."""
    grid = state.players[idx].farmyard.grid
    fields = sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type is CellType.FIELD
    )
    return fields >= 2


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    remaining = range(R + 1, 15)            # every remaining round space, R+1 .. 14
    clay_rounds = [rnd for n, rnd in enumerate(remaining) if n % 2 == 0]  # 1st, 3rd, … (clay first)
    boar_rounds = [rnd for n, rnd in enumerate(remaining) if n % 2 == 1]  # 2nd, 4th, …
    state = schedule_resources(state, idx, clay_rounds, Resources(clay=1))
    state = schedule_animals(state, idx, boar_rounds, Animals(boar=1))
    return state


register_minor(
    CARD_ID,
    cost=Cost(),                # no resource cost (card JSON cost=null)
    min_occupations=1,          # "1 Occupation" prerequisite
    prereq=_prereq_two_fields,  # "2 Fields" prerequisite
    vps=-1,                     # printed penalty
    on_play=_on_play,
)
