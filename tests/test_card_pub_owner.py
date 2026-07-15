"""Tests for Pub Owner (occupation, B160; Bubulcus Expansion).

Card text: "Immediately, when you play this card, and at the end of each work
phase, in which the "Forest", "Clay Pit", and "Reed Bank" accumulation spaces are
all occupied, you get 1 grain."

On-play grants +1 grain unconditionally (the occupancy condition binds only to the
end-of-work timing). An `end_of_work` auto grants +1 grain when Forest, Clay Pit,
and Reed Bank are all occupied. The round-end tests drive the real walk
(`_advance_until_decision` on a drained WORK state) with the three spaces' worker
tuples set.
"""
from __future__ import annotations

import agricola.cards.pub_owner  # noqa: F401  (registers the card)

import pytest

import agricola.cards.pub_owner as mod
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision
from agricola.replace import fast_replace
from agricola.setup import setup

from tests.factories import with_space

CARD_ID = "pub_owner"
_SPACES = ("forest", "clay_pit", "reed_bank")


def _own_occ(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _occupy(state, *spaces):
    for s in spaces:
        state = with_space(state, s, workers=(1, 0))
    return state


def _drained_work_state(round_number=1):
    state = fast_replace(setup(0), phase=Phase.WORK, round_number=round_number)
    for idx in (0, 1):
        state = fast_replace(state, players=tuple(
            fast_replace(state.players[i], people_home=0) if i == idx
            else state.players[i] for i in range(2)))
    return state


# --- Registration -----------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("end_of_work", [])}


# --- On play: +1 grain unconditionally --------------------------------------

def test_on_play_grants_one_grain():
    state = setup(0)   # no spaces occupied — on-play grant is unconditional
    g0 = state.players[0].resources.grain
    after = OCCUPATIONS[CARD_ID].on_play(state, 0)
    assert after.players[0].resources.grain == g0 + 1
    assert after.players[1].resources == state.players[1].resources


# --- The end-of-work occupancy condition (direct) ---------------------------

def test_eligible_all_three_occupied():
    assert mod._eligible(_occupy(setup(0), *_SPACES), 0) is True


def test_not_eligible_when_one_space_empty():
    assert mod._eligible(_occupy(setup(0), "forest", "clay_pit"), 0) is False
    assert mod._eligible(_occupy(setup(0), "forest", "reed_bank"), 0) is False
    assert mod._eligible(setup(0), 0) is False   # none occupied


# --- End of work through the real round-end walk ----------------------------

def test_grain_at_end_of_work_when_all_occupied():
    state = _occupy(_own_occ(_drained_work_state(), 0), *_SPACES)
    g0 = state.players[0].resources.grain
    out = _advance_until_decision(state)
    assert out.phase == Phase.PREPARATION
    assert out.players[0].resources.grain == g0 + 1


def test_no_grain_when_not_all_occupied():
    state = _occupy(_own_occ(_drained_work_state(), 0), "forest", "clay_pit")
    g0 = state.players[0].resources.grain
    out = _advance_until_decision(state)
    assert out.players[0].resources.grain == g0   # reed_bank empty -> no grain


def test_unowned_no_grain():
    state = _occupy(_drained_work_state(), *_SPACES)   # nobody owns Pub Owner
    g0 = state.players[0].resources.grain
    out = _advance_until_decision(state)
    assert out.players[0].resources.grain == g0


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
