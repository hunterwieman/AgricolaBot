"""Tests for Nave (minor E32): +1 point per farmyard column containing a room."""
import agricola.cards.nave  # noqa: F401  (registers the card)

from agricola.cards.specs import MINORS
from agricola.constants import CellType
from agricola.resources import Cost, Resources
from agricola.scoring import SCORING_TERMS
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_grid


def _score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == "nave")


def test_registration():
    spec = MINORS["nave"]
    assert spec.cost == Cost(resources=Resources(stone=2, reed=1))
    assert any(cid == "nave" for cid, _ in SCORING_TERMS)


def test_default_two_rooms_share_column_zero():
    # The two starting rooms sit at (1,0) and (2,0) — both in column 0 -> 1 column.
    state = setup(seed=0)
    assert _score_fn()(state, 0) == 1


def test_counts_distinct_columns_with_a_room():
    state = setup(seed=0)
    # Add rooms in columns 2 and 4; column 0 already has the starting rooms -> 3 columns.
    state = with_grid(state, 0, {
        (0, 2): Cell(cell_type=CellType.ROOM),
        (0, 4): Cell(cell_type=CellType.ROOM),
    })
    assert _score_fn()(state, 0) == 3


def test_two_rooms_same_column_count_once():
    state = setup(seed=0)
    # A second room in column 0 (already occupied) adds no column.
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.ROOM)})
    assert _score_fn()(state, 0) == 1


def test_all_five_columns():
    state = setup(seed=0)
    state = with_grid(state, 0, {
        (0, c): Cell(cell_type=CellType.ROOM) for c in range(5)
    })
    assert _score_fn()(state, 0) == 5
