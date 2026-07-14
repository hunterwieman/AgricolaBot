"""Tests for Stable Planner (occupation, A89; Artifex Expansion).

Card text: "Add 3, 6, and 9 to the current round. You can place 1 stable on each
corresponding round space. At the start of these rounds (not earlier), you can build
the stable at no cost."

Stable Planner schedules a deferred OPTIONAL free-stable grant onto rounds R+3, R+6,
R+9 via `future_rewards` (the Handplow carrier), surfaced at each scheduled round start
as a FireTrigger on the preparation ladder's start_of_round window frame (a
PendingHarvestWindow, ruling 54, 2026-07-14; Proceed = decline). The build is one
free stable (cost Resources(), cap 1). The frame is eligibility-driven — the schedule
slot gates the trigger — so an owner gets one only on the three scheduled rounds.
"""
from __future__ import annotations

import agricola.cards.stable_planner  # noqa: F401  (registers the card)

from agricola.actions import CommitBuildStable, FireTrigger, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import TRIGGERS
from agricola.constants import CellType, Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import _can_build_stable, legal_actions
from agricola.pending import PendingBuildStables, PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import Cell, FutureReward, GameState

CARD_ID = "stable_planner"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _schedule_on(state, idx, entered_round, card_id=CARD_ID):
    """Put `card_id`'s grant into player `idx`'s future_rewards slot for the round that
    `_complete_preparation` is about to enter."""
    p = state.players[idx]
    rewards = list(p.future_rewards)
    rewards[entered_round - 1] = fast_replace(
        rewards[entered_round - 1],
        effect_card_ids=rewards[entered_round - 1].effect_card_ids | {card_id})
    p = fast_replace(p, future_rewards=tuple(rewards))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _prep_with_grant_scheduled(idx=0, prev_round=2):
    """A PREPARATION state where player `idx` owns Stable Planner with its grant
    scheduled for the round `_complete_preparation` is about to enter (prev_round+1)."""
    state = setup(0)
    entered = prev_round + 1
    state = _own_occ(state, idx)
    state = _schedule_on(state, idx, entered)
    state = fast_replace(state, round_number=prev_round, phase=Phase.PREPARATION)
    return state, entered


def _fill_grid(state, idx):
    """Fill every non-room EMPTY cell with FIELD so no empty (stable-able) cell remains."""
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
    assert CARD_ID in OCCUPATIONS
    assert any(t.card_id == CARD_ID for t in TRIGGERS.get("start_of_round", ()))
    # An OPTIONAL trigger, gated by the schedule slot — never a blanket auto that
    # would fire on every round.
    entry = next(t for t in TRIGGERS["start_of_round"] if t.card_id == CARD_ID)
    assert entry.mandatory is False
    from agricola.cards.triggers import AUTO_EFFECTS
    assert all(e.card_id != CARD_ID for e in AUTO_EFFECTS.get("start_of_round", ()))


# ---------------------------------------------------------------------------
# on_play — schedules R+3, R+6, R+9 on future_rewards, no immediate goods
# ---------------------------------------------------------------------------

def test_on_play_schedules_three_rounds():
    s = setup(0)  # R=1 → rounds 4, 7, 10 (slots 3, 6, 9)
    out = OCCUPATIONS[CARD_ID].on_play(s, 0)
    fr = out.players[0].future_rewards
    assert CARD_ID in fr[3].effect_card_ids   # round 4
    assert CARD_ID in fr[6].effect_card_ids   # round 7
    assert CARD_ID in fr[9].effect_card_ids   # round 10
    assert sum(1 for r in fr if CARD_ID in r.effect_card_ids) == 3
    # No immediate goods, and the goods carrier is untouched.
    assert out.players[0].resources == s.players[0].resources
    assert all(r.food == 0 for r in out.players[0].future_resources)


def test_on_play_drops_rounds_past_14():
    # Played late (R=13): R+3=16, R+6=19, R+9=22 all > 14 → silently dropped.
    s = setup(0)
    s = fast_replace(s, round_number=13)
    out = OCCUPATIONS[CARD_ID].on_play(s, 0)
    fr = out.players[0].future_rewards
    assert all(CARD_ID not in r.effect_card_ids for r in fr)


# ---------------------------------------------------------------------------
# Round start — optional free-stable grant
# ---------------------------------------------------------------------------

def test_offers_optional_free_stable_at_scheduled_round():
    s, entered = _prep_with_grant_scheduled(idx=0, prev_round=2)
    s = _complete_preparation(s)
    assert s.round_number == entered
    top = s.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow) and top.player_idx == 0
    assert top.window_id == "start_of_round"
    assert s.phase is Phase.PREPARATION   # the ladder is paused at the window
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) in la
    assert Proceed() in la                        # optional → declinable
    s2 = step(s, FireTrigger(card_id=CARD_ID))
    # Firing pushes the free-stable build primitive (cost zero, cap 1).
    bs = s2.pending_stack[-1]
    assert isinstance(bs, PendingBuildStables)
    assert bs.cost == Resources() and bs.max_builds == 1
    assert bs.initiated_by_id == "card:stable_planner"
    # The grant was consumed from this round's slot only.
    assert CARD_ID not in s2.players[0].future_rewards[entered - 1].effect_card_ids


def test_free_stable_build_completes_and_costs_nothing():
    s, _ = _prep_with_grant_scheduled(idx=0, prev_round=2)
    s = _complete_preparation(s)
    before_wood = s.players[0].resources.wood
    s = step(s, FireTrigger(card_id=CARD_ID))
    # Drive the actual build: place one stable on an empty cell, then finish the action.
    s = step(s, CommitBuildStable(row=0, col=2))
    s = step(s, Proceed())   # flip PendingBuildStables to its after-phase
    s = step(s, Stop())      # pop the build host (back to the window frame)
    # A stable now sits on (0, 2) and no resources were spent.
    assert s.players[0].farmyard.grid[0][2].cell_type == CellType.STABLE
    assert s.players[0].resources.wood == before_wood


def test_can_be_declined():
    s, entered = _prep_with_grant_scheduled(idx=0, prev_round=2)
    s = _complete_preparation(s)
    s = step(s, Proceed())   # decline the grant
    assert all(not isinstance(f, PendingBuildStables) for f in s.pending_stack)
    # No stable was built.
    assert all(c.cell_type != CellType.STABLE
               for row in s.players[0].farmyard.grid for c in row)


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_not_offered_when_unscheduled_round():
    # Owning the card but with no grant due this round → no window frame at all
    # (the frame is eligibility-driven, and the schedule slot gates eligibility).
    state = setup(0)
    state = _own_occ(state, 0)
    state = fast_replace(state, round_number=5, phase=Phase.PREPARATION)
    out = _complete_preparation(state)
    assert out.pending_stack == ()   # no frame pushed
    assert out.phase is Phase.WORK


def test_not_offered_when_no_buildable_cell():
    # Scheduled, but no empty cell remains → the grant is not eligible, so NO
    # window frame is pushed (frames appear exactly when a trigger is eligible)
    # and the ladder runs straight through to WORK.
    s, _ = _prep_with_grant_scheduled(idx=0, prev_round=2)
    s = _fill_grid(s, 0)
    assert not _can_build_stable(s, s.players[0], Resources())
    s = _complete_preparation(s)
    assert s.pending_stack == ()
    assert s.phase is Phase.WORK
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


# ---------------------------------------------------------------------------
# Per-slot scoping — each of the three rounds fires independently
# ---------------------------------------------------------------------------

def test_each_scheduled_round_fires_independently():
    # Two separate scheduled rounds: firing the first leaves the second's grant intact.
    s = setup(0)
    s = _own_occ(s, 0)
    # Schedule grants for the rounds entered after prev_round 2 (→3) and after 5 (→6).
    s = _schedule_on(s, 0, 3)
    s = _schedule_on(s, 0, 6)

    # Enter round 3 and fire its grant.
    s3 = fast_replace(s, round_number=2, phase=Phase.PREPARATION)
    s3 = _complete_preparation(s3)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s3)
    s3 = step(s3, FireTrigger(card_id=CARD_ID))
    # Round 3's slot consumed, round 6's grant survives.
    assert CARD_ID not in s3.players[0].future_rewards[2].effect_card_ids
    assert CARD_ID in s3.players[0].future_rewards[5].effect_card_ids
