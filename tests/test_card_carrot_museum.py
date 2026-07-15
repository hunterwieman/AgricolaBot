"""Tests for Carrot Museum (minor improvement, D79; Consul Dirigens Expansion).

Card text (verbatim): "At the end of rounds 8, 10, and 12, you get 1 stone for
each vegetable field you have and a number of wood equal to the number of
vegetables in your supply."

Cost 1 Wood + 2 Clay, prereq "Play in Round 8 or Before", 2 VPs. A mandatory
AUTO on the round-end ladder's ``end_of_round`` rung, latched to rounds
{8, 10, 12}: +1 stone per vegetable field (a grid FIELD holding veg), +1 wood
per vegetable in supply. Tests drive the real round-end walk (the Credit idiom).
"""
from __future__ import annotations

import agricola.cards.carrot_museum  # noqa: F401  (registers the card)

import pytest

from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup

from tests.factories import with_resources, with_sown_fields

CARD_ID = "carrot_museum"


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    return _edit_player(state, idx, minor_improvements=p.minor_improvements | {card_id})


def _drained_work_state(round_number=8):
    state = setup(seed=0)
    state = fast_replace(
        state, phase=Phase.WORK, round_number=round_number, starting_player=0)
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    return state


def _cm_state(*, round_number=8, owned=True, veg_fields=((0, 2), (0, 3)), veg_supply=3):
    state = _drained_work_state(round_number=round_number)
    if owned:
        state = _own_minor(state, 0, CARD_ID)
    if veg_fields:
        state = with_sown_fields(state, 0, veg_fields=veg_fields)
    state = with_resources(state, 0, veg=veg_supply)
    return state


# --- Registration -----------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1, clay=2))
    assert spec.vps == 2
    entries = [e for e in AUTO_EFFECTS.get("end_of_round", ()) if e.card_id == CARD_ID]
    assert len(entries) == 1
    assert entries[0].any_player is False


def test_prereq_play_in_round_8_or_before():
    assert prereq_met(MINORS[CARD_ID], fast_replace(setup(0), round_number=8), 0)
    assert not prereq_met(MINORS[CARD_ID], fast_replace(setup(0), round_number=9), 0)


# --- The grant on rounds 8 / 10 / 12 ----------------------------------------

def test_grants_stone_per_veg_field_and_wood_per_veg_supply_round_8():
    # The grant fires at round 8's end_of_round (during the ladder), so it has
    # applied by the time the walk halts (where it halts is env-dependent —
    # the round-9 reveal is a nature step — so we assert the grant, not phase).
    state = _cm_state(round_number=8, veg_fields=((0, 2), (0, 3)), veg_supply=3)
    out = _advance_until_decision(state)
    # 2 vegetable fields -> 2 stone; 3 veg in supply -> 3 wood.
    assert out.players[0].resources.stone == 2
    assert out.players[0].resources.wood == 3
    assert out.players[0].resources.veg == 3         # supply veg is COUNTED, not spent


@pytest.mark.parametrize("rnd", [10, 12])
def test_grants_on_rounds_10_and_12(rnd):
    state = _cm_state(round_number=rnd, veg_fields=((1, 2),), veg_supply=1)
    out = _advance_until_decision(state)
    assert out.players[0].resources.stone == 1       # 1 veg field
    assert out.players[0].resources.wood == 1        # 1 veg in supply


def test_not_fired_on_a_non_listed_round():
    """Round 5 is not in {8, 10, 12}: no grant."""
    state = _cm_state(round_number=5, veg_fields=((0, 2), (0, 3)), veg_supply=3)
    out = _advance_until_decision(state)
    assert out.players[0].resources.stone == 0
    assert out.players[0].resources.wood == 0


def test_zero_veg_fields_and_empty_supply_grants_nothing():
    state = _cm_state(round_number=8, veg_fields=(), veg_supply=0)
    out = _advance_until_decision(state)
    assert out.players[0].resources.stone == 0
    assert out.players[0].resources.wood == 0


def test_unowned_no_grant():
    state = _cm_state(round_number=8, owned=False, veg_fields=((0, 2),), veg_supply=2)
    out = _advance_until_decision(state)
    assert out.players[0].resources.stone == 0
    assert out.players[0].resources.wood == 0


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
