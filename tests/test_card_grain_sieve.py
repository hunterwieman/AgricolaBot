"""Tests for Grain Sieve (minor improvement, D65; Dulcinaria; harvest-field hook).

Card text: "In the field phase of each harvest, if you harvest at least 2 grain,
you get 1 additional grain from the general supply."

The ordering subtlety (the heart of the card): the `harvest_field` hook fires in
`_resolve_harvest_field` BEFORE the mechanical crop take, while the grid is still
fully sown. The mechanical take removes EXACTLY ONE grain per grain-bearing field
this harvest, so the grain you "harvest" in the field phase equals the NUMBER of
grain-bearing FIELD cells — NOT the total grain on them. The eligibility test is
therefore ">= 2 FIELD cells with grain > 0":
  - one 3-grain field harvests only 1 grain -> NO bonus,
  - two 1-grain fields harvest 2 grain      -> +1 bonus grain.
"""
from __future__ import annotations

import agricola.cards.grain_sieve  # noqa: F401  (registers the card)

from agricola.cards.specs import MINORS, OCCUPATIONS
from agricola.cards.triggers import HARVEST_FIELD_CARDS, should_host_harvest_field
from agricola.constants import CellType, Phase
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_grid, with_phase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id="grain_sieve"):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _field_state(seed=0):
    """A HARVEST_FIELD-phase state (no card owned yet)."""
    return with_phase(setup(seed), Phase.HARVEST_FIELD)


def _grain_fields(state, idx, grain_per_field):
    """Plow + sow FIELD cells. grain_per_field is a dict {(r,c): grain}."""
    overrides = {
        rc: Cell(cell_type=CellType.FIELD, grain=g)
        for rc, g in grain_per_field.items()
    }
    return with_grid(state, idx, overrides)


def _run_field_phase(state):
    # Import here so the card module's registration (above) is already in place.
    from agricola.engine import _resolve_harvest_field
    return _resolve_harvest_field(state)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_grain_sieve_registered():
    assert "grain_sieve" in MINORS
    assert "grain_sieve" in HARVEST_FIELD_CARDS
    # It's a minor, not an occupation.
    assert "grain_sieve" not in OCCUPATIONS


def test_cost_is_one_wood():
    spec = MINORS["grain_sieve"]
    assert spec.cost.resources == Resources(wood=1)
    # No prereq / occupation bounds / passing / vps.
    assert spec.prereq is None
    assert spec.passing_left is False
    assert spec.vps == 0
    assert spec.min_occupations == 0


def test_on_play_is_noop():
    state = setup(0)
    before = state.players[0].resources
    after = MINORS["grain_sieve"].on_play(state, 0)
    assert after.players[0].resources == before
    assert after == state


# ---------------------------------------------------------------------------
# should_host_harvest_field — the card-dependent push gate
# ---------------------------------------------------------------------------

def test_no_host_without_card():
    assert should_host_harvest_field(setup(0)) is False


def test_host_when_owned():
    assert should_host_harvest_field(_own_minor(setup(0), 0)) is True


def test_no_host_when_only_in_hand():
    state = setup(0)
    p = state.players[0]
    p = fast_replace(p, hand_minors=p.hand_minors | {"grain_sieve"})
    state = fast_replace(state, players=(p, state.players[1]))
    assert should_host_harvest_field(state) is False


# ---------------------------------------------------------------------------
# Eligibility boundary: >= 2 grain-bearing FIELDS, counted as fields not grain
# ---------------------------------------------------------------------------

def test_two_grain_fields_grants_bonus():
    # Two separate 1-grain fields -> 2 grain harvested -> +1 bonus.
    state = _grain_fields(_own_minor(_field_state(), 0),
                          0, {(0, 0): 1, (0, 1): 1})
    g0 = state.players[0].resources.grain
    after = _run_field_phase(state)
    # +2 from the mechanical take (1 per field) +1 bonus from the sieve = +3.
    assert after.players[0].resources.grain == g0 + 3


def test_one_grain_field_no_bonus():
    # A single grain field harvests only 1 grain -> below threshold, no bonus.
    state = _grain_fields(_own_minor(_field_state(), 0), 0, {(0, 0): 1})
    g0 = state.players[0].resources.grain
    after = _run_field_phase(state)
    assert after.players[0].resources.grain == g0 + 1   # take only, no bonus


def test_single_field_with_three_grain_no_bonus():
    # The crux: ONE field sown to 3 grain harvests only 1 grain this phase
    # (count fields, not grain). No bonus, and the field keeps its other 2 grain.
    state = _grain_fields(_own_minor(_field_state(), 0), 0, {(0, 0): 3})
    g0 = state.players[0].resources.grain
    after = _run_field_phase(state)
    assert after.players[0].resources.grain == g0 + 1   # mechanical take only
    # The 3-grain field dropped to 2 (only 1 taken), confirming "harvest 1 grain".
    assert after.players[0].farmyard.grid[0][0].grain == 2


def test_three_grain_fields_still_only_one_bonus():
    # Threshold is "at least 2", the bonus is a flat +1 regardless of how many.
    state = _grain_fields(_own_minor(_field_state(), 0),
                          0, {(0, 0): 1, (0, 1): 1, (0, 2): 1})
    g0 = state.players[0].resources.grain
    after = _run_field_phase(state)
    # +3 from the take, +1 (not +3) bonus.
    assert after.players[0].resources.grain == g0 + 4


def test_no_grain_fields_no_bonus():
    state = _own_minor(_field_state(), 0)  # no fields
    g0 = state.players[0].resources.grain
    after = _run_field_phase(state)
    assert after.players[0].resources.grain == g0


def test_veg_fields_do_not_count():
    # Veg fields are not grain, so two veg fields don't reach the grain threshold.
    overrides = {
        (0, 0): Cell(cell_type=CellType.FIELD, veg=2),
        (0, 1): Cell(cell_type=CellType.FIELD, veg=2),
    }
    state = with_grid(_own_minor(_field_state(), 0), 0, overrides)
    g0 = state.players[0].resources.grain
    v0 = state.players[0].resources.veg
    after = _run_field_phase(state)
    assert after.players[0].resources.grain == g0   # no grain bonus
    assert after.players[0].resources.veg == v0 + 2  # veg still harvested


# ---------------------------------------------------------------------------
# Owner-gating: fires only for the owner
# ---------------------------------------------------------------------------

def test_fires_only_for_owner():
    # P0 owns the sieve and has 2 grain fields; P1 also has 2 grain fields but
    # no card -> only P0 gets the bonus.
    state = _own_minor(_field_state(), 0)
    state = _grain_fields(state, 0, {(0, 0): 1, (0, 1): 1})
    state = _grain_fields(state, 1, {(0, 0): 1, (0, 1): 1})
    g0 = state.players[0].resources.grain
    g1 = state.players[1].resources.grain
    after = _run_field_phase(state)
    assert after.players[0].resources.grain == g0 + 3   # take(2) + bonus(1)
    assert after.players[1].resources.grain == g1 + 2   # take only, no bonus


def test_owner_with_too_few_fields_gets_no_bonus_but_partner_does():
    # P0 owns the card but has only 1 grain field (no bonus); P1 owns it too with
    # 2 fields (bonus). Confirms per-player eligibility under a shared host frame.
    state = _own_minor(_own_minor(_field_state(), 0), 1)
    state = _grain_fields(state, 0, {(0, 0): 1})
    state = _grain_fields(state, 1, {(0, 0): 1, (0, 1): 1})
    g0 = state.players[0].resources.grain
    g1 = state.players[1].resources.grain
    after = _run_field_phase(state)
    assert after.players[0].resources.grain == g0 + 1   # take only
    assert after.players[1].resources.grain == g1 + 3   # take + bonus
