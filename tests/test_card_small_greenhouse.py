"""Tests for Small Greenhouse (minor improvement, D69; Consul Dirigens Expansion).

Card text: "Add 4 and 7 to the current round and place 1 vegetable on each
corresponding round space. At the start of these rounds, you can buy the vegetable
for 1 food."
Cost: 2 Wood. Prerequisite: 1 Occupation. VPs: 1. Not passing.

The paid sibling of Large Greenhouse (A69): the round-start vegetable is BOUGHT for 1
food (an OPTIONAL paid grant), so this fuses Chain Float's per-slot effect scheduling
(offsets R+4 / R+7 on `future_rewards`, per-round slot scoping) with Plow Driver's paid
optional start-of-round grant + food-payment resume. The buy surfaces as a FireTrigger
on the preparation ladder's start_of_round window frame (a PendingHarvestWindow,
ruling 54, 2026-07-14), pushed exactly when the trigger is eligible; Proceed declines.
Mirrors `tests/test_card_chain_float.py` (scheduling/scoping) and
`tests/test_card_rocky_terrain.py` (the food-payment path).
"""
from __future__ import annotations

import agricola.cards.small_greenhouse  # noqa: F401

from agricola.actions import CommitFoodPayment, FireTrigger, Proceed
from agricola.cards.specs import FOOD_PAYMENT_RESUMES, MINORS
from agricola.cards.triggers import TRIGGERS
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingFoodPayment, PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.setup import setup
from agricola.state import FutureReward
from tests.factories import with_resources

CARD_ID = "small_greenhouse"


# ---------------------------------------------------------------------------
# Helpers (mirroring test_card_chain_float.py)
# ---------------------------------------------------------------------------

def _prep_with_scheduled(idx=0, prev_round=3, rounds=(4, 7), food=5):
    """A PREPARATION state where player `idx` owns Small Greenhouse with the paid veg
    scheduled for `rounds`, poised for `_complete_preparation` to enter `prev_round+1`."""
    state = setup(0)
    state = with_resources(state, idx, food=food, veg=0)
    p = state.players[idx]
    rewards = list(p.future_rewards)
    for rnd in rounds:
        rewards[rnd - 1] = FutureReward(effect_card_ids=frozenset({CARD_ID}))
    p = fast_replace(p,
                     minor_improvements=p.minor_improvements | {CARD_ID},
                     future_rewards=tuple(rewards))
    state = fast_replace(state,
                         players=tuple(p if i == idx else state.players[i] for i in range(2)),
                         round_number=prev_round, phase=Phase.PREPARATION)
    return state, prev_round + 1


def _strip_animals(state, idx):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, animals=Animals()) if i == idx else state.players[i]
        for i in range(2)))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=2))
    assert spec.min_occupations == 1          # prereq "1 Occupation"
    assert spec.max_occupations is None
    assert spec.prereq is None
    assert spec.vps == 1
    assert spec.passing_left is False
    # OPTIONAL start_of_round trigger + the food-payment resume continuation.
    assert CARD_ID in {e.card_id for e in TRIGGERS.get("start_of_round", [])}
    entry = next(e for e in TRIGGERS["start_of_round"] if e.card_id == CARD_ID)
    assert entry.mandatory is False
    assert CARD_ID in FOOD_PAYMENT_RESUMES


# ---------------------------------------------------------------------------
# on_play — two round offsets R+4 / R+7
# ---------------------------------------------------------------------------

def test_on_play_schedules_two_rounds():
    # R=1 (setup) → veg on rounds 1+4=5, 1+7=8 (slots 4, 7).
    s = setup(0)
    out = MINORS[CARD_ID].on_play(s, 0)
    fr = out.players[0].future_rewards
    assert CARD_ID in fr[4].effect_card_ids   # round 5
    assert CARD_ID in fr[7].effect_card_ids   # round 8
    assert sum(1 for r in fr if CARD_ID in r.effect_card_ids) == 2
    # This is an EFFECT (paid pickup), not goods — the goods carrier is untouched.
    assert all(r.veg == 0 for r in out.players[0].future_resources)


def test_on_play_offsets_track_current_round():
    # "Add 4/7 to the current round" is relative: from round 3 → rounds 7, 10.
    s = fast_replace(setup(0), round_number=3)
    out = MINORS[CARD_ID].on_play(s, 0)
    fr = out.players[0].future_rewards
    assert CARD_ID in fr[6].effect_card_ids    # round 7
    assert CARD_ID in fr[9].effect_card_ids    # round 10
    assert sum(1 for r in fr if CARD_ID in r.effect_card_ids) == 2


def test_on_play_clamps_offsets_past_round_14():
    # From round 9 → rounds 13, 16. The second (16) is past the game and dropped.
    s = fast_replace(setup(0), round_number=9)
    out = MINORS[CARD_ID].on_play(s, 0)
    fr = out.players[0].future_rewards
    assert CARD_ID in fr[12].effect_card_ids   # round 13
    assert sum(1 for r in fr if CARD_ID in r.effect_card_ids) == 1  # round 16 dropped


# ---------------------------------------------------------------------------
# Round-start optional paid buy (the deferred effect firing)
# ---------------------------------------------------------------------------

def test_offers_optional_buy_at_round_start():
    s, entered = _prep_with_scheduled(idx=0, prev_round=3, rounds=(4, 7), food=5)
    s = _complete_preparation(s)
    assert s.round_number == entered          # round 4
    top = s.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow) and top.player_idx == 0
    assert top.window_id == "start_of_round"
    assert s.phase is Phase.PREPARATION       # the ladder is paused at the window
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) in la
    assert Proceed() in la                    # optional → declinable


def test_direct_buy_veg_for_food():
    s, _ = _prep_with_scheduled(idx=0, prev_round=3, rounds=(4, 7), food=5)
    s = _complete_preparation(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    # Food on hand: no food-payment frame; the window frame stays on top.
    assert isinstance(s.pending_stack[-1], PendingHarvestWindow)
    assert s.players[0].resources.food == 4   # 5 - 1
    assert s.players[0].resources.veg == 1    # +1 veg
    # Only the entered round's slot consumed; the later scheduled round keeps its grant.
    fr = s.players[0].future_rewards
    assert CARD_ID not in fr[3].effect_card_ids   # round 4 consumed
    assert CARD_ID in fr[6].effect_card_ids       # round 7 intact


def test_buy_via_liquidation():
    # 0 food but 1 grain liquidatable -> 1 food covers the buy.
    s, _ = _prep_with_scheduled(idx=0, prev_round=3, rounds=(4, 7), food=0)
    s = with_resources(s, 0, food=0, grain=1, veg=0)
    s = _complete_preparation(s)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 1 and top.resume_kind == CARD_ID
    pay = CommitFoodPayment(grain=1, veg=0, sheep=0, boar=0, cattle=0)
    assert pay in legal_actions(s)
    s = step(s, pay)                          # 1 grain -> 1 food, resume buys the veg
    assert isinstance(s.pending_stack[-1], PendingHarvestWindow)
    assert s.players[0].resources.food == 0   # raised 1, paid 1
    assert s.players[0].resources.grain == 0  # the grain was liquidated
    assert s.players[0].resources.veg == 1    # +1 veg
    # The slot was consumed on the resume path (not double-offered).
    assert CARD_ID not in s.players[0].future_rewards[3].effect_card_ids


def test_each_scheduled_round_fires_independently():
    # Entering round 7 (with rounds 7 and 10 scheduled) consumes only round 7's slot.
    s, entered = _prep_with_scheduled(idx=0, prev_round=6, rounds=(7, 10), food=5)
    s = _complete_preparation(s)
    assert s.round_number == entered          # round 7
    s = step(s, FireTrigger(card_id=CARD_ID))
    fr = s.players[0].future_rewards
    assert CARD_ID not in fr[6].effect_card_ids   # round 7 consumed
    assert CARD_ID in fr[9].effect_card_ids       # round 10 still scheduled


def test_can_be_declined():
    s, _ = _prep_with_scheduled(idx=0, prev_round=3, rounds=(4, 7), food=5)
    s = _complete_preparation(s)
    s = step(s, Proceed())
    # Declined: no veg gained, the round's slot is NOT consumed (left as-is — it just
    # wasn't taken this round; it only mattered for THIS round's offer).
    assert s.players[0].resources.veg == 0
    assert all(not isinstance(f, PendingFoodPayment) for f in s.pending_stack)


def test_not_offered_when_unaffordable():
    # 0 food and nothing convertible -> cannot pay the 1 food -> the trigger is not
    # eligible, so NO window frame is pushed (frames appear exactly when a trigger
    # is eligible) and the ladder runs straight through to WORK.
    s, _ = _prep_with_scheduled(idx=0, prev_round=3, rounds=(4, 7), food=0)
    s = with_resources(s, 0, food=0, grain=0, veg=0)
    s = _strip_animals(s, 0)
    s = _complete_preparation(s)
    assert s.pending_stack == ()
    assert s.phase is Phase.WORK
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_owner_not_hosted_on_unscheduled_round():
    # Owning the card does NOT produce a window frame on a round its veg isn't due
    # (eligibility is gated on the schedule, not card ownership).
    s, _ = _prep_with_scheduled(idx=0, prev_round=1, rounds=(4, 7), food=5)
    out = _complete_preparation(s)
    assert out.pending_stack == ()
    assert out.phase is Phase.WORK


def test_scoped_to_owner_only():
    # The opponent (no schedule) is not offered the buy on the entered round: the
    # one window frame on the stack belongs to the owner.
    s, _ = _prep_with_scheduled(idx=0, prev_round=3, rounds=(4, 7), food=5)
    s = _complete_preparation(s)
    frames = [f for f in s.pending_stack if isinstance(f, PendingHarvestWindow)]
    assert len(frames) == 1 and frames[0].player_idx == 0
    for f in s.pending_stack:
        assert getattr(f, "player_idx", 0) == 0
