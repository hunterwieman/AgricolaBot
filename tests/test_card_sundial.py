"""Tests for Sundial (minor improvement, E26; Ephipparius Expansion).

Card text (verbatim): "At the end of the work phases in rounds 7 and 9, you can
take a "Sow" action without placing a person."

Cost 1 Wood, no VPs. An optional trigger on the round-end ladder's
``end_of_work`` rung, latched to rounds 7 and 9: firing pushes a FULL (uncapped)
``PendingSow``. Tests drive the real round-end walk (the Master Renovator
idiom); rounds 7/9 are harvest rounds, so assertions stop once the sow resolves.
"""
from __future__ import annotations

import agricola.cards.sundial  # noqa: F401  (registers the card)

import pytest

from agricola.actions import CommitSow, FireTrigger, Proceed
from agricola.cards.specs import MINORS
from agricola.cards.triggers import CARDS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow, PendingSow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup

from tests.factories import with_fields, with_resources

CARD_ID = "sundial"


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


def _drained_work_state(round_number=7):
    state = setup(seed=0)
    state = fast_replace(
        state, phase=Phase.WORK, round_number=round_number, starting_player=0)
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    return state


def _sd_state(*, round_number=7, owned=True, fields=((0, 2), (0, 3)), grain=2):
    state = _drained_work_state(round_number=round_number)
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
    assert MINORS[CARD_ID].cost == Cost(resources=Resources(wood=1))
    entry = CARDS[CARD_ID]
    assert entry.event == "end_of_work"
    assert entry.mandatory is False


# --- The fire: a full (uncapped) Sow at rounds 7 and 9 ----------------------

@pytest.mark.parametrize("rnd", [7, 9])
def test_offered_and_full_sow_at_rounds_7_and_9(rnd):
    state = _walk_to_window(_sd_state(round_number=rnd, fields=((0, 2), (0, 3)), grain=2))
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)

    state = step(state, FireTrigger(card_id=CARD_ID))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingSow)
    assert top.max_fields == 0                         # uncapped — a full Sow action
    assert top.initiated_by_id == f"card:{CARD_ID}"

    # Uncapped: a two-field sow is legal (both fields at once).
    sows = [a for a in legal_actions(state) if isinstance(a, CommitSow)]
    assert any(a.grain + a.veg == 2 for a in sows)
    both = max(sows, key=lambda a: a.grain + a.veg)
    state = step(state, both)
    assert _sown_grain(state, 0) == 6                  # 2 fields sown -> 3 grain each


# --- Round gating ------------------------------------------------------------

def test_not_offered_outside_rounds_7_and_9():
    state = _sd_state(round_number=5, fields=((0, 2), (0, 3)), grain=2)
    _no_window(state)


def test_not_offered_without_a_legal_sow():
    """Round 7 but no seed: never a dead-end offer."""
    state = _sd_state(round_number=7, fields=((0, 2),), grain=0)
    _no_window(state)


def test_declinable_leaves_the_fields_empty():
    state = _walk_to_window(_sd_state(round_number=7))
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert _sown_grain(state, 0) == 0


def test_unowned_never_hosts():
    state = _sd_state(round_number=7, owned=False)
    _no_window(state)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
