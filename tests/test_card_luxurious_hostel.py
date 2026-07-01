"""Tests for Luxurious Hostel (minor improvement, D34; Dulcinaria Expansion).

Card text: "During scoring, if you then have more stone rooms than people, you
get 4 bonus points. You can only use one card to get bonus points for your
stone house."
Cost: 1 Wood + 2 Clay; no prerequisite; not passing; printed bonus is the
CONDITIONAL 4 points (implemented via register_scoring, not flat vps).

Shape: a pure end-game scoring term (Category 1). +4 only when the player has
STRICTLY more stone rooms than people (people = people_total), and stone rooms
exist only when the house is stone.
"""
import agricola.cards.luxurious_hostel  # noqa: F401  (registers the card)

from agricola.cards.specs import MINORS
from agricola.constants import CellType, HouseMaterial
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import SCORING_TERMS, score
from agricola.setup import setup
from agricola.state import Cell
from tests.factories import (
    with_grid,
    with_house,
    with_minors,
    with_people,
)

CARD_ID = "luxurious_hostel"


def _scorer():
    """The registered scoring fn for this card."""
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


def _stone_house_with_rooms(state, idx, *, n_rooms, people):
    """Make P{idx} a STONE house with exactly n_rooms rooms and `people` people.

    The starting farmyard has rooms at (1,0) and (2,0). We rebuild the room set
    to be exactly n_rooms cells of CellType.ROOM, set the material to stone, and
    set people_total.
    """
    # Candidate cells for rooms (column 0 + spillover), enough for up to 6 rooms.
    cells = [(1, 0), (2, 0), (0, 0), (1, 1), (2, 1), (0, 1)]
    assert n_rooms <= len(cells)
    # Clear the two starting rooms, then set exactly the first n_rooms cells.
    overrides = {(1, 0): Cell(), (2, 0): Cell()}
    for (r, c) in cells[:n_rooms]:
        overrides[(r, c)] = Cell(cell_type=CellType.ROOM)
    state = with_grid(state, idx, overrides)
    state = with_house(state, idx, HouseMaterial.STONE)
    state = with_people(state, idx, total=people)
    state = with_minors(state, idx, frozenset({CARD_ID}))
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_luxurious_hostel_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1, clay=2))
    assert spec.min_occupations == 0          # no prerequisite
    assert spec.max_occupations is None
    assert spec.passing_left is False         # kept, not passing
    assert spec.vps == 0                       # the 4 points are conditional, not flat
    # The conditional bonus is read at scoring.
    assert CARD_ID in {cid for cid, _ in SCORING_TERMS}


def test_on_play_is_noop():
    s = setup(seed=4)
    spec = MINORS[CARD_ID]
    # on_play must leave the state unchanged (the value is all in scoring).
    assert spec.on_play(s, 0) is s


# ---------------------------------------------------------------------------
# The scoring effect: +4 when stone rooms STRICTLY exceed people
# ---------------------------------------------------------------------------

def test_scores_4_when_more_stone_rooms_than_people():
    s = setup(seed=7)
    s = _stone_house_with_rooms(s, 0, n_rooms=3, people=2)
    assert _scorer()(s, 0) == 4


def test_no_score_when_equal_stone_rooms_and_people():
    # STRICT comparison: equal counts → 0 (not >=).
    s = setup(seed=7)
    s = _stone_house_with_rooms(s, 0, n_rooms=2, people=2)
    assert _scorer()(s, 0) == 0


def test_no_score_when_fewer_stone_rooms_than_people():
    s = setup(seed=7)
    s = _stone_house_with_rooms(s, 0, n_rooms=2, people=3)
    assert _scorer()(s, 0) == 0


# ---------------------------------------------------------------------------
# Eligibility boundary: material must be STONE (wood/clay rooms never count)
# ---------------------------------------------------------------------------

def test_wood_house_scores_zero_even_with_many_rooms():
    # 3 rooms, 2 people, but the house is WOOD → stone_rooms is 0 → no bonus.
    s = setup(seed=7)
    s = _stone_house_with_rooms(s, 0, n_rooms=3, people=2)
    s = with_house(s, 0, HouseMaterial.WOOD)
    assert _scorer()(s, 0) == 0


def test_clay_house_scores_zero_even_with_many_rooms():
    s = setup(seed=7)
    s = _stone_house_with_rooms(s, 0, n_rooms=3, people=2)
    s = with_house(s, 0, HouseMaterial.CLAY)
    assert _scorer()(s, 0) == 0


# ---------------------------------------------------------------------------
# Ownership scoping: the term only fires for a player who OWNS the card
# ---------------------------------------------------------------------------

def test_full_score_includes_bonus_only_for_owner():
    s = setup(seed=9)
    # Both seats have the qualifying farmyard, but only P0 owns the card.
    s = _stone_house_with_rooms(s, 0, n_rooms=3, people=2)   # owns + qualifies
    s = _stone_house_with_rooms(s, 1, n_rooms=3, people=2)
    s = with_minors(s, 1, frozenset())                       # P1 does NOT own it

    total0, _ = score(s, 0)
    total1, _ = score(s, 1)
    # Strip the card to measure the baseline for each identical farmyard.
    s_no = with_minors(s, 0, frozenset())
    base0, _ = score(s_no, 0)
    base1, _ = score(s_no, 1)

    assert total0 - base0 == 4     # owner gets the +4
    assert total1 - base1 == 0     # non-owner, identical farmyard, gets nothing


def test_non_owner_with_qualifying_house_scores_no_bonus():
    s = setup(seed=11)
    s = _stone_house_with_rooms(s, 1, n_rooms=4, people=2)
    s = with_minors(s, 1, frozenset())                       # qualifies but doesn't own
    assert _scorer()(s, 1) == 4    # the raw scorer is unconditional on ownership,
    # but score() gates it on ownership:
    with_card, _ = score(with_minors(s, 1, frozenset({CARD_ID})), 1)
    without_card, _ = score(s, 1)
    assert with_card - without_card == 4
