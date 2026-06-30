import agricola.cards.potato_harvester  # noqa: F401
"""Tests for Potato Harvester (occupation, C106; Consul Dirigens; players 1+).

Card text: "When you play this card, you immediately get 3 food. For each
vegetable you get from your fields during the field phase of the harvest, you get
1 additional food."

Two effects:
  - on-play +3 food (an occupation `on_play`).
  - a Category-6 harvest-field hook: 1 food per vegetable the mechanical field-take
    harvests from the player's fields. The take removes 1 crop per field with grain
    taking precedence, so a field yields a vegetable exactly when `grain == 0 and
    veg > 0`; the bonus equals the count of such fields. `_apply` only READS the
    fields (no mutation) — it merely credits food.

The harvest tests drive `_resolve_harvest_field` directly (like
`tests/test_cards_category6.py`) so the fire-before-the-take ordering is exercised
end-to-end, and confirm the fields still yield their veg to the normal take.
"""
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import HARVEST_FIELD_CARDS, should_host_harvest_field
from agricola.constants import CellType, Phase
from agricola.engine import _resolve_harvest_field
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


def _field_state(seed=0):
    """A HARVEST_FIELD-phase state (no card owned yet)."""
    return with_phase(setup(seed), Phase.HARVEST_FIELD)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_occupation_and_harvest_field_card():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in HARVEST_FIELD_CARDS
    # No printed VPs / cost / prereq on the occupation (pure on-play + harvest).
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
# Hosting gate — card-dependent push
# ---------------------------------------------------------------------------

def test_no_host_without_card():
    assert should_host_harvest_field(setup(0)) is False


def test_host_when_owned():
    state = _own_occ(setup(0), 0, CARD_ID)
    assert should_host_harvest_field(state) is True
    # Owned by the OTHER player still hosts (autos fire per-owner).
    state2 = _own_occ(setup(0), 1, CARD_ID)
    assert should_host_harvest_field(state2) is True


def test_no_host_when_only_in_hand():
    state = setup(0)
    p = state.players[0]
    p = fast_replace(p, hand_occupations=p.hand_occupations | {CARD_ID})
    state = fast_replace(state, players=(p, state.players[1]))
    assert should_host_harvest_field(state) is False


# ---------------------------------------------------------------------------
# Harvest hook: 1 food per vegetable harvested from fields
# ---------------------------------------------------------------------------

def test_one_food_per_veg_field():
    state = _own_occ(_field_state(), 0, CARD_ID)
    # Two veg fields (2 veg each) + one grain field. Each veg field yields 1 veg
    # in the take -> +2 food. The grain field yields grain, not veg, so no bonus.
    state = with_sown_fields(state, 0, veg_fields=[(0, 2), (0, 3)],
                             grain_fields=[(1, 2)])
    food0 = state.players[0].resources.food
    veg0 = state.players[0].resources.veg
    grain0 = state.players[0].resources.grain
    after = _resolve_harvest_field(state)
    # Bonus: +2 food (one per veg field). Mechanical take: +2 veg, +1 grain.
    assert after.players[0].resources.food == food0 + 2
    assert after.players[0].resources.veg == veg0 + 2
    assert after.players[0].resources.grain == grain0 + 1


def test_apply_does_not_mutate_fields():
    """The harvest hook only counts; it must not deplete the field. Each veg field
    still loses exactly 1 veg — to the mechanical take, not the bonus (a 2-veg field
    goes to 1, not 0)."""
    state = _own_occ(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, veg_fields=[(0, 2)])  # 2 veg
    after = _resolve_harvest_field(state)
    # 2 - 1 (mechanical take only) = 1. If the hook double-counted this would be 0.
    assert after.players[0].farmyard.grid[0][2].veg == 1


def test_no_bonus_without_veg_fields():
    state = _own_occ(_field_state(), 0, CARD_ID)
    state = with_sown_fields(state, 0, grain_fields=[(0, 2)])  # grain only
    food0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == food0


def test_no_bonus_empty_field():
    """An unsown (empty) field yields nothing and earns no food."""
    state = _own_occ(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 2): Cell(cell_type=CellType.FIELD)})  # empty
    food0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == food0


def test_grain_field_with_veg_takes_grain_no_bonus():
    """If a field somehow holds both grain and veg, grain takes precedence in the
    take (`if grain > 0`), so no vegetable is harvested and no food is awarded —
    `_veg_fields` requires grain == 0."""
    state = _own_occ(_field_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 2): Cell(cell_type=CellType.FIELD, grain=2, veg=2)})
    food0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == food0


# ---------------------------------------------------------------------------
# Scoping: fires only for its owner
# ---------------------------------------------------------------------------

def test_fires_only_for_owner():
    state = _own_occ(_field_state(), 0, CARD_ID)
    # Both players have a veg field, but only P0 owns the card.
    state = with_sown_fields(state, 0, veg_fields=[(0, 2)])
    state = with_sown_fields(state, 1, veg_fields=[(0, 2)])
    f0, f1 = state.players[0].resources.food, state.players[1].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0 + 1   # owner gets the bonus
    assert after.players[1].resources.food == f1       # non-owner unchanged


def test_fires_for_owner_in_seat_one():
    state = _own_occ(_field_state(), 1, CARD_ID)
    state = with_sown_fields(state, 1, veg_fields=[(0, 2), (0, 3)])
    f1 = state.players[1].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[1].resources.food == f1 + 2
