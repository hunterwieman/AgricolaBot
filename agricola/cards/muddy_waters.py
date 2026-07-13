"""Muddy Waters (minor improvement, E41; Ephipparius Expansion; Goods Provider).

Card text (verbatim): "Alternate placing 1 food and 1 clay on each remaining
even-numbered round space, starting with food. At the start of these rounds, you
get the respective good."
No cost. Prerequisite: 5 Cards in Play. VPs: 1.

Category 8 (deferred goods). The EVEN round spaces are 2, 4, 6, 8, 10, 12, 14;
"remaining" = those whose round has not yet begun (strictly after the current
round). Over that sequence, place 1 food / 1 clay alternately, starting with food
(so the 1st remaining even space gets food, the 2nd clay, ...). All ride on
`future_resources` via `schedule_resources`, collected at each round's start.

Prerequisite "5 Cards in Play" — a HAVE-check that the player has >= 5 of their
OWN played cards in front of them: occupations + minor improvements (built major
improvements are tiles, not cards — the Abort Oriel reading). Checked before this
card joins the tableau, so the player must already hold 5 (this becomes their
6th+); there is no "may be played as your 5th" clarification (contrast Abort
Oriel). User-confirmed 2026-07-13.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "muddy_waters"
_EVEN_ROUND_SPACES = (2, 4, 6, 8, 10, 12, 14)


def _prereq(state: GameState, idx: int) -> bool:
    p = state.players[idx]
    return len(p.occupations) + len(p.minor_improvements) >= 5


def _on_play(state: GameState, idx: int) -> GameState:
    remaining = [r for r in _EVEN_ROUND_SPACES if r > state.round_number]
    for i, rnd in enumerate(remaining):
        good = Resources(food=1) if i % 2 == 0 else Resources(clay=1)
        state = schedule_resources(state, idx, (rnd,), good)
    return state


register_minor(
    CARD_ID,
    prereq=_prereq,
    vps=1,
    on_play=_on_play,
)
