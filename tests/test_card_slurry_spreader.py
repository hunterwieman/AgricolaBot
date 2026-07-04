"""Tests for Slurry Spreader (occupation, A106; Artifex Expansion).

Card text: "In the field phase of each harvest, each time you take the last
grain/vegetable from a field, you also get 2 food/1 food."

A per-occasion harvest AUTO (`register_harvest_occasion_auto`) keyed on fields
BECOMING EMPTY during the field-phase take: it reads the take manifest and pays
+2 food per emptied `grain` entry and +1 food per emptied `veg` entry (the
per-entry `emptied` flag records "took the source's last crop"). Scoped on
`state.phase == Phase.HARVEST_FIELD` ("in the field phase of each harvest, each
time…" scopes the window — a card-granted extra harvest that empties a field in
the field phase counts too; a WORK-phase Bumper Crop take does not).

The harvest tests drive a real harvest through the walk (`_advance_until_decision`
over a `Phase.HARVEST_FIELD` state), including an emptied-field case, so the
occasion auto fires off the actual take manifest rather than a pre-take grid
snapshot.
"""
from __future__ import annotations

import agricola.cards.slurry_spreader  # noqa: F401  (registers the card)

from agricola.cards.harvest_windows import (
    HARVEST_OCCASION_AUTOS,
    apply_harvest_occasion_autos,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision
from agricola.pending import HarvestEntry, HarvestOccasion
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


def _harvest_state(seed=0, food=10):
    """A HARVEST_FIELD-phase state with both players fed (feeding painless)."""
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        state = fast_replace(state, players=tuple(
            fast_replace(state.players[i],
                         resources=fast_replace(state.players[i].resources, food=food))
            if i == idx else state.players[i] for i in range(2)))
    return state


def _run_field_phase(state):
    """Advance from HARVEST_FIELD until the field phase completes. Slurry Spreader
    is an occasion AUTO (no choice frame), so the take runs inline inside
    `_advance_until_decision`, which lands at the HARVEST_FEED feeding decision
    with the field-phase income applied and feeding food NOT yet spent."""
    state = _advance_until_decision(state)
    assert state.phase in (Phase.HARVEST_FEED, Phase.HARVEST_BREED,
                           Phase.PREPARATION, Phase.WORK), state.phase
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_slurry_spreader_registered():
    assert CARD_ID in OCCUPATIONS
    assert any(e.card_id == CARD_ID for e in HARVEST_OCCASION_AUTOS)
    assert OCCUPATIONS[CARD_ID].on_play is not None


def test_slurry_spreader_on_play_is_noop():
    state = setup(0)
    after = OCCUPATIONS[CARD_ID].on_play(state, 0)
    # No on-play effect: resources unchanged.
    assert after.players[0].resources == state.players[0].resources


# ---------------------------------------------------------------------------
# Last-grain / last-veg threshold — emptied fields (the core effect)
# ---------------------------------------------------------------------------

def test_last_grain_field_gives_2_food():
    """A 1-grain field: the take empties it -> +2 food."""
    state = _own_occ(_harvest_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    f0 = state.players[0].resources.food
    g0 = state.players[0].resources.grain
    after = _run_field_phase(state)
    assert after.players[0].resources.food == f0 + 2     # +2 food bonus
    assert after.players[0].resources.grain == g0 + 1    # mechanical take of the 1 grain
    assert after.players[0].farmyard.grid[0][0].grain == 0


def test_last_veg_field_gives_1_food():
    """A 1-veg field: the take empties it -> +1 food."""
    state = _own_occ(_harvest_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(1, 0): Cell(cell_type=CellType.FIELD, veg=1)})
    f0 = state.players[0].resources.food
    v0 = state.players[0].resources.veg
    after = _run_field_phase(state)
    assert after.players[0].resources.food == f0 + 1     # +1 food bonus
    assert after.players[0].resources.veg == v0 + 1       # mechanical take of the 1 veg


def test_multi_field_sums_grain_and_veg_bonuses():
    """Two emptied 1-grain fields (+2 each) and one emptied 1-veg field (+1)
    -> +5 food total."""
    state = _own_occ(_harvest_state(), 0, CARD_ID)
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=1),
        (0, 1): Cell(cell_type=CellType.FIELD, grain=1),
        (1, 0): Cell(cell_type=CellType.FIELD, veg=1),
    })
    f0 = state.players[0].resources.food
    after = _run_field_phase(state)
    assert after.players[0].resources.food == f0 + 2 + 2 + 1


# ---------------------------------------------------------------------------
# Eligibility boundaries — does NOT fire on a field that keeps a crop
# ---------------------------------------------------------------------------

def test_no_bonus_for_field_not_emptied():
    """A field with >1 crop keeps a crop after the take (not emptied) -> no bonus.
    (A fresh 3-grain field and a 2-grain field both survive the take.)"""
    state = _own_occ(_harvest_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])  # 3 grain
    state2 = with_grid(_own_occ(_harvest_state(), 0, CARD_ID), 0,
                       {(0, 0): Cell(cell_type=CellType.FIELD, grain=2)})
    for s in (state, state2):
        f0 = s.players[0].resources.food
        after = _run_field_phase(s)
        assert after.players[0].resources.food == f0   # not emptied -> no bonus


def test_no_bonus_for_empty_or_unsown_field():
    """An empty (already-harvested / never-sown) field has no crop to take, so the
    take emits no entry for it -> no bonus."""
    state = _own_occ(_harvest_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD)})  # empty
    f0 = state.players[0].resources.food
    after = _run_field_phase(state)
    assert after.players[0].resources.food == f0


def test_no_bonus_with_no_fields_at_all():
    state = _own_occ(_harvest_state(), 0, CARD_ID)
    f0 = state.players[0].resources.food
    after = _run_field_phase(state)
    assert after.players[0].resources.food == f0


def test_mixed_emptied_and_surviving_fields():
    """Only the emptied fields pay: a 1-grain field (+2) and a 1-veg field (+1)
    empty, while a 3-grain field survives -> +3 food total."""
    state = _own_occ(_harvest_state(), 0, CARD_ID)
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=1),   # empties -> +2
        (0, 1): Cell(cell_type=CellType.FIELD, grain=3),   # survives -> 0
        (1, 0): Cell(cell_type=CellType.FIELD, veg=1),     # empties -> +1
    })
    f0 = state.players[0].resources.food
    after = _run_field_phase(state)
    assert after.players[0].resources.food == f0 + 3
    assert after.players[0].farmyard.grid[0][1].grain == 2  # survivor depleted by 1


# ---------------------------------------------------------------------------
# emptied-flag semantics on the occasion manifest (direct)
# ---------------------------------------------------------------------------

def test_reads_emptied_flag_not_grain_count():
    """The reward keys on the manifest's `emptied` flag, not a grid count: a
    non-emptied entry pays nothing even at amount 1; an emptied one pays."""
    state = with_phase(_own_occ(setup(0), 0, CARD_ID), Phase.HARVEST_FIELD)
    occ = HarvestOccasion(source="take", entries=(
        HarvestEntry(source="cell:0,0", crop="grain", amount=1, emptied=False),
        HarvestEntry(source="cell:0,1", crop="grain", amount=1, emptied=True),
        HarvestEntry(source="cell:1,0", crop="veg", amount=1, emptied=True),
    ))
    f0 = state.players[0].resources.food
    after = apply_harvest_occasion_autos(state, 0, occ)
    assert after.players[0].resources.food == f0 + 2 + 1   # only the two emptied


def test_card_granted_field_phase_occasion_earns_food():
    """"in the field phase of each harvest, each time…" scopes the window, not the
    take: a card-granted extra harvest that empties a field DURING the field phase
    is still "taking the last crop from a field in the field phase" -> it counts."""
    state = with_phase(_own_occ(setup(0), 0, CARD_ID), Phase.HARVEST_FIELD)
    occ = HarvestOccasion(source="card:some_extra_harvest", entries=(
        HarvestEntry(source="cell:0,0", crop="grain", amount=1, emptied=True),
    ))
    f0 = state.players[0].resources.food
    after = apply_harvest_occasion_autos(state, 0, occ)
    assert after.players[0].resources.food == f0 + 2


def test_occasion_outside_field_phase_earns_nothing():
    """The phase gate models user ruling 4: a Bumper Crop take fires the field-phase
    EFFECT during WORK, not the field phase, so Slurry Spreader earns nothing."""
    state = _own_occ(setup(0), 0, CARD_ID)   # setup() is Phase.WORK
    occ = HarvestOccasion(source="take", entries=(
        HarvestEntry(source="cell:0,0", crop="grain", amount=1, emptied=True),
    ))
    f0 = state.players[0].resources.food
    after = apply_harvest_occasion_autos(state, 0, occ)
    assert after.players[0].resources.food == f0


# ---------------------------------------------------------------------------
# Owner-gating — fires only for the player who owns it
# ---------------------------------------------------------------------------

def test_fires_only_for_owner():
    state = _own_occ(_harvest_state(), 0, CARD_ID)   # P0 owns, P1 does not
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    state = with_grid(state, 1, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    f0, f1 = state.players[0].resources.food, state.players[1].resources.food
    after = _run_field_phase(state)
    assert after.players[0].resources.food == f0 + 2   # owner gets the bonus
    assert after.players[1].resources.food == f1       # non-owner unchanged


# ---------------------------------------------------------------------------
# Family byte-identity — no income without the card
# ---------------------------------------------------------------------------

def test_no_income_without_card():
    state = _harvest_state(seed=3)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    f0 = state.players[0].resources.food
    after = _run_field_phase(state)
    # Mechanical take only; no Slurry food.
    assert after.players[0].resources.food == f0
