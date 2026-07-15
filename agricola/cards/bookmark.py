"""Bookmark (minor improvement, E28; Ephipparius Expansion; Actions Booster).

Card text (verbatim): "Add 3 to the current round and mark the corresponding round
space. At the start of that round, you can play 1 occupation without paying an
occupation cost."
Cost: 1 Wood. Prerequisite: none. VPs: none. Not passing.

Category 8 (deferred EFFECT), the Handplow shape — a scheduled round-start GRANT,
not goods, so it rides on `future_rewards` (the effect-hook tuple), not
`future_resources`. On play, "add 3 to the current round and mark the corresponding
round space" schedules this card's grant onto round R+3 via `schedule_effect`
(unioning "bookmark" into that round's `future_rewards` slot).

"At the start of that round, you can play 1 occupation without paying an occupation
cost" is an OPTIONAL grant — a free occupation play the owner may take or decline.
Modeled exactly like Handplow's deferred optional grant and Seed Researcher's free
occupation play combined: an optional `round_space_collection` trigger (surfaced as
a FireTrigger at that window's choice host, with the host's Proceed as the decline
— user ruling 2026-07-14: round-space schedule grants resolve at COLLECTION time).

Eligibility checks (a) this round's `future_rewards` slot carries the grant AND (b)
a playable hand occupation exists (`playable_occupations` non-empty), so it never
offers a dead-end. Firing consumes the grant (removes "bookmark" from the slot) so
it fires at most once, then pushes `PendingPlayOccupation(cost=Resources())` — the
empty cost, so `_execute_play_occupation` debits nothing ("without paying an
occupation cost", the Scholar / Seed Researcher free-play precedent). Hosting is
schedule-driven (the trigger's own eligibility reads the slot), so a played Bookmark
only hosts a window frame on round R+3, the round its grant comes due.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_effect
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.legality import playable_occupations
from agricola.pending import PendingPlayOccupation, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "bookmark"


def _on_play(state: GameState, idx: int) -> GameState:
    # "Add 3 to the current round" -> schedule the deferred free-occupation grant on
    # round R+3 (a slot past round 14 is silently dropped by schedule_effect).
    R = state.round_number
    return schedule_effect(state, idx, (R + 3,), CARD_ID)


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
    return (
        _scheduled_slot(p, state.round_number) is not None
        and bool(playable_occupations(state, idx))
    )


def _apply(state: GameState, idx: int) -> GameState:
    # Consume the grant (remove "bookmark" from this round's slot) so it fires once,
    # then push the FREE occupation play (cost=Resources()). Proceed = decline.
    p = state.players[idx]
    slot = _scheduled_slot(p, state.round_number)
    reward = p.future_rewards[slot]
    new_reward = fast_replace(
        reward, effect_card_ids=reward.effect_card_ids - {CARD_ID})
    new_rewards = p.future_rewards[:slot] + (new_reward,) + p.future_rewards[slot + 1:]
    p = fast_replace(p, future_rewards=new_rewards)
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingPlayOccupation(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}", cost=Resources()))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), on_play=_on_play)
# "At the start of that round, you can play 1 occupation ..." — the
# round_space_collection window (schedule grants resolve at COLLECTION time).
register("round_space_collection", CARD_ID, _eligible, _apply)
