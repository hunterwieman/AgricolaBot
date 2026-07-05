import agricola.cards.lynchet  # noqa: F401
"""Tests for Lynchet (minor improvement, D63; Dulcinaria Expansion; Food Provider).

Card text: "In the field phase of each harvest, you get 1 food for each harvested
field tile that is orthogonally adjacent to your house."

A take-occasion AUTO (migrated 2026-07-05 off the legacy pre-take grid snapshot):
1 food per board-cell ENTRY of the take occasion whose cell is orthogonally
adjacent to a ROOM cell — per harvested TILE, ignoring the entry's amount (a
take-modifier's folded-in extra doesn't add a second food for the same tile).
Gated `occasion.source == "take"`, which carries the card's "of each harvest"
scoping (a card-played field phase passes its own source). Default starting rooms
sit at (1,0) and (2,0), so a field at (0,0), (1,1) or (2,1) borders the house,
while a field at e.g. (0,3) does not.
"""
from agricola.cards.harvest_windows import HARVEST_OCCASION_AUTOS
from agricola.cards.specs import MINORS
from agricola.cards.triggers import HARVEST_FIELD_CARDS
from agricola.constants import CellType, Phase
from agricola.engine import _resolve_harvest_field
from agricola.replace import fast_replace
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_grid, with_phase, with_sown_fields

CARD_ID = "lynchet"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _field_state(seed=0):
    """A HARVEST_FIELD-phase state (no card owned yet)."""
    return with_phase(setup(seed), Phase.HARVEST_FIELD)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_minor_and_take_occasion_auto():
    assert CARD_ID in MINORS
    # A take-occasion auto — OFF the legacy harvest-field hook (2026-07-05).
    assert CARD_ID not in HARVEST_FIELD_CARDS
    assert any(e.card_id == CARD_ID for e in HARVEST_OCCASION_AUTOS)
    spec = MINORS[CARD_ID]
    # No printed VPs, no cost, no prereq, not a passing card.
    assert spec.vps == 0
    assert spec.prereq is None
    assert spec.passing_left is False


# ---------------------------------------------------------------------------
# Harvest hook: 1 food per sown field adjacent to the house
# ---------------------------------------------------------------------------

def test_one_food_per_adjacent_sown_field():
    state = _own_minor(_field_state(), 0, CARD_ID)
    # Rooms at (1,0),(2,0). Fields at (0,0) [adj to (1,0)] and (1,1) [adj to (1,0)]
    # both border the house -> +2 food.
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)], veg_fields=[(1, 1)])
    food0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == food0 + 2


def test_non_adjacent_field_does_not_count():
    state = _own_minor(_field_state(), 0, CARD_ID)
    # Field at (0,3) is far from the house -> no bonus.
    state = with_sown_fields(state, 0, grain_fields=[(0, 3)])
    food0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == food0


def test_mixes_adjacent_and_non_adjacent():
    state = _own_minor(_field_state(), 0, CARD_ID)
    # (0,0) adjacent -> counts; (0,3) not adjacent -> ignored. +1 food.
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 3)])
    food0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == food0 + 1


def test_empty_field_adjacent_to_house_does_not_count():
    """An unsown (empty) FIELD yields nothing this harvest, so it earns no food
    even though it borders the house."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD)})  # empty
    food0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == food0


def test_veg_field_counts():
    """A vegetable-only field adjacent to the house counts too."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, veg_fields=[(0, 0)])
    food0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == food0 + 1


# ---------------------------------------------------------------------------
# Non-mutation: the bonus only counts, the take still depletes the field
# ---------------------------------------------------------------------------

def test_apply_does_not_mutate_fields():
    """The hook only counts; the field still loses exactly 1 crop to the
    mechanical take (a 3-grain field goes to 2, not 1 or 0)."""
    state = _own_minor(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])  # 3 grain
    after = _resolve_harvest_field(state)
    assert after.players[0].farmyard.grid[0][0].grain == 2


# ---------------------------------------------------------------------------
# Scoping: fires only for its owner
# ---------------------------------------------------------------------------

def test_fires_only_for_owner():
    state = _own_minor(_field_state(), 0, CARD_ID)
    # Both players have an adjacent sown field, but only P0 owns the card.
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = with_sown_fields(state, 1, grain_fields=[(0, 0)])
    f0, f1 = state.players[0].resources.food, state.players[1].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0 + 1   # owner gets the bonus
    assert after.players[1].resources.food == f1       # non-owner unchanged


def test_fires_for_owner_in_seat_one():
    state = _own_minor(_field_state(), 1, CARD_ID)
    state = with_sown_fields(state, 1, grain_fields=[(0, 0)], veg_fields=[(1, 1)])
    f1 = state.players[1].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[1].resources.food == f1 + 2


def test_no_bonus_with_no_fields():
    state = _own_minor(_field_state(), 0, CARD_ID)
    food0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == food0


# ---------------------------------------------------------------------------
# The manifest read (post-migration guards)
# ---------------------------------------------------------------------------

def test_fold_in_extra_is_still_one_tile():
    """Per-TILE counting: an adjacent 2-grain field emptied in one combined take
    (Stable Manure's folded-in extra, ruling 11) is ONE harvested tile -> 1 food,
    not 2 — the entry's amount is ignored."""
    from agricola.actions import CommitFieldTake, Proceed
    from agricola.engine import _advance_until_decision, step
    from agricola.legality import legal_actions
    from agricola.pending import PendingFieldPhase
    state = _own_minor(_own_minor(_field_state(), 0, CARD_ID), 0, "stable_manure")
    for idx in (0, 1):   # feed both so the walk is painless
        p = state.players[idx]
        state = fast_replace(state, players=tuple(
            fast_replace(p, resources=fast_replace(p.resources, food=10))
            if i == idx else state.players[i] for i in range(2)))
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=2),   # adjacent to (1,0) room
        (0, 4): Cell(cell_type=CellType.STABLE),
    })
    f0 = state.players[0].resources.food
    state = _advance_until_decision(state)
    assert isinstance(state.pending_stack[-1], PendingFieldPhase)
    take = next(a for a in legal_actions(state)
                if isinstance(a, CommitFieldTake) and a.modifiers)
    state = step(state, take)
    # The one event took 2 grain from ONE adjacent tile -> exactly +1 food.
    assert state.players[0].farmyard.grid[0][0].grain == 0
    assert state.players[0].resources.food == f0 + 1
    state = step(state, Proceed())
    assert _advance_until_decision(state).phase == Phase.HARVEST_FEED


def test_played_field_phase_pays_nothing():
    """"In the field phase of each HARVEST": a card-played field phase (Bumper
    Crop / Harvest Festival Planning, ruling 4) calls the bare take with its own
    source, and the source gate keeps Lynchet silent."""
    from agricola.resolution import emit_harvest_occasion, field_take
    state = _own_minor(setup(0), 0, CARD_ID)          # Phase.WORK, mid-round
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])   # adjacent
    f0 = state.players[0].resources.food
    state, occ = field_take(state, 0, source="card:bumper_crop")
    state = emit_harvest_occasion(state, 0, occ)
    assert state.players[0].resources.grain >= 1      # the take itself happened
    assert state.players[0].resources.food == f0      # ...but Lynchet paid nothing
