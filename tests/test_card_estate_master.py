"""Tests for Estate Master (occupation B132).

Card text: "Once you have no unused farmyard spaces left, you get 1 bonus point for
each vegetable that you harvest."
Clarification: activation persists even if the farmyard is later changed.

Two seams: a boundary one-shot that ACTIVATES the card permanently the first time
the farmyard is full, and a harvest-occasion auto that (once activated) banks 1
point per vegetable UNIT harvested in the field phase. Tests cover the activation
latch, the veg banking, the not-activated no-op, grain-doesn't-count, the
persistence-after-change clarification, and scoring readback.
"""
import agricola.cards.estate_master  # noqa: F401  (registers the card)

from agricola.cards.estate_master import CARD_ID
from agricola.cards.harvest_windows import HARVEST_OCCASION_AUTOS
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import BOUNDARY_ONE_SHOTS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, _fire_boundary_one_shots
from agricola.replace import fast_replace
from agricola.scoring import SCORING_TERMS
from agricola.setup import setup
from agricola.state import Cell, GameState

from tests.factories import with_grid, with_phase


def _own(state, idx):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | {CARD_ID})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _full_farmyard(state, idx):
    """Fill every one of the 15 farmyard cells with a FIELD (all spaces used)."""
    overrides = {(r, c): Cell(cell_type=CellType.FIELD)
                 for r in range(3) for c in range(5)}
    return with_grid(state, idx, overrides)


def _activate(state, idx, banked=0):
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, (True, banked)))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _harvest_state(seed=0, food=10):
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        state = fast_replace(state, players=tuple(
            fast_replace(state.players[i], resources=fast_replace(
                state.players[i].resources, food=food))
            if i == idx else state.players[i] for i in range(2)))
    return state


def _score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


def _banked(state, idx):
    return state.players[idx].card_state.get(CARD_ID, (False, 0))[1]


def _activated(state, idx):
    return state.players[idx].card_state.get(CARD_ID, (False, 0))[0]


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in BOUNDARY_ONE_SHOTS
    assert any(e.card_id == CARD_ID for e in HARVEST_OCCASION_AUTOS)
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


def test_on_play_is_noop():
    s = setup(0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) == s


# --- Activation latch (boundary one-shot) -----------------------------------

def test_activates_on_full_farmyard():
    s = _full_farmyard(_own(setup(0), 0), 0)
    out = _fire_boundary_one_shots(s)
    assert _activated(out, 0) is True
    assert CARD_ID in out.players[0].fired_once


def test_no_activation_when_farmyard_not_full():
    s = _own(setup(0), 0)                        # default farm has empty cells
    out = _fire_boundary_one_shots(s)
    assert _activated(out, 0) is False


def test_no_activation_when_unowned():
    s = _full_farmyard(setup(0), 0)              # full farm, but card not owned
    out = _fire_boundary_one_shots(s)
    assert _activated(out, 0) is False


# --- Banking veg during the field phase (activated) -------------------------

def test_banks_one_point_per_veg_when_activated():
    """Activated + two veg-sown fields -> +2 banked points over the field phase."""
    s = _activate(_own(_harvest_state(), 0), 0)
    s = with_grid(s, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, veg=1),
        (0, 1): Cell(cell_type=CellType.FIELD, veg=1),
    })
    out = _advance_until_decision(s)
    assert _banked(out, 0) == 2


def test_no_banking_when_not_activated():
    """Veg fields but the card was never activated -> no points banked."""
    s = _own(_harvest_state(), 0)
    s = with_grid(s, 0, {(0, 0): Cell(cell_type=CellType.FIELD, veg=1)})
    out = _advance_until_decision(s)
    assert _banked(out, 0) == 0


def test_grain_does_not_bank():
    """Only vegetables count; a grain-sown field banks nothing."""
    s = _activate(_own(_harvest_state(), 0), 0)
    s = with_grid(s, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=3)})
    out = _advance_until_decision(s)
    assert _banked(out, 0) == 0


def test_only_owner_banks():
    s = _activate(_own(_harvest_state(), 0), 0)
    # Player 1 does NOT own the card; give both a veg field.
    s = with_grid(s, 0, {(0, 0): Cell(cell_type=CellType.FIELD, veg=1)})
    s = with_grid(s, 1, {(0, 0): Cell(cell_type=CellType.FIELD, veg=1)})
    out = _advance_until_decision(s)
    assert _banked(out, 0) == 1
    assert out.players[1].card_state.get(CARD_ID, (False, 0))[1] == 0


# --- Persistence after farmyard change (the clarification) ------------------

def test_banking_persists_when_farmyard_no_longer_full():
    """Activation is latched: a harvest still banks even though the farm is NOT
    full at harvest time (the printed clarification)."""
    s = _activate(_own(_harvest_state(), 0), 0)   # activated, farm NOT full
    assert not agricola.cards.estate_master._all_farmyard_spaces_used(s, 0)
    s = with_grid(s, 0, {(0, 0): Cell(cell_type=CellType.FIELD, veg=1)})
    out = _advance_until_decision(s)
    assert _banked(out, 0) == 1


def test_activation_not_cleared_when_farm_empties():
    s = _full_farmyard(_own(setup(0), 0), 0)
    out = _fire_boundary_one_shots(s)
    assert _activated(out, 0) is True
    # Empty the farm again; the latch (and the flag) survive.
    out = with_grid(out, 0, {(r, c): Cell() for r in range(3) for c in range(5)})
    out = _fire_boundary_one_shots(out)
    assert _activated(out, 0) is True


# --- Scoring ----------------------------------------------------------------

def test_scoring_reads_banked_points():
    score = _score_fn()
    s = setup(0)
    assert score(s, 0) == 0
    s = _activate(s, 0, banked=4)
    assert score(s, 0) == 4
