"""Tests for Food Distributor (occupation, C155; Corbarius Expansion).

Card text: "When you play this card, you immediately get 1 grain and, at the start
of this returning home phase, an amount of food equal to the number of occupied
action space cards."
Clarification: "Action space cards = Round 1-14 action spaces."

Two halves: an on-play +1 grain that also stamps the play round into the
CardStore, and a ONE-SHOT automatic effect on the round-end ladder's
start_of_returning_home window that (only in the round the card was played) grants
food equal to the number of occupied Round-1–14 STAGE spaces (permanent spaces
excluded, per the clarification). The one-shot fires only when the stored
play-round equals the current round number, and clears the stamp when it fires.
"""
from __future__ import annotations

import agricola.cards.food_distributor  # noqa: F401  (registers the card)

from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision
from agricola.replace import fast_replace
from agricola.setup import setup
from tests.factories import with_space

CARD_ID = "food_distributor"


def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_occ(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {CARD_ID})


def _drained_work_state(*, occupied=(), stored_round=None, round_number=1,
                        owned=True, seed=0):
    """A WORK state with every person placed (people_home=0); the named spaces hold
    a worker; P0 (optionally) owns the card with `stored_round` stamped in its
    CardStore (simulating a play in that round)."""
    state = setup(seed)
    state = fast_replace(state, phase=Phase.WORK, round_number=round_number)
    for sid in occupied:
        state = with_space(state, sid, workers=(1, 0))
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    if owned:
        state = _own_occ(state, 0)
    if stored_round is not None:
        p = state.players[0]
        state = _edit_player(state, 0, card_state=p.card_state.set(CARD_ID, stored_round))
    return state


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    assert any(e.card_id == CARD_ID
               for e in AUTO_EFFECTS.get("start_of_returning_home", ()))


# --- Half 1: on-play grain + play-round stamp -------------------------------

def test_on_play_grants_grain_and_stamps_round():
    s = setup(0)                                   # a round-1 WORK state
    before = s.players[0].resources.grain
    after = OCCUPATIONS[CARD_ID].on_play(s, 0)
    assert after.players[0].resources.grain == before + 1
    assert after.players[0].card_state.get(CARD_ID) == s.round_number


# --- Half 2: the one-shot returning-home food -------------------------------

def test_food_equals_occupied_stage_spaces_in_the_played_round():
    # Two STAGE spaces occupied → +2 food, in the round the card was played (1).
    state = _drained_work_state(
        occupied=("grain_utilization", "sheep_market"),
        stored_round=1, round_number=1)
    before = state.players[0].resources.food
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION            # round 1: no harvest
    assert state.players[0].resources.food == before + 2
    # The stamp is cleared so it can never fire again.
    assert state.players[0].card_state.get(CARD_ID) is None


def test_permanent_spaces_do_not_count():
    # Only Round-1–14 stage spaces count (the clarification): a worker on Forest
    # (permanent) and Grain Seeds (permanent) contributes nothing; one stage
    # space (Fencing) contributes 1.
    state = _drained_work_state(
        occupied=("forest", "grain_seeds", "fencing"),
        stored_round=1, round_number=1)
    before = state.players[0].resources.food
    state = _advance_until_decision(state)
    assert state.players[0].resources.food == before + 1


def test_no_food_when_no_stage_spaces_occupied():
    state = _drained_work_state(occupied=("forest",), stored_round=1, round_number=1)
    before = state.players[0].resources.food
    state = _advance_until_decision(state)
    assert state.players[0].resources.food == before


def test_one_shot_does_not_fire_in_a_later_round():
    # Played in round 1 (stamp = 1) but now round 2: the returning-home food is a
    # one-shot for the played round only, so nothing fires.
    state = _drained_work_state(
        occupied=("grain_utilization", "sheep_market"),
        stored_round=1, round_number=2)
    before = state.players[0].resources.food
    state = _advance_until_decision(state)
    assert state.players[0].resources.food == before


def test_no_fire_when_never_played():
    # Owned but never played (no stamp) → the auto is ineligible.
    state = _drained_work_state(
        occupied=("grain_utilization", "sheep_market"),
        stored_round=None, round_number=1)
    before = state.players[0].resources.food
    state = _advance_until_decision(state)
    assert state.players[0].resources.food == before


def test_unowned_does_not_fire():
    state = _drained_work_state(
        occupied=("grain_utilization", "sheep_market"),
        stored_round=None, round_number=1, owned=False)
    before = state.players[0].resources.food
    state = _advance_until_decision(state)
    assert state.players[0].resources.food == before
