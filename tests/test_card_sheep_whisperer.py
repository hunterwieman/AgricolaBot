"""Tests for Sheep Whisperer (occupation, B164; Base Revised).

Card text: "Add 2, 5, 8, and 10 to the current round and place 1 sheep on each
corresponding round space. At the start of these rounds, you get the sheep."

Category 8 (deferred animals): at play, schedule 1 sheep onto rounds R+2, R+5,
R+8, R+10 of `future_rewards`, collected + accommodated at each round's start.
Mirrors tests/test_card_acorns_basket.py.
"""
from __future__ import annotations

import agricola.cards.sheep_whisperer  # noqa: F401  (registers the card)

import pytest

from agricola.cards.specs import OCCUPATIONS
from agricola.engine import _collect_future_rewards
from agricola.replace import fast_replace
from agricola.resources import Animals
from agricola.setup import setup

CARD_ID = "sheep_whisperer"


# --- Registration -----------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS


# --- On play: schedule sheep onto R+2/5/8/10 --------------------------------

def test_schedules_sheep_at_offsets():
    s = setup(0)                       # round 1
    R = s.round_number
    out = OCCUPATIONS[CARD_ID].on_play(s, 0)
    # Rounds R+2, R+5, R+8, R+10 -> future_rewards slots R+1, R+4, R+7, R+9.
    for d in (2, 5, 8, 10):
        assert out.players[0].future_rewards[R + d - 1].animals == Animals(sheep=1)
    # Exactly 4 sheep scheduled, nothing on the opponent.
    assert sum(fr.animals.sheep for fr in out.players[0].future_rewards) == 4
    assert all(not fr for fr in out.players[1].future_rewards)


def test_late_play_clamps_past_game_end():
    # Played in round 6: R+8=14 (kept), R+10=16 (past the game -> dropped); R+2=8,
    # R+5=11 kept. So 3 of the 4 land.
    s = fast_replace(setup(0), round_number=6)
    out = OCCUPATIONS[CARD_ID].on_play(s, 0)
    assert sum(fr.animals.sheep for fr in out.players[0].future_rewards) == 3


def test_all_dropped_when_played_too_late():
    s = fast_replace(setup(0), round_number=13)   # R+2=15.. all past 14
    out = OCCUPATIONS[CARD_ID].on_play(s, 0)
    assert all(not fr for fr in out.players[0].future_rewards)


# --- Collection at round start ----------------------------------------------

def test_sheep_collected_at_scheduled_round():
    s = setup(0)                       # round 1
    R = s.round_number
    s = OCCUPATIONS[CARD_ID].on_play(s, 0)    # first sheep on round R+2 (slot R+1)
    sheep0 = s.players[0].animals.sheep
    # _collect_future_rewards(state, slot): the round-R+2 sheep rides slot R+1.
    out = _collect_future_rewards(s, R + 1)
    assert out.players[0].animals.sheep == sheep0 + 1
    assert out.players[0].future_rewards[R + 1].animals == Animals()


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
