"""Tests for Bale of Straw (minor improvement, D61; Dulcinaria Expansion).

Card text: "At the start of each harvest, if you have at least 3 grain fields
(including field cards with planted grain), you get 2 food."

A harvest-window AUTO on window #2, `start_of_harvest` (the window opening the
whole harvest, before the field phase). No cost, no VPs, kept. The auto fires
mechanically inside the harvest walk (`_process_simple_window`, window-major,
starting player first) per owner — no frame. At `start_of_harvest` the fields
are still fully sown (the field-phase take is window #5, later on the ladder),
so "you have at least 3 grain fields" is read on the still-sown grid (FIELD
cells with grain > 0). When the count is >= 3 the player gets a flat 2 food (not
per-field); below 3, nothing. The card never mutates the grid, so the mechanical
take is unaffected.

The harvest tests drive the real walk (`_advance_until_decision` + `step`, like
`tests/test_harvest_windows.py`) so the fire-at-start-of-harvest timing is
exercised end-to-end; players are given ample food so feeding is painless and
the +2 bonus is isolated by comparison against a no-card baseline run.
"""
from __future__ import annotations

import agricola.cards.bale_of_straw  # noqa: F401  (registers the card)

import pytest

from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import MINORS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_grid, with_phase

CARD_ID = "bale_of_straw"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id):
    """Put the (played) minor in player `idx`'s tableau."""
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _harvest_state(seed=0, food=10):
    """A HARVEST_FIELD-phase state with enough food that feeding is painless."""
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        state = fast_replace(state, players=tuple(
            fast_replace(state.players[i],
                         resources=fast_replace(state.players[i].resources, food=food))
            if i == idx else state.players[i] for i in range(2)))
    return state


def _grain_cells(*cells):
    """Override dict: each given (r, c) becomes a grain-sown FIELD cell."""
    return {(r, c): Cell(cell_type=CellType.FIELD, grain=3) for (r, c) in cells}


def _run_harvest(state, pick=lambda acts: acts[0]):
    """Drive the harvest to completion (into the next round's reveal)."""
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        state = step(state, pick(legal_actions(state)))
    return state


def _food_after_harvest(state, idx):
    """Owner idx's food once the whole harvest has resolved."""
    return _run_harvest(state).players[idx].resources.food


def _baseline_food(state, idx):
    """Owner idx's food after the same harvest WITHOUT owning the card — the
    reference against which the +2 bonus is measured (feeding subtracts the same
    in both runs)."""
    return _run_harvest(state).players[idx].resources.food


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("start_of_harvest", set())
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()            # free card
    assert spec.cost_fn is None
    assert spec.prereq is None
    assert spec.min_occupations == 0
    assert spec.max_occupations is None
    assert spec.passing_left is False
    assert spec.vps == 0


# ---------------------------------------------------------------------------
# Start-of-harvest income (the core effect)
# ---------------------------------------------------------------------------

def test_three_grain_fields_gives_two_food():
    """Exactly 3 grain-sown fields meets the threshold -> +2 food vs baseline."""
    base = with_grid(_harvest_state(), 0, _grain_cells((0, 0), (0, 1), (0, 2)))
    baseline = _baseline_food(base, 0)
    owned = _food_after_harvest(_own_minor(base, 0, CARD_ID), 0)
    assert owned == baseline + 2


def test_more_than_three_grain_fields_still_two_food():
    """The reward is a FLAT 2 food regardless of how many grain fields (not
    per-field): 5 grain fields still gives exactly +2 food."""
    base = with_grid(_harvest_state(), 0,
                     _grain_cells((0, 0), (0, 1), (0, 2), (1, 0), (1, 1)))
    baseline = _baseline_food(base, 0)
    owned = _food_after_harvest(_own_minor(base, 0, CARD_ID), 0)
    assert owned == baseline + 2


def test_fires_before_the_take_on_still_sown_grid():
    """The bonus is evaluated at start_of_harvest, BEFORE the field-phase crop
    take depletes the fields: with exactly 3 grain fields it fires (it does not
    see the post-take grid where one grain has been removed per field). The
    mechanical take is unaffected (1 grain/field -> +3 grain, cells depleted)."""
    base = with_grid(_harvest_state(), 0, _grain_cells((0, 0), (0, 1), (0, 2)))
    baseline = _run_harvest(base)
    owned = _run_harvest(_own_minor(base, 0, CARD_ID))
    # +2 food bonus over the no-card baseline.
    assert owned.players[0].resources.food == baseline.players[0].resources.food + 2
    # Same mechanical grain take in both runs (the bonus never mutates the grid).
    assert owned.players[0].resources.grain == baseline.players[0].resources.grain
    assert owned.players[0].farmyard.grid[0][0].grain == 2


# ---------------------------------------------------------------------------
# Eligibility boundaries — threshold of 3
# ---------------------------------------------------------------------------

def test_two_grain_fields_below_threshold_no_food():
    base = with_grid(_harvest_state(), 0, _grain_cells((0, 0), (0, 1)))
    baseline = _baseline_food(base, 0)
    owned = _food_after_harvest(_own_minor(base, 0, CARD_ID), 0)
    assert owned == baseline


def test_no_fields_at_all_no_food():
    base = _harvest_state()
    baseline = _baseline_food(base, 0)
    owned = _food_after_harvest(_own_minor(base, 0, CARD_ID), 0)
    assert owned == baseline


def test_veg_fields_do_not_count():
    """Vegetable-sown fields are not 'grain fields' — three veg fields do NOT
    meet the threshold."""
    veg = {
        (0, 0): Cell(cell_type=CellType.FIELD, veg=2),
        (0, 1): Cell(cell_type=CellType.FIELD, veg=2),
        (0, 2): Cell(cell_type=CellType.FIELD, veg=2),
    }
    base = with_grid(_harvest_state(), 0, veg)
    baseline = _baseline_food(base, 0)
    owned = _food_after_harvest(_own_minor(base, 0, CARD_ID), 0)
    assert owned == baseline


def test_empty_fields_do_not_count():
    """Plowed-but-unsown fields are not grain fields."""
    empty = {
        (0, 0): Cell(cell_type=CellType.FIELD),
        (0, 1): Cell(cell_type=CellType.FIELD),
        (0, 2): Cell(cell_type=CellType.FIELD),
    }
    base = with_grid(_harvest_state(), 0, empty)
    baseline = _baseline_food(base, 0)
    owned = _food_after_harvest(_own_minor(base, 0, CARD_ID), 0)
    assert owned == baseline


def test_mixed_two_grain_one_veg_below_threshold():
    """Only grain fields count: 2 grain + 1 veg = 2 grain fields -> no food."""
    mixed = {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 1): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 2): Cell(cell_type=CellType.FIELD, veg=2),
    }
    base = with_grid(_harvest_state(), 0, mixed)
    baseline = _baseline_food(base, 0)
    owned = _food_after_harvest(_own_minor(base, 0, CARD_ID), 0)
    assert owned == baseline


# ---------------------------------------------------------------------------
# Card-fields count as grain fields (ruling 45, 2026-07-12 — the card's own
# printed "(including field cards with planted grain)")
# ---------------------------------------------------------------------------

def _own_card_field(state, idx, cid, stacks, *, occupation=False):
    """Give player `idx` the card-field `cid` holding `stacks` — the
    tests/test_card_fields_seam.py idiom."""
    from agricola.cards.card_fields import stacks_to_store
    p = state.players[idx]
    if occupation:
        p = fast_replace(p, occupations=p.occupations | {cid})
    else:
        p = fast_replace(p, minor_improvements=p.minor_improvements | {cid})
    p = fast_replace(p, card_state=stacks_to_store(p.card_state, cid, stacks))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def test_grain_card_field_completes_threshold_in_real_harvest():
    """Ruling 45 (2026-07-12) — and the card's own parenthetical "(including
    field cards with planted grain)": 2 grid grain fields + a grain-holding
    card-field = 3 grain fields, so the threshold is crossed ONLY via the
    card-field and the +2 food lands in the real harvest walk. Both runs own
    the card-field (Patch Caregiver: 1 stack, no harvest hooks of its own);
    only Bale of Straw ownership differs."""
    import agricola.cards.patch_caregiver  # noqa: F401  (registers the card-field)
    base = with_grid(_harvest_state(), 0, _grain_cells((0, 0), (0, 1)))
    base = _own_card_field(base, 0, "patch_caregiver", [(3, 0, 0, 0)],
                           occupation=True)
    baseline = _baseline_food(base, 0)
    owned = _food_after_harvest(_own_minor(base, 0, CARD_ID), 0)
    assert owned == baseline + 2


def test_wood_planted_card_field_is_not_a_grain_field():
    """A wood-planted Wood Field is NOT a grain field (the count is per-good):
    2 grid grain fields + a wood-holding Wood Field stays below the threshold
    -> no food, driven through the real harvest walk."""
    import agricola.cards.wood_field  # noqa: F401  (registers the card-field)
    base = with_grid(_harvest_state(), 0, _grain_cells((0, 0), (0, 1)))
    base = _own_card_field(base, 0, "wood_field", [(0, 0, 3, 0), (0, 0, 0, 0)])
    baseline = _baseline_food(base, 0)
    owned = _food_after_harvest(_own_minor(base, 0, CARD_ID), 0)
    assert owned == baseline


# ---------------------------------------------------------------------------
# Owner-gating — fires only for the player who owns it
# ---------------------------------------------------------------------------

def test_fires_only_for_owner():
    base = with_grid(_harvest_state(), 0, _grain_cells((0, 0), (0, 1), (0, 2)))
    base = with_grid(base, 1, _grain_cells((0, 0), (0, 1), (0, 2)))
    baseline = _run_harvest(base)
    owned = _run_harvest(_own_minor(base, 0, CARD_ID))   # P0 owns, P1 does not
    assert owned.players[0].resources.food == baseline.players[0].resources.food + 2
    assert owned.players[1].resources.food == baseline.players[1].resources.food


# ---------------------------------------------------------------------------
# Direct effect-fn unit checks (eligibility / apply in isolation)
# ---------------------------------------------------------------------------

def test_eligible_predicate():
    state = setup(0)
    state = with_grid(state, 0, _grain_cells((0, 0), (0, 1)))
    assert agricola.cards.bale_of_straw._eligible(state, 0) is False
    state = with_grid(state, 0, _grain_cells((0, 0), (0, 1), (0, 2)))
    assert agricola.cards.bale_of_straw._eligible(state, 0) is True


def test_apply_adds_two_food():
    state = setup(0)
    f0 = state.players[0].resources.food
    after = agricola.cards.bale_of_straw._apply(state, 0)
    assert after.players[0].resources.food == f0 + 2
    # Only the acting player changes.
    assert after.players[1].resources == state.players[1].resources


# ---------------------------------------------------------------------------
# Family fast path — no window frame, no income without the card
# ---------------------------------------------------------------------------

def test_family_no_frame_no_income_without_card():
    state = with_grid(_harvest_state(seed=3), 0, _grain_cells((0, 0), (0, 1), (0, 2)))
    final = _run_harvest(state)
    # Harvest resolved to the next round's PREPARATION, no lingering window frame,
    # and no Bale-of-Straw food (nobody owns it -> the auto never registered a fire).
    assert final.phase == Phase.PREPARATION
    assert all(type(f).__name__ != "PendingHarvestWindow"
               for f in final.pending_stack)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
