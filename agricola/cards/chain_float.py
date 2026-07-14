"""Chain Float (minor improvement, B20; Bubulcus Expansion).

Card text: "Add 7, 8, and 9 to the current round and place 1 field on each
corresponding round space. At the start of these rounds, you can plow the field."
Cost: 3 Wood. Prerequisite: none. VPs: none. Not passing.

This is Handplow (A19) repeated across THREE round spaces. Handplow adds a fixed 5 to
the current round and schedules one deferred plow; Chain Float adds 7, 8, and 9 to the
current round — i.e. offsets R+7, R+8, R+9 (the current round number plus each, exactly
parallel to Handplow's "Add 5 to the current round" = R+5; NOT fixed rounds 7/8/9) — and
schedules a deferred plow on each. Like Handplow it schedules round-start EFFECTS (the
optional plows), not goods — so each rides on `future_rewards` (the FutureReward
effect-hook tuple) via `schedule_effect`, NOT on `future_resources`.

`schedule_effect` clamps slots to the 14-round game, so a field that would land on a
round past 14 is silently dropped ("place on each corresponding round space" — there is
no space past 14). Played late enough that all three offsets exceed 14, the card is a
wasted but legal play.

"At the start of these rounds, you **can** plow" is OPTIONAL — a granted sub-action is
the player's to take or decline (a new field consumes a farmyard cell that may be wanted
for a pasture/stable). So, exactly like Handplow: an optional `start_of_round` trigger
surfaced as a FireTrigger at the start_of_round window's choice host, with the host's
Proceed as the decline. Eligibility checks the SCHEDULE (the card id sits in the entered round's
`future_rewards` slot) plus a plowable cell (`_can_plow`, so it never offers a dead-end).

The three rounds are handled with NO three-round-specific code: `_apply` consumes ONLY
the current round's slot (`_scheduled_slot(p, state.round_number)`), so firing the grant
on round R+7 leaves the R+8 and R+9 slots intact for those later rounds. The per-round
slot scoping makes each scheduled round fire its own grant independently, at most once.

The schedule itself drives preparation hosting
(the trigger's own eligibility reads the slot), so a played Chain Float only hosts a
window frame on the rounds its plows come due — hosting is eligibility-driven under the
preparation ladder (ruling 54, 2026-07-14), with no ownership index.
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

CARD_ID = "chain_float"


def _on_play(state: GameState, idx: int) -> GameState:
    # "Add 7, 8, and 9 to the current round" → schedule a deferred plow on each of
    # rounds R+7, R+8, R+9. schedule_effect silently drops any slot past round 14.
    R = state.round_number
    return schedule_effect(state, idx, (R + 7, R + 8, R + 9), CARD_ID)


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
    # Consume ONLY this round's grant (remove this card from the current round's slot)
    # so the other two scheduled rounds keep their grants, then push the optional plow.
    # The host's Proceed is the decline path.
    p = state.players[idx]
    slot = _scheduled_slot(p, state.round_number)
    reward = p.future_rewards[slot]
    new_reward = fast_replace(
        reward, effect_card_ids=reward.effect_card_ids - {CARD_ID})
    new_rewards = p.future_rewards[:slot] + (new_reward,) + p.future_rewards[slot + 1:]
    p = fast_replace(p, future_rewards=new_rewards)
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingPlow(player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=3)), on_play=_on_play)
register("start_of_round", CARD_ID, _eligible, _apply)
