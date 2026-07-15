"""Tests for Master Huntsman (occupation, E165; Ephipparius Expansion).

Card text: "When you play this card and each time you build a major improvement,
you get 1 wild boar."

On-play grants 1 boar; a `before_build_major` automatic effect grants 1 boar per
major-improvement build. Both via grant_animals. A real Major Improvement build
drives the end-to-end path (tests/test_major_improvement.py idiom).
"""
from __future__ import annotations

import agricola.cards.master_huntsman  # noqa: F401  (registers the card)

import pytest

import agricola.cards.master_huntsman as mod
from agricola.actions import ChooseSubAction, PlaceWorker, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, apply_auto_effects
from agricola.replace import fast_replace
from agricola.setup import setup
from tests.factories import with_current_player, with_resources, with_space
from tests.test_utils import build_major, run_actions

CARD_ID = "master_huntsman"


def _own_occ(state, idx):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {CARD_ID}) if i == idx
        else state.players[i] for i in range(2)))


# --- Registration -----------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("before_build_major", [])}


# --- On play: +1 boar -------------------------------------------------------

def test_on_play_grants_one_boar():
    state = setup(0)
    b0 = state.players[0].animals.boar
    after = OCCUPATIONS[CARD_ID].on_play(state, 0)
    assert after.players[0].animals.boar == b0 + 1
    assert after.players[0].animals_need_accommodation   # routed via grant_animals


# --- before_build_major auto (direct) ---------------------------------------

def test_before_build_major_auto_grants_boar():
    state = _own_occ(setup(0), 0)
    b0 = state.players[0].animals.boar
    out = apply_auto_effects(state, "before_build_major", 0)
    assert out.players[0].animals.boar == b0 + 1


def test_unowned_build_major_grants_nothing():
    state = setup(0)   # nobody owns Master Huntsman
    b0 = state.players[0].animals.boar
    out = apply_auto_effects(state, "before_build_major", 0)
    assert out.players[0].animals.boar == b0


# --- A real Major Improvement build -----------------------------------------

def test_real_major_build_grants_boar():
    """Build Fireplace (idx 0, cost 2 clay): the `before_build_major` auto fires
    at ChooseSubAction('build_major') and grants 1 boar (fits the default pet
    slot, so the build proceeds normally)."""
    state = _own_occ(with_current_player(setup(0), 0), 0)
    state = with_resources(state, 0, clay=2)
    state = with_space(state, "major_improvement", revealed=True)
    b0 = state.players[0].animals.boar
    state = run_actions(state, [
        PlaceWorker(space="major_improvement"),
        ChooseSubAction(name="improvement"),
        ChooseSubAction(name="build_major"),
        build_major(0),
        Stop(),   # pop PendingBuildMajor's after-phase
        Stop(),   # pop PendingMajorMinorImprovement's after-phase
        Stop(),   # pop PendingSubActionSpace
    ])
    assert state.board.major_improvement_owners[0] == 0   # Fireplace built
    assert state.players[0].animals.boar == b0 + 1        # +1 boar for the build


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
