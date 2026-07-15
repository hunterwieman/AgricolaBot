"""Tests for Fruit Ladder (minor improvement, E45; Ephipparius Expansion).

Card text: "Place 1 food on each remaining even-numbered round space. At the start of
these rounds, you get the food."
Cost: 2 Wood. Prerequisite: none. VPs: 1. Not passing.

Category 8 (deferred goods), the Pond Hut shape. On play, +1 food is scheduled onto
each remaining EVEN-numbered round space (even rounds strictly after R). Food rides on
`future_resources`, collected at each round's start by `engine._complete_preparation`.
"""
from __future__ import annotations

import agricola.cards.fruit_ladder  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.specs import MINORS
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
    minors=("fruit_ladder",) + tuple(f"m{i}" for i in range(20)),
)


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def _food(state: GameState, idx: int):
    return [r.food for r in state.players[idx].future_resources]


# ---------------------------------------------------------------------------
# Registration / spec
# ---------------------------------------------------------------------------

def test_fruit_ladder_registered():
    assert "fruit_ladder" in MINORS
    spec = MINORS["fruit_ladder"]
    assert spec.cost == Cost(resources=Resources(wood=2))
    assert spec.alt_costs == ()
    assert spec.vps == 1
    assert spec.passing_left is False
    assert spec.min_occupations == 0
    assert spec.max_occupations is None
    assert spec.prereq is None           # no prerequisite


# ---------------------------------------------------------------------------
# on_play scheduling — remaining even rounds
# ---------------------------------------------------------------------------

def test_fruit_ladder_schedules_remaining_even_rounds():
    s = setup(0)   # R=1 → remaining even rounds are 2, 4, 6, 8, 10, 12, 14
    out = MINORS["fruit_ladder"].on_play(s, 0)
    food = _food(out, 0)
    for rnd in (2, 4, 6, 8, 10, 12, 14):
        assert food[rnd - 1] == 1
    for rnd in (1, 3, 5, 7, 9, 11, 13):
        assert food[rnd - 1] == 0
    assert sum(food) == 7
    assert sum(_food(out, 1)) == 0   # opponent untouched


def test_fruit_ladder_only_even_rounds_after_current():
    # Played on round 7 → remaining even rounds are 8, 10, 12, 14 (only those > 7).
    s = fast_replace(setup(0), round_number=7)
    out = MINORS["fruit_ladder"].on_play(s, 0)
    food = _food(out, 0)
    for rnd in (8, 10, 12, 14):
        assert food[rnd - 1] == 1
    assert sum(food) == 4
    assert food[5] == 0   # round 6 (even but past) untouched


# ---------------------------------------------------------------------------
# End-to-end collection at round start
# ---------------------------------------------------------------------------

def test_fruit_ladder_food_collected_at_even_round_start():
    s = MINORS["fruit_ladder"].on_play(setup(0), 0)   # schedules 2, 4, 6, ...
    food_before = s.players[0].resources.food
    s = fast_replace(s, round_number=1, phase=Phase.PREPARATION)
    out = _complete_preparation(s)
    assert out.round_number == 2
    assert out.players[0].resources.food == food_before + 1
    assert out.players[0].future_resources[1].food == 0


# ---------------------------------------------------------------------------
# Real play flow — play the minor through a live engine decision point
# ---------------------------------------------------------------------------

def test_fruit_ladder_played_via_engine_schedules_food():
    cs, _env = setup_env(0, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = with_resources(cs, cp, wood=2)   # pay the 2-wood cost
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"fruit_ladder"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    R = cs.round_number

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "fruit_ladder"))

    assert "fruit_ladder" in cs.players[cp].minor_improvements
    assert cs.players[cp].resources.wood == 0   # cost paid
    food = _food(cs, cp)
    expected = [r for r in range(R + 1, 15) if r % 2 == 0]
    for rnd in expected:
        assert food[rnd - 1] == 1
    assert sum(food) == len(expected)
