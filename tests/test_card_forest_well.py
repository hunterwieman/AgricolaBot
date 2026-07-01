"""Tests for Forest Well (minor improvement, D44; Dulcinaria Expansion).

Card text: "Place 1 food on each remaining round space, up to the amount of wood in
your supply. At the start of these rounds, you get the food."
Cost: 1 Stone, 1 Food. Prerequisite: 2 Occupations. VPs: 1. Not passing.

Category 8 (deferred goods) with a COUNT CAP: place 1 food on the first `wood`
remaining round spaces (R+1 .. 14 in board order), where `wood` is the player's wood
supply at play. Wood is NOT spent — it only caps how many spaces are seeded. The food
rides on `future_resources` and is collected at the start of each scheduled round in
`engine._complete_preparation`.
"""
from __future__ import annotations

import agricola.cards.forest_well  # noqa: F401  (registers the card)

from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import Phase
from agricola.engine import _complete_preparation
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from agricola.state import GameState

CARD_ID = "forest_well"


def _food(state: GameState, idx: int):
    return [r.food for r in state.players[idx].future_resources]


def _set_wood(state: GameState, idx: int, n: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=fast_replace(p.resources, wood=n))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _give_occ_count(state: GameState, idx: int, n: int) -> GameState:
    """Give player `idx` exactly `n` placeholder occupations (for the count prereq)."""
    p = state.players[idx]
    p = fast_replace(p, occupations=frozenset(f"_occ{i}" for i in range(n)))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_forest_well_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(stone=1, food=1))
    assert spec.min_occupations == 2
    assert spec.vps == 1
    assert spec.passing_left is False


# ---------------------------------------------------------------------------
# on_play effect — count cap = wood in supply
# ---------------------------------------------------------------------------

def test_on_play_caps_count_to_wood():
    # R=1, wood=3 → food on the next 3 remaining round spaces (rounds 2,3,4).
    s = _set_wood(setup(0), 0, 3)
    out = MINORS[CARD_ID].on_play(s, 0)
    f = _food(out, 0)
    for slot in range(14):
        rnd = slot + 1
        assert f[slot] == (1 if rnd in (2, 3, 4) else 0)
    assert sum(f) == 3


def test_on_play_zero_wood_schedules_nothing():
    s = _set_wood(setup(0), 0, 0)
    out = MINORS[CARD_ID].on_play(s, 0)
    assert sum(_food(out, 0)) == 0


def test_on_play_wood_exceeds_remaining_rounds_maxes_out():
    # R=1, wood=100 → every remaining round space (2..14) gets food, surplus unused.
    s = _set_wood(setup(0), 0, 100)
    out = MINORS[CARD_ID].on_play(s, 0)
    f = _food(out, 0)
    assert f[0] == 0                                   # current round 1 not scheduled
    for slot in range(1, 14):                          # rounds 2..14
        assert f[slot] == 1
    assert sum(f) == 13


def test_on_play_takes_remaining_rounds_in_order():
    # Entering mid-game on round 10 with wood=2 → only rounds 11,12 get food.
    s = _set_wood(fast_replace(setup(0), round_number=10), 0, 2)
    out = MINORS[CARD_ID].on_play(s, 0)
    f = _food(out, 0)
    assert f[10] == 1 and f[11] == 1                   # rounds 11, 12
    assert f[9] == 0                                   # round 10 (current) skipped
    assert f[12] == 0 and f[13] == 0                   # rounds 13, 14 beyond the cap
    assert sum(f) == 2


def test_on_play_clamps_past_14():
    # R=13, wood=5 → only round 14 remains; the over-large cap clamps to it.
    s = _set_wood(fast_replace(setup(0), round_number=13), 0, 5)
    out = MINORS[CARD_ID].on_play(s, 0)
    f = _food(out, 0)
    assert f[13] == 1
    assert sum(f) == 1


def test_on_play_does_not_spend_wood():
    s = _set_wood(setup(0), 0, 4)
    out = MINORS[CARD_ID].on_play(s, 0)
    assert out.players[0].resources.wood == 4          # wood is a cap, never spent


def test_on_play_additive_with_existing_schedule():
    # schedule_resources is additive: a pre-existing food promise stacks.
    s = _set_wood(setup(0), 0, 2)                       # seeds rounds 2,3
    p = s.players[0]
    slots = list(p.future_resources)
    slots[1] = slots[1] + Resources(food=2)            # round 2 already has 2 food
    p = fast_replace(p, future_resources=tuple(slots))
    s = fast_replace(s, players=(p, s.players[1]))
    out = MINORS[CARD_ID].on_play(s, 0)
    assert _food(out, 0)[1] == 3                        # 2 existing + 1 scheduled


# ---------------------------------------------------------------------------
# Prerequisite — hold >=2 occupations (have-check, not spent)
# ---------------------------------------------------------------------------

def test_prereq_requires_two_occupations():
    s = setup(0)
    assert not prereq_met(MINORS[CARD_ID], _give_occ_count(s, 0, 1), 0)
    assert prereq_met(MINORS[CARD_ID], _give_occ_count(s, 0, 2), 0)
    assert prereq_met(MINORS[CARD_ID], _give_occ_count(s, 0, 4), 0)  # >=2, no upper cap


# ---------------------------------------------------------------------------
# Real round-start collection flow
# ---------------------------------------------------------------------------

def test_scheduled_food_collected_at_round_start():
    # Schedule from round 1 (wood=2 → rounds 2,3), enter round 2 (PREPARATION → WORK)
    # and confirm the owner receives exactly the 1 food promised for round 2, with the
    # slot cleared.
    s = _set_wood(setup(0), 0, 2)
    s = MINORS[CARD_ID].on_play(s, 0)
    assert _food(s, 0)[1] == 1                          # round 2 slot armed

    before_food = s.players[0].resources.food
    s = fast_replace(s, round_number=1, phase=Phase.PREPARATION)
    out = _complete_preparation(s)
    assert out.round_number == 2
    assert out.players[0].resources.food == before_food + 1
    assert _food(out, 0)[1] == 0                        # round-2 carrier slot cleared
    assert _food(out, 0)[2] == 1                        # round 3 still armed


def test_only_owner_receives_food():
    # Food rides on the owner's schedule only; the opponent gets nothing.
    s = _set_wood(setup(0), 0, 3)
    s = MINORS[CARD_ID].on_play(s, 0)
    assert sum(_food(s, 1)) == 0
