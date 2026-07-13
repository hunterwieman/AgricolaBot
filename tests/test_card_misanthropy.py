"""Tests for Misanthropy (minor E35): exactly 4/3/2 people -> 2/3/5 bonus points."""
import agricola.cards.misanthropy  # noqa: F401  (registers the card)

from agricola.cards.specs import MINORS
from agricola.resources import Cost, Resources
from agricola.scoring import SCORING_TERMS
from agricola.setup import setup

from tests.factories import with_people


def _score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == "misanthropy")


def test_registration():
    spec = MINORS["misanthropy"]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert any(cid == "misanthropy" for cid, _ in SCORING_TERMS)


def test_points_by_people_count():
    state = setup(seed=0)
    score = _score_fn()
    assert score(with_people(state, 0, total=2), 0) == 5
    assert score(with_people(state, 0, total=3), 0) == 3
    assert score(with_people(state, 0, total=4), 0) == 2
    # A full family of 5 (or fewer than 2) scores nothing.
    assert score(with_people(state, 0, total=5), 0) == 0
