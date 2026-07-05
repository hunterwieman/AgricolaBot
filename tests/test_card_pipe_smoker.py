"""Tests for Pipe Smoker (occupation, E117; Ephipparius Expansion).

Card text: "At the start of each harvest, if you have at least 1 grain field, you
get 2 wood."

A harvest-window AUTO on window #2, `start_of_harvest`, gated on the printed
condition "at least 1 grain field" (a FIELD cell with grain > 0). No structured
cost / prereq, no on-play. The auto fires mechanically inside the harvest walk
(`_process_simple_window`, window-major, starting player first) per owner — no
frame — and reads the still-sown grid (start_of_harvest precedes the field-phase
take). The reward is a flat 2 wood; the auto never mutates the grid.

The harvest tests drive the real walk (`_advance_until_decision` + `step`);
players are given ample food so feeding is painless and the +2 wood is isolated by
comparison against a no-card baseline run.
"""
from __future__ import annotations

import agricola.cards.pipe_smoker  # noqa: F401  (registers the card)

import pytest

from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_grid, with_phase

CARD_ID = "pipe_smoker"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _harvest_state(seed=0, food=10):
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        state = fast_replace(state, players=tuple(
            fast_replace(state.players[i],
                         resources=fast_replace(state.players[i].resources, food=food))
            if i == idx else state.players[i] for i in range(2)))
    return state


def _grain_cells(*cells):
    return {(r, c): Cell(cell_type=CellType.FIELD, grain=3) for (r, c) in cells}


def _run_harvest(state, pick=lambda acts: acts[0]):
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        state = step(state, pick(legal_actions(state)))
    return state


def _wood_after_harvest(state, idx):
    return _run_harvest(state).players[idx].resources.wood


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_occupation():
    assert CARD_ID in OCCUPATIONS
    # No on-play effect: playing it leaves resources untouched.
    s = setup(0)
    before = s.players[0].resources
    s2 = OCCUPATIONS[CARD_ID].on_play(s, 0)
    assert s2.players[0].resources == before


def test_registered_on_start_of_harvest_window():
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("start_of_harvest", set())
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("start_of_harvest", ())}
    assert CARD_ID in auto_ids
    # Mandatory auto, not a declinable trigger.
    trigger_ids = {e.card_id for e in TRIGGERS.get("start_of_harvest", ())}
    assert CARD_ID not in trigger_ids


# ---------------------------------------------------------------------------
# Start-of-harvest income (the core effect) — +2 wood with >= 1 grain field
# ---------------------------------------------------------------------------

def test_one_grain_field_gives_two_wood():
    base = with_grid(_harvest_state(), 0, _grain_cells((0, 0)))
    baseline = _wood_after_harvest(base, 0)
    owned = _wood_after_harvest(_own_occ(base, 0), 0)
    assert owned == baseline + 2


def test_many_grain_fields_still_two_wood():
    """Flat 2 wood regardless of how many grain fields (not per-field)."""
    base = with_grid(_harvest_state(), 0, _grain_cells((0, 0), (0, 1), (0, 2)))
    baseline = _wood_after_harvest(base, 0)
    owned = _wood_after_harvest(_own_occ(base, 0), 0)
    assert owned == baseline + 2


def test_reads_still_sown_grid_before_take():
    """The 'at least 1 grain field' condition is read at start_of_harvest, BEFORE
    the field-phase take depletes the fields; the mechanical take is unchanged."""
    base = with_grid(_harvest_state(), 0, _grain_cells((0, 0)))
    baseline = _run_harvest(base)
    owned = _run_harvest(_own_occ(base, 0))
    assert owned.players[0].resources.wood == baseline.players[0].resources.wood + 2
    # Same mechanical grain take (the bonus never mutates the grid).
    assert owned.players[0].resources.grain == baseline.players[0].resources.grain
    assert owned.players[0].farmyard.grid[0][0].grain == \
        baseline.players[0].farmyard.grid[0][0].grain


# ---------------------------------------------------------------------------
# Eligibility boundary — no grain field -> no income
# ---------------------------------------------------------------------------

def test_no_grain_field_no_wood():
    base = _harvest_state(seed=1)
    baseline = _wood_after_harvest(base, 0)
    owned = _wood_after_harvest(_own_occ(base, 0), 0)
    assert owned == baseline


def test_veg_field_does_not_count():
    veg = {(0, 0): Cell(cell_type=CellType.FIELD, veg=2)}
    base = with_grid(_harvest_state(seed=1), 0, veg)
    baseline = _wood_after_harvest(base, 0)
    owned = _wood_after_harvest(_own_occ(base, 0), 0)
    assert owned == baseline


def test_empty_field_does_not_count():
    empty = {(0, 0): Cell(cell_type=CellType.FIELD)}
    base = with_grid(_harvest_state(seed=1), 0, empty)
    baseline = _wood_after_harvest(base, 0)
    owned = _wood_after_harvest(_own_occ(base, 0), 0)
    assert owned == baseline


# ---------------------------------------------------------------------------
# Owner-gating
# ---------------------------------------------------------------------------

def test_fires_only_for_owner():
    base = with_grid(_harvest_state(), 0, _grain_cells((0, 0)))
    base = with_grid(base, 1, _grain_cells((0, 0)))
    baseline = _run_harvest(base)
    owned = _run_harvest(_own_occ(base, 0))   # P0 owns, P1 does not
    assert owned.players[0].resources.wood == baseline.players[0].resources.wood + 2
    assert owned.players[1].resources.wood == baseline.players[1].resources.wood


# ---------------------------------------------------------------------------
# Direct effect-fn unit checks
# ---------------------------------------------------------------------------

def test_eligible_predicate():
    s = setup(0)
    s = with_grid(s, 0, {(0, 0): Cell(cell_type=CellType.FIELD)})  # empty field
    assert agricola.cards.pipe_smoker._eligible(s, 0) is False
    s = with_grid(s, 0, _grain_cells((0, 0)))
    assert agricola.cards.pipe_smoker._eligible(s, 0) is True


def test_apply_adds_two_wood():
    s = setup(0)
    w0 = s.players[0].resources.wood
    after = agricola.cards.pipe_smoker._apply(s, 0)
    assert after.players[0].resources.wood == w0 + 2
    assert after.players[1].resources == s.players[1].resources


# ---------------------------------------------------------------------------
# Family fast path
# ---------------------------------------------------------------------------

def test_family_no_income_without_card():
    state = with_grid(_harvest_state(seed=3), 0, _grain_cells((0, 0)))
    final = _run_harvest(state)
    assert final.phase == Phase.PREPARATION
    assert all(type(f).__name__ != "PendingHarvestWindow"
               for f in final.pending_stack)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
