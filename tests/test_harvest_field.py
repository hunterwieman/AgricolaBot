"""Tests for the mechanical HARVEST_FIELD resolution (Task 7).

Verifies _resolve_harvest_field's three concerns: take 1 crop per planted
field, reset harvest_conversions_used, and transition to HARVEST_FEED with
FEED pendings pushed (one per player).
"""
from __future__ import annotations

import dataclasses

from agricola.constants import CellType, Phase
from agricola.engine import _resolve_harvest_field
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


def test_feed_pendings_pushed_one_per_player_sp_on_top():
    state = setup(seed=0)
    state = with_phase(state, Phase.HARVEST_FIELD)
    sp = state.starting_player

    new_state = _resolve_harvest_field(state)

    assert len(new_state.pending_stack) == 2
    assert all(isinstance(f, PendingHarvestFeed) for f in new_state.pending_stack)
    # Top frame is the starting player.
    assert new_state.pending_stack[-1].player_idx == sp
    assert new_state.pending_stack[0].player_idx == 1 - sp


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


def test_pre_debit_food_in_feed_push():
    """_initiate_harvest_feed (invoked by _resolve_harvest_field) pre-debits
    food per the cannot-withhold rule.

    Player with 5 food and need=4 -> pre-debit 4, food_owed=0, supply=1.
    """
    state = setup(seed=0)
    # Both default players: people_total=2 -> need=4. Player 0 has 2 food
    # (seed=0 starts SP with 2 and non-SP with 3); set explicitly.
    state = with_resources(state, 0, food=5)
    state = with_resources(state, 1, food=5)
    state = with_phase(state, Phase.HARVEST_FIELD)

    new_state = _resolve_harvest_field(state)

    for p_idx in (0, 1):
        # Find this player's pending.
        pendings = [f for f in new_state.pending_stack
                    if isinstance(f, PendingHarvestFeed) and f.player_idx == p_idx]
        assert len(pendings) == 1
        assert pendings[0].food_owed == 0
        assert new_state.players[p_idx].resources.food == 1
