"""Tests for Animal Driver (occupation, E147; Ephipparius Expansion).

Card text: "At the start of each harvest, if you have 1/2/3+ fenced stables, you
get 1 sheep/wild boar/cattle."

A `start_of_harvest` harvest-window AUTO granting a single tiered animal keyed to
the fenced-stable count (1->sheep, 2->boar, 3+->cattle) via grant_animals. Direct
tier tests use constructed pastures with `num_stables`; a real-harvest drive
confirms the timing.
"""
from __future__ import annotations

import agricola.cards.animal_driver  # noqa: F401  (registers the card)

import pytest

import agricola.cards.animal_driver as mod
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pasture import Pasture
from agricola.replace import fast_replace
from agricola.resources import Animals
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_phase

CARD_ID = "animal_driver"


def _own_occ(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _fenced_stables(state, idx, n):
    """Give player `idx` one pasture holding `n` fenced stables — a CONSISTENT
    farm: `n` grid cells are actual STABLE cells covered by the pasture, so
    `stables_built` matches the pasture's `num_stables` (else standalone-stable
    accounting goes negative and the harvest walk breaks)."""
    p = state.players[idx]
    cells = tuple((0, c) for c in range(max(n, 1)))
    stable_cells = frozenset(cells[:n])
    grid = tuple(
        tuple(Cell(cell_type=CellType.STABLE) if (r, c) in stable_cells
              else p.farmyard.grid[r][c] for c in range(5))
        for r in range(3))
    cap = 2 * len(cells) * (2 ** n)
    pasture = Pasture(cells=frozenset(cells), num_stables=n, capacity=cap)
    p = fast_replace(p, farmyard=fast_replace(p.farmyard, grid=grid, pastures=(pasture,)))
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


def _run_harvest(state, pick=lambda acts: acts[0]):
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED):
        state = step(state, pick(legal_actions(state)))
    return state


# --- Registration -----------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("start_of_harvest", set())
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("start_of_harvest", [])}


# --- Fenced-stable count + tier mapping (direct) ----------------------------

def test_fenced_stable_count():
    assert mod._fenced_stables(_fenced_stables(setup(0), 0, 2), 0) == 2
    assert mod._fenced_stables(setup(0), 0) == 0   # default farm: no pastures


def test_tier_mapping():
    assert mod._tier_animal(0) == Animals()
    assert mod._tier_animal(1) == Animals(sheep=1)
    assert mod._tier_animal(2) == Animals(boar=1)
    assert mod._tier_animal(3) == Animals(cattle=1)
    assert mod._tier_animal(5) == Animals(cattle=1)   # 3+ -> cattle


def test_eligible_needs_a_fenced_stable():
    assert mod._eligible(setup(0), 0) is False              # zero fenced stables
    assert mod._eligible(_fenced_stables(setup(0), 0, 1), 0) is True


def test_apply_grants_tier_animal():
    s = _fenced_stables(setup(0), 0, 2)   # 2 fenced stables -> 1 boar
    b0 = s.players[0].animals.boar
    after = mod._apply(s, 0)
    assert after.players[0].animals.boar == b0 + 1
    assert after.players[0].animals_need_accommodation  # routed via grant_animals


# --- The tier grant through the real harvest walk ---------------------------

def test_two_fenced_stables_grant_a_boar_in_harvest():
    base = _fenced_stables(_harvest_state(), 0, 2)   # -> 1 boar at start_of_harvest
    baseline = _run_harvest(base)
    owned = _run_harvest(_own_occ(base, 0, CARD_ID))
    assert owned.players[0].animals.boar == baseline.players[0].animals.boar + 1


def test_no_fenced_stables_no_grant():
    base = _harvest_state()                          # default farm: no fenced stables
    baseline = _run_harvest(base)
    owned = _run_harvest(_own_occ(base, 0, CARD_ID))
    assert owned.players[0].animals == baseline.players[0].animals


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
