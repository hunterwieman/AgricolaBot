"""Grassland Harrow (minor improvement, B18; Bubulcus Expansion).

Card text: "Add 1 to the current round for each building resource in your supply and
place 1 field on the corresponding round space. At the start of the round, you can plow
the field."
Cost: 2 Wood. Prerequisite: 2 Occupations, 1 Building Resource in Your Supply.
VPs: none. Not passing.

This is Handplow (A19) with a VARIABLE round offset and two prerequisites. Handplow adds
a fixed 5; Grassland Harrow adds "1 for each building resource (wood + clay + reed +
stone) in your supply". Like Handplow it schedules a round-start EFFECT (a deferred,
optional plow), not goods — so it rides on `future_rewards` (the FutureReward effect-hook
tuple) via `schedule_effect`, NOT on `future_resources`.

Timing of the count. A minor's cost (here 2 wood) is debited BEFORE its `on_play` runs
(`resolution._execute_play_minor`), and "Add 1 ... for each building resource in your
supply ... and place 1 field" both happen at play. So `n` is counted over the supply that
REMAINS after paying the 2-wood cost — the natural reading (the wood you spent is no
longer "in your supply"). The field is placed on round `R + n`. With `n == 0` (the player
had nothing left after the cost) `schedule_effect` writes the already-entered current
round (`R + 0`), whose plow opportunity has passed — a wasted but legal play, matching the
rules; no special handling needed (the slot is simply never hosted again).

`schedule_effect` clamps slots to the 14-round game, so a field that would land on a round
past 14 is silently dropped ("place on the corresponding round space" — there is no space
past 14).

Prerequisites. `min_occupations=2` for the occupation-count, plus a custom predicate for
"≥1 building resource in your supply" (a HAVE-check over current resources at the moment of
play, distinct from the spent 2-wood cost).

"At the start of the round, you **can** plow" is OPTIONAL — a granted sub-action is the
player's to take or decline (a new field consumes a farmyard cell that may be wanted for a
pasture/stable). So, exactly like Handplow: an optional `start_of_round` trigger surfaced
as a FireTrigger at the start_of_round window's choice host, with the host's Proceed as
the decline.
Eligibility checks the SCHEDULE (the card id sits in this round's `future_rewards` slot)
plus a plowable cell (`_can_plow`, so it never offers a dead-end). Firing pushes the
reusable PendingPlow primitive and consumes the grant so it fires at most once.

The schedule itself drives hosting (the trigger's own eligibility
— the trigger's own eligibility reads the slot), so a played Grassland Harrow only hosts
a window frame on the round its plow comes due: hosting is eligibility-driven under the
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

CARD_ID = "grassland_harrow"


def _building_resources(p) -> int:
    """The count of building resources (wood + clay + reed + stone) in player `p`'s
    supply. Food / grain / vegetables are not building resources."""
    r = p.resources
    return r.wood + r.clay + r.reed + r.stone


def _prereq(state: GameState, idx: int) -> bool:
    """≥1 building resource in your supply (the printed prerequisite, beyond the
    occupation-count handled by `min_occupations`)."""
    return _building_resources(state.players[idx]) >= 1


def _on_play(state: GameState, idx: int) -> GameState:
    # "Add 1 to the current round for each building resource in your supply" → schedule
    # the deferred plow on round R + n (n counted AFTER the 2-wood cost was debited).
    R = state.round_number
    n = _building_resources(state.players[idx])
    return schedule_effect(state, idx, (R + n,), CARD_ID)


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
    # Consume the grant (remove this card from this round's slot) so it fires once, then
    # push the optional plow. The host's Proceed is the decline path.
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


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=2)),
    min_occupations=2,
    prereq=_prereq,
    on_play=_on_play,
)
register("start_of_round", CARD_ID, _eligible, _apply)
