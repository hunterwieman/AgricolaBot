"""Tests for Reed Pond (minor improvement, D78; Consul Dirigens Expansion).

Card text: "Place 1 reed on each of the next 3 round spaces. At the start of these
rounds, you get the reed."
Cost: none (free). Prerequisite: 3 Occupations. VPs: none. Not passing.

Category 8 (deferred goods), the Pond Hut shape. On play, +1 reed is scheduled onto
each of the NEXT 3 rounds (R+1, R+2, R+3 RELATIVE to the current round), riding on
`future_resources` and collected at each round's start by
`engine._complete_preparation`. The "3 Occupations" prerequisite is "at least 3".
"""
from __future__ import annotations

import agricola.cards.reed_pond  # noqa: F401  (registers the card)

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
    minors=("reed_pond",) + tuple(f"m{i}" for i in range(20)),
)


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def _reed(state: GameState, idx: int):
    return [r.reed for r in state.players[idx].future_resources]


def _with_occupations(state: GameState, idx: int, n: int) -> GameState:
    p = fast_replace(state.players[idx],
                     occupations=frozenset(f"occ{i}" for i in range(n)))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


# ---------------------------------------------------------------------------
# Registration / spec
# ---------------------------------------------------------------------------

def test_reed_pond_registered():
    assert "reed_pond" in MINORS
    spec = MINORS["reed_pond"]
    assert spec.cost == Cost()           # free
    assert spec.vps == 0
    assert spec.passing_left is False
    assert spec.min_occupations == 3
    assert spec.max_occupations is None  # "at least 3", no upper bound


# ---------------------------------------------------------------------------
# Prerequisite: at least 3 occupations
# ---------------------------------------------------------------------------

def test_reed_pond_prereq_requires_three_occupations():
    spec = MINORS["reed_pond"]
    s = setup(0)
    # 0, 1, 2 occupations: prereq NOT met.
    assert not prereq_met(spec, _with_occupations(s, 0, 0), 0)
    assert not prereq_met(spec, _with_occupations(s, 0, 2), 0)
    # Exactly 3: met.
    assert prereq_met(spec, _with_occupations(s, 0, 3), 0)


def test_reed_pond_prereq_no_upper_bound():
    # More than 3 occupations still satisfies the prerequisite (no max).
    spec = MINORS["reed_pond"]
    s = _with_occupations(setup(0), 0, 5)
    assert prereq_met(spec, s, 0)


# ---------------------------------------------------------------------------
# on_play scheduling — the deferred goods (RELATIVE next-3 rounds)
# ---------------------------------------------------------------------------

def test_reed_pond_schedules_next_three_rounds():
    s = setup(0)   # R=1 → next 3 rounds are 2, 3, 4
    out = MINORS["reed_pond"].on_play(s, 0)
    reed = _reed(out, 0)
    for rnd in (2, 3, 4):
        assert reed[rnd - 1] == 1
    assert sum(reed) == 3
    # Only the owner is scheduled; the opponent is untouched.
    assert sum(_reed(out, 1)) == 0


def test_reed_pond_relative_to_current_round():
    # Played on round 6 → the next 3 rounds are 7, 8, 9 (relative, not absolute).
    s = fast_replace(setup(0), round_number=6)
    out = MINORS["reed_pond"].on_play(s, 0)
    reed = _reed(out, 0)
    assert reed[6] == 1 and reed[7] == 1 and reed[8] == 1  # rounds 7, 8, 9
    assert sum(reed) == 3
    # Earlier rounds untouched.
    assert reed[1] == 0


def test_reed_pond_clamps_rounds_past_14():
    # Played on round 13 → next 3 would be 14, 15, 16; only round 14 is in-game.
    s = fast_replace(setup(0), round_number=13)
    out = MINORS["reed_pond"].on_play(s, 0)
    reed = _reed(out, 0)
    assert reed[13] == 1   # round 14 kept
    assert sum(reed) == 1  # rounds 15, 16 silently dropped (out of range)


def test_reed_pond_schedule_is_additive():
    # on_play adds onto whatever is already promised (the helper is additive).
    s = setup(0)
    p = s.players[0]
    fr = list(p.future_resources)
    fr[1] = fr[1] + Resources(reed=2)   # round 2 already has 2 reed promised
    s = fast_replace(s, players=(fast_replace(p, future_resources=tuple(fr)),
                                 s.players[1]))
    out = MINORS["reed_pond"].on_play(s, 0)
    reed = _reed(out, 0)
    assert reed[1] == 3   # 2 pre-existing + 1 from Reed Pond


# ---------------------------------------------------------------------------
# End-to-end collection at round start
# ---------------------------------------------------------------------------

def test_reed_pond_reed_collected_at_round_start():
    # Schedule the reed (played on round 1 → rounds 2, 3, 4), then enter a scheduled
    # round via _complete_preparation and confirm the reed lands in actual supply.
    s = MINORS["reed_pond"].on_play(setup(0), 0)
    reed_before = s.players[0].resources.reed
    # Sit in PREPARATION on round 1; completing it enters round 2 (a scheduled round).
    s = fast_replace(s, round_number=1, phase=Phase.PREPARATION)
    out = _complete_preparation(s)
    assert out.round_number == 2
    assert out.players[0].resources.reed == reed_before + 1
    # The consumed slot is cleared so it is not collected again.
    assert out.players[0].future_resources[1].reed == 0


def test_reed_pond_unscheduled_round_grants_nothing():
    # Played on round 1 → schedules rounds 2, 3, 4. Entering round 5 grants nothing.
    s = MINORS["reed_pond"].on_play(setup(0), 0)
    reed_before = s.players[0].resources.reed
    s = fast_replace(s, round_number=4, phase=Phase.PREPARATION)
    out = _complete_preparation(s)
    assert out.round_number == 5
    assert out.players[0].resources.reed == reed_before


# ---------------------------------------------------------------------------
# Real play flow — play the minor through a live engine decision point
# ---------------------------------------------------------------------------

def test_reed_pond_played_via_engine_schedules_reed():
    # Drive the actual play-minor flow through the Major Improvement space in CARDS
    # mode (PlaceWorker -> improvement -> play_minor -> CommitPlayMinor), confirming
    # the card enters the tableau (it is free) and the reed is scheduled.
    cs, _env = setup_env(0, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = _with_occupations(cs, cp, 3)   # satisfy the 3-occupations prerequisite
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"reed_pond"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    R = cs.round_number

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "reed_pond"))

    # The card is now in the tableau and its reed is scheduled on rounds R+1..R+3.
    assert "reed_pond" in cs.players[cp].minor_improvements
    reed = _reed(cs, cp)
    for rnd in (R + 1, R + 2, R + 3):
        if rnd - 1 < len(reed):
            assert reed[rnd - 1] == 1
    assert sum(reed) == 3
