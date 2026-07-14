"""Tests for Grassland Harrow (minor improvement, B18; Bubulcus Expansion).

Card text: "Add 1 to the current round for each building resource in your supply and
place 1 field on the corresponding round space. At the start of the round, you can plow
the field."
Cost: 2 Wood. Prerequisite: 2 Occupations, 1 Building Resource in Your Supply.

A Handplow (A19) variant: a deferred, optional round-start plow that rides on the
card-only `future_rewards` (FutureReward), differing in that (a) the round offset is
VARIABLE — "1 per building resource in your supply" rather than a fixed 5 — and (b) it
carries two prerequisites (≥2 occupations + ≥1 building resource). Mirrors
`test_cards_category8.py`'s Handplow coverage.
"""
from __future__ import annotations

import agricola.cards.grassland_harrow  # noqa: F401

from agricola.actions import FireTrigger, Proceed
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import TRIGGERS
from agricola.constants import CellType, Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import _can_plow, legal_actions
from agricola.pending import PendingHarvestWindow, PendingPlow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from agricola.state import Cell, FutureReward

CARD_ID = "grassland_harrow"


# ---------------------------------------------------------------------------
# Test helpers (mirroring test_cards_category8.py)
# ---------------------------------------------------------------------------

def _give_occ_count(state, idx, n):
    p = state.players[idx]
    p = fast_replace(p, occupations=frozenset(f"_occ{i}" for i in range(n)))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_resources(state, idx, **kw):
    p = state.players[idx]
    p = fast_replace(p, resources=Resources(**kw))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


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
    assert spec.cost == Cost(resources=Resources(wood=2))
    assert spec.min_occupations == 2
    assert spec.prereq is not None
    # The deferred plow is an OPTIONAL start_of_round trigger (not a forced auto).
    assert CARD_ID in {e.card_id for e in TRIGGERS.get("start_of_round", [])}


# ---------------------------------------------------------------------------
# on_play — variable round offset
# ---------------------------------------------------------------------------

def test_on_play_schedules_at_round_plus_building_resources():
    # R=1 (setup), 3 building resources in supply → field on round 1+3 = 4 (slot 3).
    s = setup(0)
    s = _set_resources(s, 0, wood=1, clay=1, reed=1)  # 3 building resources
    out = MINORS[CARD_ID].on_play(s, 0)
    fr = out.players[0].future_rewards
    assert CARD_ID in fr[3].effect_card_ids          # round 4
    assert sum(1 for r in fr if r) == 1              # only that one slot populated
    # Goods carrier untouched (this is an effect, not goods).
    assert all(r.food == 0 for r in out.players[0].future_resources)


def test_on_play_counts_all_four_building_resources():
    # wood + clay + reed + stone = 1+2+1+1 = 5 → round 1+5 = 6 (slot 5).
    s = setup(0)
    s = _set_resources(s, 0, wood=1, clay=2, reed=1, stone=1)
    out = MINORS[CARD_ID].on_play(s, 0)
    fr = out.players[0].future_rewards
    assert CARD_ID in fr[5].effect_card_ids          # round 6


def test_on_play_ignores_non_building_resources():
    # food / grain / veg are NOT building resources: count = wood only = 1 → round 2.
    s = setup(0)
    s = _set_resources(s, 0, wood=1, food=5, grain=3, veg=2)
    out = MINORS[CARD_ID].on_play(s, 0)
    fr = out.players[0].future_rewards
    assert CARD_ID in fr[1].effect_card_ids          # round 1+1 = 2
    assert sum(1 for r in fr if r) == 1


def test_on_play_clamps_past_round_14():
    # From a late round with a large building-resource count, the target round exceeds
    # 14 → schedule_effect silently drops it (no round space past 14).
    s = setup(0)
    s = fast_replace(s, round_number=13)
    s = _set_resources(s, 0, wood=5)                 # round 13+5 = 18 → dropped
    out = MINORS[CARD_ID].on_play(s, 0)
    fr = out.players[0].future_rewards
    assert all(CARD_ID not in r.effect_card_ids for r in fr)


def test_on_play_zero_building_resources_schedules_current_round():
    # n == 0 → field placed on the (already-entered) current round; a wasted but legal
    # play. The current-round slot is in range, so schedule_effect writes it, but it is
    # never re-hosted (preparation already passed).
    s = setup(0)
    s = fast_replace(s, round_number=5)
    s = _set_resources(s, 0)                          # no building resources
    out = MINORS[CARD_ID].on_play(s, 0)
    fr = out.players[0].future_rewards
    assert CARD_ID in fr[4].effect_card_ids          # round 5 (current), slot 4


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

def test_prereq_requires_two_occupations():
    s = setup(0)
    s = _set_resources(s, 0, wood=1)                  # building-resource part met
    assert not prereq_met(MINORS[CARD_ID], _give_occ_count(s, 0, 1), 0)
    assert prereq_met(MINORS[CARD_ID], _give_occ_count(s, 0, 2), 0)
    assert prereq_met(MINORS[CARD_ID], _give_occ_count(s, 0, 3), 0)  # >= 2


def test_prereq_requires_one_building_resource():
    s = _give_occ_count(setup(0), 0, 2)              # occupation part met
    # No building resources → fails (food/grain/veg do not count).
    s0 = _set_resources(s, 0, food=9, grain=3, veg=3)
    assert not prereq_met(MINORS[CARD_ID], s0, 0)
    # Exactly 1 building resource (clay) → passes.
    s1 = _set_resources(s, 0, clay=1)
    assert prereq_met(MINORS[CARD_ID], s1, 0)


# ---------------------------------------------------------------------------
# Round-start optional plow (the deferred effect firing)
# ---------------------------------------------------------------------------

def _prep_with_scheduled(idx=0, prev_round=1):
    """A PREPARATION state where player `idx` owns Grassland Harrow with its plow
    scheduled for the round `_complete_preparation` is about to enter (prev_round+1)."""
    state = setup(0)
    entered = prev_round + 1
    p = state.players[idx]
    rewards = list(p.future_rewards)
    rewards[entered - 1] = FutureReward(effect_card_ids=frozenset({CARD_ID}))
    p = fast_replace(p,
                     minor_improvements=p.minor_improvements | {CARD_ID},
                     future_rewards=tuple(rewards))
    state = fast_replace(state,
                         players=tuple(p if i == idx else state.players[i] for i in range(2)),
                         round_number=prev_round, phase=Phase.PREPARATION)
    return state, entered


def test_offers_optional_plow_at_round_start():
    s, entered = _prep_with_scheduled(idx=0, prev_round=1)
    s = _complete_preparation(s)
    assert s.round_number == entered
    top = s.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "start_of_round" and top.player_idx == 0
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) in la
    assert Proceed() in la                            # optional → declinable
    s2 = step(s, FireTrigger(card_id=CARD_ID))
    assert isinstance(s2.pending_stack[-1], PendingPlow)
    # Grant consumed so it fires at most once.
    assert CARD_ID not in s2.players[0].future_rewards[entered - 1].effect_card_ids


def test_can_be_declined():
    s, _ = _prep_with_scheduled(idx=0, prev_round=1)
    s = _complete_preparation(s)
    s = step(s, Proceed())
    assert all(not isinstance(f, PendingPlow) for f in s.pending_stack)
    # Declining resumes the ladder, which completes into WORK.
    assert s.pending_stack == ()
    assert s.phase == Phase.WORK


def test_not_offered_when_unplowable():
    # Scheduled but no plowable cell → the trigger is not eligible, so no window
    # frame is pushed at all: the ladder completes straight into WORK.
    s, _ = _prep_with_scheduled(idx=0, prev_round=1)
    s = _fill_grid_fields(s, 0)
    assert not _can_plow(s.players[0])
    s = _complete_preparation(s)
    assert s.pending_stack == ()
    assert s.phase == Phase.WORK


def test_owner_not_hosted_on_unscheduled_round():
    # Owning the card does NOT surface a window frame on rounds its plow isn't due
    # (eligibility is gated on the schedule, not card ownership).
    state = setup(0)
    p = state.players[0]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {CARD_ID})
    state = fast_replace(state, players=(p, state.players[1]),
                         round_number=3, phase=Phase.PREPARATION)
    out = _complete_preparation(state)
    assert out.pending_stack == ()                    # no frame pushed


def test_scoped_to_owner_only():
    # The opponent (no schedule) is not offered the plow on the entered round:
    # the only window frame belongs to player 0 (the owner).
    s, entered = _prep_with_scheduled(idx=0, prev_round=1)
    s = _complete_preparation(s)
    assert [f.player_idx for f in s.pending_stack
            if isinstance(f, PendingHarvestWindow)] == [0]
    for f in s.pending_stack:
        assert getattr(f, "player_idx", 0) == 0
