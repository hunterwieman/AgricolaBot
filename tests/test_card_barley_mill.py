"""Tests for Barley Mill (minor improvement, A64; Artifex Expansion).

Card text: "In the field phase of each harvest, you get 1 food for each grain
field that you harvest."

Barley Mill is a per-occasion consequence: it reads the field-phase TAKE
occasion's manifest and grants 1 food for each grain FIELD harvested.

Governing user ruling 9 (2026-07-03): a take-once card (the Grain Sieve shape)
fires once, with the take occasion, and keys off the specifics of what that
action took. So Barley Mill gates on `occasion.source == "take"` and counts the
grain-bearing FIELDS in that occasion's entries — never a separate card-granted
additional-harvest occasion.

THE COUNTING RULE — "for each grain FIELD that you harvest" counts grain ENTRIES
(one HarvestEntry == one field), NOT grain units. The per-field `amount` is
ignored: two grain fields -> +2 food; a single field yielding 2 grain in one
combined take (a take-modifier's folded-in extra) is still ONE grain field -> +1
food.
"""
from __future__ import annotations

import agricola.cards.barley_mill  # noqa: F401  (registers the card)
import agricola.cards.scythe_worker  # noqa: F401  (registers the take modifier)

from agricola.cards.harvest_windows import (
    HARVEST_OCCASION_AUTOS,
    apply_harvest_occasion_autos,
)
from agricola.cards.specs import MINORS, OCCUPATIONS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision
from agricola.pending import HarvestEntry, HarvestOccasion
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from agricola.state import Cell, GameState

from tests.factories import with_grid, with_phase, with_sown_fields


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id="barley_mill"):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _own_occupation(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _harvest_state(seed=0, food=10):
    """A HARVEST_FIELD-phase state, everyone fed (so feeding is painless)."""
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        p = state.players[idx]
        p = fast_replace(p, resources=fast_replace(p.resources, food=food))
        state = fast_replace(state, players=tuple(
            p if i == idx else state.players[i] for i in range(2)))
    return state


def _run_harvest(state):
    """Drive the harvest field-phase (into feeding) via the real walk."""
    return _advance_until_decision(state)


# ---------------------------------------------------------------------------
# Registration (spec fields vs the JSON)
# ---------------------------------------------------------------------------

def test_barley_mill_registered():
    assert "barley_mill" in MINORS
    assert "barley_mill" not in OCCUPATIONS
    # It registered a per-occasion auto (not the legacy harvest_field hook).
    assert any(e.card_id == "barley_mill" for e in HARVEST_OCCASION_AUTOS)


def test_cost_and_spec_fields_match_json():
    spec = MINORS["barley_mill"]
    # "1 Wood, 4 Clay/2 Stone": always 1 wood + (4 clay OR 2 stone).
    assert spec.cost.resources == Resources(wood=1, clay=4)
    assert spec.alt_costs == (Cost(Resources(wood=1, stone=2)),)
    assert spec.prereq is None
    assert spec.passing_left is False
    assert spec.vps == 1
    assert spec.min_occupations == 0
    assert spec.max_occupations is None


def test_on_play_is_noop():
    state = setup(0)
    before = state.players[0].resources
    after = MINORS["barley_mill"].on_play(state, 0)
    assert after.players[0].resources == before
    assert after == state


# ---------------------------------------------------------------------------
# Per-field counting, driven through a real harvest (the take occasion)
# ---------------------------------------------------------------------------

def test_two_grain_fields_grants_two_food():
    # Two grain fields -> two grain entries -> +2 food.
    state = with_sown_fields(_own_minor(_harvest_state(), 0), 0,
                             grain_fields=[(0, 0), (0, 1)])
    f0 = state.players[0].resources.food
    g0 = state.players[0].resources.grain
    after = _run_harvest(state)
    assert after.phase == Phase.HARVEST_FEED
    assert after.players[0].resources.food == f0 + 2      # 1 food per field
    assert after.players[0].resources.grain == g0 + 2     # +1 grain per field taken


def test_one_grain_field_grants_one_food():
    state = with_sown_fields(_own_minor(_harvest_state(), 0), 0,
                             grain_fields=[(0, 0)])
    f0 = state.players[0].resources.food
    after = _run_harvest(state)
    assert after.players[0].resources.food == f0 + 1


def test_three_grain_fields_grants_three_food():
    state = with_sown_fields(_own_minor(_harvest_state(), 0), 0,
                             grain_fields=[(0, 0), (0, 1), (0, 2)])
    f0 = state.players[0].resources.food
    after = _run_harvest(state)
    assert after.players[0].resources.food == f0 + 3


def test_single_field_with_three_grain_is_one_field():
    # THE COUNTING RULE: one field sown to 3 grain harvests 1 grain this phase in
    # a single entry -> ONE grain field -> +1 food (NOT +3 for the units, NOT
    # more). The `amount` is irrelevant to per-field counting.
    state = with_sown_fields(_own_minor(_harvest_state(), 0), 0,
                             grain_fields=[(0, 0)])
    f0 = state.players[0].resources.food
    after = _run_harvest(state)
    assert after.players[0].resources.food == f0 + 1
    # The 3-grain field dropped to 2 (only 1 taken this phase).
    assert after.players[0].farmyard.grid[0][0].grain == 2


def test_no_grain_fields_no_food():
    state = _own_minor(_harvest_state(), 0)  # no fields
    f0 = state.players[0].resources.food
    after = _run_harvest(state)
    assert after.players[0].resources.food == f0


def test_veg_fields_do_not_count():
    # Two veg fields harvest veg, not grain, so Barley Mill pays nothing.
    state = with_sown_fields(_own_minor(_harvest_state(), 0), 0,
                             veg_fields=[(0, 0), (0, 1)])
    f0 = state.players[0].resources.food
    v0 = state.players[0].resources.veg
    after = _run_harvest(state)
    assert after.players[0].resources.food == f0    # no grain fields, no food
    assert after.players[0].resources.veg == v0 + 2  # veg still harvested


def test_mixed_fields_count_only_grain():
    # Two grain fields + two veg fields -> +2 food (grain fields only).
    state = with_sown_fields(_own_minor(_harvest_state(), 0), 0,
                             grain_fields=[(0, 0), (0, 1)],
                             veg_fields=[(0, 2), (0, 3)])
    f0 = state.players[0].resources.food
    after = _run_harvest(state)
    assert after.players[0].resources.food == f0 + 2


# ---------------------------------------------------------------------------
# Ruling 11 (2026-07-05): a take-modifier's folded-in extra is IN the take, but
# a 2-grain combined take from ONE field is still ONE grain field -> +1 food.
# ---------------------------------------------------------------------------

def test_scythe_worker_fold_in_is_still_one_field():
    """One 2-grain field with Scythe Worker: its folded-in extra makes the one
    take EVENT yield 2 grain (base 1 + extra 1), emptying the field. That is a
    single HarvestEntry (amount 2) for ONE field, so Barley Mill pays exactly
    +1 food (per-field count ignores `amount`), end-to-end through the walk.
    +2 grain taken, +1 food (NOT +2)."""
    state = _own_occupation(_own_minor(_harvest_state(), 0), 0, "scythe_worker")
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=2)})
    f0 = state.players[0].resources.food
    g0 = state.players[0].resources.grain
    after = _run_harvest(state)
    assert after.players[0].resources.food == f0 + 1     # ONE grain field
    assert after.players[0].resources.grain == g0 + 2    # base + folded-in extra
    assert after.players[0].farmyard.grid[0][0].grain == 0  # field emptied


def test_two_fold_in_fields_count_two():
    """Two 2-grain fields, both folded in by Scythe Worker: each is one entry
    (amount 2), so two grain fields -> +2 food, +4 grain taken."""
    state = _own_occupation(_own_minor(_harvest_state(), 0), 0, "scythe_worker")
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=2),
        (0, 1): Cell(cell_type=CellType.FIELD, grain=2),
    })
    f0 = state.players[0].resources.food
    g0 = state.players[0].resources.grain
    after = _run_harvest(state)
    assert after.players[0].resources.food == f0 + 2
    assert after.players[0].resources.grain == g0 + 4


# ---------------------------------------------------------------------------
# Owner-gating: fires only for the owner
# ---------------------------------------------------------------------------

def test_fires_only_for_owner():
    # P0 owns Barley Mill and has 2 grain fields; P1 also has 2 grain fields but
    # no card -> only P0 gets food.
    state = _own_minor(_harvest_state(), 0)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    state = with_sown_fields(state, 1, grain_fields=[(0, 0), (0, 1)])
    f0 = state.players[0].resources.food
    f1 = state.players[1].resources.food
    after = _run_harvest(state)
    assert after.players[0].resources.food == f0 + 2     # owner gets food
    assert after.players[1].resources.food == f1         # non-owner gets none


def test_both_owners_each_paid_off_their_own_take():
    state = _own_minor(_own_minor(_harvest_state(), 0), 1)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])                # 1 field
    state = with_sown_fields(state, 1, grain_fields=[(0, 0), (0, 1)])       # 2 fields
    f0 = state.players[0].resources.food
    f1 = state.players[1].resources.food
    after = _run_harvest(state)
    assert after.players[0].resources.food == f0 + 1
    assert after.players[1].resources.food == f1 + 2


# ---------------------------------------------------------------------------
# Ruling 9: fires ONLY on the take occasion, not a card-granted extra harvest
# ---------------------------------------------------------------------------

def test_does_not_fire_on_non_take_occasion():
    # A SEPARATE harvesting occasion (source != "take") that removes grain from
    # 3 fields must NOT trigger Barley Mill — it reads the take (ruling 9). Under
    # ruling 11 no during-phase card creates such an occasion (their extras fold
    # INTO the take and DO count — see the fold-in tests above); a non-take
    # occasion now means an out-of-phase event, which "in the field phase of each
    # harvest" excludes.
    state = _own_minor(setup(0), 0)
    f0 = state.players[0].resources.food
    occ = HarvestOccasion(
        source="card:some_extra_harvest",
        entries=(
            HarvestEntry(source="cell:0,0", crop="grain", amount=1, emptied=False),
            HarvestEntry(source="cell:0,1", crop="grain", amount=1, emptied=False),
            HarvestEntry(source="cell:0,2", crop="grain", amount=1, emptied=False),
        ),
    )
    after = apply_harvest_occasion_autos(state, 0, occ)
    assert isinstance(after, GameState)
    assert after.players[0].resources.food == f0   # no food off a non-take occasion


def test_fires_on_a_hand_built_take_occasion():
    # Mirror of the negative test: the same manifest DOES pay when its source is
    # the field-phase take. Two grain entries -> +2 food. A veg entry is ignored.
    state = _own_minor(setup(0), 0)
    f0 = state.players[0].resources.food
    occ = HarvestOccasion(
        source="take",
        entries=(
            HarvestEntry(source="cell:0,0", crop="grain", amount=1, emptied=False),
            HarvestEntry(source="cell:0,1", crop="grain", amount=3, emptied=True),
            HarvestEntry(source="cell:0,2", crop="veg", amount=2, emptied=True),
        ),
    )
    after = apply_harvest_occasion_autos(state, 0, occ)
    # 2 grain entries (amounts 1 and 3 both counted as ONE field each), veg
    # ignored -> +2 food.
    assert after.players[0].resources.food == f0 + 2
