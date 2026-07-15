"""Sheep Whisperer (occupation, B164; Base Revised; players 4+; Livestock Provider).

Card text (verbatim): "Add 2, 5, 8, and 10 to the current round and place 1 sheep
on each corresponding round space. At the start of these rounds, you get the sheep."
No clarifications / errata printed.

Category 8 (deferred goods), the ANIMAL variant — the Acorns Basket shape. At play
(`on_play`) it schedules 1 sheep onto the round spaces R+2, R+5, R+8, and R+10
(where R is the current round). The sheep ride the card-only `future_rewards`
tuple and are collected at the START of each scheduled round by
`engine._collect_future_rewards`, which grants them via `helpers.grant_animals`
(so an over-capacity farm surfaces a keep-which choice at the accommodation
barrier). `schedule_animals` clamps any target beyond round 14 to nothing (e.g.
played late, R+8 / R+10 may be past the game), matching "place on each
corresponding round space" for the rounds that still exist.

Played via Lessons; the whole effect runs at play. The `future_rewards` tuple is
empty in the Family game, so it stays byte-identical and the C++ gates are
untouched. See acorns_basket.py (the animal-schedule sibling) and schedules.py.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_animals
from agricola.cards.specs import register_occupation
from agricola.resources import Animals
from agricola.state import GameState

CARD_ID = "sheep_whisperer"

# "Add 2, 5, 8, and 10 to the current round".
_OFFSETS = (2, 5, 8, 10)


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    return schedule_animals(state, idx, tuple(R + d for d in _OFFSETS), Animals(sheep=1))


register_occupation(CARD_ID, _on_play)
