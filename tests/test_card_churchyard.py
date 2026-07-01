"""Tests for Churchyard (minor improvement, D47; Dulcinaria Expansion).

Card text: "Place 2 food on each remaining round space. At the start of these
rounds, you get the food. (*Occupations and Improvements)"

Cost: 1 Stone, 1 Reed (spendable). Prerequisite: 10 Cards (Occupations and
Improvements = minors + owned majors) in front of you. VPs: 1. Not passing.

Category 8 (deferred goods): the food rides on `future_resources` and is
collected at the start of each scheduled round in `engine._complete_preparation`.
"""
from __future__ import annotations

import agricola.cards.churchyard  # noqa: F401  (registers the card)

from agricola.cards.specs import MINORS, MinorSpec, prereq_met
from agricola.constants import Phase
from agricola.engine import _complete_preparation
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup, setup_env, CardPool
from agricola.state import GameState
from tests.factories import with_majors

CARD_ID = "churchyard"


def _food(state: GameState, idx: int):
    return [r.food for r in state.players[idx].future_resources]


def _give_counts(state: GameState, idx: int, *, occ=0, minors=0) -> GameState:
    """Give player `idx` exactly `occ` placeholder occupations and `minors`
    placeholder minor improvements (for the 10-card prereq)."""
    p = state.players[idx]
    p = fast_replace(
        p,
        occupations=frozenset(f"_occ{i}" for i in range(occ)),
        minor_improvements=frozenset(f"_min{i}" for i in range(minors)),
    )
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_churchyard_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(stone=1, reed=1))  # spendable
    assert spec.min_occupations == 0       # the 10-card prereq is custom, not occ-count
    assert spec.max_occupations is None
    assert spec.vps == 1
    assert spec.passing_left is False
    assert spec.on_play is not None


# ---------------------------------------------------------------------------
# on_play effect — schedule 2 food on each remaining round
# ---------------------------------------------------------------------------

def test_on_play_schedules_all_remaining_rounds():
    s = setup(0)   # R=1 → remaining rounds 2..14
    out = MINORS[CARD_ID].on_play(s, 0)
    f = _food(out, 0)
    for slot in range(14):
        rnd = slot + 1
        assert f[slot] == (2 if rnd > 1 else 0)
    assert f[0] == 0                # current round (1) NOT scheduled
    assert sum(f) == 2 * 13         # rounds 2..14, 2 food each


def test_on_play_strict_lower_bound_skips_current_round():
    # Entering on round 7: that round's space was already collected at its start,
    # so the strict R+1 bound must NOT re-schedule it.
    s = fast_replace(setup(0), round_number=7)   # remaining rounds: 8..14
    out = MINORS[CARD_ID].on_play(s, 0)
    f = _food(out, 0)
    assert f[6] == 0                # round 7 (current) NOT scheduled
    for rnd in range(8, 15):
        assert f[rnd - 1] == 2
    assert sum(f) == 2 * 7


def test_on_play_clamps_at_round_14():
    s = fast_replace(setup(0), round_number=14)  # no remaining rounds after 14
    out = MINORS[CARD_ID].on_play(s, 0)
    assert sum(_food(out, 0)) == 0


def test_on_play_additive_with_existing_schedule():
    # schedule_resources is additive: a pre-existing food promise stacks.
    s = setup(0)
    p = s.players[0]
    slots = list(p.future_resources)
    slots[1] = slots[1] + Resources(food=3)       # round 2 already has 3 food
    p = fast_replace(p, future_resources=tuple(slots))
    s = fast_replace(s, players=(p, s.players[1]))
    out = MINORS[CARD_ID].on_play(s, 0)
    assert _food(out, 0)[1] == 5                   # 3 existing + 2 scheduled


def test_on_play_only_affects_owner():
    s = setup(0)
    out = MINORS[CARD_ID].on_play(s, 0)
    assert sum(_food(out, 1)) == 0                 # opponent untouched


# ---------------------------------------------------------------------------
# Prerequisite — 10 cards (occupations + minors + owned majors), have-check
# ---------------------------------------------------------------------------

def test_prereq_requires_ten_cards():
    spec = MINORS[CARD_ID]
    s = setup(0)
    assert not prereq_met(spec, _give_counts(s, 0, occ=5, minors=4), 0)   # 9 < 10
    assert prereq_met(spec, _give_counts(s, 0, occ=5, minors=5), 0)       # 10
    assert prereq_met(spec, _give_counts(s, 0, occ=8, minors=6), 0)       # 14 > 10


def test_prereq_counts_majors_too():
    spec = MINORS[CARD_ID]
    # 5 occupations + 4 minors = 9, plus one owned major = 10 -> met.
    s = _give_counts(setup(0), 0, occ=5, minors=4)
    s = with_majors(s, owner_by_idx={0: 0})  # owner idx 0 owns major index 0
    assert prereq_met(spec, s, 0)


def test_prereq_ignores_opponent_cards():
    spec = MINORS[CARD_ID]
    s = setup(0)
    # Opponent (player 1) has plenty; current player (0) has none.
    s = _give_counts(s, 1, occ=8, minors=8)
    s = with_majors(s, owner_by_idx={0: 1, 2: 1})
    assert not prereq_met(spec, s, 0)


def test_prereq_does_not_count_self():
    # The prereq is evaluated before the card is played (it sits in hand, not in
    # minor_improvements), so a player at exactly 10 OTHER cards qualifies and the
    # played Churchyard would be the 11th.
    spec = MinorSpec(
        CARD_ID,
        prereq=MINORS[CARD_ID].prereq,
    )
    s = _give_counts(setup(0), 0, occ=5, minors=5)  # exactly 10 other cards
    assert prereq_met(spec, s, 0)


# ---------------------------------------------------------------------------
# Real round-start collection flow
# ---------------------------------------------------------------------------

def test_scheduled_food_collected_at_round_start():
    # Schedule from round 1, then enter round 2 (PREPARATION → WORK) and confirm
    # the owner receives exactly the 2 food promised for round 2, slot cleared.
    s = setup(0)
    s = MINORS[CARD_ID].on_play(s, 0)
    assert _food(s, 0)[1] == 2                      # round 2 slot armed

    before_food = s.players[0].resources.food
    s = fast_replace(s, round_number=1, phase=Phase.PREPARATION)
    out = _complete_preparation(s)
    assert out.round_number == 2
    assert out.players[0].resources.food == before_food + 2
    assert _food(out, 0)[1] == 0                    # round-2 carrier slot now empty


def test_food_collected_each_remaining_round():
    # Walk a few rounds and confirm 2 food arrives at the start of each.
    s = MINORS[CARD_ID].on_play(setup(0), 0)
    food = s.players[0].resources.food
    for entering in (2, 3, 4):
        s = fast_replace(s, round_number=entering - 1, phase=Phase.PREPARATION)
        s = _complete_preparation(s)
        assert s.round_number == entering
        food += 2
        assert s.players[0].resources.food == food


# ---------------------------------------------------------------------------
# playable_minors gates on prereq + cost (real legality path)
# ---------------------------------------------------------------------------

def test_playable_only_when_prereq_and_cost_met():
    from agricola.legality import playable_minors

    pool = CardPool(
        occupations=tuple(f"o{i}" for i in range(20)),
        minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
    )

    def _state(*, res, occ, minors):
        cs, _env = setup_env(7, card_pool=pool)
        cp = cs.current_player
        p = fast_replace(
            cs.players[cp],
            hand_minors=frozenset({CARD_ID}),
            resources=res,
            occupations=frozenset(f"_occ{i}" for i in range(occ)),
            minor_improvements=frozenset(f"_min{i}" for i in range(minors)),
        )
        opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
        cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
        return cs, cp

    # Holds card, has stone+reed, 10 other cards -> playable.
    cs, cp = _state(res=Resources(stone=1, reed=1), occ=5, minors=5)
    assert playable_minors(cs, cp) == [CARD_ID]
    # Missing reed -> cost unaffordable.
    cs, cp = _state(res=Resources(stone=1, reed=0), occ=5, minors=5)
    assert playable_minors(cs, cp) == []
    # Prereq unmet (only 9 other cards) even with the cost in hand.
    cs, cp = _state(res=Resources(stone=1, reed=1), occ=5, minors=4)
    assert playable_minors(cs, cp) == []
