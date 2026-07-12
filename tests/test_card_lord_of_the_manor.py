"""Tests for Lord of the Manor (occupation, D100; Dulcinaria Expansion).

Card text: "During scoring, you get 1 bonus point for each scoring category in
which you score the maximum 4 points. (The bonus point is also awarded for 4
fenced stables.)"

A pure end-game scoring occupation (no on-play effect): +1 bonus point for each
of the eight max-4-capped categories (field tiles, pastures, grain, vegetables,
sheep, boar, cattle, fenced stables) in which the player scores the full 4.
"""
import agricola.cards.lord_of_the_manor  # noqa: F401  (registers the card)
import agricola.cards.beanfield  # noqa: F401  (registers the card-fields below)
import agricola.cards.crop_rotation_field  # noqa: F401
import agricola.cards.wood_field  # noqa: F401

import dataclasses

from agricola.cards.card_fields import stacks_to_store
from agricola.cards.lord_of_the_manor import CARD_ID, _score
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import CellType, HouseMaterial
from agricola.pasture import Pasture
from agricola.scoring import SCORING_TERMS, score
from agricola.setup import setup
from agricola.state import Cell
from tests.factories import (
    with_animals,
    with_grid,
    with_house,
    with_majors,
    with_people,
    with_resources,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base():
    """A fresh round-1 state."""
    return setup(seed=5)


def _own(state, idx):
    p = state.players[idx]
    return dataclasses.replace(state, players=tuple(
        dataclasses.replace(p, occupations=p.occupations | {CARD_ID}) if i == idx
        else state.players[i] for i in range(2)))


def _with_pastures(state, idx, pastures):
    """Set player idx's farmyard pasture decomposition directly."""
    p = state.players[idx]
    fy = dataclasses.replace(p.farmyard, pastures=tuple(pastures))
    return dataclasses.replace(state, players=tuple(
        dataclasses.replace(p, farmyard=fy) if i == idx
        else state.players[i] for i in range(2)))


def _scorer():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


def _pasture(cells, num_stables=0):
    return Pasture(cells=frozenset(cells), num_stables=num_stables,
                   capacity=2 * len(cells) * (2 ** num_stables))


def _own_minor(state, idx, card_id):
    """Give player idx a minor improvement (a card-field card)."""
    p = state.players[idx]
    return dataclasses.replace(state, players=tuple(
        dataclasses.replace(p, minor_improvements=p.minor_improvements | {card_id})
        if i == idx else state.players[i] for i in range(2)))


def _set_stacks(state, idx, cid, stacks):
    """Write a card-field's per-stack (grain, veg, wood, stone) contents."""
    p = state.players[idx]
    p = dataclasses.replace(p, card_state=stacks_to_store(p.card_state, cid, stacks))
    return dataclasses.replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    spec = OCCUPATIONS[CARD_ID]
    # Pure scoring occupation: no cost / prereq / vps surfaced.
    assert getattr(spec, "vps", 0) == 0
    # Registered as an end-game scoring term.
    assert CARD_ID in {cid for cid, _ in SCORING_TERMS}


def test_no_on_play_effect():
    s = _base()
    s = with_resources(s, 0, wood=3, clay=2, grain=1)
    before = s.players[0].resources
    s2 = _own(s, 0)
    # Owning the occupation changes nothing on play.
    assert s2.players[0].resources == before
    assert s2.players[0].farmyard == s.players[0].farmyard


# ---------------------------------------------------------------------------
# No category at maximum -> 0 bonus points
# ---------------------------------------------------------------------------

def test_zero_when_no_category_maxed():
    s = _base()
    # A small, sub-max farm: 1 field, no pastures, a little grain/veg, few animals.
    s = with_grid(s, 0, {(0, 0): Cell(cell_type=CellType.FIELD)})
    s = with_resources(s, 0, grain=2, veg=1)
    s = with_animals(s, 0, sheep=1, boar=1, cattle=1)
    assert _score(s, 0) == 0


# ---------------------------------------------------------------------------
# Each individual max-4 category, in isolation, awards exactly 1 bonus point
# ---------------------------------------------------------------------------

def test_field_tiles_max_awards_one():
    s = _base()
    # 5 field tiles -> field_tiles scores 4.
    s = with_grid(s, 0, {(r, c): Cell(cell_type=CellType.FIELD)
                         for (r, c) in [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)]})
    assert _score(s, 0) == 1


def test_grain_max_awards_one():
    s = _base()
    # 8 grain in supply -> grain scores 4. (Threshold: >7.)
    s = with_resources(s, 0, grain=8)
    assert _score(s, 0) == 1


def test_grain_includes_grain_on_fields():
    s = _base()
    # 6 supply + a field carrying 3 grain = 9 total -> grain scores 4.
    s = with_grid(s, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=3)})
    s = with_resources(s, 0, grain=6)
    # The field tile alone (1 field) is NOT maxed, so the only maxed category is grain.
    assert _score(s, 0) == 1


def test_veg_max_awards_one():
    s = _base()
    s = with_resources(s, 0, veg=4)  # >=4 -> veg scores 4
    assert _score(s, 0) == 1


def test_sheep_max_awards_one():
    s = _base()
    s = with_animals(s, 0, sheep=8)  # >7 -> sheep scores 4
    assert _score(s, 0) == 1


def test_boar_max_awards_one():
    s = _base()
    s = with_animals(s, 0, boar=7)  # >6 -> boar scores 4
    assert _score(s, 0) == 1


def test_cattle_max_awards_one():
    s = _base()
    s = with_animals(s, 0, cattle=6)  # >5 -> cattle scores 4
    assert _score(s, 0) == 1


def test_pastures_max_awards_one():
    s = _base()
    # 4 distinct single-cell pastures -> pastures scores 4 (min(n,4)).
    pastures = [
        _pasture([(0, 0)]),
        _pasture([(0, 1)]),
        _pasture([(0, 2)]),
        _pasture([(0, 3)]),
    ]
    s = _with_pastures(s, 0, pastures)
    assert _score(s, 0) == 1


def test_fenced_stables_max_awards_one():
    s = _base()
    # 4 stable cells, each enclosed in a pasture -> fenced_stables scores 4.
    cells = [(0, 0), (0, 1), (0, 2), (0, 3)]
    s = with_grid(s, 0, {c: Cell(cell_type=CellType.STABLE) for c in cells})
    s = _with_pastures(s, 0, [_pasture([c], num_stables=1) for c in cells])
    # The four single-cell pastures also max the pastures category, so 2 maxed.
    assert _score(s, 0) == 2


# ---------------------------------------------------------------------------
# Boundary: one short of the max scores no bonus point
# ---------------------------------------------------------------------------

def test_grain_one_short_no_bonus():
    s = _base()
    s = with_resources(s, 0, grain=7)  # 7 -> grain scores 3 (max is >7)
    assert _score(s, 0) == 0


def test_pastures_three_no_bonus():
    s = _base()
    pastures = [_pasture([(0, 0)]), _pasture([(0, 1)]), _pasture([(0, 2)])]
    s = _with_pastures(s, 0, pastures)  # 3 pastures -> scores 3, not 4
    assert _score(s, 0) == 0


def test_fenced_stables_three_no_bonus():
    s = _base()
    cells = [(0, 0), (0, 1), (0, 2)]
    s = with_grid(s, 0, {c: Cell(cell_type=CellType.STABLE) for c in cells})
    s = _with_pastures(s, 0, [_pasture([c], num_stables=1) for c in cells])
    # 3 fenced stables -> not maxed; 3 pastures -> not maxed.
    assert _score(s, 0) == 0


# ---------------------------------------------------------------------------
# Card-fields (ruling 45, 2026-07-12): the Fields category and the grain/veg
# totals count card-fields, exactly as scoring.score() does — the mirror in
# _category_point_values must stay in lockstep with it
# ---------------------------------------------------------------------------

def test_fields_category_maxed_only_via_card_field():
    """4 grid fields score 3; owning Beanfield (even unplanted) makes the 5th
    field, pushing the Fields category to its 4-point max -> the bonus point.
    The grid-only mirror saw 4 fields -> 3 points -> no bonus."""
    s = _base()
    s = with_grid(s, 0, {(r, c): Cell(cell_type=CellType.FIELD)
                         for (r, c) in [(0, 0), (0, 1), (0, 2), (0, 3)]})
    assert _score(s, 0) == 0  # 4 fields -> 3 points, not maxed
    s = _own_minor(s, 0, "beanfield")
    assert _score(s, 0) == 1  # 5th field via the card-field -> maxed


def test_multi_stack_card_field_counts_once_and_wood_is_not_grain():
    """Ruling 47: Wood Field (2 stacks) is "considered 1 field" — 3 grid fields
    + Wood Field = 4 fields -> 3 points, NOT maxed (counting it as 2 fields
    would wrongly max the category). Its planted wood is also not grain: the
    grain total stays 0."""
    s = _base()
    s = with_grid(s, 0, {(r, c): Cell(cell_type=CellType.FIELD)
                         for (r, c) in [(0, 0), (0, 1), (0, 2)]})
    s = _own_minor(s, 0, "wood_field")
    s = _set_stacks(s, 0, "wood_field", [(0, 0, 3, 0), (0, 0, 3, 0)])
    assert _score(s, 0) == 0


def test_grain_category_maxed_via_card_field_crops():
    """6 supply grain + 3 grain planted on Crop Rotation Field = 9 -> the grain
    category's 4-point max (threshold >7). Grid-only counting saw 6 -> 3."""
    s = _base()
    s = with_resources(s, 0, grain=6)
    s = _own_minor(s, 0, "crop_rotation_field")
    s = _set_stacks(s, 0, "crop_rotation_field", [(3, 0, 0, 0)])
    # Only grain is maxed (1 field -> -1; nothing else held).
    assert _score(s, 0) == 1


def test_veg_category_maxed_via_card_field_crops():
    """2 supply veg + 2 veg planted on Beanfield = 4 -> the veg category's
    4-point max. Grid-only counting saw 2 -> 2 points."""
    s = _base()
    s = with_resources(s, 0, veg=2)
    s = _own_minor(s, 0, "beanfield")
    s = _set_stacks(s, 0, "beanfield", [(0, 2, 0, 0)])
    # Only veg is maxed (1 field -> -1; nothing else held).
    assert _score(s, 0) == 1


# ---------------------------------------------------------------------------
# Categories NOT capped at 4 are excluded (rooms / people / majors)
# ---------------------------------------------------------------------------

def test_excluded_categories_do_not_count():
    s = _base()
    # 5 stone rooms (worth 10 pts), 4 people (12 pts), and a major — none of which
    # is a "max 4" category, so they must contribute 0 to the bonus.
    s = with_grid(s, 0, {(r, c): Cell(cell_type=CellType.ROOM)
                         for (r, c) in [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1)]})
    s = with_house(s, 0, HouseMaterial.STONE)
    s = with_people(s, 0, total=4, home=4)
    s = with_majors(s, owner_by_idx={4: 0})  # the 4-point major improvement
    assert _score(s, 0) == 0


# ---------------------------------------------------------------------------
# All eight categories maxed simultaneously -> 8 bonus points
# ---------------------------------------------------------------------------

def test_all_eight_categories_maxed():
    s = _base()
    # 5 fields (field_tiles=4), 8 grain + 4 veg in supply.
    field_cells = [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)]
    s = with_grid(s, 0, {c: Cell(cell_type=CellType.FIELD) for c in field_cells})
    s = with_resources(s, 0, grain=8, veg=4)
    s = with_animals(s, 0, sheep=8, boar=7, cattle=6)
    # 4 fenced stables (each its own pasture) -> pastures=4 AND fenced_stables=4.
    stable_cells = [(1, 0), (1, 1), (1, 2), (1, 3)]
    s = with_grid(s, 0, {c: Cell(cell_type=CellType.STABLE) for c in stable_cells})
    s = _with_pastures(s, 0, [_pasture([c], num_stables=1) for c in stable_cells])
    assert _score(s, 0) == 8


# ---------------------------------------------------------------------------
# Scoping: only the owner gets the bonus, and it shows up in score()
# ---------------------------------------------------------------------------

def test_only_owner_scores_via_score():
    s = _base()
    # Give P0 a maxed grain category; P0 owns the card, P1 does not.
    s = with_resources(s, 0, grain=8)
    s = with_resources(s, 1, grain=8)
    s = _own(s, 0)

    total0, bd0 = score(s, 0)
    total1, bd1 = score(s, 1)
    # P0's card_points include the +1 bonus; P1's do not.
    assert bd0.card_points == 1
    assert bd1.card_points == 0
    # And the +1 is reflected in P0's total relative to the same farm without it.
    s_noown = dataclasses.replace(s, players=tuple(
        dataclasses.replace(s.players[i], occupations=frozenset()) for i in range(2)))
    total0_noown, _ = score(s_noown, 0)
    assert total0 == total0_noown + 1


def test_score_does_not_recurse():
    # Smoke test: score() must terminate (the term must not call score()).
    s = _base()
    s = with_resources(s, 0, grain=8, veg=4)
    s = _own(s, 0)
    total, bd = score(s, 0)  # would hang/recurse if _score called score()
    assert isinstance(total, int)
    assert bd.card_points == 2  # grain + veg maxed
