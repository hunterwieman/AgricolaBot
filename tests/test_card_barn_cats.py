"""Tests for Barn Cats (minor improvement, E43; Ephipparius Expansion).

Card text: "If you have 1/2/3/4 stables, place 1 food on each of the next 2/3/4/5
round spaces. At the start of these rounds, you get the food."
Cost: none (free). Prerequisite: 1 Stable. VPs: 1. Not passing.

Category 8 (deferred goods), the Pond Hut shape. On play, +1 food is scheduled onto
each of the next N rounds where N = (stables built) + 1 (1 stable -> 2 rounds, ...,
4 stables -> 5 rounds). Food rides on `future_resources`, collected at each round's
start by `engine._complete_preparation`. Prereq: at least 1 stable built.
"""
from __future__ import annotations

import agricola.cards.barn_cats  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import CellType, Phase
from agricola.engine import _complete_preparation, step
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell, GameState, get_space, with_space
from tests.factories import with_grid
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("barn_cats",) + tuple(f"m{i}" for i in range(20)),
)


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def _food(state: GameState, idx: int):
    return [r.food for r in state.players[idx].future_resources]


def _with_stables(state: GameState, idx: int, n: int) -> GameState:
    cells = [(0, 0), (0, 1), (0, 2), (0, 3)]  # up to 4 standalone stables
    overrides = {cells[i]: Cell(cell_type=CellType.STABLE) for i in range(n)}
    return with_grid(state, idx, overrides)


# ---------------------------------------------------------------------------
# Registration / spec
# ---------------------------------------------------------------------------

def test_barn_cats_registered():
    assert "barn_cats" in MINORS
    spec = MINORS["barn_cats"]
    assert spec.cost == Cost()           # free
    assert spec.vps == 1
    assert spec.passing_left is False
    assert spec.min_occupations == 0
    assert spec.max_occupations is None
    assert spec.prereq is not None       # the "1 stable" have-check


# ---------------------------------------------------------------------------
# Prerequisite: at least 1 stable built
# ---------------------------------------------------------------------------

def test_barn_cats_prereq_requires_a_stable():
    spec = MINORS["barn_cats"]
    s = setup(0)
    assert not prereq_met(spec, s, 0)                  # 0 stables → not met
    assert prereq_met(spec, _with_stables(s, 0, 1), 0)  # 1 stable → met
    assert prereq_met(spec, _with_stables(s, 0, 4), 0)  # more still met


# ---------------------------------------------------------------------------
# on_play scheduling — N = stables + 1
# ---------------------------------------------------------------------------

def test_barn_cats_rounds_scale_with_stables():
    # 1/2/3/4 stables → 2/3/4/5 next round spaces.
    for stables, expected_rounds in ((1, 2), (2, 3), (3, 4), (4, 5)):
        s = _with_stables(setup(0), 0, stables)  # R=1 → rounds 2..(1+N)
        out = MINORS["barn_cats"].on_play(s, 0)
        food = _food(out, 0)
        assert sum(food) == expected_rounds
        for rnd in range(2, 2 + expected_rounds):
            assert food[rnd - 1] == 1
        assert sum(_food(out, 1)) == 0   # opponent untouched


def test_barn_cats_relative_to_current_round():
    # 2 stables on round 6 → next 3 rounds are 7, 8, 9.
    s = _with_stables(fast_replace(setup(0), round_number=6), 0, 2)
    out = MINORS["barn_cats"].on_play(s, 0)
    food = _food(out, 0)
    assert food[6] == 1 and food[7] == 1 and food[8] == 1  # rounds 7, 8, 9
    assert sum(food) == 3


def test_barn_cats_clamps_rounds_past_14():
    # 4 stables on round 13 → next 5 would be 14..18; only round 14 is in-game.
    s = _with_stables(fast_replace(setup(0), round_number=13), 0, 4)
    out = MINORS["barn_cats"].on_play(s, 0)
    food = _food(out, 0)
    assert food[13] == 1   # round 14 kept
    assert sum(food) == 1  # rounds 15..18 dropped


# ---------------------------------------------------------------------------
# End-to-end collection at round start
# ---------------------------------------------------------------------------

def test_barn_cats_food_collected_at_round_start():
    s = _with_stables(setup(0), 0, 1)             # 1 stable → rounds 2, 3
    s = MINORS["barn_cats"].on_play(s, 0)
    food_before = s.players[0].resources.food
    s = fast_replace(s, round_number=1, phase=Phase.PREPARATION)
    out = _complete_preparation(s)
    assert out.round_number == 2
    assert out.players[0].resources.food == food_before + 1
    assert out.players[0].future_resources[1].food == 0


# ---------------------------------------------------------------------------
# Real play flow — play the minor through a live engine decision point
# ---------------------------------------------------------------------------

def test_barn_cats_played_via_engine_schedules_food():
    cs, _env = setup_env(0, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = _with_stables(cs, cp, 1)   # satisfy the 1-stable prerequisite (→ 2 rounds)
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"barn_cats"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    R = cs.round_number

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "barn_cats"))

    assert "barn_cats" in cs.players[cp].minor_improvements
    food = _food(cs, cp)
    for rnd in (R + 1, R + 2):
        if rnd - 1 < len(food):
            assert food[rnd - 1] == 1
    assert sum(food) == 2
