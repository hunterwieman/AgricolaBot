"""Tests for Night-School Student (occupation, A152; Artifex Expansion).

Card text: "Each returning home phase in which no player returns a person from a
'Lessons' action space, you can play an occupation for an occupation cost of 1
food."

An OPTIONAL trigger on the round-end ladder's returning_home window (ruling 49,
the Silage rung), gated on the Lessons space being empty (pre-reset live
occupancy). Firing pushes PendingPlayOccupation with a flat 1-food cost
(Scholar's occupation route). Tests drive the REAL round-end walk
(_advance_until_decision from a drained WORK state) and play a hand occupation.
"""
from __future__ import annotations

import agricola.cards.night_school_student  # noqa: F401  (registers the card)
import agricola.cards.consultant            # noqa: F401  (a playable hand occupation)

from agricola.actions import CommitPlayOccupation, FireTrigger, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import CARDS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow, PendingPlayOccupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import Cell
from tests.factories import with_space

CARD_ID = "night_school_student"
_FIRE = FireTrigger(card_id=CARD_ID)
_HAND_OCC = "consultant"


def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _state(*, lessons_workers=(0, 0), food=1, hand=(_HAND_OCC,), owned=True,
           round_number=1, seed=0):
    """Drained WORK state; P0 (optionally) owns the card, holds `hand` occupations
    with `food`, and the Lessons space carries `lessons_workers`."""
    state = setup(seed)
    state = fast_replace(state, phase=Phase.WORK, round_number=round_number,
                         starting_player=0)
    state = with_space(state, "lessons", workers=lessons_workers)
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    occ = state.players[0].occupations | ({CARD_ID} if owned else set())
    state = _edit_player(state, 0, occupations=occ,
                         hand_occupations=frozenset(hand),
                         resources=Resources(food=food))
    return state


def _walk(state):
    return _advance_until_decision(state)


def _fires(state):
    return [a for a in legal_actions(state)
            if isinstance(a, FireTrigger) and a.card_id == CARD_ID]


def _at_returning_home(state) -> bool:
    top = state.pending_stack[-1] if state.pending_stack else None
    return (isinstance(top, PendingHarvestWindow)
            and top.window_id == "returning_home")


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    entry = CARDS[CARD_ID]
    assert entry.event == "returning_home"
    assert entry.mandatory is False                      # "you can play" → optional


# --- Offered exactly when the gate holds ------------------------------------

def test_offered_when_lessons_empty_with_playable_occupation_and_food():
    state = _walk(_state())
    assert _at_returning_home(state)
    assert _fires(state) == [_FIRE]
    assert Proceed() in legal_actions(state)             # declining is available


def test_not_offered_when_lessons_occupied():
    state = _walk(_state(lessons_workers=(1, 0)))
    assert not _fires(state)
    # occupied by the OPPONENT also suppresses ("no PLAYER returns from Lessons").
    state = _walk(_state(lessons_workers=(0, 1)))
    assert not _fires(state)


def test_not_offered_without_a_playable_occupation():
    state = _walk(_state(hand=()))                       # empty hand
    assert not _fires(state)


def test_not_offered_without_affordable_food():
    state = _walk(_state(food=0))                        # can't pay the 1 food
    assert not _fires(state)


# --- Firing plays an occupation for 1 food ----------------------------------

def test_fire_pushes_play_occupation_then_plays_for_one_food():
    state = _walk(_state(food=1))
    state = step(state, _FIRE)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingPlayOccupation)
    assert top.cost == Resources(food=1)

    commit = CommitPlayOccupation(card_id=_HAND_OCC)
    assert commit in legal_actions(state)
    state = step(state, commit)
    p = state.players[0]
    assert _HAND_OCC in p.occupations                    # the occupation entered play
    assert _HAND_OCC not in p.hand_occupations           # left the hand
    assert p.resources.food == 0                         # the 1-food cost paid
    assert p.resources.clay == 3                         # Consultant's 2p on-play gift

    # The play-occupation host is in its after-phase now — Stop pops it back to
    # the returning_home window.
    state = step(state, Stop())
    assert _at_returning_home(state)
    # Once per phase: the window does not re-offer the trigger.
    assert not _fires(state)
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION


def test_decline_via_proceed_changes_nothing():
    state = _walk(_state(food=1))
    assert _fires(state)
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    p = state.players[0]
    assert _HAND_OCC in p.hand_occupations               # not played
    assert p.resources.food == 1
    assert state.phase == Phase.PREPARATION


def test_unowned_never_hosts():
    state = _walk(_state(owned=False))
    assert not any(isinstance(f, PendingHarvestWindow)
                   and f.window_id == "returning_home"
                   for f in state.pending_stack)
    assert state.phase == Phase.PREPARATION
