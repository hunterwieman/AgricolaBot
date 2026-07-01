"""Tests for Bale of Straw (minor improvement, D61; Dulcinaria Expansion).

Card text: "At the start of each harvest, if you have at least 3 grain fields
(including field cards with planted grain), you get 2 food."

A Category-6 harvest-field hook (no cost, no VPs, kept). The field-phase hook
(`_resolve_harvest_field` / `_fire_harvest_field_hook`) fires for each owner
BEFORE the mechanical "take 1 crop per field" runs, but only when some player
owns a harvest-field card (`should_host_harvest_field`). At fire time the fields
are still fully sown, so "you have at least 3 grain fields" is read on the
still-sown grid (FIELD cells with grain > 0). When the count is >= 3 the player
gets a flat 2 food (not per-field); below 3, nothing. The card never mutates the
grid, so the mechanical take is unaffected.

The harvest tests drive `_resolve_harvest_field` directly (like
`tests/test_harvest_field.py` and `tests/test_card_crack_weeder.py`) so the
firing-before-the-take ordering is exercised end-to-end.
"""
from __future__ import annotations

import agricola.cards.bale_of_straw  # noqa: F401  (registers the card)

import pytest

from agricola.cards.specs import MINORS
from agricola.cards.triggers import (
    HARVEST_FIELD_CARDS,
    should_host_harvest_field,
)
from agricola.constants import CellType, Phase
from agricola.engine import _resolve_harvest_field
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_grid, with_phase

CARD_ID = "bale_of_straw"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id):
    """Put the (played) minor in player `idx`'s tableau."""
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _field_state(seed=0):
    """A HARVEST_FIELD-phase state (no card owned yet)."""
    return with_phase(setup(seed), Phase.HARVEST_FIELD)


def _grain_cells(*cells):
    """Override dict: each given (r, c) becomes a grain-sown FIELD cell."""
    return {(r, c): Cell(cell_type=CellType.FIELD, grain=3) for (r, c) in cells}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    assert CARD_ID in HARVEST_FIELD_CARDS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()            # free card
    assert spec.cost_fn is None
    assert spec.prereq is None
    assert spec.min_occupations == 0
    assert spec.max_occupations is None
    assert spec.passing_left is False
    assert spec.vps == 0


# ---------------------------------------------------------------------------
# Host gate
# ---------------------------------------------------------------------------

def test_host_gate():
    assert should_host_harvest_field(setup(0)) is False
    assert should_host_harvest_field(_own_minor(setup(0), 0, CARD_ID)) is True


def test_hand_card_does_not_host():
    """Holding the card in hand (not played) must NOT host the harvest-field
    frame — only a tableau (played) minor counts."""
    state = setup(0)
    p = fast_replace(state.players[0], hand_minors=frozenset({CARD_ID}))
    state = fast_replace(state, players=tuple(
        p if i == 0 else state.players[i] for i in range(2)))
    assert should_host_harvest_field(state) is False


# ---------------------------------------------------------------------------
# Field-phase income (the core effect)
# ---------------------------------------------------------------------------

def test_three_grain_fields_gives_two_food():
    """Exactly 3 grain-sown fields meets the threshold -> +2 food."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, _grain_cells((0, 0), (0, 1), (0, 2)))
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0 + 2


def test_more_than_three_grain_fields_still_two_food():
    """The reward is a FLAT 2 food regardless of how many grain fields (not
    per-field): 5 grain fields still gives exactly +2 food."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0,
                      _grain_cells((0, 0), (0, 1), (0, 2), (1, 0), (1, 1)))
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0 + 2


def test_reads_still_sown_grid_before_take():
    """The bonus is evaluated BEFORE the mechanical crop take depletes the
    fields: with exactly 3 grain fields the bonus fires (it does not see the
    post-take grid where one grain has been removed per field)."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, _grain_cells((0, 0), (0, 1), (0, 2)))
    g0 = state.players[0].resources.grain
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0 + 2       # +2 food bonus
    assert after.players[0].resources.grain == g0 + 3      # mechanical take: 1/field
    # Grid depleted by exactly 1 grain per field (bonus never mutates the grid).
    assert after.players[0].farmyard.grid[0][0].grain == 2


# ---------------------------------------------------------------------------
# Eligibility boundaries — threshold of 3
# ---------------------------------------------------------------------------

def test_two_grain_fields_below_threshold_no_food():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, _grain_cells((0, 0), (0, 1)))
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0


def test_no_fields_at_all_no_food():
    state = _own_minor(_field_state(), 0, CARD_ID)
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0


def test_veg_fields_do_not_count():
    """Vegetable-sown fields are not 'grain fields' — three veg fields do NOT
    meet the threshold."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, veg=2),
        (0, 1): Cell(cell_type=CellType.FIELD, veg=2),
        (0, 2): Cell(cell_type=CellType.FIELD, veg=2),
    })
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0


def test_empty_fields_do_not_count():
    """Plowed-but-unsown fields are not grain fields."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD),
        (0, 1): Cell(cell_type=CellType.FIELD),
        (0, 2): Cell(cell_type=CellType.FIELD),
    })
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0


def test_mixed_two_grain_one_veg_below_threshold():
    """Only grain fields count: 2 grain + 1 veg = 2 grain fields -> no food."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 1): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 2): Cell(cell_type=CellType.FIELD, veg=2),
    })
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0


# ---------------------------------------------------------------------------
# Owner-gating — fires only for the player who owns it
# ---------------------------------------------------------------------------

def test_fires_only_for_owner():
    state = _own_minor(_field_state(), 0, CARD_ID)   # P0 owns, P1 does not
    state = with_grid(state, 0, _grain_cells((0, 0), (0, 1), (0, 2)))
    state = with_grid(state, 1, _grain_cells((0, 0), (0, 1), (0, 2)))
    f0, f1 = state.players[0].resources.food, state.players[1].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0 + 2   # owner gets the bonus
    assert after.players[1].resources.food == f1       # non-owner unchanged


# ---------------------------------------------------------------------------
# Direct effect-fn unit checks (optionality / eligibility in isolation)
# ---------------------------------------------------------------------------

def test_eligible_predicate():
    state = setup(0)
    state = with_grid(state, 0, _grain_cells((0, 0), (0, 1)))
    assert agricola.cards.bale_of_straw._eligible(state, 0) is False
    state = with_grid(state, 0, _grain_cells((0, 0), (0, 1), (0, 2)))
    assert agricola.cards.bale_of_straw._eligible(state, 0) is True


def test_apply_adds_two_food():
    state = setup(0)
    f0 = state.players[0].resources.food
    after = agricola.cards.bale_of_straw._apply(state, 0)
    assert after.players[0].resources.food == f0 + 2
    # Only the acting player changes.
    assert after.players[1].resources == state.players[1].resources


# ---------------------------------------------------------------------------
# Family byte-identity — no frame, no income without the card
# ---------------------------------------------------------------------------

def test_byte_identical_without_card():
    state = _field_state(seed=3)
    state = with_grid(state, 0, _grain_cells((0, 0), (0, 1), (0, 2)))
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    # Mechanical take only; no Bale of Straw food, no lingering frame.
    assert after.players[0].resources.food == f0
    assert after.phase == Phase.HARVEST_FEED
    assert all(type(f).__name__ != "PendingHarvestField" for f in after.pending_stack)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
