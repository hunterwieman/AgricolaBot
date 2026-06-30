"""Tests for Farm Building (minor improvement, C43).

Card text: "Each time you build a major improvement, place 1 food on each of the
next 3 round spaces. At the start of these rounds, you get the food." cost 1 clay +
1 reed; 1 VP.

Covers: registration (cost / vps / not-passing / no-prereq), the real build-major
flow scheduling food on the next 3 rounds, the unowned no-op and opponent-scoping,
late-game clamping ("each REMAINING round space"), per-build re-fire ("each time"),
and that the scheduled food is actually collected at round start.
"""
import agricola.cards.farm_building  # noqa: F401

from agricola.actions import ChooseSubAction, PlaceWorker, Stop
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import apply_auto_effects
from agricola.engine import _complete_preparation, step
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup

from tests.factories import with_current_player, with_minors, with_resources, with_space
from tests.test_utils import build_major, run_actions


CARD_ID = "farm_building"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _food(state, idx):
    return [r.food for r in state.players[idx].future_resources]


def _set_round(state, rnd):
    return fast_replace(state, round_number=rnd)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_with_cost_and_vps():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == __import__("agricola.resources", fromlist=["Cost"]).Cost(
        resources=Resources(clay=1, reed=1))
    assert spec.vps == 1
    assert not spec.passing_left


def test_no_prereq():
    # No prereq / occupation requirement: playable from a bare setup.
    assert prereq_met(MINORS[CARD_ID], setup(0), 0)


# ---------------------------------------------------------------------------
# Real build-major flow: schedules +1 food on the next 3 round spaces
# ---------------------------------------------------------------------------

def _mi_build_fireplace(state):
    """Build the Fireplace (major idx 0, cost 2 clay) through the full step chain."""
    state = with_current_player(state, 0)
    state = with_space(state, "major_improvement", revealed=True)
    return run_actions(state, [
        PlaceWorker(space="major_improvement"),
        ChooseSubAction(name="improvement"),
        ChooseSubAction(name="build_major"),
        build_major(0),
        Stop(),   # pop PendingBuildMajor after-phase
        Stop(),   # pop PendingMajorMinorImprovement after-phase
        Stop(),   # pop PendingSubActionSpace
    ])


def test_build_major_schedules_next_3():
    s = setup(0)                              # round 1
    s = with_resources(s, 0, clay=2)
    s = _own_minor(s, 0, CARD_ID)
    out = _mi_build_fireplace(s)
    f = _food(out, 0)
    assert f[0] == 0                          # round 1 (current) untouched
    assert f[1] == f[2] == f[3] == 1          # rounds 2, 3, 4 scheduled
    assert f[4] == 0                          # round 5 not scheduled
    assert out.board.major_improvement_owners[0] == 0


def test_build_major_without_card_does_not_schedule():
    """Same build, but the player does NOT own Farm Building → no food scheduled."""
    s = setup(0)
    s = with_resources(s, 0, clay=2)
    out = _mi_build_fireplace(s)
    assert _food(out, 0) == [0] * len(out.players[0].future_resources)


# ---------------------------------------------------------------------------
# Auto-effect unit semantics (apply_auto_effects)
# ---------------------------------------------------------------------------

def test_unowned_is_noop():
    s = setup(0)
    out = apply_auto_effects(s, "after_build_major", 0)
    assert out is s   # registered but unowned → unchanged


def test_opponent_scoping():
    """P1 owns the card; a P0 build (acting_player=0) must not schedule P1 food."""
    s = _own_minor(setup(0), 1, CARD_ID)
    out = apply_auto_effects(s, "after_build_major", 0)
    assert _food(out, 1) == [0] * len(out.players[1].future_resources)
    # But a P1 build does schedule P1's food.
    out2 = apply_auto_effects(s, "after_build_major", 1)
    f1 = _food(out2, 1)
    assert f1[1] == f1[2] == f1[3] == 1 and f1[0] == 0


def test_each_time_re_fires():
    """'Each time you build a major' — two builds stack +1 food each on shared slots."""
    s = _own_minor(setup(0), 0, CARD_ID)      # round 1
    out = apply_auto_effects(s, "after_build_major", 0)
    out = apply_auto_effects(out, "after_build_major", 0)
    f = _food(out, 0)
    assert f[1] == f[2] == f[3] == 2          # two builds → +2 on rounds 2,3,4


# ---------------------------------------------------------------------------
# Late-game clamping: "each REMAINING round space"
# ---------------------------------------------------------------------------

def test_round_13_only_round_14_scheduled():
    s = _own_minor(_set_round(setup(0), 13), 0, CARD_ID)
    out = apply_auto_effects(s, "after_build_major", 0)
    f = _food(out, 0)
    assert f[13] == 1                          # round 14 (only remaining)
    assert sum(f) == 1                         # rounds 15, 16 dropped


def test_round_14_schedules_nothing():
    s = _own_minor(_set_round(setup(0), 14), 0, CARD_ID)
    out = apply_auto_effects(s, "after_build_major", 0)
    assert _food(out, 0) == [0] * len(out.players[0].future_resources)


# ---------------------------------------------------------------------------
# The scheduled food is actually collected at round start
# ---------------------------------------------------------------------------

def test_scheduled_food_is_collected():
    """Build in round 1, then advance into round 2 → +1 food delivered, slot cleared."""
    s = setup(0)
    s = with_resources(s, 0, clay=2)
    s = _own_minor(s, 0, CARD_ID)
    out = _mi_build_fireplace(s)
    food_before = out.players[0].resources.food
    # _complete_preparation distributes future_resources[round_number] for the new round.
    out2 = _complete_preparation(fast_replace(out, round_number=1))
    assert out2.players[0].resources.food == food_before + 1
    assert out2.players[0].future_resources[1].food == 0   # consumed slot cleared
