"""Tests for the field-phase harvest cards:
Scythe Worker, Butter Churn, Three-Field Rotation, Loom.

All fire in the field phase, through three different seams:

- **Scythe Worker** harvests extra grain FROM its owner's grain fields as part
  of the one take event (user ruling 11, 2026-07-05: all field-phase harvesting
  is simultaneous), so it is an AUTO take-modifier fold-in
  (`register_take_modifier`, no variants): `resolution.field_take` applies its
  +1-per-≥2-grain-field extras with the base take, and the take occasion's
  manifest carries the combined amounts. Outcomes are identical to its earlier
  pre-take-auto form (the effect tests below survived the migration unchanged).
- **Loom and Butter Churn** are flat state-readers (they read the owner's own
  animals, not what the take harvested), so they ride the "field_phase"
  during-window auto (HARVEST_WINDOWS_DESIGN.md §4d): fired pre-take by
  `engine._field_phase_step` via `apply_auto_effects("field_phase", …)`, once
  per player per harvest.
- **Three-Field Rotation** rides the start_of_field_phase window (its printed
  timing).

The legacy `harvest_field` hook was RETIRED 2026-07-05 (its last cards — lynchet,
wood_rake — migrated to the window machinery). With no harvest card owned the
field resolution is byte-identical to the Family game (a
`test_harvest_field_byte_identical` guard below).

Most tests drive `_resolve_harvest_field` (the compat alias into the harvest-window
walk at HARVEST_FIELD, which fires the "field_phase" window autos pre-take) so the
firing-before-the-take ordering is exercised end-to-end; Scythe Worker's on-play +1 grain is checked through its
OccupationSpec, and Loom's scoring term through `score`.
"""
from __future__ import annotations

import numpy as np

from agricola.agents.base import decider_of
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import MINORS, OCCUPATIONS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, _resolve_harvest_field, step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.scoring import score
from agricola.setup import setup, setup_env
from agricola.state import Cell
from tests.test_utils import filter_implemented

from tests.factories import (
    with_animals,
    with_grid,
    with_phase,
    with_sown_fields,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _field_state(seed=0):
    """A HARVEST_FIELD-phase state with both hands dropped (no card owned yet)."""
    state = setup(seed)
    state = with_phase(state, Phase.HARVEST_FIELD)
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_category6_cards_registered():
    assert "scythe_worker" in OCCUPATIONS
    for cid in ("loom", "butter_churn", "three_field_rotation"):
        assert cid in MINORS
    # scythe_worker rides the take-modifier fold-in seam (user ruling 11,
    # 2026-07-05: all field-phase harvesting is one simultaneous event — its
    # extra grain folds INTO the take, as an AUTO modifier with no variants).
    # The legacy harvest-field hook is fully RETIRED (2026-07-05): lynchet went
    # to the take-occasion autos and wood_rake to window #1.
    from agricola.cards.harvest_windows import TAKE_MODIFIERS
    sw = next(e for e in TAKE_MODIFIERS if e.card_id == "scythe_worker")
    assert sw.variants_fn is None            # an auto fold-in, no choice
    # Loom and Butter Churn are flat state-readers (they read the owner's own
    # animals, not what the take harvested) on the "field_phase" during-window
    # auto (their printed timing, "in the field phase of each harvest").
    assert {"loom", "butter_churn"} <= HARVEST_WINDOW_CARDS.get("field_phase", set())
    # Three-Field Rotation rides the start_of_field_phase harvest window (its
    # printed timing, "at the start of the field phase of each harvest").
    assert "three_field_rotation" in HARVEST_WINDOW_CARDS.get(
        "start_of_field_phase", set())
    # Printed VPs (verbatim from JSON): Loom 1, Butter Churn 1, Three-Field 0.
    assert MINORS["loom"].vps == 1
    assert MINORS["butter_churn"].vps == 1
    assert MINORS["three_field_rotation"].vps == 0
    # Prerequisites: Loom ≥2 occ, Butter Churn ≤3 occ, Three-Field ≥3 occ.
    assert MINORS["loom"].min_occupations == 2
    assert MINORS["butter_churn"].max_occupations == 3
    assert MINORS["three_field_rotation"].min_occupations == 3


# ---------------------------------------------------------------------------
# Family byte-identity — the load-bearing invariant
# ---------------------------------------------------------------------------

def test_harvest_field_byte_identical_without_card():
    """With no harvest-field card owned, _resolve_harvest_field is byte-identical
    whether or not the card system is loaded — the frame is never pushed."""
    state = _field_state(seed=3)
    state = with_sown_fields(state, 0, grain_fields=[(0, 2)], veg_fields=[(1, 3)])
    state = with_sown_fields(state, 1, grain_fields=[(0, 1)])
    before = state
    after = _resolve_harvest_field(state)
    # Mechanical take only: P0 +1 grain +1 veg, P1 +1 grain. No card income.
    assert after.players[0].resources.grain == before.players[0].resources.grain + 1
    assert after.players[0].resources.veg == before.players[0].resources.veg + 1
    assert after.players[1].resources.grain == before.players[1].resources.grain + 1
    assert after.players[0].resources.food == before.players[0].resources.food
    assert after.phase == Phase.HARVEST_FEED
    # Only the FEED frames are on the returned stack — no field-phase frame.
    assert all(type(f).__name__ == "PendingHarvestFeed" for f in after.pending_stack)


# ---------------------------------------------------------------------------
# Loom — 1/2/3 food at ≥1/4/7 sheep + scoring term
# ---------------------------------------------------------------------------

def test_loom_food_tiers():
    for sheep, expected in [(0, 0), (1, 1), (3, 1), (4, 2), (6, 2), (7, 3), (10, 3)]:
        state = _own_minor(_field_state(), 0, "loom")
        state = with_animals(state, 0, sheep=sheep)
        food0 = state.players[0].resources.food
        after = _resolve_harvest_field(state)
        assert after.players[0].resources.food == food0 + expected, f"sheep={sheep}"


def test_loom_scoring_one_bonus_per_three_sheep():
    state = _own_minor(setup(0), 0, "loom")
    state = with_animals(state, 0, sheep=7)
    state = with_phase(state, Phase.BEFORE_SCORING)
    total, breakdown = score(state, 0)
    # 7 // 3 = 2 bonus points from the scoring term, plus the printed 1 VP.
    # Compare against the same state without the card.
    base_state = with_phase(with_animals(setup(0), 0, sheep=7), Phase.BEFORE_SCORING)
    base_total, _ = score(base_state, 0)
    assert total == base_total + 2 + 1   # +2 scoring term, +1 printed VP


def test_loom_fires_only_for_its_owner():
    state = _own_minor(_field_state(), 0, "loom")
    state = with_animals(state, 0, sheep=5)
    state = with_animals(state, 1, sheep=5)   # P1 does NOT own Loom
    f0, f1 = state.players[0].resources.food, state.players[1].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0 + 2   # owner gets tier-2
    assert after.players[1].resources.food == f1       # non-owner unchanged


# ---------------------------------------------------------------------------
# Butter Churn — 1 food per 3 sheep + 1 food per 2 cattle
# ---------------------------------------------------------------------------

def test_butter_churn_food_from_sheep_and_cattle():
    for sheep, cattle, expected in [
        (0, 0, 0), (3, 0, 1), (2, 0, 0), (0, 2, 1), (6, 4, 2 + 2), (5, 3, 1 + 1),
    ]:
        state = _own_minor(_field_state(), 0, "butter_churn")
        state = with_animals(state, 0, sheep=sheep, cattle=cattle)
        food0 = state.players[0].resources.food
        after = _resolve_harvest_field(state)
        assert after.players[0].resources.food == food0 + expected, \
            f"sheep={sheep} cattle={cattle}"


# ---------------------------------------------------------------------------
# Three-Field Rotation — 3 food with a grain + veg + empty field
# ---------------------------------------------------------------------------

# Three-Field Rotation MIGRATED off the legacy harvest-field hook onto the
# start_of_field_phase harvest window (#4 — its printed timing, "at the start of
# the field phase of each harvest"). That window is inside the per-player FIELD
# segment and fires BEFORE the field-phase crop take (window #5), so eligibility
# still reads the fields while sown — same instant the old hook saw. These tests
# drive the real harvest walk and measure the +3 food as a delta over a no-card
# baseline run (feeding subtracts the same in both).

def _tfr_harvest_state(seed=0, food=10):
    """A HARVEST_FIELD-phase state with ample food so feeding is painless."""
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        state = fast_replace(state, players=tuple(
            fast_replace(state.players[i],
                         resources=fast_replace(state.players[i].resources, food=food))
            if i == idx else state.players[i] for i in range(2)))
    return state


def _run_harvest(state):
    """Drive the harvest to completion (into the next round's reveal)."""
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        state = step(state, legal_actions(state)[0])
    return state


def test_three_field_rotation_fires_with_all_three_field_kinds():
    # A grain field, a veg field, and an empty field.
    base = with_sown_fields(_tfr_harvest_state(), 0,
                            grain_fields=[(0, 2)], veg_fields=[(0, 3)])
    base = with_grid(base, 0, {(0, 4): Cell(cell_type=CellType.FIELD)})  # empty
    baseline = _run_harvest(base).players[0].resources.food
    owned = _run_harvest(
        _own_minor(base, 0, "three_field_rotation")).players[0].resources.food
    assert owned == baseline + 3


def test_three_field_rotation_no_fire_missing_empty_field():
    # Grain + veg field, but NO empty field.
    base = with_sown_fields(_tfr_harvest_state(), 0,
                            grain_fields=[(0, 2)], veg_fields=[(0, 3)])
    baseline = _run_harvest(base).players[0].resources.food
    owned = _run_harvest(
        _own_minor(base, 0, "three_field_rotation")).players[0].resources.food
    assert owned == baseline   # condition unmet


def test_three_field_rotation_no_fire_missing_veg_field():
    base = with_sown_fields(_tfr_harvest_state(), 0, grain_fields=[(0, 2)])
    base = with_grid(base, 0, {(0, 3): Cell(cell_type=CellType.FIELD)})  # empty
    baseline = _run_harvest(base).players[0].resources.food
    owned = _run_harvest(
        _own_minor(base, 0, "three_field_rotation")).players[0].resources.food
    assert owned == baseline


# ---------------------------------------------------------------------------
# Scythe Worker — on-play +1 grain + 1 extra grain per grain field
# ---------------------------------------------------------------------------

def test_scythe_worker_on_play_grain():
    state = setup(0)
    grain0 = state.players[0].resources.grain
    after = OCCUPATIONS["scythe_worker"].on_play(state, 0)
    assert after.players[0].resources.grain == grain0 + 1


def test_scythe_worker_extra_grain_per_grain_field():
    state = _own_occ(_field_state(), 0, "scythe_worker")
    # Two grain fields (3 grain each) + one veg field. Scythe takes 1 ADDITIONAL
    # grain FROM each grain field (+2 grain, each field -1), then the mechanical
    # take removes another 1 grain from each (+2 grain) and 1 veg from the veg
    # field (+1). So each grain field is depleted by 2 this harvest: 3 -> 1.
    state = with_sown_fields(state, 0, grain_fields=[(0, 2), (0, 3)],
                             veg_fields=[(1, 2)])
    grain0 = state.players[0].resources.grain
    veg0 = state.players[0].resources.veg
    after = _resolve_harvest_field(state)
    # Scythe: +2 (one per >=2-grain field). Take: +2 grain, +1 veg.
    assert after.players[0].resources.grain == grain0 + 2 + 2
    assert after.players[0].resources.veg == veg0 + 1
    # Each grain field is depleted by 2 (the additional + the mechanical take):
    # 3 -> 1. (Regression: previously the field lost only 1 — duplicated grain.)
    assert after.players[0].farmyard.grid[0][2].grain == 1
    assert after.players[0].farmyard.grid[0][3].grain == 1


def test_scythe_worker_caps_additional_at_field_grain():
    """The additional grain only comes from a field with >= 2 grain. A 1-grain
    field gives its single grain to the mechanical take with none to spare, and a
    2-grain field is fully exhausted (1 additional + 1 take = 2)."""
    state = _own_occ(_field_state(), 0, "scythe_worker")
    # One 1-grain field at (0,2), one 2-grain field at (0,3).
    state = with_grid(state, 0, {
        (0, 2): Cell(cell_type=CellType.FIELD, grain=1),
        (0, 3): Cell(cell_type=CellType.FIELD, grain=2),
    })
    grain0 = state.players[0].resources.grain
    after = _resolve_harvest_field(state)
    # 1-grain field: 1 total (no additional). 2-grain field: 2 total (1 additional
    # + 1 take). Supply gains 1 + 2 = 3.
    assert after.players[0].resources.grain == grain0 + 3
    assert after.players[0].farmyard.grid[0][2].grain == 0   # 1-grain field emptied
    assert after.players[0].farmyard.grid[0][3].grain == 0   # 2-grain field exhausted


def test_scythe_worker_no_extra_without_grain_fields():
    state = _own_occ(_field_state(), 0, "scythe_worker")
    state = with_sown_fields(state, 0, veg_fields=[(1, 2)])   # veg only
    grain0 = state.players[0].resources.grain
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.grain == grain0   # no grain field -> no extra


# ---------------------------------------------------------------------------
# Two harvest-field cards on opposite players fire independently
# ---------------------------------------------------------------------------

def test_full_family_game_never_pushes_field_phase_frame():
    """A complete Family game (no card owned) drives all six harvests without ever
    constructing a card-only field-phase frame (PendingFieldPhase /
    PendingHarvestWindow) — the card-dependent push keeps the Family field phase
    byte-identical (the C++ Family gate's invariant)."""
    from agricola.pending import PendingFieldPhase, PendingHarvestWindow
    state, env = setup_env(seed=7)
    rng = np.random.default_rng(7)
    saw_field_phase = 0
    while state.phase != Phase.BEFORE_SCORING:
        # No card-only harvest frame may ever appear on a Family game's stack.
        assert all(not isinstance(f, (PendingFieldPhase, PendingHarvestWindow))
                   for f in state.pending_stack)
        if state.phase == Phase.HARVEST_FEED:
            saw_field_phase += 1   # FEED follows a resolved FIELD phase
        d = decider_of(state)
        if d is None:
            action = env.resolve(state)
        else:
            actions = filter_implemented(legal_actions(state))
            action = actions[int(rng.integers(len(actions)))]
        state = step(state, action)
    # Six harvests over the 14 rounds — each produced a FEED phase.
    assert saw_field_phase >= 1


def test_both_players_harvest_field_cards_fire():
    state = _field_state()
    state = _own_minor(state, 0, "loom")
    state = _own_minor(state, 1, "butter_churn")
    state = with_animals(state, 0, sheep=4)        # Loom tier-2 -> +2 food
    state = with_animals(state, 1, sheep=3, cattle=2)  # Butter: 1 + 1 -> +2 food
    f0, f1 = state.players[0].resources.food, state.players[1].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0 + 2
    assert after.players[1].resources.food == f1 + 2
