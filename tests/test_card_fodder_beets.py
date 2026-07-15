"""Tests for Fodder Beets (minor improvement, E44; Ephipparius Expansion).

Card text: "Place 1 food on each remaining odd-numbered round space. At the start of
these rounds, you get the food."
Cost: none (free). Prerequisite: 3 Field Tiles. VPs: 1. Not passing.

Category 8 (deferred goods), the Pond Hut shape. On play, +1 food is scheduled onto
each remaining ODD-numbered round space (odd rounds strictly after R). Food rides on
`future_resources`, collected at each round's start by `engine._complete_preparation`.
Prereq: at least 3 plowed FIELD tiles on the farmyard grid (card-fields excluded).
"""
from __future__ import annotations

import agricola.cards.fodder_beets  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import CardPool, setup, setup_env
from agricola.state import GameState, get_space, with_space
from tests.factories import with_fields
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("fodder_beets",) + tuple(f"m{i}" for i in range(20)),
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

def test_fodder_beets_registered():
    assert "fodder_beets" in MINORS
    spec = MINORS["fodder_beets"]
    assert spec.cost == Cost()           # free
    assert spec.vps == 1
    assert spec.passing_left is False
    assert spec.min_occupations == 0
    assert spec.max_occupations is None
    assert spec.prereq is not None       # the "3 field tiles" have-check


# ---------------------------------------------------------------------------
# Prerequisite: at least 3 field tiles (grid FIELD cells only)
# ---------------------------------------------------------------------------

def test_fodder_beets_prereq_requires_three_field_tiles():
    spec = MINORS["fodder_beets"]
    s = setup(0)
    assert not prereq_met(spec, s, 0)                                   # 0 fields
    assert not prereq_met(spec, with_fields(s, 0, [(0, 0), (0, 1)]), 0)  # 2 fields
    assert prereq_met(spec, with_fields(s, 0, [(0, 0), (0, 1), (0, 2)]), 0)  # 3 fields


# ---------------------------------------------------------------------------
# on_play scheduling — remaining odd rounds
# ---------------------------------------------------------------------------

def test_fodder_beets_schedules_remaining_odd_rounds():
    s = setup(0)   # R=1 → remaining odd rounds are 3, 5, 7, 9, 11, 13
    out = MINORS["fodder_beets"].on_play(s, 0)
    food = _food(out, 0)
    for rnd in (3, 5, 7, 9, 11, 13):
        assert food[rnd - 1] == 1
    for rnd in (1, 2, 4, 6, 8, 10, 12, 14):
        assert food[rnd - 1] == 0
    assert sum(food) == 6
    assert sum(_food(out, 1)) == 0   # opponent untouched


def test_fodder_beets_only_odd_rounds_after_current():
    # Played on round 8 → remaining odd rounds are 9, 11, 13 (only those > 8).
    s = fast_replace(setup(0), round_number=8)
    out = MINORS["fodder_beets"].on_play(s, 0)
    food = _food(out, 0)
    for rnd in (9, 11, 13):
        assert food[rnd - 1] == 1
    assert sum(food) == 3
    assert food[6] == 0   # round 7 (odd but past) untouched


# ---------------------------------------------------------------------------
# End-to-end collection at round start
# ---------------------------------------------------------------------------

def test_fodder_beets_food_collected_at_odd_round_start():
    # Played on round 2 → schedules rounds 3, 5, 7, ...; entering round 3 grants food.
    s = fast_replace(setup(0), round_number=2)
    s = MINORS["fodder_beets"].on_play(s, 0)
    food_before = s.players[0].resources.food
    s = fast_replace(s, round_number=2, phase=Phase.PREPARATION)
    out = _complete_preparation(s)
    assert out.round_number == 3
    assert out.players[0].resources.food == food_before + 1
    assert out.players[0].future_resources[2].food == 0


# ---------------------------------------------------------------------------
# Real play flow — play the minor through a live engine decision point
# ---------------------------------------------------------------------------

def test_fodder_beets_played_via_engine_schedules_food():
    cs, _env = setup_env(0, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = with_fields(cs, cp, [(0, 0), (0, 1), (0, 2)])  # satisfy 3-field prerequisite
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"fodder_beets"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    R = cs.round_number

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "fodder_beets"))

    assert "fodder_beets" in cs.players[cp].minor_improvements
    food = _food(cs, cp)
    expected = [r for r in range(R + 1, 15) if r % 2 == 1]
    for rnd in expected:
        assert food[rnd - 1] == 1
    assert sum(food) == len(expected)
