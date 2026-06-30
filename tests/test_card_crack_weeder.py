"""Tests for Crack Weeder (minor improvement, B58; Bubulcus Expansion).

Card text: "When you play this card, you immediately get 1 food. For each
vegetable you take from a field in the field phase of a harvest, you also get
1 food."

A Category-2 on-play (+1 food) + Category-6 harvest-field hook. The field-phase
hook (`_resolve_harvest_field` / `_fire_harvest_field_hook`) fires for each
owner BEFORE the mechanical "take 1 crop per field" runs, but only when some
player owns a harvest-field card (`should_host_harvest_field`). At fire time the
fields are still fully sown, so a veg-sown field (veg > 0) is exactly a field
the mechanical take will harvest a vegetable from this harvest: +1 food per such
field. Unlike Scythe Worker, Crack Weeder does NOT take extra crops — it only
adds food and never mutates the grid (so it must not deplete the fields).

The harvest tests drive `_resolve_harvest_field` directly (like
`tests/test_harvest_field.py` and `tests/test_card_slurry_spreader.py`) so the
firing-before-the-take ordering is exercised end-to-end; the on-play test drives
a real PendingPlayMinor -> CommitPlayMinor engine flow.
"""
from __future__ import annotations

import agricola.cards.crack_weeder  # noqa: F401  (registers the card)

import pytest

from agricola.cards.specs import MINORS
from agricola.cards.triggers import (
    HARVEST_FIELD_CARDS,
    should_host_harvest_field,
)
from agricola.constants import CellType, Phase
from agricola.engine import _resolve_harvest_field, step
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell

from tests.factories import with_grid, with_pending_stack, with_phase
from tests.test_utils import sole_play_minor

CARD_ID = "crack_weeder"


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


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_crack_weeder_registered():
    assert CARD_ID in MINORS
    assert CARD_ID in HARVEST_FIELD_CARDS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.prereq is None
    assert spec.passing_left is False
    assert spec.vps == 0


# ---------------------------------------------------------------------------
# On-play: immediate +1 food (driven through a real play-minor engine flow)
# ---------------------------------------------------------------------------

def test_on_play_gives_one_food_via_engine():
    pool = CardPool(occupations=tuple(f"o{i}" for i in range(20)),
                    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)))
    cs, _env = setup_env(5, card_pool=pool)
    cp = cs.current_player
    # Give the active player the card in hand + the 1 wood it costs.
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({CARD_ID}),
                     resources=Resources(wood=1))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp,
                              initiated_by_id="space:meeting_place_cards"),))

    f0 = cs.players[cp].resources.food
    w0 = cs.players[cp].resources.wood
    cs = step(cs, sole_play_minor(cs, CARD_ID))

    after = cs.players[cp]
    assert after.resources.food == f0 + 1          # immediate +1 food
    assert after.resources.wood == w0 - 1          # 1 wood cost paid
    assert CARD_ID in after.minor_improvements     # kept in tableau (not passing)


def test_on_play_spec_fn_directly():
    state = setup(0)
    f0 = state.players[0].resources.food
    after = MINORS[CARD_ID].on_play(state, 0)
    assert after.players[0].resources.food == f0 + 1


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

def test_single_veg_field_gives_one_food():
    """A veg-sown field yields +1 food (and the mechanical take removes 1 veg)."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, veg=1)})
    f0 = state.players[0].resources.food
    v0 = state.players[0].resources.veg
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0 + 1     # +1 food bonus
    assert after.players[0].resources.veg == v0 + 1      # mechanical take of the veg
    assert after.players[0].farmyard.grid[0][0].veg == 0


def test_multi_veg_field_still_only_one_food():
    """A 2-veg field yields only ONE vegetable per harvest -> +1 food (not +2),
    and the grid is depleted by exactly 1 (no double-take by this card)."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, veg=2)})
    f0 = state.players[0].resources.food
    v0 = state.players[0].resources.veg
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0 + 1     # one vegetable -> +1 food
    assert after.players[0].resources.veg == v0 + 1      # only 1 veg taken
    assert after.players[0].farmyard.grid[0][0].veg == 1  # 2 -> 1, not 2 -> 0


def test_multiple_veg_fields_sum():
    """Three veg-sown fields -> +3 food."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, veg=1),
        (0, 1): Cell(cell_type=CellType.FIELD, veg=2),
        (1, 0): Cell(cell_type=CellType.FIELD, veg=1),
    })
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0 + 3


# ---------------------------------------------------------------------------
# Eligibility boundaries — only vegetable takes earn food
# ---------------------------------------------------------------------------

def test_grain_field_gives_no_food():
    """A grain-sown field has its grain (not a vegetable) taken -> no food."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=3)})
    f0 = state.players[0].resources.food
    g0 = state.players[0].resources.grain
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0          # no food bonus
    assert after.players[0].resources.grain == g0 + 1     # mechanical grain take


def test_empty_or_unsown_field_gives_no_food():
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD)})  # empty
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0


def test_no_fields_at_all_gives_no_food():
    state = _own_minor(_field_state(), 0, CARD_ID)
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0


# ---------------------------------------------------------------------------
# Owner-gating — fires only for the player who owns it
# ---------------------------------------------------------------------------

def test_fires_only_for_owner():
    state = _own_minor(_field_state(), 0, CARD_ID)   # P0 owns, P1 does not
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, veg=1)})
    state = with_grid(state, 1, {(0, 0): Cell(cell_type=CellType.FIELD, veg=1)})
    f0, f1 = state.players[0].resources.food, state.players[1].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0 + 1   # owner gets the bonus
    assert after.players[1].resources.food == f1       # non-owner unchanged


# ---------------------------------------------------------------------------
# Does not take extra crop (vs Scythe Worker) — grid only depleted by the take
# ---------------------------------------------------------------------------

def test_does_not_double_deplete_fields():
    """Crack Weeder adds food but takes NO crop itself: a 2-veg field ends at
    1 veg (the single mechanical take), never 0."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, veg=2)})
    after = _resolve_harvest_field(state)
    assert after.players[0].farmyard.grid[0][0].veg == 1


# ---------------------------------------------------------------------------
# Family byte-identity — no frame, no income without the card
# ---------------------------------------------------------------------------

def test_byte_identical_without_card():
    state = _field_state(seed=3)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, veg=1)})
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    # Mechanical take only; no Crack Weeder food, no lingering frame.
    assert after.players[0].resources.food == f0
    assert after.phase == Phase.HARVEST_FEED
    assert all(type(f).__name__ != "PendingHarvestField" for f in after.pending_stack)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
