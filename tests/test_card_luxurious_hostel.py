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
import agricola.cards.half_timbered_house  # noqa: F401  (registers the sibling)
import agricola.cards.luxurious_hostel  # noqa: F401  (registers the card)

from agricola.cards.specs import MINORS
from agricola.constants import CellType, HouseMaterial
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import SCORING_GROUPS, SCORING_TERMS, score
from agricola.setup import setup
from agricola.state import Cell
from tests.factories import (
    with_grid,
    with_house,
    with_minors,
    with_people,
)

CARD_ID = "luxurious_hostel"
GROUP_ID = "stone_house_bonus"


def _scorer():
    """The registered scoring fn for this card (from its scoring group)."""
    return next(fn for cid, fn in SCORING_GROUPS[GROUP_ID] if cid == CARD_ID)


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
    # The conditional bonus is read at scoring, via the mutual-exclusion group
    # (NOT the plain SCORING_TERMS path — that would double-count with the
    # sibling stone-house card).
    assert CARD_ID in {cid for cid, _ in SCORING_GROUPS[GROUP_ID]}
    assert CARD_ID not in {cid for cid, _ in SCORING_TERMS}


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


# ---------------------------------------------------------------------------
# Mutual exclusion with Half-Timbered House (SC1): owning BOTH scores the MAX,
# never the sum — "you can only use one card ... for your stone house."
# ---------------------------------------------------------------------------

HALF_TIMBERED = "half_timbered_house"  # scores 1 per stone room


def _bonus_from_scoring(state, idx):
    """Bonus attributable to the stone-house-bonus cards owned by idx = its
    card_points delta vs an identical farmyard owning NEITHER card."""
    stripped = with_minors(state, idx, frozenset())
    return score(state, idx)[0] - score(stripped, idx)[0]


def test_luxurious_hostel_wins_max_when_owning_both():
    # 3 stone rooms, 2 people: luxurious_hostel = 4 (rooms > people),
    # half_timbered = 3 (1/room). Owning BOTH must score max(4, 3) = 4, not 7.
    s = setup(seed=7)
    s = _stone_house_with_rooms(s, 0, n_rooms=3, people=2)
    s = with_minors(s, 0, frozenset({CARD_ID, HALF_TIMBERED}))
    assert _bonus_from_scoring(s, 0) == 4    # max, not 4 + 3 = 7


def test_half_timbered_wins_max_when_owning_both():
    # 5 stone rooms, 5 people: luxurious_hostel = 0 (rooms NOT > people),
    # half_timbered = 5 (1/room). Owning BOTH must score max(0, 5) = 5.
    s = setup(seed=7)
    s = _stone_house_with_rooms(s, 0, n_rooms=5, people=5)
    s = with_minors(s, 0, frozenset({CARD_ID, HALF_TIMBERED}))
    assert _bonus_from_scoring(s, 0) == 5    # max, not 0 + 5 (which happens to = 5 anyway)

    # A case where the sum would visibly exceed the max: 6 rooms, 2 people.
    # luxurious_hostel = 4, half_timbered = 6 → max 6, sum would be 10.
    s2 = setup(seed=7)
    s2 = _stone_house_with_rooms(s2, 0, n_rooms=6, people=2)
    s2 = with_minors(s2, 0, frozenset({CARD_ID, HALF_TIMBERED}))
    assert _bonus_from_scoring(s2, 0) == 6    # max(4, 6), NOT 4 + 6 = 10


def test_owning_both_never_double_counts_via_score_breakdown():
    # Verify through the ScoreBreakdown.card_points that only one member counts.
    s = setup(seed=7)
    s = _stone_house_with_rooms(s, 0, n_rooms=6, people=2)  # lux=4, half=6
    s_both = with_minors(s, 0, frozenset({CARD_ID, HALF_TIMBERED}))
    s_lux = with_minors(s, 0, frozenset({CARD_ID}))
    s_half = with_minors(s, 0, frozenset({HALF_TIMBERED}))

    _, bd_both = score(s_both, 0)
    _, bd_lux = score(s_lux, 0)
    _, bd_half = score(s_half, 0)

    assert bd_lux.card_points == 4
    assert bd_half.card_points == 6
    # Owning both = max(4, 6) = 6, NOT 4 + 6 = 10.
    assert bd_both.card_points == 6
