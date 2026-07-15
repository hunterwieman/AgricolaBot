"""Land Heir (occupation, E119; Ephipparius Expansion; players 1+).

Card text: "If you play this card in round 4 or before, place 4 wood and 4 clay
on the space for round 9. At the start of this round, you get the resources."

Category 8 (deferred goods on a round space), with a play-time round gate: the
whole effect is conditional on WHEN the card is played. Played while
`round_number <= 4` (the play happens during that round's WORK phase, so the
current round number IS the round it is played in), the on-play schedules
4 wood + 4 clay onto the round-9 space (`future_resources` slot 8), collected
at the start of round 9 by the preparation ladder's collection step. Played in
round 5 or later, the condition fails and the card does nothing — it is still
playable (occupations are played via Lessons; there is no prerequisite), it
just places nothing.

Round 9 is strictly in the future whenever the gate passes (played rounds 1-4),
so the schedule slot always exists. No cost / prereq / vps / passing — all
defaults; the round-gated schedule is the entire effect. Choice-free.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_occupation
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "land_heir"

_TARGET_ROUND = 9
_LAST_ELIGIBLE_ROUND = 4


def _on_play(state: GameState, idx: int) -> GameState:
    # "If you play this card in round 4 or before": the gate reads the round the
    # play happens in. Round 5+ → the condition fails, nothing is placed.
    if state.round_number > _LAST_ELIGIBLE_ROUND:
        return state
    return schedule_resources(
        state, idx, (_TARGET_ROUND,), Resources(wood=4, clay=4))


register_occupation(CARD_ID, _on_play)
