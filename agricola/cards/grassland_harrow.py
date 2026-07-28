"""Grassland Harrow (minor improvement, B18; Bubulcus Expansion).

Card text: "Add 1 to the current round for each building resource in your supply and
place 1 field on the corresponding round space. At the start of the round, you can plow
the field."
Cost: 2 Wood. Prerequisite: 2 Occupations, 1 Building Resource in Your Supply **After
Payment**. VPs: none. Not passing.

TRANSCRIPTION CORRECTED (user, 2026-07-27): the catalog JSON had transcribed the
prerequisite as "1 Building Resource in Your Supply", dropping the physical card's
"After Payment" qualifier; the row in `revised_minor_improvements.json` was corrected
against the physical card and this module rebuilt on the corrected text.

This is Handplow (A19) with a VARIABLE round offset. Handplow adds a fixed 5; Grassland
Harrow adds "1 for each building resource (wood + clay + reed + stone) in your supply".
Like Handplow it schedules a round-start EFFECT (a deferred, optional plow), not goods —
so it rides on `future_rewards` (the FutureReward effect-hook tuple) via
`schedule_effect`, NOT on `future_resources`.

THE POST-PAYMENT PREREQUISITE is a per-PAYMENT gate, not a pre-play HAVE-check: whether
"1 building resource remains after payment" depends on WHICH payment is chosen (paying
the printed 2 wood from exactly 2 wood leaves zero; paying Wood Expert's 1-food
substitution from the same supply leaves both wood). So the play is legal iff SOME
payment's post-debit state keeps >= 1 building resource, and ONLY qualifying payments
are offered at the commit — the `register_play_minor_payment_gate` seam (built for this
card, user ruling 2026-07-27; the minor-side analog of the occupation (variant x
payment) pair-gate). The gate is consulted on the simulated post-debit state at
enumeration and, when the payment's food is short, per liquidation bundle at the
PendingFoodPayment frame — so a bundle whose post-resume state fails it is withheld
too. The occupation-count half of the prerequisite stays an ordinary pre-play check
(`min_occupations=2`).

Timing of the count. A minor's cost (here 2 wood, or a converted payment) is debited
BEFORE its `on_play` runs (`resolution._execute_play_minor`), and "Add 1 ... for each
building resource in your supply ... and place 1 field" both happen at play. So `n` is
counted over the supply that REMAINS after paying the cost — the same post-payment
supply the corrected prerequisite reads, which guarantees `n >= 1`: the n == 0
wasted-play case the pre-correction module documented is unreachable (a play leaving
zero building resources is simply not offered). The field is placed on round `R + n`.

`schedule_effect` clamps slots to the 14-round game, so a field that would land on a
round past 14 is silently dropped ("place on the corresponding round space" — there is
no space past 14).

"At the start of the round, you **can** plow" is OPTIONAL — a granted sub-action is the
player's to take or decline (a new field consumes a farmyard cell that may be wanted for a
pasture/stable). So, exactly like Handplow: an optional `round_space_collection` trigger surfaced
as a FireTrigger at the collection window's choice host, with the host's Proceed as
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
from agricola.cards.specs import register_minor, register_play_minor_payment_gate
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


def _payment_ok(post_state: GameState, idx: int, payment) -> bool:
    """The corrected prerequisite "1 Building Resource in Your Supply After Payment"
    (per-payment gate — user ruling 2026-07-27): the simulated post-debit supply must
    keep >= 1 building resource. `post_state` is the state after the chosen payment
    (and, on the food-short path, the liquidation bundle) has been applied."""
    return _building_resources(post_state.players[idx]) >= 1


def _on_play(state: GameState, idx: int) -> GameState:
    # "Add 1 to the current round for each building resource in your supply" → schedule
    # the deferred plow on round R + n. The executor debits the cost before on_play
    # runs, so n reads the POST-PAYMENT supply — the same supply the corrected
    # prerequisite gates on, hence n >= 1 on every reachable play.
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
    on_play=_on_play,
)
# The building-resource half of the prerequisite is POST-PAYMENT (corrected
# transcription, user 2026-07-27) — a per-payment gate, not a `prereq=` HAVE-check.
register_play_minor_payment_gate(CARD_ID, _payment_ok)
# "At the start of these rounds, you can [take the thing on the round
# space]" — the round_space_collection window (user ruling 2026-07-14:
# round-space schedule grants resolve at COLLECTION time, immediately
# after the mechanical collect, not at the start_of_round rung).
register("round_space_collection", CARD_ID, _eligible, _apply)
