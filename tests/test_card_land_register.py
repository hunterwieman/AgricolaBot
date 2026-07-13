"""Tests for Land Register (minor E34): +2 points if no farmyard space is unused."""
import agricola.cards.land_register  # noqa: F401  (registers the card)

from agricola.cards.specs import MINORS
from agricola.constants import CellType
from agricola.resources import Cost, Resources
from agricola.scoring import SCORING_TERMS
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_grid


def _score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == "land_register")


def test_registration():
    spec = MINORS["land_register"]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert any(cid == "land_register" for cid, _ in SCORING_TERMS)


def test_default_farm_has_unused_spaces():
    # Starting farm: 2 rooms, 13 empty cells -> unused -> 0.
    state = setup(seed=0)
    assert _score_fn()(state, 0) == 0


def test_partially_filled_still_zero():
    state = setup(seed=0)
    state = with_grid(state, 0, {
        (r, c): Cell(cell_type=CellType.FIELD) for r in range(3) for c in range(4)
    })  # column 4 still empty
    assert _score_fn()(state, 0) == 0


def test_all_cells_used_scores_two():
    state = setup(seed=0)
    state = with_grid(state, 0, {
        (r, c): Cell(cell_type=CellType.FIELD) for r in range(3) for c in range(5)
    })
    assert _score_fn()(state, 0) == 2
