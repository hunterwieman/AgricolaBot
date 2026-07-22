"""Stable Planner (occupation, A89; Artifex Expansion; players 1+).

Card text: "Add 3, 6, and 9 to the current round. You can place 1 stable on each
corresponding round space. At the start of these rounds (not earlier), you can build
the stable at no cost."
Clarification: "Stables built this way are not built on your turn and do not trigger
Stable Tree A074 or Farmyard Manure A043."
Cost: none (occupation, played free via Lessons). No prereq / VPs / passing.

Category-8 deferred EFFECT (like Handplow): on play it schedules a round-start grant
onto three FUTURE rounds — R+3, R+6, R+9 — using `schedule_effect`, which unions this
card's id into each of those `future_rewards` slots. It places NO immediate goods.

"At the start of these rounds (not earlier), you can build the stable at no cost" is an
OPTIONAL granted sub-action: at each scheduled round start the owner MAY build exactly
one free stable, or decline (a stable consumes a farmyard cell that may be wanted
elsewhere, so it is not always correct). It is therefore modeled exactly like the
optional start-of-round stable grant Groom uses, but schedule-gated like Handplow:
an optional `round_space_collection` FireTrigger surfaced at that window's choice host, with
the host's Proceed as the decline. Eligibility checks (a) this round's `future_rewards`
slot carries the grant and (b) a free stable is actually buildable (`_can_build_stable`
with zero cost), so it never offers a dead-end. Firing consumes ONLY the entered
round's slot (so each of R+3 / R+6 / R+9 independently surfaces its own grant and fires
at most once) and pushes the reusable PendingBuildStables primitive at cost
`Resources()` (free), cap 1.

Like Handplow, hosting is schedule-driven (the trigger's own eligibility reads the
`future_rewards` slots) — eligibility-driven under the preparation ladder (ruling 54,
2026-07-14); it only hosts on R+3 / R+6 / R+9, the rounds its grant comes due.

OFF-TURN NOTE for future implementers: the clarification says stables built this way are
"not built on your turn" and must NOT trigger Stable Tree (A074) or Farmyard Manure
(A043). Neither of those is implemented today, so there is no `after_build_stables`
automatic effect that this card's PendingBuildStables push could spuriously fire — no
live impact. When Stable Tree / Farmyard Manure are implemented, they MUST gate on
on-turn vs off-turn (this push runs under a collection-window host at the stack
base, i.e. off-turn) and not fire on this card's stable build. (Sibling Groom, B89, named in
the same clarification, builds stables off-turn via the identical
window → PendingBuildStables path.)
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_effect
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register
from agricola.legality import _can_build_stable
from agricola.pending import PendingBuildStables, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "stable_planner"
_STABLE_COST = Resources()  # build the stable at no cost


def _on_play(state: GameState, idx: int) -> GameState:
    # "Add 3, 6, and 9 to the current round" → schedule the deferred free-stable grant
    # on rounds R+3, R+6, R+9 (slots past round 14 are silently dropped).
    R = state.round_number
    return schedule_effect(state, idx, (R + 3, R + 6, R + 9), CARD_ID)


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
        and _can_build_stable(state, p, _STABLE_COST)
    )


def _apply(state: GameState, idx: int) -> GameState:
    # Consume ONLY this round's slot (so the other scheduled rounds' grants survive and
    # each fires at most once), then push the optional free stable. Proceed = decline.
    p = state.players[idx]
    slot = _scheduled_slot(p, state.round_number)
    reward = p.future_rewards[slot]
    new_reward = fast_replace(
        reward, effect_card_ids=reward.effect_card_ids - {CARD_ID})
    new_rewards = p.future_rewards[:slot] + (new_reward,) + p.future_rewards[slot + 1:]
    p = fast_replace(p, future_rewards=new_rewards)
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingBuildStables(
        player_idx=idx, initiated_by_id="card:stable_planner",
        build_stables_action=False,  # user ruling 75, 2026-07-21: a card-effect build, not the named action (§9.6)
        cost=_STABLE_COST, max_builds=1))


register_occupation(CARD_ID, _on_play)
# "At the start of these rounds, you can [take the thing on the round
# space]" — the round_space_collection window (user ruling 2026-07-14:
# round-space schedule grants resolve at COLLECTION time, immediately
# after the mechanical collect, not at the start_of_round rung).
register("round_space_collection", CARD_ID, _eligible, _apply)
