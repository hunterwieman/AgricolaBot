"""Tests for Wood Rake (minor improvement, D32; Dulcinaria Expansion).

Card text: "During scoring, if you had at least 7 goods in your fields before the
final harvest, you get 2 bonus points."

A window-#1 (`immediately_before_harvest`, round-14-gated) automatic snapshot
feeding a banked Category-1 scoring term — MIGRATED 2026-07-05 off the legacy
pre-take `harvest_field` seam: "before the final harvest" precedes every
in-harvest effect (Straw Manure's #3 vegetable adds no longer count toward the
threshold, per the print). The 2 points are BANKED in the CardStore at the
round-14 window (the qualifying field state is gone by scoring time) and read
back by the scoring term.

These tests drive `_resolve_harvest_field` (the compat alias into the harvest
walk, which opens at window #1) so the fire-before-the-harvest ordering and the
round-14-only gate are exercised end-to-end.
"""
from __future__ import annotations

import agricola.cards.wood_rake  # noqa: F401  (registers the card)
import agricola.cards.beanfield  # noqa: F401  (registers the card-fields below)
import agricola.cards.rock_garden  # noqa: F401
import agricola.cards.wood_field  # noqa: F401

from agricola.cards.card_fields import stacks_to_store
from agricola.cards.specs import MINORS
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.constants import CellType, Phase
from agricola.engine import _resolve_harvest_field
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import score
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_grid, with_phase, with_round

CARD_ID = "wood_rake"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _final_harvest_state(seed=0):
    """A HARVEST_FIELD-phase state at the FINAL harvest (round 14)."""
    return with_round(with_phase(setup(seed), Phase.HARVEST_FIELD), 14)


def _seven_grain_fields(state, idx):
    """Sow 7 grain across FIELD cells of player `idx` (>= the 7-goods threshold).
    Uses three fields holding 3/3/1 grain = 7 total."""
    return with_grid(state, idx, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 1): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 2): Cell(cell_type=CellType.FIELD, grain=1),
    })


def _banked(state, idx):
    return state.players[idx].card_state.get(CARD_ID, 0)


def _set_stacks(state, idx, cid, stacks):
    """Write a card-field's per-stack (grain, veg, wood, stone) contents."""
    p = state.players[idx]
    p = fast_replace(p, card_state=stacks_to_store(p.card_state, cid, stacks))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_wood_rake_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.prereq is None
    assert spec.passing_left is False
    # The 2 points are conditional and banked, NOT a printed vps.
    assert spec.vps == 0
    # Window #1 membership — OFF the legacy harvest-field hook (2026-07-05).
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("immediately_before_harvest", set())


# ---------------------------------------------------------------------------
# The core effect: banks 2 at round 14 when field-goods >= 7
# ---------------------------------------------------------------------------

def test_banks_2_at_round_14_with_7_field_goods():
    state = _own_minor(_final_harvest_state(), 0, CARD_ID)
    state = _seven_grain_fields(state, 0)
    assert _banked(state, 0) == 0
    after = _resolve_harvest_field(state)
    assert _banked(after, 0) == 2


def test_grain_and_veg_both_count_toward_goods():
    """'Goods in your fields' = grain + veg on FIELD cells (a field is sown with
    one or the other). 4 grain + 3 veg across fields = 7 -> qualifies."""
    state = _own_minor(_final_harvest_state(), 0, CARD_ID)
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 1): Cell(cell_type=CellType.FIELD, grain=1),
        (1, 0): Cell(cell_type=CellType.FIELD, veg=3),
    })
    after = _resolve_harvest_field(state)
    assert _banked(after, 0) == 2


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_no_bank_with_only_6_field_goods():
    """6 field-goods is below the threshold -> nothing banked."""
    state = _own_minor(_final_harvest_state(), 0, CARD_ID)
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 1): Cell(cell_type=CellType.FIELD, grain=3),
    })
    after = _resolve_harvest_field(state)
    assert _banked(after, 0) == 0


def test_exactly_7_qualifies():
    """The threshold is 'at least 7' -> exactly 7 banks."""
    state = _own_minor(_final_harvest_state(), 0, CARD_ID)
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 1): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 2): Cell(cell_type=CellType.FIELD, grain=1),
    })
    after = _resolve_harvest_field(state)
    assert _banked(after, 0) == 2


def test_stockpiled_grain_does_not_count():
    """'Goods in your fields' is field crops only — a large grain stockpile that
    is NOT on field cells does not qualify."""
    state = _own_minor(_final_harvest_state(), 0, CARD_ID)
    p = state.players[0]
    p = fast_replace(p, resources=p.resources + Resources(grain=20, veg=20))
    state = fast_replace(state, players=tuple(
        p if i == 0 else state.players[i] for i in range(2)))
    # No FIELD cells with crops.
    after = _resolve_harvest_field(state)
    assert _banked(after, 0) == 0


# ---------------------------------------------------------------------------
# Card-fields (ruling 45, 2026-07-12): a card-field is a field, and the print
# reads "GOODS in your fields" — so EVERYTHING planted on card-fields counts,
# wood/stone included (unlike the crop-only readers)
# ---------------------------------------------------------------------------

def test_threshold_reached_only_via_card_field_crops():
    """Boundary the grid-only code failed: 5 grain on grid fields + 2 veg
    planted on Beanfield = 7 field-goods -> banks (grid alone saw 5)."""
    state = _own_minor(_final_harvest_state(), 0, CARD_ID)
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 1): Cell(cell_type=CellType.FIELD, grain=2),
    })
    state = _own_minor(state, 0, "beanfield")
    state = _set_stacks(state, 0, "beanfield", [(0, 2, 0, 0)])
    after = _resolve_harvest_field(state)
    assert _banked(after, 0) == 2


def test_wood_and_stone_on_card_fields_are_goods():
    """The print says GOODS, not crops: 6 wood on Wood Field + 2 stone on Rock
    Garden = 8 field-goods with NO grid field at all -> banks."""
    state = _own_minor(_final_harvest_state(), 0, CARD_ID)
    state = _own_minor(state, 0, "wood_field")
    state = _set_stacks(state, 0, "wood_field", [(0, 0, 3, 0), (0, 0, 3, 0)])
    state = _own_minor(state, 0, "rock_garden")
    state = _set_stacks(state, 0, "rock_garden",
                        [(0, 0, 0, 2), (0, 0, 0, 0), (0, 0, 0, 0)])
    after = _resolve_harvest_field(state)
    assert _banked(after, 0) == 2


def test_card_field_goods_one_short_no_bank():
    """4 grid grain + 2 Beanfield veg = 6 field-goods -> below the threshold."""
    state = _own_minor(_final_harvest_state(), 0, CARD_ID)
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 1): Cell(cell_type=CellType.FIELD, grain=1),
    })
    state = _own_minor(state, 0, "beanfield")
    state = _set_stacks(state, 0, "beanfield", [(0, 2, 0, 0)])
    after = _resolve_harvest_field(state)
    assert _banked(after, 0) == 0


# ---------------------------------------------------------------------------
# The round gate — only the FINAL harvest (round 14) qualifies
# ---------------------------------------------------------------------------

def test_does_not_bank_at_an_earlier_harvest():
    """A qualifying field state at an EARLIER harvest (round 13) banks nothing —
    only the final harvest (round 14) counts."""
    state = with_round(with_phase(setup(0), Phase.HARVEST_FIELD), 13)
    state = _own_minor(state, 0, CARD_ID)
    state = _seven_grain_fields(state, 0)
    after = _resolve_harvest_field(state)
    assert _banked(after, 0) == 0


# ---------------------------------------------------------------------------
# Owner-gating — banks only for the player who owns it
# ---------------------------------------------------------------------------

def test_banks_only_for_owner():
    state = _own_minor(_final_harvest_state(), 0, CARD_ID)  # P0 owns, P1 does not
    state = _seven_grain_fields(state, 0)
    state = _seven_grain_fields(state, 1)
    after = _resolve_harvest_field(state)
    assert _banked(after, 0) == 2
    assert _banked(after, 1) == 0


# ---------------------------------------------------------------------------
# Scoring — the banked points show up at end-game scoring
# ---------------------------------------------------------------------------

def test_scoring_reads_banked_points():
    state = _own_minor(_final_harvest_state(), 0, CARD_ID)
    state = _seven_grain_fields(state, 0)
    after = _resolve_harvest_field(state)

    # The card scoring term reads back exactly the banked 2.
    from agricola.cards.wood_rake import _score
    assert _score(after, 0) == 2
    assert _score(after, 1) == 0

    # And it flows into the full score breakdown (delta vs. an un-banked baseline).
    total_owner, _ = score(after, 0)
    baseline = fast_replace(after, players=tuple(
        fast_replace(after.players[i], card_state=type(after.players[0].card_state)())
        if i == 0 else after.players[i]
        for i in range(2)))
    total_baseline, _ = score(baseline, 0)
    assert total_owner - total_baseline == 2


def test_scoring_zero_when_not_qualified():
    """Owner played the card but never hit 7 field-goods at round 14 -> 0 bonus."""
    state = _own_minor(_final_harvest_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=3)})
    after = _resolve_harvest_field(state)
    from agricola.cards.wood_rake import _score
    assert _score(after, 0) == 0


# ---------------------------------------------------------------------------
# Family byte-identity — no frame, no bank without the card
# ---------------------------------------------------------------------------

def test_byte_identical_without_card():
    state = _final_harvest_state(seed=3)
    state = _seven_grain_fields(state, 0)
    after = _resolve_harvest_field(state)
    # Mechanical take only; nothing banked, no lingering host frame.
    assert _banked(after, 0) == 0
    assert after.phase == Phase.HARVEST_FEED
    assert all(type(f).__name__ == "PendingHarvestFeed" for f in after.pending_stack)
