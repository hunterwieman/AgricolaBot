"""Tree Farm Joiner (occupation, B96; Bubulcus Expansion; players 1+).

Card text: "Place 1 wood on each of the next 2 odd-numbered round spaces. At the
start of these rounds, you get the wood and, immediately afterward, a 'Minor
Improvement' action."
Cost: none. Prerequisite: none. VPs: none. Not passing. Played via Lessons.

Category 8 (deferred goods AND a deferred EFFECT). On play this schedules, on the
next two odd-numbered round spaces strictly after the current round:
1. **+1 wood** per round — riding on `future_resources` via `schedule_resources`
   (the same Well/Lumberjack structure), distributed at the start of that round.
2. **A round-start "Minor Improvement" action** — riding on `future_rewards` via
   `schedule_effect` (the FutureReward effect-hook tuple), exactly like Handplow's
   deferred plow. The scheduled card id is what this card's OPTIONAL
   `start_of_round` trigger checks for eligibility, and it also drives whether the
   PendingPreparation host is pushed that round
   (`triggers.has_scheduled_round_start_effect`) — so a played Tree Farm Joiner only
   hosts a preparation frame on its two scheduled rounds, NOT every round. It is
   therefore deliberately NOT registered via `register_start_of_round_hook`.

"the next 2 odd-numbered round spaces" = the two smallest odd integers strictly
greater than the current round. `schedule_resources` / `schedule_effect` silently
drop any round > 14 (the "remaining round spaces" clamp), so a late play schedules
fewer than two.

OPTIONALITY: "a Minor Improvement action" is the player's to take or decline (a
granted action is optional unless the text says "you must"), so it is modeled as an
OPTIONAL `start_of_round` trigger surfaced as a FireTrigger at the PendingPreparation
host — the host's Proceed IS the decline. `PendingPlayMinor` has no decline of its
own (it forces exactly one minor once pushed), so eligibility ALSO requires at least
one affordable hand minor (`legality.playable_minors`); otherwise a fired grant would
dead-end on an empty legal set.

WOOD-BEFORE-MINOR ORDERING is provided by `_complete_preparation`, which distributes
`future_resources` (the +1 wood) BEFORE `_fire_preparation_hook` surfaces the minor
trigger — so the wood is on hand to pay the minor, matching "you get the wood and,
immediately afterward, a Minor Improvement action."

Firing the trigger consumes the grant (removes this card id from the round's
`future_rewards` slot, mirroring Handplow) so it fires at most once per round, then
pushes the reusable `PendingPlayMinor` primitive.
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_effect, schedule_resources
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register
from agricola.legality import playable_minors
from agricola.pending import PendingPlayMinor, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "tree_farm_joiner"


def _next_two_odd_rounds(round_number: int) -> tuple[int, ...]:
    """The two smallest odd round numbers strictly greater than `round_number`.
    Rounds > 14 are kept here and dropped by the schedule helpers (the "remaining
    round spaces" clamp)."""
    rounds: list[int] = []
    r = round_number + 1
    while len(rounds) < 2:
        if r % 2 == 1:
            rounds.append(r)
        r += 1
    return tuple(rounds)


def _on_play(state: GameState, idx: int) -> GameState:
    rounds = _next_two_odd_rounds(state.round_number)
    # +1 wood per scheduled round, then the round-start minor-action grant. The two
    # write the same odd-round slots; schedule helpers drop rounds > 14.
    state = schedule_resources(state, idx, rounds, Resources(wood=1))
    return schedule_effect(state, idx, rounds, CARD_ID)


def _scheduled_slot(p, round_number: int):
    """The future_rewards slot index for `round_number` if it carries this card's
    grant, else None."""
    slot = round_number - 1
    fr = p.future_rewards
    if 0 <= slot < len(fr) and CARD_ID in fr[slot].effect_card_ids:
        return slot
    return None


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # Fire only on a scheduled round AND only when there is at least one affordable
    # hand minor (else PendingPlayMinor would dead-end on an empty legal set).
    p = state.players[idx]
    return (_scheduled_slot(p, state.round_number) is not None
            and len(playable_minors(state, idx)) > 0)


def _apply(state: GameState, idx: int) -> GameState:
    # Consume the grant (remove this card from the round's slot) so it fires once,
    # then push the optional minor play. The host's Proceed is the decline path.
    p = state.players[idx]
    slot = _scheduled_slot(p, state.round_number)
    reward = p.future_rewards[slot]
    new_reward = fast_replace(
        reward, effect_card_ids=reward.effect_card_ids - {CARD_ID})
    new_rewards = p.future_rewards[:slot] + (new_reward,) + p.future_rewards[slot + 1:]
    p = fast_replace(p, future_rewards=new_rewards)
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingPlayMinor(
        player_idx=idx, initiated_by_id="card:tree_farm_joiner"))


register_occupation(CARD_ID, _on_play)
register("start_of_round", CARD_ID, _eligible, _apply)
