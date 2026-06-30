"""Cattle Whisperer (occupation, C166; Consul Dirigens Expansion; printed players 4+).

Card text: "Add 5 and 8 to the current round and place 1 cattle on each corresponding
round space. At the start of these rounds, you get the cattle."

A Category-8 deferred-goods occupation, the ANIMAL variant (the cattle sibling of the
boar/resource schedulers). "Add 5 and 8 to the current round" is printed-board phrasing
for the two future round spaces R+5 and R+8, where R is the round the card is played
(`state.round_number`) — NOT the fixed rounds 5 and 8. One cattle is placed on each of
those two round spaces; the cattle are collected AND auto-accommodated (best
`pareto_frontier` point, decision-free) at the start of each scheduled round by
`engine._collect_future_rewards` — the SAME machinery the animal markets and Acorns
Basket use.

The cattle ride on the card-only `future_rewards` tuple (a `FutureReward.animals` slot
per round) via the shared `schedule_animals` helper, additive into the round R+5 and R+8
slots. `schedule_animals` is 1-indexed and silently drops any round outside 1..14, so a
late play (R >= 10 → R+5 = 15, or R >= 7 → R+8 > 14) places only on the round spaces that
still exist, correctly modeling "place on each corresponding round space" near game-end.

Played via Lessons; the on-play schedule IS the effect. No cost / prereq / vps / passing
— all occupation defaults. See FutureReward in state.py, the schedule_animals docstring,
and CARD_AUTHORING_GUIDE.md §4 (deferred animals). Acorns Basket (the minor) is the named
precedent; Estate Worker is the occupation+schedule precedent.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_animals
from agricola.cards.specs import register_occupation
from agricola.resources import Animals
from agricola.state import GameState

CARD_ID = "cattle_whisperer"


def _on_play(state: GameState, idx: int) -> GameState:
    # "Add 5 and 8 to the current round" → the two future round spaces R+5 and R+8.
    R = state.round_number
    return schedule_animals(state, idx, (R + 5, R + 8), Animals(cattle=1))


register_occupation(CARD_ID, _on_play)
