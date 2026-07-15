"""Tests for Ropemaker (occupation, A145; Artifex Expansion).

Card text: "At the end of each harvest, you get 1 reed from the general supply."

An `end_of_harvest` harvest-window AUTO (mandatory, choice-free +1 reed). The
harvest tests drive the real walk (`_advance_until_decision` + `step`, the
tests/test_card_bale_of_straw.py idiom) and isolate the +1 reed against a no-card
baseline.
"""
from __future__ import annotations

import agricola.cards.ropemaker  # noqa: F401  (registers the card)

import pytest

import agricola.cards.ropemaker as mod
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.setup import setup

from tests.factories import with_phase

CARD_ID = "ropemaker"


def _own_occ(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _harvest_state(seed=0, food=10):
    """A HARVEST_FIELD-phase state with enough food that feeding is painless."""
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        state = fast_replace(state, players=tuple(
            fast_replace(state.players[i],
                         resources=fast_replace(state.players[i].resources, food=food))
            if i == idx else state.players[i] for i in range(2)))
    return state


def _run_harvest(state, pick=lambda acts: acts[0]):
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED):
        state = step(state, pick(legal_actions(state)))
    return state


# --- Registration -----------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("end_of_harvest", set())
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("end_of_harvest", [])}


# --- The +1 reed at the end of the harvest ----------------------------------

def test_one_reed_per_harvest():
    base = _harvest_state()
    baseline = _run_harvest(base)
    owned = _run_harvest(_own_occ(base, 0, CARD_ID))
    assert owned.players[0].resources.reed == baseline.players[0].resources.reed + 1


def test_fires_only_for_owner():
    base = _harvest_state()
    baseline = _run_harvest(base)
    owned = _run_harvest(_own_occ(base, 0, CARD_ID))   # P0 owns, P1 does not
    assert owned.players[0].resources.reed == baseline.players[0].resources.reed + 1
    assert owned.players[1].resources.reed == baseline.players[1].resources.reed


def test_apply_adds_one_reed():
    state = setup(0)
    r0 = state.players[0].resources.reed
    after = mod._apply(state, 0)
    assert after.players[0].resources.reed == r0 + 1
    assert after.players[1].resources == state.players[1].resources


def test_family_no_reed_without_card():
    final = _run_harvest(_harvest_state(seed=3))
    assert final.phase == Phase.PREPARATION
    assert all(type(f).__name__ != "PendingHarvestWindow" for f in final.pending_stack)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
