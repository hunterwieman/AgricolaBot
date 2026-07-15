"""Tests for Ale-Benches (minor improvement, A29; Artifex Expansion).

Card text (verbatim): "In the returning home phase of each round, you can pay
exactly 1 grain from your supply to get 1 bonus point. If you do, each other
player gets 1 food."

Cost 1 Wood, prereq "2 Occupations", no printed VPs. An optional trigger on the
round-end ladder's ``returning_home`` window (ruling 49): pay 1 supply grain →
bank 1 bonus point in the per-card CardStore (scored at end-game) → each other
player gets 1 food. Offered on ALL rounds (no harvest condition).

The tests drive the REAL round-end walk (``_advance_until_decision`` on a
drained WORK state — the test_round_end_ladder.py idiom).
"""
from __future__ import annotations

import agricola.cards.ale_benches  # noqa: F401  (registers the card)

import dataclasses

import pytest

from agricola.actions import FireTrigger, Proceed
from agricola.cards.ale_benches import _score
from agricola.cards.specs import MINORS
from agricola.cards.triggers import CARDS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import SCORING_TERMS
from agricola.setup import setup

CARD_ID = "ale_benches"


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    return _edit_player(state, idx, minor_improvements=p.minor_improvements | {card_id})


def _drained_work_state(round_number=1):
    state = setup(seed=0)
    state = fast_replace(
        state, phase=Phase.WORK, round_number=round_number, starting_player=0)
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    return state


def _ab_state(*, round_number=1, owned=True, grain=1):
    state = _drained_work_state(round_number=round_number)
    if owned:
        state = _own_minor(state, 0, CARD_ID)
    state = _edit_player(state, 0, resources=Resources(grain=grain))
    return state


def _walk_to_window(state):
    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow), (
        f"no returning_home window (top={top!r}, phase={state.phase})")
    assert top.window_id == "returning_home" and top.player_idx == 0
    return state


# --- Registration -----------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.min_occupations == 2
    assert spec.vps == 0
    entry = CARDS[CARD_ID]
    assert entry.event == "returning_home"
    assert entry.mandatory is False
    assert any(cid == CARD_ID for cid, _fn in SCORING_TERMS)


# --- The fire: bank a point, opponent gets food -----------------------------

def test_fire_banks_point_debits_grain_and_feeds_opponent():
    state = _ab_state(round_number=1, grain=1)
    opp_food = state.players[1].resources.food
    state = _walk_to_window(state)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)
    assert Proceed() in legal_actions(state)

    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.players[0].resources.grain == 0          # paid the 1 grain
    assert state.players[1].resources.food == opp_food + 1  # opponent +1 food
    assert _score(state, 0) == 1                          # banked 1 bonus point
    # Once per window: only Proceed remains.
    assert legal_actions(state) == [Proceed()]

    # The rest of the ladder runs to preparation (round 1: no harvest).
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION
    assert _score(state, 0) == 1


def test_offered_on_a_harvest_round_too():
    """No "after which there is no harvest" clause — the returning home phase
    happens every round (it precedes the harvest), so round 4 offers it."""
    state = _ab_state(round_number=4, grain=1)
    state = _walk_to_window(state)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)


# --- Eligibility + optionality ----------------------------------------------

def test_not_offered_without_supply_grain():
    state = _ab_state(round_number=1, grain=0)
    out = _advance_until_decision(state)
    assert out.phase == Phase.PREPARATION            # never paused at the window
    assert out.players[1].resources.food == state.players[1].resources.food
    assert _score(out, 0) == 0


def test_declinable_via_proceed_changes_nothing():
    state = _ab_state(round_number=1, grain=1)
    opp_food = state.players[1].resources.food
    state = _walk_to_window(state)
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.players[0].resources.grain == 1     # grain kept
    assert state.players[1].resources.food == opp_food
    assert _score(state, 0) == 0                      # nothing banked


def test_unowned_never_hosts():
    state = _ab_state(round_number=1, owned=False, grain=1)
    out = _advance_until_decision(state)
    assert out.phase == Phase.PREPARATION
    assert out.players[0].resources.grain == 1


# --- Scoring accumulates -----------------------------------------------------

def test_score_reads_the_banked_counter():
    """The scoring term is the CardStore counter — one point per round paid."""
    state = setup(seed=0)
    state = _edit_player(state, 0, card_state=state.players[0].card_state.set(CARD_ID, 3))
    assert _score(state, 0) == 3
    assert _score(state, 1) == 0                      # a non-bearer scores 0


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
