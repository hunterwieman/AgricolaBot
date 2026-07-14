"""Tests for Chain Float (minor improvement, B20; Bubulcus Expansion).

Card text: "Add 7, 8, and 9 to the current round and place 1 field on each
corresponding round space. At the start of these rounds, you can plow the field."
Cost: 3 Wood. Prerequisite: none.

A Handplow (A19) variant that schedules THREE deferred, optional round-start plows
(offsets R+7, R+8, R+9 — current round plus each, NOT fixed rounds 7/8/9) on the
card-only `future_rewards` (FutureReward). Each scheduled round consumes only its own
slot when fired, so the three rounds fire independently. Mirrors
`tests/test_card_grassland_harrow.py`.
"""
from __future__ import annotations

import agricola.cards.chain_float  # noqa: F401

from agricola.actions import FireTrigger, Proceed
from agricola.cards.specs import MINORS
from agricola.cards.triggers import TRIGGERS
from agricola.constants import CellType, Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import _can_plow, legal_actions
from agricola.pending import PendingHarvestWindow, PendingPlow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from agricola.state import Cell, FutureReward

CARD_ID = "chain_float"


# ---------------------------------------------------------------------------
# Test helpers (mirroring test_card_grassland_harrow.py)
# ---------------------------------------------------------------------------

def _fill_grid_fields(state, idx):
    """Fill every EMPTY cell with FIELD so no plowable cell remains."""
    p = state.players[idx]
    grid = [list(row) for row in p.farmyard.grid]
    for r in range(3):
        for c in range(5):
            if grid[r][c].cell_type == CellType.EMPTY:
                grid[r][c] = Cell(cell_type=CellType.FIELD)
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    p = fast_replace(p, farmyard=fy)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=3))
    # No prerequisites / occupation count / vps; not passing.
    assert spec.min_occupations == 0
    assert spec.prereq is None
    assert spec.vps == 0
    assert spec.passing_left is False
    # The deferred plow is an OPTIONAL start_of_round trigger (not a forced auto).
    assert CARD_ID in {e.card_id for e in TRIGGERS.get("start_of_round", [])}


# ---------------------------------------------------------------------------
# on_play — three round offsets R+7 / R+8 / R+9
# ---------------------------------------------------------------------------

def test_on_play_schedules_three_rounds():
    # R=1 (setup) → fields on rounds 1+7=8, 1+8=9, 1+9=10 (slots 7, 8, 9).
    s = setup(0)
    out = MINORS[CARD_ID].on_play(s, 0)
    fr = out.players[0].future_rewards
    assert CARD_ID in fr[7].effect_card_ids   # round 8
    assert CARD_ID in fr[8].effect_card_ids   # round 9
    assert CARD_ID in fr[9].effect_card_ids   # round 10
    # Exactly those three slots carry the grant; nothing else.
    assert sum(1 for r in fr if CARD_ID in r.effect_card_ids) == 3
    # This is an EFFECT, not goods — the goods carrier is untouched.
    assert all(r.food == 0 for r in out.players[0].future_resources)


def test_on_play_offsets_track_current_round():
    # "Add 7/8/9 to the current round" is relative: from round 3 → rounds 10, 11, 12.
    s = fast_replace(setup(0), round_number=3)
    out = MINORS[CARD_ID].on_play(s, 0)
    fr = out.players[0].future_rewards
    assert CARD_ID in fr[9].effect_card_ids    # round 10
    assert CARD_ID in fr[10].effect_card_ids   # round 11
    assert CARD_ID in fr[11].effect_card_ids   # round 12
    assert sum(1 for r in fr if CARD_ID in r.effect_card_ids) == 3


def test_on_play_clamps_offsets_past_round_14():
    # From round 6 → rounds 13, 14, 15. The third (15) is past the game and dropped;
    # only rounds 13 and 14 are scheduled.
    s = fast_replace(setup(0), round_number=6)
    out = MINORS[CARD_ID].on_play(s, 0)
    fr = out.players[0].future_rewards
    assert CARD_ID in fr[12].effect_card_ids   # round 13
    assert CARD_ID in fr[13].effect_card_ids   # round 14
    assert sum(1 for r in fr if CARD_ID in r.effect_card_ids) == 2  # round 15 dropped


# ---------------------------------------------------------------------------
# Round-start optional plow (the deferred effect firing)
# ---------------------------------------------------------------------------

def _prep_with_scheduled(idx=0, prev_round=7, rounds=(8, 9, 10)):
    """A PREPARATION state where player `idx` owns Chain Float with its plows scheduled
    for `rounds`, poised for `_complete_preparation` to enter `prev_round + 1`."""
    state = setup(0)
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


def test_offers_optional_plow_at_round_start():
    s, entered = _prep_with_scheduled(idx=0, prev_round=7, rounds=(8, 9, 10))
    s = _complete_preparation(s)
    assert s.round_number == entered          # round 8
    top = s.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "start_of_round" and top.player_idx == 0
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) in la
    assert Proceed() in la                    # optional → declinable
    s2 = step(s, FireTrigger(card_id=CARD_ID))
    assert isinstance(s2.pending_stack[-1], PendingPlow)
    # Only the entered round's grant was consumed; later rounds keep theirs.
    fr = s2.players[0].future_rewards
    assert CARD_ID not in fr[entered - 1].effect_card_ids   # round 8 consumed
    assert CARD_ID in fr[8].effect_card_ids                 # round 9 intact
    assert CARD_ID in fr[9].effect_card_ids                 # round 10 intact


def test_each_scheduled_round_fires_independently():
    # Entering round 9 (with rounds 9 and 10 still scheduled) consumes only round 9's
    # slot — the three-round schedule is handled by per-round-slot consumption.
    s, entered = _prep_with_scheduled(idx=0, prev_round=8, rounds=(9, 10))
    s = _complete_preparation(s)
    assert s.round_number == entered          # round 9
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert isinstance(s.pending_stack[-1], PendingPlow)
    fr = s.players[0].future_rewards
    assert CARD_ID not in fr[8].effect_card_ids   # round 9 consumed
    assert CARD_ID in fr[9].effect_card_ids       # round 10 still scheduled


def test_can_be_declined():
    s, _ = _prep_with_scheduled(idx=0, prev_round=7, rounds=(8, 9, 10))
    s = _complete_preparation(s)
    s = step(s, Proceed())
    assert all(not isinstance(f, PendingPlow) for f in s.pending_stack)
    # Declining resumes the ladder, which completes into WORK.
    assert s.pending_stack == ()
    assert s.phase == Phase.WORK


def test_not_offered_when_unplowable():
    # Scheduled but no plowable cell → the trigger is not eligible, so no window
    # frame is pushed at all: the ladder completes straight into WORK.
    s, _ = _prep_with_scheduled(idx=0, prev_round=7, rounds=(8, 9, 10))
    s = _fill_grid_fields(s, 0)
    assert not _can_plow(s.players[0])
    s = _complete_preparation(s)
    assert s.pending_stack == ()
    assert s.phase == Phase.WORK


def test_owner_not_hosted_on_unscheduled_round():
    # Owning the card does NOT surface a window frame on a round its plow isn't due
    # (eligibility is gated on the schedule, not card ownership). Entering round 6
    # with the plows scheduled only for 8/9/10 produces no frame.
    s, _ = _prep_with_scheduled(idx=0, prev_round=5, rounds=(8, 9, 10))
    out = _complete_preparation(s)
    assert out.pending_stack == ()


def test_scoped_to_owner_only():
    # The opponent (no schedule) is not offered the plow on the entered round:
    # the only window frame belongs to player 0 (the owner).
    s, _ = _prep_with_scheduled(idx=0, prev_round=7, rounds=(8, 9, 10))
    s = _complete_preparation(s)
    assert [f.player_idx for f in s.pending_stack
            if isinstance(f, PendingHarvestWindow)] == [0]
    for f in s.pending_stack:
        assert getattr(f, "player_idx", 0) == 0
