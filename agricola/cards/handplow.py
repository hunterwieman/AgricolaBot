"""Handplow (minor improvement, A19; Base Revised).

Card text: "Add 5 to the current round and place 1 field tile on the corresponding
round space. At the start of that round, you can plow the field."
Cost: 1 Wood. Prerequisite: none. VPs: none. Not passing.

Category 8 (deferred EFFECT, the exotic case). Unlike the goods-scheduling
Category-8 cards, Handplow schedules a round-start EFFECT, not goods — so it rides
on `future_rewards` (the FutureReward effect-hook tuple), not `future_resources`.
On play it unions the card id "handplow" into the round R+5 slot (`schedule_effect`).

"At the start of that round, you **can** plow" is OPTIONAL — a granted sub-action is
the player's to take or decline (a new field consumes a farmyard cell that may be
wanted for a pasture/stable, so plowing is not always correct). So Handplow is
modeled exactly like the other optional start-of-round plow grant, Plow Driver: an
optional `start_of_round` trigger surfaced as a FireTrigger at the PendingPreparation
host, with the host's Proceed as the decline. The difference from Plow Driver is the
gate: instead of "owns the card + lives in stone", Handplow's eligibility checks the
SCHEDULE — the card id sits in this round's `future_rewards` slot — plus a plowable
cell (`_can_plow`, so it never offers a dead-end). Firing pushes the reusable
PendingPlow primitive and consumes the grant (removes "handplow" from the slot) so it
fires at most once.

The schedule itself drives preparation hosting (see
`triggers.has_scheduled_round_start_effect` / `engine._fire_preparation_hook`), so a
played Handplow only hosts a preparation frame on the round its plow comes due — it is
deliberately NOT registered via `register_start_of_round_hook` (which would host every
round for the rest of the game).
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_effect
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.legality import _can_plow
from agricola.pending import PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "handplow"


def _on_play(state: GameState, idx: int) -> GameState:
    # "Add 5 to the current round" → schedule the deferred plow on round R+5.
    R = state.round_number
    return schedule_effect(state, idx, (R + 5,), CARD_ID)


def _scheduled_slot(p, round_number: int):
    """The future_rewards slot index for `round_number` if it carries this card's
    grant, else None."""
    slot = round_number - 1
    fr = p.future_rewards
    if 0 <= slot < len(fr) and CARD_ID in fr[slot].effect_card_ids:
        return slot
    return None


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    p = state.players[idx]
    return _scheduled_slot(p, state.round_number) is not None and _can_plow(p)


def _apply(state: GameState, idx: int) -> GameState:
    # Consume the grant (remove "handplow" from this round's slot) so it fires once,
    # then push the optional plow. The host's Proceed is the decline path.
    p = state.players[idx]
    slot = _scheduled_slot(p, state.round_number)
    reward = p.future_rewards[slot]
    new_reward = fast_replace(
        reward, effect_card_ids=reward.effect_card_ids - {CARD_ID})
    new_rewards = p.future_rewards[:slot] + (new_reward,) + p.future_rewards[slot + 1:]
    p = fast_replace(p, future_rewards=new_rewards)
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingPlow(player_idx=idx, initiated_by_id="card:handplow"))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), on_play=_on_play)
register("start_of_round", CARD_ID, _eligible, _apply)
