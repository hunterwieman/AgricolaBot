"""Acorns Basket (B84) — schedules 1 wild boar onto each of the next 2 round spaces;
the boar are collected + auto-accommodated at the start of those rounds via
engine._collect_future_rewards. See agricola/cards/acorns_basket.py.
"""
import agricola.cards.acorns_basket  # noqa: F401  (registers the MinorSpec)

from agricola.cards.specs import MINORS, prereq_met
from agricola.engine import _collect_future_rewards, _complete_preparation
from agricola.constants import Phase
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.setup import setup


def _with_occupations(state, idx, n):
    p = fast_replace(state.players[idx],
                     occupations=frozenset(f"o{i}" for i in range(n)))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def test_acorns_basket_registered():
    spec = MINORS["acorns_basket"]
    assert spec.cost == Cost(resources=Resources(reed=1))
    assert spec.min_occupations == 3
    assert spec.passing_left is False
    assert spec.vps == 0


def test_acorns_basket_prereq_needs_3_occupations():
    s = setup(0)
    assert not prereq_met(MINORS["acorns_basket"], _with_occupations(s, 0, 2), 0)
    assert prereq_met(MINORS["acorns_basket"], _with_occupations(s, 0, 3), 0)


def test_acorns_basket_schedules_boar_next_2_rounds():
    s = setup(0)                              # round 1
    R = s.round_number
    s2 = MINORS["acorns_basket"].on_play(s, 0)
    # 1 boar onto rounds R+1, R+2 → future_rewards slots R, R+1.
    assert s2.players[0].future_rewards[R].animals == Animals(boar=1)        # round R+1
    assert s2.players[0].future_rewards[R + 1].animals == Animals(boar=1)    # round R+2
    # No animals leak onto any other slot, and the opponent is untouched.
    assert sum(fr.animals.boar for fr in s2.players[0].future_rewards) == 2
    assert all(not fr for fr in s2.players[1].future_rewards)


def test_acorns_basket_late_play_clamps_to_game_end():
    # Played in round 14 → both target rounds (15, 16) are past the game → dropped.
    s = setup(0)
    s = fast_replace(s, round_number=14)
    s2 = MINORS["acorns_basket"].on_play(s, 0)
    assert all(not fr for fr in s2.players[0].future_rewards)


def test_acorns_basket_boar_collected_and_accommodated_at_round_start():
    s = setup(0)                              # round 1
    R = s.round_number
    s = MINORS["acorns_basket"].on_play(s, 0)
    boar0 = s.players[0].animals.boar
    # Collect the slot for round R+1 (slot index R): 1 boar fits the house pet on a
    # default farm, so it is kept and the slot is cleared.
    out = _collect_future_rewards(s, R)
    assert out.players[0].animals.boar == boar0 + 1
    assert out.players[0].future_rewards[R].animals == Animals()


def test_acorns_basket_collected_via_full_preparation():
    # Drive the real round-boundary path (_complete_preparation), not just the
    # collector, to confirm the boar lands when the scheduled round is entered.
    s = setup(0)
    s = MINORS["acorns_basket"].on_play(s, 0)   # schedules rounds 2, 3
    boar0 = s.players[0].animals.boar
    s = fast_replace(s, round_number=1, phase=Phase.PREPARATION)  # entering round 2
    out = _complete_preparation(s)
    assert out.players[0].animals.boar == boar0 + 1
