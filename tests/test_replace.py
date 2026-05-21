"""Tests for agricola.replace.fast_replace.

Verifies behavioral equivalence with stdlib `dataclasses.replace` across
every dataclass shape the engine uses. The migration assumes drop-in
equivalence; these tests guard that assumption.
"""
from __future__ import annotations

import dataclasses

from agricola.actions import CommitSow, PlaceWorker
from agricola.pending import PendingBakeBread, PendingSow, push
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.setup import setup
from agricola.state import ActionSpaceState, Cell, get_space


# ---------------------------------------------------------------------------
# Per-class equivalence: result equals dataclasses.replace's output
# ---------------------------------------------------------------------------

def test_resources_single_field():
    r = Resources(wood=3, food=5)
    expected = dataclasses.replace(r, wood=10)
    got = fast_replace(r, wood=10)
    assert got == expected
    assert got.wood == 10
    assert got.food == 5


def test_resources_multi_field():
    r = Resources(wood=3, food=5, grain=1)
    expected = dataclasses.replace(r, wood=10, food=0)
    got = fast_replace(r, wood=10, food=0)
    assert got == expected


def test_animals():
    a = Animals(sheep=2, boar=1)
    got = fast_replace(a, sheep=5)
    assert got == dataclasses.replace(a, sheep=5)


def test_cell():
    c = Cell()
    got = fast_replace(c, grain=3)
    assert got == dataclasses.replace(c, grain=3)


def test_action_space_state():
    sp = ActionSpaceState(workers=(0, 0), accumulated_amount=2)
    got = fast_replace(sp, workers=(1, 0))
    assert got == dataclasses.replace(sp, workers=(1, 0))
    assert got.accumulated_amount == 2


def test_player_state():
    state = setup(seed=0)
    p = state.players[0]
    got = fast_replace(p, people_home=1)
    assert got == dataclasses.replace(p, people_home=1)
    assert got.resources == p.resources  # untouched fields preserved


def test_farmyard():
    state = setup(seed=0)
    fy = state.players[0].farmyard
    new_grid = fy.grid  # same grid; just exercise replace shape
    got = fast_replace(fy, grid=new_grid)
    assert got == dataclasses.replace(fy, grid=new_grid)


def test_game_state_single_field():
    state = setup(seed=0)
    got = fast_replace(state, current_player=1 - state.current_player)
    expected = dataclasses.replace(state, current_player=1 - state.current_player)
    assert got == expected


def test_game_state_multi_field():
    state = setup(seed=0)
    other = 1 - state.current_player
    got = fast_replace(state, current_player=other, round_number=2)
    expected = dataclasses.replace(state, current_player=other, round_number=2)
    assert got == expected


def test_board_state():
    state = setup(seed=0)
    board = state.board
    got = fast_replace(board, round_card_order=board.round_card_order)
    assert got == board  # no actual change → equal


def test_pending_carries_init_fields():
    """Pendings have ClassVar PENDING_ID/TRIGGER_EVENT plus init instance
    fields. fast_replace must skip the ClassVars and only mutate instance fields.
    """
    p = PendingSow(player_idx=0, initiated_by_id="space:grain_utilization")
    got = fast_replace(p, player_idx=1)
    assert got == dataclasses.replace(p, player_idx=1)
    assert got.player_idx == 1
    assert got.initiated_by_id == "space:grain_utilization"


def test_no_changes_returns_equal():
    """fast_replace(obj) with no changes is equal to obj."""
    state = setup(seed=0)
    got = fast_replace(state)
    assert got == state


def test_does_not_mutate_input():
    """The original object is unmodified after fast_replace."""
    r = Resources(wood=3)
    before_wood = r.wood
    _ = fast_replace(r, wood=99)
    assert r.wood == before_wood


# ---------------------------------------------------------------------------
# End-to-end: setup state survives a fast_replace chain
# ---------------------------------------------------------------------------

def test_chained_replace_matches_stdlib():
    state = setup(seed=0)
    a = fast_replace(state, current_player=0)
    a = fast_replace(a, round_number=5)
    b = dataclasses.replace(state, current_player=0)
    b = dataclasses.replace(b, round_number=5)
    assert a == b
