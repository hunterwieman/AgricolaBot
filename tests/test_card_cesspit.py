"""Tests for Cesspit (minor improvement, D40; Dulcinaria Expansion).

Card text: "Alternate placing 1 clay and 1 wild boar on each remaining round space,
starting with clay. At the start of these rounds, you get the respective good."
Cost: none. Prerequisite: 2 Fields and 1 Occupation. VPs: -1. Not passing.

Category 8 (deferred goods), combining the clay (`schedule_resources`,
`future_resources`) and boar (`schedule_animals`, `future_rewards`) siblings. The goods
alternate over the SEQUENCE of remaining round spaces (R+1 .. 14), clay first.
"""
import agricola.cards.cesspit  # noqa: F401  (registers the MinorSpec)

from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import CellType, Phase
from agricola.engine import _collect_future_rewards, _complete_preparation, step
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import GameState, get_space, with_space
from tests.factories import with_fields
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("cesspit",) + tuple(f"m{i}" for i in range(20)),
)


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def _clay(state: GameState, idx: int):
    return [r.clay for r in state.players[idx].future_resources]


def _boar(state: GameState, idx: int):
    return [fr.animals.boar for fr in state.players[idx].future_rewards]


def _with_occupations(state, idx, n):
    p = fast_replace(state.players[idx],
                     occupations=frozenset(f"o{i}" for i in range(n)))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registration / spec
# ---------------------------------------------------------------------------

def test_cesspit_registered():
    assert "cesspit" in MINORS
    spec = MINORS["cesspit"]
    assert spec.cost == Cost()           # no resource cost
    assert spec.min_occupations == 1
    assert spec.vps == -1                 # printed penalty
    assert spec.passing_left is False


# ---------------------------------------------------------------------------
# Prerequisite — 2 Fields AND 1 Occupation
# ---------------------------------------------------------------------------

def test_cesspit_prereq_needs_two_fields_and_one_occupation():
    s = setup(0)
    # Bare setup: 0 fields, 0 occupations -> fails.
    assert not prereq_met(MINORS["cesspit"], s, 0)
    # 1 occupation but only 1 field -> still fails (need 2 fields).
    s1 = with_fields(_with_occupations(s, 0, 1), 0, [(0, 0)])
    assert not prereq_met(MINORS["cesspit"], s1, 0)
    # 2 fields but 0 occupations -> fails on the occupation bound.
    s2 = with_fields(s, 0, [(0, 0), (0, 1)])
    assert not prereq_met(MINORS["cesspit"], s2, 0)
    # 2 fields AND 1 occupation -> satisfied.
    s3 = with_fields(_with_occupations(s, 0, 1), 0, [(0, 0), (0, 1)])
    assert prereq_met(MINORS["cesspit"], s3, 0)


def test_cesspit_prereq_counts_unsown_fields():
    # The 2-field prereq counts any FIELD tiles (no crop required, unlike Ash Trees).
    s = with_fields(_with_occupations(setup(0), 0, 1), 0, [(0, 0), (1, 0)])
    grid = s.players[0].farmyard.grid
    assert grid[0][0].cell_type is CellType.FIELD and grid[0][0].grain == 0
    assert prereq_met(MINORS["cesspit"], s, 0)


# ---------------------------------------------------------------------------
# on_play scheduling — the alternating deferred goods
# ---------------------------------------------------------------------------

def test_cesspit_alternates_clay_boar_from_round_one():
    s = setup(0)            # R=1 -> remaining spaces are rounds 2..14 (13 spaces)
    out = MINORS["cesspit"].on_play(s, 0)
    clay = _clay(out, 0)
    boar = _boar(out, 0)
    # Current round (1) untouched.
    assert clay[0] == 0 and boar[0] == 0
    # Remaining spaces R+1..14: clay on 1st,3rd,... (rounds 2,4,6,...),
    # boar on 2nd,4th,... (rounds 3,5,7,...). slot r-1 holds round r.
    clay_rounds = [r for n, r in enumerate(range(2, 15)) if n % 2 == 0]   # 2,4,6,8,10,12,14
    boar_rounds = [r for n, r in enumerate(range(2, 15)) if n % 2 == 1]   # 3,5,7,9,11,13
    assert [r for r in range(1, 15) if clay[r - 1] == 1] == clay_rounds
    assert [r for r in range(1, 15) if boar[r - 1] == 1] == boar_rounds
    # No round-space gets BOTH goods; every remaining round-space gets exactly one.
    assert all(not (clay[r - 1] and boar[r - 1]) for r in range(1, 15))
    assert sum(clay) + sum(boar) == 13   # all 13 remaining spaces loaded
    # Opponent untouched.
    assert sum(_clay(out, 1)) == 0 and sum(_boar(out, 1)) == 0


def test_cesspit_starts_with_clay_relative_to_play_round():
    # First remaining space (R+1) always gets CLAY regardless of R's parity.
    for R in (1, 2, 6, 7):
        s = fast_replace(setup(0), round_number=R)
        out = MINORS["cesspit"].on_play(s, 0)
        clay = _clay(out, 0)
        boar = _boar(out, 0)
        assert clay[R] == 1, f"R={R}: first remaining space (R+1) should be clay"
        assert boar[R] == 0
        if R + 1 < 14:  # the next remaining space (R+2) is boar
            assert boar[R + 1] == 1 and clay[R + 1] == 0


def test_cesspit_late_play_clamps_to_game_end():
    # Round 13: one remaining space (round 14) -> clay only (the "starting with clay" one).
    s = fast_replace(setup(0), round_number=13)
    out = MINORS["cesspit"].on_play(s, 0)
    clay = _clay(out, 0)
    boar = _boar(out, 0)
    assert clay[13] == 1 and sum(clay) == 1   # round 14 clay
    assert sum(boar) == 0                       # no remaining boar space


def test_cesspit_no_spaces_at_round_14():
    # Round 14 (last round): no remaining round spaces, nothing scheduled.
    s = fast_replace(setup(0), round_number=14)
    out = MINORS["cesspit"].on_play(s, 0)
    assert sum(_clay(out, 0)) == 0 and sum(_boar(out, 0)) == 0


def test_cesspit_schedule_is_additive():
    # on_play adds onto whatever is already promised (the helpers are additive).
    s = setup(0)
    p = s.players[0]
    fr_res = list(p.future_resources)
    fr_res[1] = fr_res[1] + Resources(clay=2)   # round 2 already has 2 clay promised
    s = fast_replace(s, players=(fast_replace(p, future_resources=tuple(fr_res)),
                                 s.players[1]))
    out = MINORS["cesspit"].on_play(s, 0)
    # Round 2 is the 1st remaining space -> +1 clay from Cesspit, on top of the 2.
    assert _clay(out, 0)[1] == 3


# ---------------------------------------------------------------------------
# End-to-end collection at round start
# ---------------------------------------------------------------------------

def test_cesspit_clay_collected_at_round_start():
    # Round 2 is a clay round; entering it grants the clay.
    s = MINORS["cesspit"].on_play(setup(0), 0)   # R=1
    clay_before = s.players[0].resources.clay
    s = fast_replace(s, round_number=1, phase=Phase.PREPARATION)  # entering round 2
    out = _complete_preparation(s)
    assert out.round_number == 2
    assert out.players[0].resources.clay == clay_before + 1
    assert out.players[0].future_resources[1].clay == 0   # slot cleared


def test_cesspit_boar_collected_and_accommodated_at_round_start():
    # Round 3 is a boar round; the boar is collected + auto-accommodated (house pet).
    # `_collect_future_rewards` takes the 0-indexed slot (round r -> slot r-1).
    s = MINORS["cesspit"].on_play(setup(0), 0)   # R=1 -> round 3 boar lives in slot 2
    boar0 = s.players[0].animals.boar
    out = _collect_future_rewards(s, 2)   # slot 2 == round 3
    assert out.players[0].animals.boar == boar0 + 1
    assert out.players[0].future_rewards[2].animals == Animals()   # slot cleared


# ---------------------------------------------------------------------------
# Real play flow — play the minor through a live engine decision point
# ---------------------------------------------------------------------------

def test_cesspit_played_via_engine_schedules_goods():
    cs, _env = setup_env(0, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    # Satisfy the prereq: 2 fields + 1 occupation. (No cost to pay.)
    cs = with_fields(_with_occupations(cs, cp, 1), cp, [(0, 0), (0, 1)])
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"cesspit"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    R = cs.round_number

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "cesspit"))

    assert "cesspit" in cs.players[cp].minor_improvements
    clay = _clay(cs, cp)
    boar = _boar(cs, cp)
    # First remaining space (R+1) is clay, next (R+2) is boar.
    assert clay[R] == 1 and boar[R] == 0          # round R+1 -> slot R
    if R + 1 < 14:
        assert boar[R + 1] == 1 and clay[R + 1] == 0  # round R+2 -> slot R+1
    # Every remaining round space got exactly one good.
    assert sum(clay) + sum(boar) == (14 - R)
