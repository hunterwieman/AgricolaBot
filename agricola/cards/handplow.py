"""Handplow (minor improvement, A19; Base Revised).

Card text: "Add 5 to the current round and place 1 field tile on the corresponding
round space. At the start of that round, you can plow the field."
Cost: 1 Wood. Prerequisite: none. VPs: none. Not passing.

Category 8 (deferred EFFECT, the exotic case). Unlike the goods-scheduling
Category-8 cards, Handplow schedules a round-start EFFECT, not goods — so it rides
on `future_rewards` (the FutureReward effect-hook tuple), not `future_resources`.
On play it unions the card id "handplow" into the round R+5 slot
(`schedule_effect`). When round R+5 is entered, `engine._collect_future_rewards`
looks up this card's registered round-start effect (register_round_start_effect)
and runs `_round_start`, which pushes a PendingPlow for the owner — the plow then
sits on the WORK stack to be resolved before the owner places a worker.

"You can plow" (optional): the plow is gated on a plowable cell existing
(`_can_plow`). With a legal cell the plow is pushed (a free field is never a
downside, so the engine's commit-terminated PendingPlow is the faithful model);
with none, the schedule is a no-op that round — matching "you CAN plow". Plowing
the same field id repeatedly across rounds would stack, but Handplow schedules a
single round (R+5), so it fires at most once per play.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_effect
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_round_start_effect
from agricola.legality import _can_plow
from agricola.pending import PendingPlow, push
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "handplow"


def _on_play(state: GameState, idx: int) -> GameState:
    # "Add 5 to the current round" → schedule the deferred plow on round R+5.
    R = state.round_number
    return schedule_effect(state, idx, (R + 5,), CARD_ID)


def _round_start(state: GameState, idx: int) -> GameState:
    # Fired by _collect_future_rewards when the scheduled round is entered. Push the
    # plow primitive only if a plowable cell exists ("you can plow" → a no-op when
    # the farm leaves no legal cell).
    if not _can_plow(state.players[idx]):
        return state
    return push(state, PendingPlow(player_idx=idx, initiated_by_id="card:handplow"))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), on_play=_on_play)
register_round_start_effect(CARD_ID, _round_start)
