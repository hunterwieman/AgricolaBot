"""Tests for Clay Supply (minor improvement, C77; Corbarius Expansion).

Card text: "Place 1 clay on each of the next 3 round spaces. At the start of these
rounds, you get the clay."
Cost: 1 Food. No prerequisite. VPs: none. Not passing.

Category 8 (deferred goods), the Lumberjack shape with a fixed relative window of 3:
on play, +1 clay is scheduled onto each of the next 3 round spaces (rounds R+1, R+2,
R+3), riding on `future_resources` and collected at each round's start by
`engine._complete_preparation`.
"""
from __future__ import annotations

import agricola.cards.clay_supply  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import GameState, get_space, with_space
from tests.factories import with_resources
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("clay_supply",) + tuple(f"m{i}" for i in range(20)),
)


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def _clay(state: GameState, idx: int):
    return [r.clay for r in state.players[idx].future_resources]


# ---------------------------------------------------------------------------
# Registration / spec
# ---------------------------------------------------------------------------

def test_clay_supply_registered():
    assert "clay_supply" in MINORS
    spec = MINORS["clay_supply"]
    assert spec.cost == Cost(resources=Resources(food=1))
    assert spec.vps == 0
    assert spec.passing_left is False
    # No prerequisite: any state satisfies it.
    assert prereq_met(spec, setup(0), 0)
    assert prereq_met(spec, setup(0), 1)


# ---------------------------------------------------------------------------
# on_play scheduling — the deferred goods
# ---------------------------------------------------------------------------

def test_clay_supply_next_three_rounds_at_round_1():
    s = setup(0)   # R=1 → next 3 round spaces are rounds 2, 3, 4
    out = MINORS["clay_supply"].on_play(s, 0)
    clay = _clay(out, 0)
    assert clay[0] == 0                     # round 1 (current) untouched
    assert clay[1] == clay[2] == clay[3] == 1  # rounds 2, 3, 4
    assert clay[4] == 0                     # round 5 not scheduled
    assert sum(clay) == 3
    # Only the owner is scheduled; the opponent is untouched.
    assert sum(_clay(out, 1)) == 0


def test_clay_supply_window_is_relative_to_current_round():
    # Playing on round 6 schedules rounds 7, 8, 9 (NOT the current round 6).
    s = fast_replace(setup(0), round_number=6)
    out = MINORS["clay_supply"].on_play(s, 0)
    clay = _clay(out, 0)
    assert clay[5] == 0                     # round 6 (current) dropped
    assert clay[6] == clay[7] == clay[8] == 1  # rounds 7, 8, 9
    assert sum(clay) == 3


def test_clay_supply_clamps_past_round_14():
    # Round 13: next 3 would be rounds 14, 15, 16 — only round 14 is in range.
    s = fast_replace(setup(0), round_number=13)
    out = MINORS["clay_supply"].on_play(s, 0)
    clay = _clay(out, 0)
    assert clay[13] == 1   # round 14
    assert sum(clay) == 1  # rounds 15, 16 dropped (past the 14-round game)


def test_clay_supply_no_spaces_at_round_14():
    # Round 14 (the last round): no future round spaces exist, so nothing is scheduled.
    s = fast_replace(setup(0), round_number=14)
    out = MINORS["clay_supply"].on_play(s, 0)
    assert sum(_clay(out, 0)) == 0


def test_clay_supply_schedule_is_additive():
    # on_play adds onto whatever is already promised (the helper is additive), so the
    # existing future_resources slots are preserved, not overwritten.
    s = setup(0)
    p = s.players[0]
    fr = list(p.future_resources)
    fr[1] = fr[1] + Resources(clay=2)   # round 2 already has 2 clay promised
    s = fast_replace(s, players=(fast_replace(p, future_resources=tuple(fr)),
                                 s.players[1]))
    out = MINORS["clay_supply"].on_play(s, 0)
    clay = _clay(out, 0)
    assert clay[1] == 3   # 2 pre-existing + 1 from Clay Supply


# ---------------------------------------------------------------------------
# End-to-end collection at round start
# ---------------------------------------------------------------------------

def test_clay_supply_clay_collected_at_round_start():
    # Schedule the clay, then enter a scheduled round via _complete_preparation and
    # confirm the promised clay lands in the player's actual supply.
    s = MINORS["clay_supply"].on_play(setup(0), 0)  # R=1 → rounds 2, 3, 4
    clay_before = s.players[0].resources.clay
    # Sit in PREPARATION on round 1; completing it enters round 2 (a scheduled round).
    s = fast_replace(s, round_number=1, phase=Phase.PREPARATION)
    out = _complete_preparation(s)
    assert out.round_number == 2
    assert out.players[0].resources.clay == clay_before + 1
    # The consumed slot is cleared so it is not collected again.
    assert out.players[0].future_resources[1].clay == 0


def test_clay_supply_unscheduled_round_grants_nothing():
    # Entering a NON-scheduled round (round 5) collects no Clay Supply clay.
    s = MINORS["clay_supply"].on_play(setup(0), 0)  # R=1 → rounds 2, 3, 4
    s = fast_replace(s, round_number=4, phase=Phase.PREPARATION)
    clay_before = s.players[0].resources.clay
    out = _complete_preparation(s)
    assert out.round_number == 5
    assert out.players[0].resources.clay == clay_before


# ---------------------------------------------------------------------------
# Real play flow — play the minor through a live engine decision point
# ---------------------------------------------------------------------------

def test_clay_supply_played_via_engine_schedules_clay():
    # Drive the actual play-minor flow through the Major Improvement space in CARDS
    # mode (PlaceWorker -> improvement -> play_minor -> CommitPlayMinor), confirming
    # the card enters the tableau, the 1-food cost is paid, and the clay is scheduled.
    cs, _env = setup_env(0, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = with_resources(cs, cp, food=1)   # afford the 1-food cost
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"clay_supply"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    food_before = cs.players[cp].resources.food
    R = cs.round_number

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "clay_supply"))

    # The card is now in the tableau and its clay is scheduled on rounds R+1..R+3.
    assert "clay_supply" in cs.players[cp].minor_improvements
    clay = _clay(cs, cp)
    assert clay[R] == clay[R + 1] == clay[R + 2] == 1   # slot r-1 → round r
    assert sum(clay) == 3
    # Cost was paid: the 1 food is gone.
    assert cs.players[cp].resources.food == food_before - 1
