"""Tests for Storeroom (minor improvement, D31; Dulcinaria Expansion).

Card text: "During scoring, you get 1/2 bonus point for each pair of grain plus
vegetable you have (considering all crops in your supply and fields), rounded up."
Cost: 1 Wood, 2 Stone. Printed VPs: 1.

A pure end-game scoring minor (no on-play, no prereq, no passing). Pool grain +
vegetables across supply and field cells: pairs = total // 2, bonus points =
ceil(pairs / 2). Plus the 1 printed VP whenever the card is kept.
"""
import agricola.cards.storeroom  # noqa: F401  (registers the card)

import dataclasses

from agricola.cards.specs import MINORS
from agricola.cards.storeroom import CARD_ID, _pooled_crops, _score
from agricola.constants import CellType
from agricola.resources import Resources
from agricola.scoring import SCORING_TERMS, score
from agricola.setup import setup
from agricola.state import Cell
from tests.factories import with_grid, with_resources


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base():
    """A fresh round-1 state with empty supplies for both players (so the only
    crops in play are the ones a test sets up)."""
    s = setup(seed=5)
    s = with_resources(s, 0, grain=0, veg=0)
    s = with_resources(s, 1, grain=0, veg=0)
    return s


def _own(state, idx):
    """Give player idx the Storeroom minor improvement."""
    p = state.players[idx]
    return dataclasses.replace(state, players=tuple(
        dataclasses.replace(p, minor_improvements=p.minor_improvements | {CARD_ID})
        if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    # Printed 1 VP, no prereq / passing.
    assert spec.vps == 1
    assert spec.prereq is None
    assert spec.passing_left is False
    # Cost 1 wood + 2 stone.
    assert spec.cost.resources == Resources(wood=1, stone=2)
    # Registered as an end-game scoring term.
    assert CARD_ID in {cid for cid, _ in SCORING_TERMS}


# ---------------------------------------------------------------------------
# The pooled-crop count (supply + field cells only)
# ---------------------------------------------------------------------------

def test_pool_counts_supply_grain_and_veg():
    s = _base()
    s = with_resources(s, 0, grain=5, veg=4)
    assert _pooled_crops(s, 0) == 9


def test_pool_counts_crops_on_field_cells():
    s = _base()
    # Supply 2 grain + 1 veg, plus a field carrying 3 grain and another 2 veg.
    s = with_resources(s, 0, grain=2, veg=1)
    s = with_grid(s, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 1): Cell(cell_type=CellType.FIELD, veg=2),
    })
    assert _pooled_crops(s, 0) == 2 + 1 + 3 + 2  # == 8


def test_pool_ignores_crops_on_non_field_cells():
    s = _base()
    # Crops sitting on a non-FIELD cell are NOT counted (only FIELD cells).
    s = with_resources(s, 0, grain=1)
    s = with_grid(s, 0, {(0, 0): Cell(cell_type=CellType.ROOM, grain=4, veg=4)})
    assert _pooled_crops(s, 0) == 1


# ---------------------------------------------------------------------------
# The bonus math: pairs = total // 2, points = ceil(pairs / 2)
# ---------------------------------------------------------------------------

def test_zero_crops_zero_points():
    s = _base()
    assert _score(s, 0) == 0


def test_one_crop_zero_points():
    # 1 crop -> 0 pairs -> 0 points.
    s = _base()
    s = with_resources(s, 0, grain=1)
    assert _score(s, 0) == 0


def test_two_crops_one_pair_one_point():
    # 2 crops -> 1 pair -> ceil(1/2) = 1 point.
    s = _base()
    s = with_resources(s, 0, grain=1, veg=1)
    assert _score(s, 0) == 1


def test_three_crops_one_pair_one_point():
    # 3 crops -> 1 pair (odd leftover unpaired) -> ceil(1/2) = 1 point.
    s = _base()
    s = with_resources(s, 0, grain=3)
    assert _score(s, 0) == 1


def test_four_crops_two_pairs_one_point():
    # 4 crops -> 2 pairs -> ceil(2/2) = 1 point.
    s = _base()
    s = with_resources(s, 0, grain=2, veg=2)
    assert _score(s, 0) == 1


def test_nine_crops_four_pairs_two_points():
    # 5 grain + 4 veg = 9 crops -> 4 pairs -> ceil(4/2) = 2 points (card example).
    s = _base()
    s = with_resources(s, 0, grain=5, veg=4)
    assert _score(s, 0) == 2


def test_six_crops_three_pairs_two_points():
    # 6 crops -> 3 pairs -> ceil(3/2) = 2 points.
    s = _base()
    s = with_resources(s, 0, grain=3, veg=3)
    assert _score(s, 0) == 2


def test_bonus_includes_field_crops():
    s = _base()
    # 4 supply grain + a field carrying 4 veg = 8 crops -> 4 pairs -> 2 points.
    s = with_resources(s, 0, grain=4)
    s = with_grid(s, 0, {(0, 0): Cell(cell_type=CellType.FIELD, veg=4)})
    assert _score(s, 0) == 2


# ---------------------------------------------------------------------------
# Scoping: only the owner gets the term + printed VP, surfaced via score()
# ---------------------------------------------------------------------------

def test_only_owner_scores_via_score():
    s = _base()
    # Both players have 9 crops, but only P0 owns Storeroom.
    s = with_resources(s, 0, grain=5, veg=4)
    s = with_resources(s, 1, grain=5, veg=4)
    s = _own(s, 0)

    _, bd0 = score(s, 0)
    _, bd1 = score(s, 1)
    # P0: 2 bonus points + 1 printed VP = 3 card_points; P1 owns nothing -> 0.
    assert bd0.card_points == 3
    assert bd1.card_points == 0


def test_owner_total_reflects_bonus_plus_vp():
    s = _base()
    s = with_resources(s, 0, grain=5, veg=4)  # 2 bonus points
    s = _own(s, 0)

    total_own, _ = score(s, 0)
    # Same farm without the card: lose the 2 bonus points AND the 1 printed VP.
    s_noown = dataclasses.replace(s, players=tuple(
        dataclasses.replace(s.players[i], minor_improvements=frozenset())
        for i in range(2)))
    total_noown, _ = score(s_noown, 0)
    assert total_own == total_noown + 3


def test_owner_with_no_crops_still_scores_printed_vp():
    s = _base()
    s = _own(s, 0)
    _, bd = score(s, 0)
    # 0 crops -> 0 bonus points, but the printed 1 VP is still kept.
    assert bd.card_points == 1


def test_score_does_not_recurse():
    # Smoke test: score() must terminate (the term must not call score()).
    s = _base()
    s = with_resources(s, 0, grain=5, veg=4)
    s = _own(s, 0)
    total, bd = score(s, 0)
    assert isinstance(total, int)
    assert bd.card_points == 3
