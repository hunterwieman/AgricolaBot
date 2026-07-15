"""Tests for Apiary (minor improvement, E23; Ephipparius Expansion).

Card text (verbatim): "At the end of each work phase, you can sow exactly 1 crop
on 1 field."

Free, prereq "4 Occupations", no VPs. An optional trigger on the round-end
ladder's ``end_of_work`` rung: firing pushes a ``PendingSow(max_fields=1)`` —
exactly one field sown. Tests drive the real round-end walk (the Master
Renovator idiom).
"""
from __future__ import annotations

import agricola.cards.apiary  # noqa: F401  (registers the card)

import pytest

from agricola.actions import CommitSow, FireTrigger, Proceed, Stop
from agricola.cards.specs import MINORS
from agricola.cards.triggers import CARDS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow, PendingSow
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import setup

from tests.factories import with_fields, with_resources

CARD_ID = "apiary"


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    return _edit_player(state, idx, minor_improvements=p.minor_improvements | {card_id})


def _sown_grain(state, idx):
    grid = state.players[idx].farmyard.grid
    return sum(cell.grain for row in grid for cell in row
               if cell.cell_type == CellType.FIELD)


def _drained_work_state(round_number=5):
    state = setup(seed=0)
    state = fast_replace(
        state, phase=Phase.WORK, round_number=round_number, starting_player=0)
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    return state


def _ap_state(*, owned=True, fields=((0, 2), (0, 3)), grain=2):
    state = _drained_work_state()
    if owned:
        state = _own_minor(state, 0, CARD_ID)
    if fields:
        state = with_fields(state, 0, fields)
    state = with_resources(state, 0, grain=grain)
    return state


def _walk_to_window(state):
    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow), (
        f"no end_of_work window (top={top!r}, phase={state.phase})")
    assert top.window_id == "end_of_work" and top.player_idx == 0
    return state


def _no_window(state):
    state = _advance_until_decision(state)
    assert not any(
        isinstance(f, PendingHarvestWindow) and f.window_id == "end_of_work"
        for f in state.pending_stack)
    return state


# --- Registration -----------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    assert MINORS[CARD_ID].cost == Cost()             # free
    assert MINORS[CARD_ID].min_occupations == 4       # "4 Occupations"
    entry = CARDS[CARD_ID]
    assert entry.event == "end_of_work"
    assert entry.mandatory is False


# --- The fire: a single-field sow -------------------------------------------

def test_offered_and_sows_exactly_one_field():
    state = _walk_to_window(_ap_state(fields=((0, 2), (0, 3)), grain=2))
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)
    assert Proceed() in legal_actions(state)

    state = step(state, FireTrigger(card_id=CARD_ID))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingSow)
    assert top.max_fields == 1                         # "exactly 1 crop on 1 field"
    assert top.initiated_by_id == f"card:{CARD_ID}"

    # The cap allows at most one field (grain + veg <= 1) in any single commit.
    sows = [a for a in legal_actions(state) if isinstance(a, CommitSow)]
    assert sows and all(a.grain + a.veg <= 1 for a in sows)

    grow = max(sows, key=lambda a: a.grain + a.veg)    # the one that sows a field
    assert grow.grain == 1 and grow.veg == 0
    state = step(state, grow)
    assert _sown_grain(state, 0) == 3                  # 1 field sown -> 3 grain
    assert state.players[0].resources.grain == 1       # 1 of the 2 grain planted

    # Sow flips to its after-phase; Stop returns to the window (once-per-window).
    state = step(state, Stop())
    assert isinstance(state.pending_stack[-1], PendingHarvestWindow)
    assert legal_actions(state) == [Proceed()]


# --- Eligibility boundaries --------------------------------------------------

def test_not_offered_without_an_empty_field():
    state = _ap_state(fields=(), grain=2)              # seed but nowhere to sow
    _no_window(state)


def test_not_offered_without_a_seed():
    state = _ap_state(fields=((0, 2),), grain=0)       # a field but no seed
    _no_window(state)


def test_declinable_leaves_the_fields_empty():
    state = _walk_to_window(_ap_state())
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert _sown_grain(state, 0) == 0


def test_unowned_never_hosts():
    state = _ap_state(owned=False)
    _no_window(state)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
