"""Horse-Drawn Boat (minor improvement, D41; Consul Dirigens Expansion).

Card text: "Alternate placing 1 food and 1 sheep on each remaining round space,
starting with food. At the start of these rounds, you get the respective good."
Cost: 2 Wood. Prerequisite: 3 Occupations. VPs: none. Not passing.

Category 8 (deferred goods), a MIXED resources + animals variant. "Each remaining
round space" = every round strictly after the current one (the current round's space
has already been collected) — rounds R+1 .. 14. The card ALTERNATES the good placed,
"starting with food": the FIRST remaining space (R+1) gets food, the next (R+2) gets a
sheep, then food, then sheep, and so on.

The alternation is anchored to POSITION in the remaining-round sequence, NOT to absolute
round parity. So with `remaining = [R+1, R+2, ..., 14]`:
  - `remaining[0::2]` (R+1, R+3, ...) get 1 food, and
  - `remaining[1::2]` (R+2, R+4, ...) get 1 sheep.
Tying food/sheep to `round % 2` would mis-assign every good and even flip the leading
good depending on whether the card is played on an odd or even round.

Mechanics:
  - The food rides `PlayerState.future_resources` (the Well-style goods schedule) via
    `schedule_resources`; it is added to the player's resources at the start of each
    scheduled round in `engine._complete_preparation`.
  - The sheep ride the card-only `PlayerState.future_rewards` (a `FutureReward.animals`
    slot per round) via `schedule_animals`; they are collected AND auto-accommodated
    (best `pareto_frontier` point, decision-free — the SAME machinery the animal markets
    use) at the start of each scheduled round by `engine._collect_future_rewards`. So
    the no-accommodation DEFER rule does not apply: 1 sheep onto a default farm fits the
    house-pet slot, and any over-capacity grant is trimmed deterministically.

The whole effect runs at play (`on_play`). See `schedules.py`, Acorns Basket (the
animal half) and Sack Cart / Thick Forest (the "remaining round space" half).
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_animals, schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Animals, Cost, Resources
from agricola.state import GameState

CARD_ID = "horse_drawn_boat"


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    remaining = list(range(R + 1, 15))     # each REMAINING round space (R+1 .. 14)
    food_rounds = remaining[0::2]          # starting with food: R+1, R+3, ...
    sheep_rounds = remaining[1::2]         # then sheep: R+2, R+4, ...
    state = schedule_resources(state, idx, food_rounds, Resources(food=1))
    state = schedule_animals(state, idx, sheep_rounds, Animals(sheep=1))
    return state


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=2)),
    min_occupations=3,                     # "3 Occupations" prerequisite
    on_play=_on_play,
)
