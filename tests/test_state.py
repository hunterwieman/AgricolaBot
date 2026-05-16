"""Tests for state dataclasses and setup initialisation."""

import pytest

from agricola.constants import (
    CellType,
    HouseMaterial,
    NUM_MAJOR_IMPROVEMENTS,
    STAGE_CARDS,
    STAGE_ROUNDS,
)
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import Farmyard, Cell


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fences_in_supply(farmyard: Farmyard) -> int:
    used = sum(
        sum(row) for row in farmyard.horizontal_fences
    ) + sum(
        sum(row) for row in farmyard.vertical_fences
    )
    return 15 - used


def stables_built(farmyard: Farmyard) -> int:
    return sum(
        1
        for row in farmyard.grid
        for cell in row
        if cell.cell_type == CellType.STABLE
    )


# ---------------------------------------------------------------------------
# Setup tests
# ---------------------------------------------------------------------------

def test_setup_starting_food():
    state = setup(seed=0)
    sp = state.starting_player
    other = 1 - sp
    assert state.players[sp].resources.food == 2
    assert state.players[other].resources.food == 3


def test_setup_starting_rooms():
    state = setup(seed=0)
    for player_state in state.players:
        grid = player_state.farmyard.grid
        assert player_state.house_material == HouseMaterial.WOOD
        for r in range(3):
            for c in range(5):
                cell = grid[r][c]
                if (r, c) in {(1, 0), (2, 0)}:
                    assert cell.cell_type == CellType.ROOM
                else:
                    assert cell.cell_type == CellType.EMPTY


def test_setup_no_fences():
    state = setup(seed=0)
    for player_state in state.players:
        farmyard = player_state.farmyard
        for row in farmyard.horizontal_fences:
            assert all(f is False for f in row)
        for row in farmyard.vertical_fences:
            assert all(f is False for f in row)


def test_fresh_farmyard_has_empty_pastures():
    state = setup(seed=0)
    for player_state in state.players:
        assert player_state.farmyard.pastures == ()


def test_setup_people():
    state = setup(seed=0)
    for player_state in state.players:
        assert player_state.people_total == 2
        assert player_state.people_home == 2


def test_setup_major_improvements_available():
    state = setup(seed=0)
    assert len(state.board.major_improvement_owners) == NUM_MAJOR_IMPROVEMENTS
    assert all(owner is None for owner in state.board.major_improvement_owners)


def test_setup_round_card_count():
    state = setup(seed=0)
    all_stage_cards = [card for cards in STAGE_CARDS.values() for card in cards]
    order = state.board.round_card_order
    assert len(order) == 14
    assert sorted(order) == sorted(all_stage_cards)


def test_setup_stage_ordering():
    state = setup(seed=0)
    order = state.board.round_card_order  # index i -> round i+1
    for stage, (first_round, last_round) in STAGE_ROUNDS.items():
        stage_card_ids = set(STAGE_CARDS[stage])
        for i, card_id in enumerate(order):
            round_number = i + 1
            if card_id in stage_card_ids:
                assert first_round <= round_number <= last_round, (
                    f"Card '{card_id}' (stage {stage}) appeared at round "
                    f"{round_number}, expected {first_round}–{last_round}"
                )


def test_setup_deterministic():
    state_a = setup(seed=42)
    state_b = setup(seed=42)
    assert state_a == state_b


def test_setup_different_seeds():
    state_a = setup(seed=0)
    state_b = setup(seed=1)
    # Different seeds must produce a different starting player or different card order
    # (in practice both will differ, but either suffices)
    assert (
        state_a.starting_player != state_b.starting_player
        or state_a.board.round_card_order != state_b.board.round_card_order
    )


def test_fences_in_supply_derivation():
    state = setup(seed=0)
    for player_state in state.players:
        assert fences_in_supply(player_state.farmyard) == 15


def test_stables_in_supply_derivation():
    state = setup(seed=0)
    for player_state in state.players:
        assert stables_built(player_state.farmyard) == 0


# ---------------------------------------------------------------------------
# Resources.__add__ and __bool__ tests
# ---------------------------------------------------------------------------

def test_resources_add():
    a = Resources(wood=3)
    b = Resources(wood=2, food=1)
    assert a + b == Resources(wood=5, food=1)


def test_resources_add_identity():
    r = Resources(clay=1)
    assert Resources() + r == r
    assert r + Resources() == r


def test_resources_add_all_fields():
    a = Resources(wood=1, clay=2, reed=3, stone=4, food=5, grain=6, veg=7)
    b = Resources(wood=1, clay=1, reed=1, stone=1, food=1, grain=1, veg=1)
    assert a + b == Resources(wood=2, clay=3, reed=4, stone=5, food=6, grain=7, veg=8)


def test_resources_add_returns_new_instance():
    a = Resources(wood=1)
    b = Resources(wood=2)
    c = a + b
    assert c is not a
    assert c is not b


def test_resources_bool_true():
    assert bool(Resources(wood=1))
    assert bool(Resources(food=3))
    assert bool(Resources(veg=1))


def test_resources_bool_false():
    assert not bool(Resources())
    assert not bool(Resources(wood=0, clay=0, reed=0, stone=0, food=0, grain=0, veg=0))


# ---------------------------------------------------------------------------
# Resources.__sub__ tests
# ---------------------------------------------------------------------------

def test_resources_sub():
    a = Resources(wood=5, food=3)
    b = Resources(wood=2, food=1)
    assert a - b == Resources(wood=3, food=2)


def test_resources_sub_identity():
    r = Resources(clay=1)
    assert r - Resources() == r


def test_resources_sub_all_fields():
    a = Resources(wood=10, clay=10, reed=10, stone=10, food=10, grain=10, veg=10)
    b = Resources(wood=1, clay=2, reed=3, stone=4, food=5, grain=6, veg=7)
    assert a - b == Resources(wood=9, clay=8, reed=7, stone=6, food=5, grain=4, veg=3)


def test_resources_sub_allows_negative_components():
    """Sub mirrors add: negative result components are allowed (no clamping)."""
    a = Resources(wood=1)
    b = Resources(wood=3)
    assert a - b == Resources(wood=-2)


def test_resources_sub_returns_new_instance():
    a = Resources(wood=5)
    b = Resources(wood=2)
    c = a - b
    assert c is not a
    assert c is not b


def test_resources_sub_round_trip():
    """a - b + b == a for arbitrary a, b."""
    a = Resources(wood=4, clay=7, food=2)
    b = Resources(wood=1, clay=3, food=1, grain=5)
    assert (a - b) + b == a


# ---------------------------------------------------------------------------
# Task 5 state additions
# ---------------------------------------------------------------------------

def test_setup_empty_pending_stack():
    state = setup(seed=0)
    assert state.pending_stack == ()


def test_setup_future_resources_default():
    state = setup(seed=0)
    for player_state in state.players:
        assert len(player_state.future_resources) == 14
        for entry in player_state.future_resources:
            assert entry == Resources()


def test_setup_minor_improvements_empty():
    state = setup(seed=0)
    for player_state in state.players:
        assert player_state.minor_improvements == frozenset()


def test_setup_occupations_empty():
    state = setup(seed=0)
    for player_state in state.players:
        assert player_state.occupations == frozenset()
