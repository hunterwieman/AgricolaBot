"""Tests for Slurry Spreader (occupation, A106; Artifex Expansion).

Card text: "In the field phase of each harvest, each time you take the last
grain/vegetable from a field, you also get 2 food/1 food."

A Category-6 harvest-field hook (II.6): `_resolve_harvest_field` pushes a
transient `PendingHarvestField` host frame and fires the `harvest_field`
automatic effects for each owner BEFORE the mechanical "take 1 crop per field"
runs — but ONLY when some player owns a harvest-field card
(`should_host_harvest_field`). At fire time the fields are still fully sown, so a
field whose count is exactly 1 (grain==1 / veg==1) is precisely the field whose
*last* crop is about to be taken: +2 food per last-grain field, +1 food per
last-veg field. A field with grain>=2 keeps a grain after the take and earns
nothing.

These tests drive `_resolve_harvest_field` directly (like `tests/test_harvest_field.py`
and `tests/test_cards_category6.py`) so the firing-before-the-take ordering is
exercised end-to-end.
"""
from __future__ import annotations

import agricola.cards.slurry_spreader  # noqa: F401  (registers the card)

from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import (
    HARVEST_FIELD_CARDS,
    should_host_harvest_field,
)
from agricola.constants import CellType, Phase
from agricola.engine import _resolve_harvest_field
from agricola.replace import fast_replace
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_grid, with_phase, with_sown_fields

CARD_ID = "slurry_spreader"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _field_state(seed=0):
    """A HARVEST_FIELD-phase state (no card owned yet)."""
    return with_phase(setup(seed), Phase.HARVEST_FIELD)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_slurry_spreader_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in HARVEST_FIELD_CARDS
    spec = OCCUPATIONS[CARD_ID]
    # Occupation played via Lessons — no cost/prereq/vps/passing overrides.
    assert spec.on_play is not None


def test_slurry_spreader_on_play_is_noop():
    state = setup(0)
    after = OCCUPATIONS[CARD_ID].on_play(state, 0)
    # No on-play effect: resources unchanged.
    assert after.players[0].resources == state.players[0].resources


def test_host_gate():
    # No card owned -> no host frame.
    assert should_host_harvest_field(setup(0)) is False
    # Owned (played) -> host.
    assert should_host_harvest_field(_own_occ(setup(0), 0, CARD_ID)) is True


# ---------------------------------------------------------------------------
# Last-grain / last-veg threshold (the core effect)
# ---------------------------------------------------------------------------

def test_last_grain_field_gives_2_food():
    """A 1-grain field: its last grain is taken this harvest -> +2 food."""
    state = _own_occ(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    f0 = state.players[0].resources.food
    g0 = state.players[0].resources.grain
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0 + 2     # +2 food bonus
    assert after.players[0].resources.grain == g0 + 1    # mechanical take of the 1 grain
    assert after.players[0].farmyard.grid[0][0].grain == 0


def test_last_veg_field_gives_1_food():
    """A 1-veg field: its last veg is taken this harvest -> +1 food."""
    state = _own_occ(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(1, 0): Cell(cell_type=CellType.FIELD, veg=1)})
    f0 = state.players[0].resources.food
    v0 = state.players[0].resources.veg
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0 + 1     # +1 food bonus
    assert after.players[0].resources.veg == v0 + 1       # mechanical take of the 1 veg


def test_multi_field_sums_grain_and_veg_bonuses():
    """Two 1-grain fields (+2 each) and one 1-veg field (+1) -> +5 food total."""
    state = _own_occ(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=1),
        (0, 1): Cell(cell_type=CellType.FIELD, grain=1),
        (1, 0): Cell(cell_type=CellType.FIELD, veg=1),
    })
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0 + 2 + 2 + 1


# ---------------------------------------------------------------------------
# Eligibility boundaries — does NOT fire on a field that keeps a crop
# ---------------------------------------------------------------------------

def test_no_bonus_for_field_with_two_grain():
    """A 2-grain field keeps a grain after the take (its last grain isn't taken
    this harvest) -> no bonus."""
    state = _own_occ(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])  # 3 grain
    state2 = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=2)})
    for s in (state, state2):
        f0 = s.players[0].resources.food
        after = _resolve_harvest_field(s)
        assert after.players[0].resources.food == f0   # no last-grain bonus


def test_no_bonus_for_empty_or_unsown_field():
    """An empty (already-harvested / never-sown) field has no crop -> no bonus."""
    state = _own_occ(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD)})  # empty
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0


def test_no_bonus_with_no_fields_at_all():
    state = _own_occ(_field_state(), 0, CARD_ID)
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0


# ---------------------------------------------------------------------------
# Owner-gating — fires only for the player who owns it
# ---------------------------------------------------------------------------

def test_fires_only_for_owner():
    state = _own_occ(_field_state(), 0, CARD_ID)   # P0 owns, P1 does not
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    state = with_grid(state, 1, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    f0, f1 = state.players[0].resources.food, state.players[1].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0 + 2   # owner gets the bonus
    assert after.players[1].resources.food == f1       # non-owner unchanged


# ---------------------------------------------------------------------------
# Family byte-identity — no frame, no income without the card
# ---------------------------------------------------------------------------

def test_byte_identical_without_card():
    state = _field_state(seed=3)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    # Mechanical take only; no Slurry food, no lingering frame.
    assert after.players[0].resources.food == f0
    assert after.phase == Phase.HARVEST_FEED
    assert all(type(f).__name__ != "PendingHarvestField" for f in after.pending_stack)
