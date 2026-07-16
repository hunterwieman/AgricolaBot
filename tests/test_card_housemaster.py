"""Tests for Housemaster (occupation, B153; Bubulcus Expansion; players 4+).

Card text: "During scoring, total the point values of your major improvements. The
smallest value counts double. If the total is at least 5/7/9/11, you get 1/2/3/4
bonus points."

Point values are the printed major VPs (Fireplace/Hearth 1, Clay Oven 2, Stone
Oven 3, Well 4, Joinery/Pottery/Basketmaker 2 — user ruling 2026-07-15).
"""
import agricola.cards.housemaster  # noqa: F401  (registers the card)

from agricola.cards.housemaster import CARD_ID, _score
from agricola.cards.specs import OCCUPATIONS
from agricola.scoring import SCORING_TERMS
from agricola.setup import CardPool, setup_env
from tests.factories import with_majors

_POOL = CardPool(occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
                 minors=tuple(f"m{i}" for i in range(20)))

# Fireplace 0 (1), Cooking Hearth 2 (1), Well 4 (4), Clay Oven 5 (2), Stone Oven 6 (3),
# Joinery 7 (2), Pottery 8 (2), Basketmaker 9 (2).


def _majors(*idxs):
    cs, _ = setup_env(0, card_pool=_POOL)
    return with_majors(cs, owner_by_idx={i: 0 for i in idxs}) if idxs else cs


def test_registration():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in {cid for cid, _fn in SCORING_TERMS}


def test_no_majors_is_zero():
    assert _score(_majors(), 0) == 0


def test_below_threshold():
    assert _score(_majors(0), 0) == 0          # [1] -> 1 + 1 = 2
    assert _score(_majors(0, 2), 0) == 0       # [1,1] -> 2 + 1 = 3


def test_smallest_counts_double_across_the_tiers():
    assert _score(_majors(4), 0) == 2          # [4] -> 4 + 4 = 8  (>=7)
    assert _score(_majors(4, 0), 0) == 1       # [4,1] -> 5 + 1 = 6  (>=5)
    assert _score(_majors(4, 5), 0) == 2       # [4,2] -> 6 + 2 = 8  (>=7)
    assert _score(_majors(4, 6, 2), 0) == 3    # [4,3,1] -> 8 + 1 = 9  (>=9)
    assert _score(_majors(4, 6, 7), 0) == 4    # [4,3,2] -> 9 + 2 = 11 (>=11)


def test_joinery_pottery_basketmaker_are_worth_two():
    # If J/P/B counted base+earned bonus they'd exceed 2; the printed 2 gives:
    assert _score(_majors(7, 8), 0) == 1       # [2,2] -> 4 + 2 = 6  (>=5)
