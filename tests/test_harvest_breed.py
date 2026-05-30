"""Tests for the HARVEST_BREED resolution (Task 7).

Engine-level integration tests for PendingHarvestBreed legality enumeration
and CommitBreed effect. The underlying breeding_frontier helper is covered
exhaustively in tests/test_helpers.py; tests here focus on the pending/commit
plumbing.

breeding_frontier returns post-breed configurations and Pareto-filters
over animal counts only (food is a deterministic consequence, not a Pareto
dim — see ENGINE_IMPLEMENTATION.md §4.2, the optionality-bundling rule).
"""
from __future__ import annotations

import dataclasses

from agricola.actions import CommitBreed, Stop
from agricola.constants import CellType, HouseMaterial, Phase
from agricola.engine import _initiate_harvest_breed, step
from agricola.legality import legal_actions
from agricola.pasture import compute_pastures_from_arrays
from agricola.pending import PendingHarvestBreed
from agricola.resources import Animals, Resources
from agricola.setup import setup
from agricola.state import Cell, Farmyard, PlayerState

from tests.factories import (
    with_animals,
    with_majors,
    with_phase,
    with_resources,
)


# --- Helpers ----------------------------------------------------------------

def _harvest_breed_state(seed=0, *, sp=None):
    """Return a state at Phase.HARVEST_BREED with BREED pendings pushed
    (one per player, SP on top)."""
    state = setup(seed=seed)
    if sp is not None:
        state = dataclasses.replace(state, starting_player=sp)
    state = with_phase(state, Phase.HARVEST_BREED)
    state = _initiate_harvest_breed(state)
    return state


def _set_pasture_1x1(state, player_idx, row=0, col=0):
    """Add a 1x1 pasture enclosed at (row, col)."""
    p = state.players[player_idx]
    h = [list(r) for r in p.farmyard.horizontal_fences]
    v = [list(r) for r in p.farmyard.vertical_fences]
    h[row][col] = True
    h[row + 1][col] = True
    v[row][col] = True
    v[row][col + 1] = True
    new_h = tuple(tuple(r) for r in h)
    new_v = tuple(tuple(r) for r in v)
    new_pastures = compute_pastures_from_arrays(p.farmyard.grid, new_h, new_v)
    new_farmyard = Farmyard(
        grid=p.farmyard.grid,
        horizontal_fences=new_h,
        vertical_fences=new_v,
        pastures=new_pastures,
    )
    new_player = dataclasses.replace(p, farmyard=new_farmyard)
    new_players = list(state.players)
    new_players[player_idx] = new_player
    return dataclasses.replace(state, players=tuple(new_players))


# --- Push order -------------------------------------------------------------

def test_push_order_sp_on_top():
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=1)
    state = with_phase(state, Phase.HARVEST_BREED)
    state = _initiate_harvest_breed(state)
    assert state.pending_stack[-1].player_idx == 1
    assert state.pending_stack[0].player_idx == 0


def test_two_pendings_pushed_one_per_player():
    state = _harvest_breed_state(seed=0, sp=0)
    assert len(state.pending_stack) == 2
    assert all(isinstance(f, PendingHarvestBreed) for f in state.pending_stack)


# --- Trivial: no animals ----------------------------------------------------

def test_no_animals_trivial_commit_stop():
    """0 animals, no cooking. breeding_frontier returns [(Animals(0,0,0), 0)].
    Legal: [CommitBreed(0,0,0)]. After commit, only Stop."""
    state = _harvest_breed_state(seed=0, sp=0)
    actions = legal_actions(state)
    assert actions == [CommitBreed(sheep=0, boar=0, cattle=0)]

    state = step(state, CommitBreed(sheep=0, boar=0, cattle=0))
    assert legal_actions(state) == [Stop()]


# --- Single-type breeding ---------------------------------------------------

def test_single_type_breeding_sheep_no_cooking():
    """2 sheep + 2x1 pasture cap, no cooking. breeding_frontier = {(3,0,0): 0}."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_animals(state, 0, sheep=2)
    state = _set_pasture_1x1(state, 0, row=0, col=0)  # cap 2 + house pet 1 = 3
    state = with_phase(state, Phase.HARVEST_BREED)
    state = _initiate_harvest_breed(state)

    actions = legal_actions(state)
    breed_actions = [a for a in actions if isinstance(a, CommitBreed)]
    assert breed_actions == [CommitBreed(sheep=3, boar=0, cattle=0)]

    pre_food = state.players[0].resources.food
    state = step(state, breed_actions[0])
    assert state.players[0].animals == Animals(sheep=3, boar=0, cattle=0)
    # No food gained — no eating happened.
    assert state.players[0].resources.food == pre_food


def test_breed_chosen_gates_stop():
    """Stop is not legal before CommitBreed; only legal after."""
    state = _harvest_breed_state(seed=0, sp=0)
    actions = legal_actions(state)
    assert Stop() not in actions

    # Pick the trivial breed.
    state = step(state, CommitBreed(sheep=0, boar=0, cattle=0))
    assert legal_actions(state) == [Stop()]


# --- Multi-type breeding ----------------------------------------------------

def test_multi_type_breeding_two_1x1_two_sheep_two_boar():
    """Two 1x1 pastures + 2 sheep + 2 boar + Fireplace. Mirrors
    test_breeding_two_pastures_two_sheep_two_boar in test_helpers.py.

    Frontier: {(3,2,0): 0, (2,3,0): 0} — only one type's newborn can use
    the house pet slot.
    """
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_majors(state, owner_by_idx={0: 0})  # Fireplace
    state = with_animals(state, 0, sheep=2, boar=2)
    state = _set_pasture_1x1(state, 0, row=0, col=0)
    state = _set_pasture_1x1(state, 0, row=0, col=2)
    state = with_phase(state, Phase.HARVEST_BREED)
    state = _initiate_harvest_breed(state)

    actions = legal_actions(state)
    breed_actions = {(a.sheep, a.boar, a.cattle)
                     for a in actions if isinstance(a, CommitBreed)}
    assert breed_actions == {(3, 2, 0), (2, 3, 0)}


# --- Stop drives alternation ------------------------------------------------

def test_sp_stop_brings_other_player_to_top():
    state = _harvest_breed_state(seed=0, sp=1)
    # Player 1 commits + stops.
    state = step(state, CommitBreed(sheep=0, boar=0, cattle=0))
    state = step(state, Stop())
    # Player 0's frame is now on top.
    assert isinstance(state.pending_stack[-1], PendingHarvestBreed)
    assert state.pending_stack[-1].player_idx == 0


# --- Food gain on release-forced configs ------------------------------------

def test_capacity_constraint_forces_release_with_cooking():
    """3 sheep + 1x1 pasture (cap 3 with house pet) + Fireplace. Breeding
    to 4 sheep exceeds capacity. Frontier = [(3,0,0): 2] — the food formula's
    breed-fired branch fires because optimal pre-breed eating of 1 sheep
    keeps cap room for the newborn.
    """
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_majors(state, owner_by_idx={0: 0})  # Fireplace (sheep rate=2)
    state = with_animals(state, 0, sheep=3)
    state = _set_pasture_1x1(state, 0, row=0, col=0)  # cap 2 + house pet = 3
    state = with_phase(state, Phase.HARVEST_BREED)
    state = _initiate_harvest_breed(state)

    actions = legal_actions(state)
    breed_actions = [a for a in actions if isinstance(a, CommitBreed)]
    assert breed_actions == [CommitBreed(sheep=3, boar=0, cattle=0)]

    pre_food = state.players[0].resources.food
    state = step(state, breed_actions[0])
    # food_gained = 2 (eat 1 sheep at rate 2; breed fires; final sheep = 3).
    assert state.players[0].animals == Animals(sheep=3)
    assert state.players[0].resources.food == pre_food + 2
