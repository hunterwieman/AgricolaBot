"""Tests for Iron Hoe (minor improvement, E20; Ephipparius Expansion).

Card text (verbatim): "At the end of each work phase, if you occupy both the
"Grain Seeds" and "Vegetable Seeds" action spaces, you can plow 1 field."

An optional trigger on the round-end ladder's ``end_of_work`` rung (pre-reset,
so the still-placed board is readable), gated on the owner occupying BOTH seed
spaces AND a legal plow existing. Firing pushes a ``PendingPlow``. Tests drive
the real round-end walk (the Master Renovator idiom).
"""
from __future__ import annotations

import agricola.cards.iron_hoe  # noqa: F401  (registers the card)

import pytest

from agricola.actions import CommitPlow, FireTrigger, Proceed, Stop
from agricola.cards.specs import MINORS
from agricola.cards.triggers import CARDS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow, PendingPlow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_grid, with_space

CARD_ID = "iron_hoe"
_SEED_SPACES = ("grain_seeds", "vegetable_seeds")


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    return _edit_player(state, idx, minor_improvements=p.minor_improvements | {card_id})


def _count_fields(state, idx):
    grid = state.players[idx].farmyard.grid
    return sum(1 for row in grid for cell in row if cell.cell_type == CellType.FIELD)


def _drained_work_state(round_number=5):
    state = setup(seed=0)
    state = fast_replace(
        state, phase=Phase.WORK, round_number=round_number, starting_player=0)
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    return state


def _ih_state(*, round_number=5, owned=True, spaces=_SEED_SPACES, plowable=True):
    state = _drained_work_state(round_number=round_number)
    if owned:
        state = _own_minor(state, 0, CARD_ID)
    for sid in spaces:
        state = with_space(state, sid, workers=(1, 0))
    if not plowable:
        # Fill every non-room cell so no plow target remains.
        state = with_grid(state, 0, {
            (r, c): Cell(cell_type=CellType.STABLE)
            for r in range(3) for c in range(5)
            if state.players[0].farmyard.grid[r][c].cell_type == CellType.EMPTY})
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


# --- The fire: a granted plow -----------------------------------------------

def test_offered_and_plows_when_both_seed_spaces_occupied():
    state = _walk_to_window(_ih_state())
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)
    assert Proceed() in legal_actions(state)          # declinable

    before = _count_fields(state, 0)
    state = step(state, FireTrigger(card_id=CARD_ID))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingPlow)
    assert top.initiated_by_id == f"card:{CARD_ID}"

    plows = [a for a in legal_actions(state) if isinstance(a, CommitPlow)]
    assert plows                                       # a legal plow target
    state = step(state, plows[0])
    assert _count_fields(state, 0) == before + 1       # a field was plowed

    # Plow flips to its after-phase; Stop returns to the window (once-per-window).
    state = step(state, Stop())
    assert isinstance(state.pending_stack[-1], PendingHarvestWindow)
    assert legal_actions(state) == [Proceed()]


# --- Eligibility boundaries --------------------------------------------------

def test_not_offered_with_only_grain_seeds_occupied():
    state = _ih_state(spaces=("grain_seeds",))
    _no_window(state)


def test_not_offered_with_only_vegetable_seeds_occupied():
    state = _ih_state(spaces=("vegetable_seeds",))
    _no_window(state)


def test_not_offered_when_no_plowable_cell():
    """Both spaces occupied but the farm is full — no dead-end offer."""
    state = _ih_state(plowable=False)
    _no_window(state)


def test_declinable_leaves_the_farm_unchanged():
    state = _walk_to_window(_ih_state())
    before = _count_fields(state, 0)
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert _count_fields(state, 0) == before


def test_unowned_never_hosts():
    state = _ih_state(owned=False)
    _no_window(state)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
