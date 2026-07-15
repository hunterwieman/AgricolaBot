"""Tests for Pig Breeder (occupation, A165; Base Revised).

Card text: "When you play this card, you immediately get 1 wild boar. Your wild
boar breed at the end of round 12 (if there is room for the new wild boar)."

On-play grants 1 boar (via grant_animals). At the end of round 12 an `end_of_round`
auto breeds a boar (>= 2 boar AND room for the newborn). The round-end tests drive
the real walk (`_advance_until_decision` on a drained WORK state — the
test_round_end_ladder.py idiom).
"""
from __future__ import annotations

import agricola.cards.pig_breeder  # noqa: F401  (registers the card)

import pytest

import agricola.cards.pig_breeder as mod
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision
from agricola.replace import fast_replace
from agricola.state import Cell
from agricola.setup import setup

from tests.factories import with_animals, with_grid, with_round

CARD_ID = "pig_breeder"


def _own_occ(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _stables(state, idx, cells):
    """Give player `idx` standalone stables (flexible slots) at `cells`."""
    return with_grid(state, idx, {(r, c): Cell(cell_type=CellType.STABLE) for r, c in cells})


def _drained_work_state(round_number):
    state = fast_replace(setup(0), phase=Phase.WORK, round_number=round_number)
    for idx in (0, 1):
        state = fast_replace(state, players=tuple(
            fast_replace(state.players[i], people_home=0) if i == idx
            else state.players[i] for i in range(2)))
    return state


# --- Registration -----------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("end_of_round", [])}


# --- On play: +1 boar -------------------------------------------------------

def test_on_play_grants_one_boar():
    state = setup(0)
    b0 = state.players[0].animals.boar
    after = OCCUPATIONS[CARD_ID].on_play(state, 0)
    assert after.players[0].animals.boar == b0 + 1
    assert after.players[0].animals_need_accommodation  # routed via grant_animals
    assert after.players[1].animals == state.players[1].animals


# --- The round-12 breed eligibility (direct) --------------------------------

def test_eligible_only_round_12():
    s = with_animals(_stables(setup(0), 0, [(0, 0), (0, 1)]), 0, boar=2)
    assert mod._eligible(with_round(s, 12), 0) is True
    assert mod._eligible(with_round(s, 11), 0) is False
    assert mod._eligible(with_round(s, 13), 0) is False


def test_eligible_needs_two_boar():
    s = _stables(setup(0), 0, [(0, 0), (0, 1)])
    assert mod._eligible(with_round(with_animals(s, 0, boar=1), 12), 0) is False
    assert mod._eligible(with_round(with_animals(s, 0, boar=2), 12), 0) is True


def test_eligible_needs_room_for_new_boar():
    """"if there is room for the new wild boar": with 2 boar and NO extra housing
    a 3rd boar cannot be accommodated on a default farm -> no breed."""
    s = with_round(with_animals(setup(0), 0, boar=2), 12)   # default farm: 1 pet slot
    assert mod._eligible(s, 0) is False
    # Two standalone stables give 3 flexible slots -> the 3rd boar fits.
    assert mod._eligible(_stables(s, 0, [(0, 0), (0, 1)]), 0) is True


# --- The round-12 breed through the real round-end walk ---------------------

def test_breeds_at_round_12_end_when_room():
    state = _own_occ(_drained_work_state(12), 0)
    state = with_animals(state, 0, boar=2)
    state = _stables(state, 0, [(0, 0), (0, 1)])   # room for 3 boar
    out = _advance_until_decision(state)
    assert out.players[0].animals.boar == 3         # 2 + 1 newborn at end of round 12


def test_no_breed_when_no_room():
    state = _own_occ(_drained_work_state(12), 0)
    state = with_animals(state, 0, boar=2)          # default farm: no room for a 3rd
    out = _advance_until_decision(state)
    assert out.players[0].animals.boar == 2


def test_no_breed_on_other_rounds():
    state = _own_occ(_drained_work_state(11), 0)
    state = with_animals(state, 0, boar=2)
    state = _stables(state, 0, [(0, 0), (0, 1)])
    out = _advance_until_decision(state)
    assert out.players[0].animals.boar == 2         # round 11 != 12


def test_unowned_no_breed():
    state = _drained_work_state(12)                 # nobody owns Pig Breeder
    state = with_animals(state, 0, boar=2)
    state = _stables(state, 0, [(0, 0), (0, 1)])
    out = _advance_until_decision(state)
    assert out.players[0].animals.boar == 2


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
