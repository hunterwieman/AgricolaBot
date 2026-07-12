"""Tests for Raised Bed (minor improvement, E61; Ephipparius Expansion).

Card text: "At the start of each harvest, you get 4 food."

A harvest-window AUTO on window #2, `start_of_harvest`. Cost 2 Clay + 2 Stone,
1 VP, prerequisite "2 Grain Fields", kept. The income is UNCONDITIONAL (no "if"
clause): every harvest the owner gets a flat +4 food. The auto fires mechanically
inside the harvest walk (`_process_simple_window`, window-major, starting player
first) per owner — no frame. It never mutates the grid, so the mechanical take is
unaffected.

The harvest tests drive the real walk (`_advance_until_decision` + `step`, like
`tests/test_harvest_windows.py`); players are given ample food so feeding is
painless and the +4 bonus is isolated by comparison against a no-card baseline run.
"""
from __future__ import annotations

import agricola.cards.raised_bed  # noqa: F401  (registers the card)

import pytest

from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_grid, with_phase

CARD_ID = "raised_bed"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id=CARD_ID):
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
    return {(r, c): Cell(cell_type=CellType.FIELD, grain=3) for (r, c) in cells}


def _run_harvest(state, pick=lambda acts: acts[0]):
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        state = step(state, pick(legal_actions(state)))
    return state


def _food_after_harvest(state, idx):
    return _run_harvest(state).players[idx].resources.food


# ---------------------------------------------------------------------------
# Registration — spec fields vs the JSON (cost / VPs / prereq)
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("start_of_harvest", set())
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(clay=2, stone=2))  # 2 Clay, 2 Stone
    assert spec.cost_fn is None
    assert spec.vps == 1
    assert spec.passing_left is False
    # Prerequisite is a custom predicate (2 Grain Fields), not an occupation count.
    assert spec.prereq is not None
    assert spec.min_occupations == 0
    assert spec.max_occupations is None


# ---------------------------------------------------------------------------
# Prerequisite — "2 Grain Fields" (HAVE-check at play time)
# ---------------------------------------------------------------------------

def test_prereq_two_grain_fields_met():
    s = with_grid(setup(0), 0, _grain_cells((0, 0), (0, 1)))
    assert prereq_met(MINORS[CARD_ID], s, 0) is True


def test_prereq_one_grain_field_not_met():
    s = with_grid(setup(0), 0, _grain_cells((0, 0)))
    assert prereq_met(MINORS[CARD_ID], s, 0) is False


def test_prereq_veg_fields_do_not_count():
    veg = {(0, 0): Cell(cell_type=CellType.FIELD, veg=2),
           (0, 1): Cell(cell_type=CellType.FIELD, veg=2)}
    s = with_grid(setup(0), 0, veg)
    assert prereq_met(MINORS[CARD_ID], s, 0) is False


def _with_grain_card_field(state, cid, *, occupation=False):
    """Own the card-field `cid` (a minor, or an occupation for Patch
    Caregiver) holding 3 grain."""
    from agricola.cards.card_fields import stacks_to_store
    p = state.players[0]
    if occupation:
        p = fast_replace(p, occupations=p.occupations | {cid})
    else:
        p = fast_replace(p, minor_improvements=p.minor_improvements | {cid})
    p = fast_replace(p, card_state=stacks_to_store(p.card_state, cid, ((3, 0, 0, 0),)))
    return fast_replace(state, players=tuple(
        p if i == 0 else state.players[i] for i in range(2)))


def test_prereq_counts_grain_card_fields():
    """Ruling 45 (2026-07-12): a grain-holding card-field IS a grain field, so
    it joins the "2 Grain Fields" count. One grid grain field + one grain
    card-field reaches 2 (the old grid-only count saw 1); two grain
    card-fields — one minor, one occupation (Patch Caregiver) — reach 2 with
    zero grid fields; a veg card-field adds nothing."""
    from agricola.cards.card_fields import stacks_to_store
    # 1 grid + 1 card-field -> met.
    s = with_grid(setup(0), 0, _grain_cells((0, 0)))
    assert prereq_met(MINORS[CARD_ID], s, 0) is False       # 1 of 2
    s = _with_grain_card_field(s, "artichoke_field")
    assert prereq_met(MINORS[CARD_ID], s, 0) is True
    # 2 card-fields, zero grid fields (occupation ownership path included).
    s2 = _with_grain_card_field(setup(0), "artichoke_field")
    assert prereq_met(MINORS[CARD_ID], s2, 0) is False      # 1 of 2
    s2 = _with_grain_card_field(s2, "patch_caregiver", occupation=True)
    assert prereq_met(MINORS[CARD_ID], s2, 0) is True
    # A veg-holding Beanfield is not a grain field -> still 1 of 2.
    s3 = _with_grain_card_field(setup(0), "artichoke_field")
    p = s3.players[0]
    p = fast_replace(
        p,
        minor_improvements=p.minor_improvements | {"beanfield"},
        card_state=stacks_to_store(p.card_state, "beanfield", ((0, 2, 0, 0),)),
    )
    s3 = fast_replace(s3, players=tuple(
        p if i == 0 else s3.players[i] for i in range(2)))
    assert prereq_met(MINORS[CARD_ID], s3, 0) is False


# ---------------------------------------------------------------------------
# Start-of-harvest income (the core effect) — unconditional +4 food
# ---------------------------------------------------------------------------

def test_grants_four_food_at_start_of_harvest():
    base = _harvest_state()
    baseline = _food_after_harvest(base, 0)
    owned = _food_after_harvest(_own_minor(base, 0), 0)
    assert owned == baseline + 4


def test_income_is_unconditional_with_no_fields():
    """No grain fields at all — the income still fires (no 'if' condition)."""
    base = _harvest_state(seed=2)
    baseline = _food_after_harvest(base, 0)
    owned = _food_after_harvest(_own_minor(base, 0), 0)
    assert owned == baseline + 4


def test_income_is_flat_regardless_of_fields():
    """Many grain fields still grant exactly +4 food (not per-field)."""
    base = with_grid(_harvest_state(), 0,
                     _grain_cells((0, 0), (0, 1), (0, 2), (1, 0), (1, 1)))
    baseline = _food_after_harvest(base, 0)
    owned = _food_after_harvest(_own_minor(base, 0), 0)
    assert owned == baseline + 4


def test_never_mutates_the_grid():
    """The bonus credits food only; the mechanical take is identical with/without
    the card."""
    base = with_grid(_harvest_state(), 0, _grain_cells((0, 0), (0, 1), (0, 2)))
    baseline = _run_harvest(base)
    owned = _run_harvest(_own_minor(base, 0))
    assert owned.players[0].resources.grain == baseline.players[0].resources.grain
    assert owned.players[0].farmyard.grid[0][0].grain == \
        baseline.players[0].farmyard.grid[0][0].grain


# ---------------------------------------------------------------------------
# Owner-gating — fires only for the player who owns it
# ---------------------------------------------------------------------------

def test_fires_only_for_owner():
    base = _harvest_state()
    baseline = _run_harvest(base)
    owned = _run_harvest(_own_minor(base, 0))   # P0 owns, P1 does not
    assert owned.players[0].resources.food == baseline.players[0].resources.food + 4
    assert owned.players[1].resources.food == baseline.players[1].resources.food


# ---------------------------------------------------------------------------
# Does NOT fire outside the start_of_harvest window (e.g. not during feeding)
# ---------------------------------------------------------------------------

def test_fires_exactly_once_per_harvest():
    """Only one +4 across the whole harvest walk — not once per window."""
    base = _harvest_state()
    baseline = _food_after_harvest(base, 0)
    owned = _food_after_harvest(_own_minor(base, 0), 0)
    assert owned - baseline == 4  # exactly one fire, not 2+


# ---------------------------------------------------------------------------
# Direct effect-fn unit checks
# ---------------------------------------------------------------------------

def test_eligible_always_true():
    s = setup(0)
    assert agricola.cards.raised_bed._eligible(s, 0) is True


def test_apply_adds_four_food():
    s = setup(0)
    f0 = s.players[0].resources.food
    after = agricola.cards.raised_bed._apply(s, 0)
    assert after.players[0].resources.food == f0 + 4
    assert after.players[1].resources == s.players[1].resources


# ---------------------------------------------------------------------------
# Family fast path — no income without the card
# ---------------------------------------------------------------------------

def test_family_no_income_without_card():
    state = _harvest_state(seed=3)
    final = _run_harvest(state)
    assert final.phase == Phase.PREPARATION
    assert all(type(f).__name__ != "PendingHarvestWindow"
               for f in final.pending_stack)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
