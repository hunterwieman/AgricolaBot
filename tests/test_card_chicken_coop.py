"""Tests for Chicken Coop (minor improvement, C44; Consul Dirigens Expansion).

Card text: "Place 1 food on each of the next 8 round spaces. At the start of these
rounds, you get the food."
Cost: 2 Wood/2 Clay, 1 Reed (2 Wood OR 2 Clay, PLUS 1 Reed). Prerequisite: none.
VPs: 1. Not passing.

Category 8 (deferred goods), the Pond Hut shape. On play, +1 food is scheduled onto
each of the NEXT 8 rounds (R+1..R+8 RELATIVE to the current round), riding on
`future_resources` and collected at each round's start by
`engine._complete_preparation`.
"""
from __future__ import annotations

import agricola.cards.chicken_coop  # noqa: F401  (registers the card)

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
    minors=("chicken_coop",) + tuple(f"m{i}" for i in range(20)),
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

def test_chicken_coop_registered():
    assert "chicken_coop" in MINORS
    spec = MINORS["chicken_coop"]
    # "2 Wood/2 Clay, 1 Reed": base = 2 Wood + 1 Reed; alt = 2 Clay + 1 Reed.
    assert spec.cost == Cost(resources=Resources(wood=2, reed=1))
    assert spec.alt_costs == (Cost(resources=Resources(clay=2, reed=1)),)
    assert spec.vps == 1
    assert spec.passing_left is False
    assert spec.min_occupations == 0
    assert spec.max_occupations is None
    assert spec.prereq is None  # no prerequisite


# ---------------------------------------------------------------------------
# on_play scheduling — the deferred food (RELATIVE next-8 rounds)
# ---------------------------------------------------------------------------

def test_chicken_coop_schedules_next_eight_rounds():
    s = setup(0)   # R=1 → next 8 rounds are 2..9
    out = MINORS["chicken_coop"].on_play(s, 0)
    food = _food(out, 0)
    for rnd in range(2, 10):
        assert food[rnd - 1] == 1
    assert sum(food) == 8
    # Only the owner is scheduled; the opponent is untouched.
    assert sum(_food(out, 1)) == 0


def test_chicken_coop_relative_to_current_round():
    # Played on round 3 → the next 8 rounds are 4..11 (relative, not absolute).
    s = fast_replace(setup(0), round_number=3)
    out = MINORS["chicken_coop"].on_play(s, 0)
    food = _food(out, 0)
    for rnd in range(4, 12):
        assert food[rnd - 1] == 1
    assert sum(food) == 8
    assert food[1] == 0  # round 2 (already past) untouched


def test_chicken_coop_clamps_rounds_past_14():
    # Played on round 10 → next 8 would be 11..18; only 11..14 are in-game.
    s = fast_replace(setup(0), round_number=10)
    out = MINORS["chicken_coop"].on_play(s, 0)
    food = _food(out, 0)
    for rnd in (11, 12, 13, 14):
        assert food[rnd - 1] == 1
    assert sum(food) == 4  # rounds 15..18 silently dropped


# ---------------------------------------------------------------------------
# End-to-end collection at round start
# ---------------------------------------------------------------------------

def test_chicken_coop_food_collected_at_round_start():
    s = MINORS["chicken_coop"].on_play(setup(0), 0)   # schedules rounds 2..9
    food_before = s.players[0].resources.food
    s = fast_replace(s, round_number=1, phase=Phase.PREPARATION)
    out = _complete_preparation(s)
    assert out.round_number == 2
    assert out.players[0].resources.food == food_before + 1
    # The consumed slot is cleared so it is not collected again.
    assert out.players[0].future_resources[1].food == 0


# ---------------------------------------------------------------------------
# Real play flow — play the minor through a live engine decision point
# ---------------------------------------------------------------------------

def test_chicken_coop_played_via_engine_schedules_food():
    cs, _env = setup_env(0, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    # Pay wood+reed (base cost); give ONLY wood so the payment is unambiguous.
    cs = with_resources(cs, cp, wood=2, reed=1)
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"chicken_coop"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    R = cs.round_number

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "chicken_coop"))

    assert "chicken_coop" in cs.players[cp].minor_improvements
    # Cost was paid.
    assert cs.players[cp].resources.wood == 0
    assert cs.players[cp].resources.reed == 0
    food = _food(cs, cp)
    for rnd in range(R + 1, R + 9):
        if rnd - 1 < len(food):
            assert food[rnd - 1] == 1
    assert sum(food) == 8
