"""Tests for Trap Builder (occupation, D147; Dulcinaria Expansion).

Card text: "Each time you use the "Day Laborer" action space, place 1 food, 1
food, and 1 wild boar on the next 3 round spaces, respectively. At the start of
these rounds, you get the good."

A `before_action_space` automatic effect on the atomic Day Laborer space (hosted
via `register_action_space_hook`). It schedules 1 food onto R+1 and R+2
(future_resources) and 1 wild boar onto R+3 (future_rewards). Mirrors
tests/test_card_bee_statue.py's Day Laborer flow.
"""
from __future__ import annotations

import agricola.cards.trap_builder  # noqa: F401  (registers the card)

import pytest

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import (
    AUTO_EFFECTS,
    OWN_ACTION_HOOK_CARDS,
    apply_auto_effects,
)
from agricola.engine import step
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.setup import setup
from tests.factories import with_current_player, with_pending_stack

CARD_ID = "trap_builder"


def _own(state, idx):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {CARD_ID}) if i == idx
        else state.players[i] for i in range(2)))


# --- Registration -----------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("before_action_space", [])}
    assert CARD_ID in OWN_ACTION_HOOK_CARDS.get("day_laborer", set())


# --- Real Day Laborer placement schedules the goods -------------------------

def test_real_placement_schedules_food_food_boar():
    state = _own(with_current_player(setup(0), 0), 0)   # round 1
    R = state.round_number
    state = step(state, PlaceWorker(space="day_laborer"))
    p = state.players[0]
    # 1 food on R+1, R+2 (future_resources slots R, R+1); 1 boar on R+3 (slot R+2).
    assert p.future_resources[R].food == 1
    assert p.future_resources[R + 1].food == 1
    assert p.future_rewards[R + 2].animals == Animals(boar=1)
    # Nothing scheduled beyond those three slots.
    assert sum(fr.food for fr in p.future_resources) == 2
    assert sum(fr.animals.boar for fr in p.future_rewards) == 1
    # Finish the Day Laborer action (its 2 food).
    state = step(state, Proceed())
    state = step(state, Stop())
    assert state.pending_stack == ()


# --- Boundaries: wrong space, non-owner -------------------------------------

def test_not_fired_on_a_different_space():
    state = _own(with_current_player(setup(0), 0), 0)
    state = with_pending_stack(
        state, (PendingActionSpace(player_idx=0, initiated_by_id="space:forest"),))
    out = apply_auto_effects(state, "before_action_space", 0)
    assert all(not fr for fr in out.players[0].future_resources)
    assert all(not fr for fr in out.players[0].future_rewards)


def test_unowned_noop():
    state = with_pending_stack(
        with_current_player(setup(0), 0),
        (PendingActionSpace(player_idx=0, initiated_by_id="space:day_laborer"),))
    out = apply_auto_effects(state, "before_action_space", 0)
    assert out is state   # not owned -> unchanged


def test_own_only_not_opponent():
    """"You use" -> only the owner's Day Laborer use schedules; the opponent's does
    not."""
    state = _own(with_current_player(setup(0), 0), 0)   # player 0 owns
    state = with_pending_stack(
        state, (PendingActionSpace(player_idx=1, initiated_by_id="space:day_laborer"),))
    out = apply_auto_effects(state, "before_action_space", 1)   # opponent acts
    assert all(not fr for fr in out.players[0].future_resources)
    assert all(not fr for fr in out.players[0].future_rewards)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
