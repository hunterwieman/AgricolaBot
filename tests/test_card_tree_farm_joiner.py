"""Tests for Tree Farm Joiner (occupation, B96; Bubulcus Expansion).

Card text: "Place 1 wood on each of the next 2 odd-numbered round spaces. At the
start of these rounds, you get the wood and, immediately afterward, a 'Minor
Improvement' action."

On play it schedules, for the next two odd-numbered rounds strictly after the current
round: +1 wood (rides on `future_resources`) AND a round-start grant (rides on
`future_rewards`, like Handplow). At the start of each scheduled round the player gets
the wood (distributed before the hook fires) and an OPTIONAL Minor Improvement action
surfaced as a `FireTrigger` at the PendingPreparation host — the host's `Proceed` is
the decline. The grant is eligible only when at least one hand minor is playable, so a
forced `PendingPlayMinor` never dead-ends.

Mirrors the Handplow section of tests/test_cards_category8.py (it shares the exact
deferred-effect machinery) plus a real CommitPlayMinor drive.
"""
from __future__ import annotations

import agricola.cards.tree_farm_joiner  # noqa: F401  (registers the card)

from agricola.actions import CommitPlayMinor, FireTrigger, Proceed
from agricola.cards.specs import MINORS, OCCUPATIONS
from agricola.cards.triggers import TRIGGERS, should_host_preparation
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor, PendingPreparation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup

CARD_ID = "tree_farm_joiner"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _give_resources(state, idx, **kw):
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(**kw))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _give_hand_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, hand_minors=p.hand_minors | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _prep_with_grant_scheduled(idx=0, prev_round=1):
    """A PREPARATION state where player `idx` has the Tree Farm Joiner grant (wood +
    minor-action) scheduled for the round `_complete_preparation` is about to enter
    (prev_round+1). The player also holds a cheap affordable hand minor (Market Stall,
    cost 1 grain) so the grant is eligible."""
    from agricola.state import FutureReward
    state = setup(0)
    entered = prev_round + 1
    p = state.players[idx]
    rewards = list(p.future_rewards)
    rewards[entered - 1] = FutureReward(effect_card_ids=frozenset({CARD_ID}))
    resources = list(p.future_resources)
    resources[entered - 1] = resources[entered - 1] + Resources(wood=1)
    p = fast_replace(
        p,
        occupations=p.occupations | {CARD_ID},
        hand_minors=p.hand_minors | {"market_stall"},
        future_rewards=tuple(rewards),
        future_resources=tuple(resources),
    )
    # Give a grain so Market Stall (cost 1 grain) is affordable.
    p = fast_replace(p, resources=p.resources + Resources(grain=1))
    state = fast_replace(
        state,
        players=tuple(p if i == idx else state.players[i] for i in range(2)),
        round_number=prev_round, phase=Phase.PREPARATION)
    return state, entered


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_occupation_and_start_of_round_trigger():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID not in MINORS
    assert CARD_ID in {e.card_id for e in TRIGGERS.get("start_of_round", [])}


# ---------------------------------------------------------------------------
# on-play scheduling
# ---------------------------------------------------------------------------

def test_on_play_schedules_next_two_odd_rounds_from_even():
    # Round 2 (even) → next two odd rounds are 3 and 5 (slots 2, 4).
    s = setup(0)
    s = fast_replace(s, round_number=2)
    out = OCCUPATIONS[CARD_ID].on_play(s, 0)
    fr = out.players[0].future_rewards
    res = out.players[0].future_resources
    assert CARD_ID in fr[2].effect_card_ids and CARD_ID in fr[4].effect_card_ids
    assert res[2].wood == 1 and res[4].wood == 1
    # Only those two slots are populated.
    assert sum(1 for r in fr if r.effect_card_ids) == 2
    assert sum(1 for r in res if r.wood) == 2


def test_on_play_schedules_next_two_odd_rounds_from_odd():
    # Round 3 (odd) → next two odd rounds are 5 and 7 (slots 4, 6).
    s = setup(0)
    s = fast_replace(s, round_number=3)
    out = OCCUPATIONS[CARD_ID].on_play(s, 0)
    fr = out.players[0].future_rewards
    res = out.players[0].future_resources
    assert CARD_ID in fr[4].effect_card_ids and CARD_ID in fr[6].effect_card_ids
    assert res[4].wood == 1 and res[6].wood == 1


def test_on_play_late_play_clamps_rounds_past_14():
    # Round 13 (odd) → next odd rounds would be 15 and 17, both > 14, both dropped.
    s = setup(0)
    s = fast_replace(s, round_number=13)
    out = OCCUPATIONS[CARD_ID].on_play(s, 0)
    assert all(not r.effect_card_ids for r in out.players[0].future_rewards)
    assert all(r.wood == 0 for r in out.players[0].future_resources)


# ---------------------------------------------------------------------------
# hosting is driven by the schedule (not by ownership every round)
# ---------------------------------------------------------------------------

def test_owner_not_hosted_on_unscheduled_round():
    # Owning the occupation does NOT host a preparation frame on an unscheduled round.
    state = _own_occ(setup(0), 0, CARD_ID)
    state = fast_replace(state, round_number=3, phase=Phase.PREPARATION)
    assert should_host_preparation(state) is False
    out = _complete_preparation(state)
    assert out.pending_stack == ()


def test_scheduled_round_hosts_preparation():
    # Hosting is gated on the round being ENTERED. The grant for round `entered` is in
    # slot `entered-1`; a state whose round_number == entered hosts (that slot carries
    # the effect id), driving the PendingPreparation frame.
    s, entered = _prep_with_grant_scheduled(idx=0, prev_round=1)
    s_entered = fast_replace(s, round_number=entered)
    assert should_host_preparation(s_entered) is True


# ---------------------------------------------------------------------------
# round-start: wood arrives, minor action surfaces, ordering, optionality
# ---------------------------------------------------------------------------

def test_wood_distributed_then_minor_action_offered():
    s, entered = _prep_with_grant_scheduled(idx=0, prev_round=1)
    wood_before = s.players[0].resources.wood
    s = _complete_preparation(s)
    assert s.round_number == entered
    # Wood was distributed at step 2 BEFORE the hook fired (so it can pay the minor).
    assert s.players[0].resources.wood == wood_before + 1
    top = s.pending_stack[-1]
    assert isinstance(top, PendingPreparation) and top.player_idx == 0
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) in la
    assert Proceed() in la  # optional → declinable


def test_fire_pushes_play_minor_and_consumes_grant():
    s, entered = _prep_with_grant_scheduled(idx=0, prev_round=1)
    s = _complete_preparation(s)
    s2 = step(s, FireTrigger(card_id=CARD_ID))
    # Firing pushes a forced PendingPlayMinor and removes the grant from the slot.
    assert isinstance(s2.pending_stack[-1], PendingPlayMinor)
    assert CARD_ID not in s2.players[0].future_rewards[entered - 1].effect_card_ids
    # The forced minor offers exactly the playable hand minor(s) — Market Stall here.
    la = legal_actions(s2)
    assert all(isinstance(a, CommitPlayMinor) for a in la)
    assert {a.card_id for a in la} == {"market_stall"}


def test_full_drive_plays_minor():
    s, _ = _prep_with_grant_scheduled(idx=0, prev_round=1)
    s = _complete_preparation(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    veg_before = s.players[0].resources.veg
    grain_before = s.players[0].resources.grain
    la = legal_actions(s)
    commit = next(a for a in la if isinstance(a, CommitPlayMinor)
                  and a.card_id == "market_stall")
    s = step(s, commit)
    # Market Stall: pay 1 grain, gain 1 veg. It is a TRAVELING (passing) minor, so it
    # leaves the player's hand and circulates to the opponent rather than staying in
    # the player's tableau.
    assert s.players[0].resources.veg == veg_before + 1
    assert s.players[0].resources.grain == grain_before - 1
    assert "market_stall" not in s.players[0].hand_minors
    assert "market_stall" in s.players[1].hand_minors


def test_minor_action_can_be_declined():
    s, _ = _prep_with_grant_scheduled(idx=0, prev_round=1)
    s = _complete_preparation(s)
    s = step(s, Proceed())
    # Declining: no PendingPlayMinor is pushed and the host resolves.
    assert all(not isinstance(f, PendingPlayMinor) for f in s.pending_stack)
    # Market Stall stays in hand, unplayed.
    assert "market_stall" in s.players[0].hand_minors


# ---------------------------------------------------------------------------
# eligibility boundary: no playable hand minor → grant not offered
# ---------------------------------------------------------------------------

def test_not_offered_when_no_playable_hand_minor():
    # Scheduled, but the player has no affordable hand minor → only Proceed is offered
    # (the host appears because the schedule drives hosting, but the trigger is
    # ineligible so it never surfaces a dead-ending PendingPlayMinor).
    s, _ = _prep_with_grant_scheduled(idx=0, prev_round=1)
    # Strip the grain so Market Stall (cost 1 grain) is unaffordable.
    p = s.players[0]
    p = fast_replace(p, resources=fast_replace(p.resources, grain=0))
    s = fast_replace(s, players=(p, s.players[1]))
    assert playable_minors(s, 0) == []
    s = _complete_preparation(s)
    assert legal_actions(s) == [Proceed()]
