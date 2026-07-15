"""Tests for Waterlily Pond (minor improvement, E46; Ephipparius Expansion).

Card text: "Place 1 food on each of the next 2 round spaces. At the start of these
rounds, you get the food."
Cost: none (free). Prerequisite: Exactly 2 Occupations. VPs: 1. Not passing.

Category 8 (deferred goods), the Pond Hut shape. On play, +1 food is scheduled onto
each of the NEXT 2 rounds (R+1, R+2 RELATIVE to the current round), riding on
`future_resources` and collected at each round's start by
`engine._complete_preparation`. Prereq: exactly 2 occupations (min == max == 2).
"""
from __future__ import annotations

import agricola.cards.waterlily_pond  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import CardPool, setup, setup_env
from agricola.state import GameState, get_space, with_space
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("waterlily_pond",) + tuple(f"m{i}" for i in range(20)),
)


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def _food(state: GameState, idx: int):
    return [r.food for r in state.players[idx].future_resources]


def _with_occupations(state: GameState, idx: int, n: int) -> GameState:
    p = fast_replace(state.players[idx],
                     occupations=frozenset(f"occ{i}" for i in range(n)))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


# ---------------------------------------------------------------------------
# Registration / spec
# ---------------------------------------------------------------------------

def test_waterlily_pond_registered():
    assert "waterlily_pond" in MINORS
    spec = MINORS["waterlily_pond"]
    assert spec.cost == Cost()           # free
    assert spec.vps == 1
    assert spec.passing_left is False
    assert spec.min_occupations == 2
    assert spec.max_occupations == 2     # "Exactly 2 Occupations"


# ---------------------------------------------------------------------------
# Prerequisite: EXACTLY 2 occupations
# ---------------------------------------------------------------------------

def test_waterlily_pond_prereq_requires_exactly_two_occupations():
    spec = MINORS["waterlily_pond"]
    s = setup(0)
    assert not prereq_met(spec, _with_occupations(s, 0, 1), 0)  # too few
    assert prereq_met(spec, _with_occupations(s, 0, 2), 0)      # exactly 2
    assert not prereq_met(spec, _with_occupations(s, 0, 3), 0)  # too many (max 2)


# ---------------------------------------------------------------------------
# on_play scheduling — the deferred food (RELATIVE next-2 rounds)
# ---------------------------------------------------------------------------

def test_waterlily_pond_schedules_next_two_rounds():
    s = setup(0)   # R=1 → next 2 rounds are 2, 3
    out = MINORS["waterlily_pond"].on_play(s, 0)
    food = _food(out, 0)
    assert food[1] == 1 and food[2] == 1   # rounds 2, 3
    assert sum(food) == 2
    assert sum(_food(out, 1)) == 0   # opponent untouched


def test_waterlily_pond_relative_to_current_round():
    # Played on round 9 → the next 2 rounds are 10, 11.
    s = fast_replace(setup(0), round_number=9)
    out = MINORS["waterlily_pond"].on_play(s, 0)
    food = _food(out, 0)
    assert food[9] == 1 and food[10] == 1  # rounds 10, 11
    assert sum(food) == 2
    assert food[1] == 0   # round 2 untouched


def test_waterlily_pond_clamps_rounds_past_14():
    # Played on round 14 → next 2 would be 15, 16; neither is in-game.
    s = fast_replace(setup(0), round_number=14)
    out = MINORS["waterlily_pond"].on_play(s, 0)
    assert sum(_food(out, 0)) == 0


# ---------------------------------------------------------------------------
# End-to-end collection at round start
# ---------------------------------------------------------------------------

def test_waterlily_pond_food_collected_at_round_start():
    s = MINORS["waterlily_pond"].on_play(setup(0), 0)   # schedules rounds 2, 3
    food_before = s.players[0].resources.food
    s = fast_replace(s, round_number=1, phase=Phase.PREPARATION)
    out = _complete_preparation(s)
    assert out.round_number == 2
    assert out.players[0].resources.food == food_before + 1
    assert out.players[0].future_resources[1].food == 0


# ---------------------------------------------------------------------------
# Real play flow — play the minor through a live engine decision point
# ---------------------------------------------------------------------------

def test_waterlily_pond_played_via_engine_schedules_food():
    cs, _env = setup_env(0, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = _with_occupations(cs, cp, 2)   # satisfy the exactly-2-occupations prerequisite
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"waterlily_pond"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    R = cs.round_number

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "waterlily_pond"))

    assert "waterlily_pond" in cs.players[cp].minor_improvements
    food = _food(cs, cp)
    for rnd in (R + 1, R + 2):
        if rnd - 1 < len(food):
            assert food[rnd - 1] == 1
    assert sum(food) == 2
