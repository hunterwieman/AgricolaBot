"""Tests for Potato Harvester (occupation, C106; Consul Dirigens; players 1+).

Card text: "When you play this card, you immediately get 3 food. For each
vegetable you get from your fields during the field phase of the harvest, you get
1 additional food."

Two effects:
  - on-play +3 food (an occupation `on_play`).
  - a per-occasion harvest AUTO (`register_harvest_occasion_auto`): +1 additional
    food per vegetable UNIT harvested in the FIELD PHASE (ruling 6, unit
    counting), scoped on `state.phase == Phase.HARVEST_FIELD` ("during the field
    phase of the harvest" scopes the window — a card-granted extra veg harvest in
    the field phase counts too; a WORK-phase Bumper Crop take does not).

The harvest tests drive a real harvest through the walk (`_advance_until_decision`
over a `Phase.HARVEST_FIELD` state) so the occasion auto fires off the actual take
manifest, not a pre-take grid snapshot.
"""
import agricola.cards.potato_harvester  # noqa: F401

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

CARD_ID = "potato_harvester"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


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
    """Advance from HARVEST_FIELD until the field phase completes. Potato Harvester
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

def test_registered_as_occupation_and_occasion_auto():
    assert CARD_ID in OCCUPATIONS
    assert any(e.card_id == CARD_ID for e in HARVEST_OCCASION_AUTOS)
    assert OCCUPATIONS[CARD_ID].on_play is not None


# ---------------------------------------------------------------------------
# On-play: +3 food
# ---------------------------------------------------------------------------

def test_on_play_grants_three_food():
    state = setup(0)
    food0 = state.players[0].resources.food
    after = OCCUPATIONS[CARD_ID].on_play(state, 0)
    assert after.players[0].resources.food == food0 + 3
    # Only food changes; opponent untouched.
    assert after.players[1].resources == state.players[1].resources


# ---------------------------------------------------------------------------
# Harvest hook: 1 food per vegetable harvested from fields
# ---------------------------------------------------------------------------

def test_one_food_per_veg_field():
    state = _own_occ(_harvest_state(), 0, CARD_ID)
    # Two veg fields (2 veg each) + one grain field. Each veg field yields 1 veg
    # in the take -> +2 food. The grain field yields grain, not veg, so no bonus.
    state = with_sown_fields(state, 0, veg_fields=[(0, 2), (0, 3)],
                             grain_fields=[(1, 2)])
    food0 = state.players[0].resources.food
    veg0 = state.players[0].resources.veg
    grain0 = state.players[0].resources.grain
    after = _run_field_phase(state)
    # Bonus: +2 food (one per veg field). Mechanical take: +2 veg, +1 grain.
    assert after.players[0].resources.food == food0 + 2
    assert after.players[0].resources.veg == veg0 + 2
    assert after.players[0].resources.grain == grain0 + 1


def test_does_not_double_take_fields():
    """The occasion auto only credits food; each veg field still loses exactly 1
    veg to the take (a 2-veg field goes to 1, not 0)."""
    state = _own_occ(_harvest_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, veg_fields=[(0, 2)])  # 2 veg
    after = _run_field_phase(state)
    assert after.players[0].farmyard.grid[0][2].veg == 1


def test_no_bonus_without_veg_fields():
    state = _own_occ(_harvest_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 2)])  # grain only
    food0 = state.players[0].resources.food
    after = _run_field_phase(state)
    assert after.players[0].resources.food == food0


def test_no_bonus_empty_field():
    """An unsown (empty) field yields nothing and earns no food."""
    state = _own_occ(_harvest_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 2): Cell(cell_type=CellType.FIELD)})  # empty
    food0 = state.players[0].resources.food
    after = _run_field_phase(state)
    assert after.players[0].resources.food == food0


# ---------------------------------------------------------------------------
# Unit counting + field-phase gating on the occasion manifest (direct)
# ---------------------------------------------------------------------------

def test_unit_counts_veg_entries_ignores_grain():
    """A take occasion with several veg entries pays one food per veg unit; grain
    entries pay nothing (ruling 6, unit counting)."""
    state = with_phase(_own_occ(setup(0), 0, CARD_ID), Phase.HARVEST_FIELD)
    occ = HarvestOccasion(source="take", entries=(
        HarvestEntry(source="cell:0,2", crop="veg", amount=1, emptied=False),
        HarvestEntry(source="cell:0,3", crop="veg", amount=1, emptied=True),
        HarvestEntry(source="cell:1,2", crop="grain", amount=1, emptied=True),
    ))
    f0 = state.players[0].resources.food
    after = apply_harvest_occasion_autos(state, 0, occ)
    assert after.players[0].resources.food == f0 + 2


def test_card_granted_field_phase_occasion_earns_food():
    """"during the field phase" scopes the window, not the take: a card-granted
    extra veg harvest during the field phase (Stable Manure) still yields "a
    vegetable you get from your fields during the field phase" -> it counts."""
    state = with_phase(_own_occ(setup(0), 0, CARD_ID), Phase.HARVEST_FIELD)
    occ = HarvestOccasion(source="card:stable_manure", entries=(
        HarvestEntry(source="cell:0,2", crop="veg", amount=2, emptied=False),
    ))
    f0 = state.players[0].resources.food
    after = apply_harvest_occasion_autos(state, 0, occ)
    assert after.players[0].resources.food == f0 + 2


def test_occasion_outside_field_phase_earns_nothing():
    """The phase gate models user ruling 4: a Bumper Crop take fires the field-phase
    EFFECT during WORK, not the field phase, so Potato Harvester earns nothing."""
    state = _own_occ(setup(0), 0, CARD_ID)   # setup() is Phase.WORK
    occ = HarvestOccasion(source="take", entries=(
        HarvestEntry(source="cell:0,2", crop="veg", amount=2, emptied=True),
    ))
    f0 = state.players[0].resources.food
    after = apply_harvest_occasion_autos(state, 0, occ)
    assert after.players[0].resources.food == f0


# ---------------------------------------------------------------------------
# Scoping: fires only for its owner
# ---------------------------------------------------------------------------

def test_fires_only_for_owner():
    state = _own_occ(_harvest_state(), 0, CARD_ID)
    # Both players have a veg field, but only P0 owns the card.
    state = with_sown_fields(state, 0, veg_fields=[(0, 2)])
    state = with_sown_fields(state, 1, veg_fields=[(0, 2)])
    f0, f1 = state.players[0].resources.food, state.players[1].resources.food
    after = _run_field_phase(state)
    assert after.players[0].resources.food == f0 + 1   # owner gets the bonus
    assert after.players[1].resources.food == f1       # non-owner unchanged


def test_fires_for_owner_in_seat_one():
    state = _own_occ(_harvest_state(), 1, CARD_ID)
    state = with_sown_fields(state, 1, veg_fields=[(0, 2), (0, 3)])
    f1 = state.players[1].resources.food
    after = _run_field_phase(state)
    assert after.players[1].resources.food == f1 + 2
