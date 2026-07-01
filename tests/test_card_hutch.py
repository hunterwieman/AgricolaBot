"""Tests for Hutch (minor improvement, D43; Consul Dirigens).

Card text: "Place 0, 1, 2, and 3 food in this order on the next 4 round spaces. At
the start of these rounds, you get the food."
Cost: 1 Wood, 1 Reed. VPs: 1. No prerequisite. Not passing.

Category 8 (deferred goods, increasing schedule): on play, +0/+1/+2/+3 food on
rounds R+1..R+4 (the increasing amount maps k -> round R+1+k for k in 0..3). The
food rides on `future_resources` and is collected at the start of each scheduled
round by `engine._complete_preparation`.
"""
from __future__ import annotations

import agricola.cards.hutch  # noqa: F401

from agricola.cards.specs import MINORS
from agricola.constants import Phase
from agricola.engine import _complete_preparation
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup


def _food(state, idx):
    return [r.food for r in state.players[idx].future_resources]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_hutch_registered():
    assert "hutch" in MINORS
    spec = MINORS["hutch"]
    assert spec.cost == Cost(resources=Resources(wood=1, reed=1))
    assert spec.vps == 1
    assert not spec.passing_left            # not a passing minor
    assert spec.prereq is None              # no prerequisite


# ---------------------------------------------------------------------------
# on_play — the increasing schedule on the next 4 round spaces
# ---------------------------------------------------------------------------

def test_hutch_on_play_increasing_schedule():
    s = setup(0)   # R = 1 → rounds 2,3,4,5 get 0,1,2,3
    out = MINORS["hutch"].on_play(s, 0)
    f = _food(out, 0)
    assert f[0] == 0           # round 1 (current) untouched
    assert f[1] == 0           # round 2 = R+1 → 0 food (genuine no-op)
    assert f[2] == 1           # round 3 = R+2 → 1 food
    assert f[3] == 2           # round 4 = R+3 → 2 food
    assert f[4] == 3           # round 5 = R+4 → 3 food
    assert f[5] == 0           # round 6 not scheduled
    assert sum(f) == 6         # 0+1+2+3


def test_hutch_on_play_offset_from_current_round():
    # The schedule is relative to the current round, not absolute.
    s = fast_replace(setup(0), round_number=7)   # R=7 → rounds 8,9,10,11
    out = MINORS["hutch"].on_play(s, 0)
    f = _food(out, 0)
    assert f[7] == 0           # round 8 = R+1 → 0
    assert f[8] == 1           # round 9
    assert f[9] == 2           # round 10
    assert f[10] == 3          # round 11
    assert sum(f) == 6
    # Nothing scheduled on or before the current round, nor after R+4.
    assert all(f[i] == 0 for i in range(7))
    assert f[11] == 0


def test_hutch_clamps_past_round_14():
    # Played late, the slots past round 14 are silently dropped.
    s = fast_replace(setup(0), round_number=12)   # R=12 → rounds 13,14,15,16
    out = MINORS["hutch"].on_play(s, 0)
    f = _food(out, 0)
    assert f[12] == 0          # round 13 = R+1 → 0 (no-op anyway)
    assert f[13] == 1          # round 14 = R+2 → 1
    # Rounds 15 (2 food) and 16 (3 food) fall past the 14-round game → dropped.
    assert len(f) == 14
    assert sum(f) == 1


def test_hutch_additive_with_existing_schedule():
    # schedule_resources is additive: a pre-existing food promise stacks.
    s = setup(0)
    p = s.players[0]
    base = list(p.future_resources)
    base[3] = base[3] + Resources(food=5)   # round 4 already has 5 food
    s = fast_replace(s, players=(fast_replace(p, future_resources=tuple(base)),
                                 s.players[1]))
    out = MINORS["hutch"].on_play(s, 0)
    f = _food(out, 0)
    assert f[3] == 5 + 2       # existing 5 + Hutch's 2 on round 4 (R+3)
    assert f[4] == 3


def test_hutch_only_affects_owner():
    s = setup(0)
    out = MINORS["hutch"].on_play(s, 0)
    # Opponent's schedule is untouched.
    assert sum(_food(out, 1)) == 0


# ---------------------------------------------------------------------------
# End-to-end — the food is actually collected at the start of each round
# ---------------------------------------------------------------------------

def test_hutch_food_collected_at_round_start():
    # Schedule on round 1 (rounds 2..5 = 0,1,2,3), then enter round 3 (R+2) and
    # confirm 1 food is paid out and that slot cleared.
    s = setup(0)
    s = MINORS["hutch"].on_play(s, 0)
    food_before = s.players[0].resources.food
    # Drive PREPARATION entering round 3 (prev round 2).
    s = fast_replace(s, round_number=2, phase=Phase.PREPARATION)
    out = _complete_preparation(s)
    assert out.round_number == 3
    # Round 3 = R+2 → 1 food collected; the consumed slot is removed.
    assert out.players[0].resources.food == food_before + 1


def test_hutch_largest_payout_round_collected():
    # Enter round 5 (R+4) → the biggest promise (3 food) lands.
    s = setup(0)
    s = MINORS["hutch"].on_play(s, 0)
    food_before = s.players[0].resources.food
    s = fast_replace(s, round_number=4, phase=Phase.PREPARATION)
    out = _complete_preparation(s)
    assert out.round_number == 5
    assert out.players[0].resources.food == food_before + 3
