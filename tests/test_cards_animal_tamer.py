"""Tests for Animal Tamer (occupation A86):

  - the WIDE play-variant on-play (choice of 1 wood / 1 grain), driven through the real
    Lessons flow;
  - the STANDING house-pet capacity grant (one any-type animal per room), exercised through
    `extract_slots` / `can_accommodate` / `house_pet_capacity`;
  - Family byte-identity (no card owned -> the default single house pet).
"""
import pytest

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker, Stop
from agricola.cards.capacity_mods import HOUSE_CAPACITY_MODS, house_pet_capacity
from agricola.cards.specs import OCCUPATIONS, PLAY_OCCUPATION_VARIANTS
from agricola.constants import CellType
from agricola.engine import step
from agricola.helpers import can_accommodate, extract_slots
from agricola.legality import legal_actions, legal_placements
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell

_POOL = CardPool(
    occupations=("animal_tamer", "consultant") + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state_with_hand(seed=5, *, occupations=frozenset(), hand=frozenset()):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = cs.players[cp]
    p = fast_replace(p, hand_occupations=hand, occupations=occupations)
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


def _spaces(state):
    return {a.space for a in legal_placements(state)}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert "animal_tamer" in OCCUPATIONS
    assert "animal_tamer" in PLAY_OCCUPATION_VARIANTS
    assert any(cid == "animal_tamer" for cid, _fn in HOUSE_CAPACITY_MODS)


# ---------------------------------------------------------------------------
# Wide on-play variant: 1 wood OR 1 grain
# ---------------------------------------------------------------------------

def test_both_variants_offered():
    cs, _cp = _card_state_with_hand(hand=frozenset({"animal_tamer"}))
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    la = legal_actions(cs)
    assert CommitPlayOccupation(card_id="animal_tamer", variant="wood") in la
    assert CommitPlayOccupation(card_id="animal_tamer", variant="grain") in la


@pytest.mark.parametrize("variant,field", [("wood", "wood"), ("grain", "grain")])
def test_variant_grants_chosen_good(variant, field):
    cs, cp = _card_state_with_hand(hand=frozenset({"animal_tamer"}))
    before = getattr(cs.players[cp].resources, field)
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="animal_tamer", variant=variant))
    # card moved hand -> tableau, chosen good +1, the other good unchanged
    assert "animal_tamer" in cs.players[cp].occupations
    assert "animal_tamer" not in cs.players[cp].hand_occupations
    assert getattr(cs.players[cp].resources, field) == before + 1
    other = "grain" if field == "wood" else "wood"
    assert getattr(cs.players[cp].resources, other) == getattr(
        _card_state_with_hand(hand=frozenset({"animal_tamer"}))[0].players[cp].resources, other
    )


# ---------------------------------------------------------------------------
# Standing capacity: one any-type animal per room
# ---------------------------------------------------------------------------

def test_house_pet_capacity_default_is_one():
    # Family game (no card owned) -> the single house pet.
    s = setup(0)
    assert house_pet_capacity(s.players[0]) == 1


def test_house_pet_capacity_equals_room_count_when_owned():
    cs, cp = _card_state_with_hand(occupations=frozenset({"animal_tamer"}))
    p = cs.players[cp]
    # Starting house is 2 rooms.
    assert house_pet_capacity(p) == 2
    # Add a third room -> capacity tracks the room count.
    grid = p.farmyard.grid
    new_grid = tuple(
        tuple(Cell(cell_type=CellType.ROOM) if (r, c) == (0, 2) else grid[r][c]
              for c in range(5))
        for r in range(3)
    )
    p3 = fast_replace(p, farmyard=fast_replace(p.farmyard, grid=new_grid))
    assert house_pet_capacity(p3) == 3


def test_extract_slots_reflects_capacity():
    cs, cp = _card_state_with_hand(occupations=frozenset({"animal_tamer"}))
    owner = cs.players[cp]
    nonowner = cs.players[1 - cp]
    _caps_o, flex_o = extract_slots(owner)      # 2 rooms, 0 stables
    _caps_n, flex_n = extract_slots(nonowner)
    assert flex_o == 2
    assert flex_n == 1


def test_house_holds_two_different_types_when_owned():
    # The crux: each room can hold a DIFFERENT animal. With Animal Tamer + 2 rooms and no
    # pastures/stables, 1 sheep + 1 boar fit (2 flexible slots, any type each); without the
    # card only one animal fits.
    cs, cp = _card_state_with_hand(occupations=frozenset({"animal_tamer"}))
    caps, flex = extract_slots(cs.players[cp])
    assert caps == []  # no pastures
    assert can_accommodate(caps, flex, 1, 1, 0)   # sheep + boar
    assert not can_accommodate(caps, flex, 1, 1, 1)  # 3 different types > 2 rooms

    # Non-owner: the lone house pet holds at most one animal.
    caps_n, flex_n = extract_slots(cs.players[1 - cp])
    assert can_accommodate(caps_n, flex_n, 1, 0, 0)
    assert not can_accommodate(caps_n, flex_n, 1, 1, 0)
