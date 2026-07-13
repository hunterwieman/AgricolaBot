"""Tests for the mechanical HARVEST_FIELD resolution (Task 7).

Verifies _resolve_harvest_field's three concerns: take 1 crop per planted
field, reset harvest_conversions_used, and transition to HARVEST_FEED with
FEED pendings pushed (one per player).
"""
from __future__ import annotations

import dataclasses

from agricola.actions import CommitConvert, Stop
from agricola.constants import CellType, Phase
from agricola.engine import _resolve_harvest_field, step
from agricola.pending import PendingHarvestFeed
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import (
    with_grid,
    with_phase,
    with_resources,
)


def _set_field(state, player_idx, row, col, *, grain=0, veg=0):
    """Sow a field cell at (row, col) for the given player."""
    return with_grid(state, player_idx, {(row, col): Cell(
        cell_type=CellType.FIELD, grain=grain, veg=veg,
    )})


def test_single_grain_field_yields_one_grain():
    state = setup(seed=0)
    state = _set_field(state, 0, 0, 2, grain=3)
    state = with_phase(state, Phase.HARVEST_FIELD)

    new_state = _resolve_harvest_field(state)

    p0 = new_state.players[0]
    assert p0.resources.grain == state.players[0].resources.grain + 1
    assert p0.farmyard.grid[0][2].grain == 2   # one removed
    assert p0.farmyard.grid[0][2].veg == 0


def test_single_veg_field_yields_one_veg():
    state = setup(seed=0)
    state = _set_field(state, 0, 0, 2, veg=2)
    state = with_phase(state, Phase.HARVEST_FIELD)

    new_state = _resolve_harvest_field(state)

    p0 = new_state.players[0]
    assert p0.resources.veg == state.players[0].resources.veg + 1
    assert p0.farmyard.grid[0][2].veg == 1


def test_multiple_fields_per_player_each_yields_one():
    state = setup(seed=0)
    state = _set_field(state, 0, 0, 2, grain=3)
    state = _set_field(state, 0, 0, 3, grain=2)
    state = _set_field(state, 0, 1, 2, veg=2)
    state = with_phase(state, Phase.HARVEST_FIELD)

    pre = state.players[0].resources
    new_state = _resolve_harvest_field(state)
    p0 = new_state.players[0]

    assert p0.resources.grain == pre.grain + 2
    assert p0.resources.veg   == pre.veg   + 1
    assert p0.farmyard.grid[0][2].grain == 2
    assert p0.farmyard.grid[0][3].grain == 1
    assert p0.farmyard.grid[1][2].veg   == 1


def test_empty_field_no_change():
    """A FIELD cell with grain=0, veg=0 yields nothing and stays unchanged."""
    state = setup(seed=0)
    state = _set_field(state, 0, 0, 2, grain=0, veg=0)
    state = with_phase(state, Phase.HARVEST_FIELD)

    pre_grain = state.players[0].resources.grain
    pre_veg   = state.players[0].resources.veg

    new_state = _resolve_harvest_field(state)

    assert new_state.players[0].resources.grain == pre_grain
    assert new_state.players[0].resources.veg   == pre_veg
    assert new_state.players[0].farmyard.grid[0][2].cell_type == CellType.FIELD


def test_both_players_harvest_independently():
    state = setup(seed=0)
    state = _set_field(state, 0, 0, 2, grain=3)
    state = _set_field(state, 1, 0, 4, veg=2)
    state = with_phase(state, Phase.HARVEST_FIELD)

    new_state = _resolve_harvest_field(state)

    assert new_state.players[0].resources.grain == state.players[0].resources.grain + 1
    assert new_state.players[1].resources.veg   == state.players[1].resources.veg + 1


def test_harvest_conversions_used_reset():
    state = setup(seed=0)
    # Pre-populate the budget on both players to simulate a stale state.
    state = dataclasses.replace(
        state,
        players=tuple(
            dataclasses.replace(p, harvest_conversions_used=frozenset({"joinery", "pottery"}))
            for p in state.players
        ),
    )
    state = with_phase(state, Phase.HARVEST_FIELD)

    new_state = _resolve_harvest_field(state)

    for p in new_state.players:
        assert p.harvest_conversions_used == frozenset()


def test_phase_transitions_to_harvest_feed():
    state = setup(seed=0)
    state = with_phase(state, Phase.HARVEST_FIELD)
    new_state = _resolve_harvest_field(state)
    assert new_state.phase == Phase.HARVEST_FEED


def test_feed_pendings_banded_one_player_per_pass_sp_first():
    """Ruling 40 (2026-07-12): FEED resolves whole-phase-per-player — the
    walk pushes ONE payment frame per band pass (starting player first, the
    cursor carried), never both players' frames at once."""
    state = setup(seed=0)
    state = with_phase(state, Phase.HARVEST_FIELD)
    sp = state.starting_player

    new_state = _resolve_harvest_field(state)

    assert len(new_state.pending_stack) == 1
    assert isinstance(new_state.pending_stack[-1], PendingHarvestFeed)
    assert new_state.pending_stack[-1].player_idx == sp
    assert new_state.harvest_cursor is not None

    # The starting player pays and Stops; the OTHER player's frame arrives
    # on the second band pass.
    new_state = step(new_state, CommitConvert(0, 0, 0, 0, 0))
    new_state = step(new_state, Stop())
    assert len(new_state.pending_stack) == 1
    assert isinstance(new_state.pending_stack[-1], PendingHarvestFeed)
    assert new_state.pending_stack[-1].player_idx == 1 - sp


def test_pasture_cache_preserved():
    """Fields cannot lie inside pastures; the cache rides along untouched."""
    state = setup(seed=0)
    state = _set_field(state, 0, 0, 2, grain=2)
    state = with_phase(state, Phase.HARVEST_FIELD)
    pre_pastures = state.players[0].farmyard.pastures

    new_state = _resolve_harvest_field(state)

    assert new_state.players[0].farmyard.pastures == pre_pastures


def test_newborns_not_cleared():
    """_resolve_harvest_field does NOT touch newborns — they survive into FEED
    for the 1-food discount. Clearing happens in _resolve_preparation."""
    state = setup(seed=0)
    # Fabricate a player with a newborn.
    state = dataclasses.replace(
        state,
        players=(
            dataclasses.replace(state.players[0], newborns=1, people_total=3),
            state.players[1],
        ),
    )
    state = with_phase(state, Phase.HARVEST_FIELD)

    new_state = _resolve_harvest_field(state)

    assert new_state.players[0].newborns == 1


def test_feed_push_does_not_debit_food():
    """The FEED-band sentinel does NOT pre-debit food. Payment is deferred to
    CommitConvert. Each player keeps their full supply when their frame is
    up; the pending shape is just (player_idx, initiated_by_id,
    conversion_done). Banded (ruling 40): one frame per pass.
    """
    state = setup(seed=0)
    state = with_resources(state, 0, food=5)
    state = with_resources(state, 1, food=5)
    state = with_phase(state, Phase.HARVEST_FIELD)

    new_state = _resolve_harvest_field(state)

    sp = new_state.starting_player
    for expected_idx in (sp, 1 - sp):
        top = new_state.pending_stack[-1]
        assert isinstance(top, PendingHarvestFeed)
        assert top.player_idx == expected_idx
        # No food_owed field on the pending in the deferred-payment model.
        assert not hasattr(top, "food_owed")
        # Food untouched by the sentinel: the deciding player still holds
        # their full 5 when their frame comes up.
        assert new_state.players[expected_idx].resources.food == 5
        new_state = step(new_state, CommitConvert(0, 0, 0, 0, 0))
        new_state = step(new_state, Stop())
