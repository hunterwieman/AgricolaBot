"""Tests for Bookmark (minor improvement, E28; Ephipparius): "Add 3 to the current
round and mark the corresponding round space. At the start of that round, you can
play 1 occupation without paying an occupation cost." Cost 1 Wood; no prereq; no VP.

A Category-8 deferred-EFFECT card (the Handplow carrier + Seed Researcher free-play):
on play it schedules its grant onto round R+3 via `future_rewards`; at that round's
start (the round_space_collection window) it surfaces an OPTIONAL FireTrigger that
pushes a FREE `PendingPlayOccupation(cost=Resources())`. Coverage: registration;
the on-play schedule onto round R+3 (and past-14 drop); the optional offer at the
scheduled round (declinable); the free occupation play end-to-end (no food debited);
per-slot consumption; and the eligibility gates (unscheduled round, empty hand).
"""
from __future__ import annotations

import agricola.cards.bookmark  # noqa: F401  (registers the card)
import agricola.cards.consultant  # noqa: F401  (a real occupation to play free)

from agricola.actions import CommitPlayOccupation, FireTrigger, Proceed, Stop
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow, PendingPlayOccupation
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from agricola.state import GameState

CARD_ID = "bookmark"
_OCC = "consultant"   # a real occupation; on-play +3 clay in 2p


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _edit(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx):
    return _edit(state, idx, minor_improvements=state.players[idx].minor_improvements | {CARD_ID})


def _with_hand_occ(state, idx, occ_id=_OCC):
    return _edit(state, idx, hand_occupations=state.players[idx].hand_occupations | {occ_id})


def _schedule_on(state, idx, entered_round):
    """Put the bookmark grant into player `idx`'s future_rewards slot for the round
    `_complete_preparation` is about to enter."""
    p = state.players[idx]
    rewards = list(p.future_rewards)
    rewards[entered_round - 1] = fast_replace(
        rewards[entered_round - 1],
        effect_card_ids=rewards[entered_round - 1].effect_card_ids | {CARD_ID})
    return _edit(state, idx, future_rewards=tuple(rewards))


def _prep_with_grant(idx=0, prev_round=2, hand=True):
    """A PREPARATION state where player `idx` owns Bookmark with its grant scheduled
    for the round `_complete_preparation` is about to enter (prev_round+1)."""
    state = setup(0)
    entered = prev_round + 1
    state = _own(state, idx)
    state = _schedule_on(state, idx, entered)
    if hand:
        state = _with_hand_occ(state, idx)
    state = fast_replace(state, round_number=prev_round, phase=Phase.PREPARATION)
    return state, entered


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.vps == 0
    assert not spec.passing_left
    # An OPTIONAL trigger on the round_space_collection window, not a blanket auto.
    entry = next(t for t in TRIGGERS.get("round_space_collection", ()) if t.card_id == CARD_ID)
    assert entry.mandatory is False
    assert all(e.card_id != CARD_ID for e in AUTO_EFFECTS.get("round_space_collection", ()))


# ---------------------------------------------------------------------------
# on_play — schedules the grant onto round R+3 (future_rewards)
# ---------------------------------------------------------------------------

def test_on_play_schedules_round_r_plus_3():
    s = setup(0)   # R=1 -> round 4 (slot 3)
    out = MINORS[CARD_ID].on_play(s, 0)
    fr = out.players[0].future_rewards
    assert CARD_ID in fr[3].effect_card_ids
    assert sum(1 for r in fr if CARD_ID in r.effect_card_ids) == 1
    # No immediate goods.
    assert out.players[0].resources == s.players[0].resources


def test_on_play_drops_round_past_14():
    s = fast_replace(setup(0), round_number=12)   # R+3 = 15 > 14 -> dropped
    out = MINORS[CARD_ID].on_play(s, 0)
    assert all(CARD_ID not in r.effect_card_ids for r in out.players[0].future_rewards)


# ---------------------------------------------------------------------------
# The optional offer at the scheduled round
# ---------------------------------------------------------------------------

def test_offers_optional_free_play_at_scheduled_round():
    s, entered = _prep_with_grant(idx=0, prev_round=2)
    s = _complete_preparation(s)
    assert s.round_number == entered
    top = s.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow) and top.player_idx == 0
    assert top.window_id == "round_space_collection"
    assert s.phase is Phase.PREPARATION
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) in la
    assert Proceed() in la    # optional -> declinable

    s2 = step(s, FireTrigger(card_id=CARD_ID))
    top = s2.pending_stack[-1]
    assert isinstance(top, PendingPlayOccupation)
    assert top.cost == Resources()                 # FREE
    assert top.initiated_by_id == f"card:{CARD_ID}"
    # The grant was consumed from this round's slot.
    assert CARD_ID not in s2.players[0].future_rewards[entered - 1].effect_card_ids


def test_free_occupation_play_end_to_end():
    s, _ = _prep_with_grant(idx=0, prev_round=2)
    s = _complete_preparation(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert CommitPlayOccupation(card_id=_OCC) in legal_actions(s)

    food_before = s.players[0].resources.food
    s = step(s, CommitPlayOccupation(card_id=_OCC))
    p = s.players[0]
    assert p.resources.food == food_before   # nothing debited (free)
    assert _OCC in p.occupations             # hand -> tableau
    assert _OCC not in p.hand_occupations
    assert s.pending_stack[-1].phase == "after"
    s = step(s, Stop())                       # pop the play frame
    assert isinstance(s.pending_stack[-1], PendingHarvestWindow)
    assert legal_actions(s) == [Proceed()]    # bookmark consumed: no re-offer


def test_can_be_declined():
    s, _ = _prep_with_grant(idx=0, prev_round=2)
    s = _complete_preparation(s)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)
    s = step(s, Proceed())    # decline
    assert all(not isinstance(f, PendingPlayOccupation) for f in s.pending_stack)
    assert _OCC in s.players[0].hand_occupations   # still in hand


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_not_offered_when_unscheduled_round():
    state = setup(0)
    state = _own(state, 0)
    state = _with_hand_occ(state, 0)
    state = fast_replace(state, round_number=5, phase=Phase.PREPARATION)
    out = _complete_preparation(state)
    assert out.pending_stack == ()   # no frame — nothing scheduled this round
    assert out.phase is Phase.WORK


def test_not_offered_when_no_playable_occupation():
    # Scheduled, but the hand has no playable occupation -> never a dead-end fire,
    # so NO window frame is pushed and the ladder runs straight to WORK.
    s, _ = _prep_with_grant(idx=0, prev_round=2, hand=False)
    s = _complete_preparation(s)
    assert s.pending_stack == ()
    assert s.phase is Phase.WORK
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
