"""Tests for Milking Parlor (minor improvement, A57; Artifex Expansion).

Card text: "When you play this card, if you have at least 1/3/4 sheep, you
immediately get 2/3/4 food. The same applies if you have at least 1/2/3 cattle."
Cost 2 wood; prereq "At Least 4 Unused Farmyard Spaces"; 1 printed VP.

The two clauses are independent and additive, with DIFFERENT (banded) ladders:
  sheep : >=1 -> 2 food, >=3 -> 3 food, >=4 -> 4 food
  cattle: >=1 -> 2 food, >=2 -> 3 food, >=3 -> 4 food
"""
import agricola.cards.milking_parlor  # noqa: F401  (registers the card)

import pytest

from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import CellType
from agricola.engine import step
from agricola.helpers import enclosed_cells
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell
from tests.factories import with_grid
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("milking_parlor",) + tuple(f"m{i}" for i in range(20)),
)


def _state(seed=5, *, cp_minors=frozenset(), cp_res=None, animals=None):
    """A 2-player card state with the current player's hand / resources / animals
    set (opponent's hand cleared so circulation asserts are unambiguous)."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = cs.players[cp]
    changes = {"hand_minors": cp_minors}
    if cp_res is not None:
        changes["resources"] = cp_res
    if animals is not None:
        changes["animals"] = animals
    p = fast_replace(p, **changes)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


def _fill_to_n_unused(cs, cp, n_unused):
    """Plow FIELDs over EMPTY cells until exactly `n_unused` farmyard cells remain
    unused (the default farm has 2 rooms -> 13 unused). FIELD cells are 'used'."""
    fy = cs.players[cp].farmyard
    empties = [
        (r, c)
        for r in range(3)
        for c in range(5)
        if fy.grid[r][c].cell_type is CellType.EMPTY
    ]
    # Default 13 empties; fill (13 - n_unused) of them with FIELDs.
    to_fill = empties[: len(empties) - n_unused]
    overrides = {rc: Cell(cell_type=CellType.FIELD) for rc in to_fill}
    return with_grid(cs, cp, overrides)


def _push_minor(cs, cp):
    return fast_replace(
        cs,
        pending_stack=(
            PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),
        ),
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert "milking_parlor" in MINORS
    spec = MINORS["milking_parlor"]
    assert spec.cost == Cost(resources=Resources(wood=2))
    assert spec.vps == 1
    assert spec.passing_left is False
    assert spec.min_occupations == 0


# ---------------------------------------------------------------------------
# Prerequisite: at least 4 unused farmyard spaces
# ---------------------------------------------------------------------------

def test_prereq_met_when_four_or_more_unused():
    spec = MINORS["milking_parlor"]
    cs, cp = _state()  # default farm: 13 unused
    assert prereq_met(spec, cs, cp)
    cs2 = _fill_to_n_unused(cs, cp, 4)
    assert prereq_met(spec, cs2, cp)


def test_prereq_unmet_when_fewer_than_four_unused():
    spec = MINORS["milking_parlor"]
    cs, cp = _state()
    cs3 = _fill_to_n_unused(cs, cp, 3)
    assert not prereq_met(spec, cs3, cp)
    cs0 = _fill_to_n_unused(cs, cp, 0)
    assert not prereq_met(spec, cs0, cp)


def test_prereq_counts_fenced_empty_pasture_cells_as_used():
    """A fenced-but-empty pasture cell reads cell_type EMPTY but is a USED space,
    so it must NOT count toward the 4-unused prereq."""
    from agricola.pasture import compute_pastures_from_arrays

    spec = MINORS["milking_parlor"]
    cs, cp = _state()
    # Leave exactly 4 EMPTY+unfenced cells, then fence one of them into a 1x1
    # pasture so only 3 truly-unused remain -> prereq should FAIL.
    cs = _fill_to_n_unused(cs, cp, 4)
    fy = cs.players[cp].farmyard
    empties = [
        (r, c)
        for r in range(3)
        for c in range(5)
        if fy.grid[r][c].cell_type is CellType.EMPTY
    ]
    assert len(empties) == 4
    # Fence the first empty cell on all 4 sides (a 1x1 enclosure).
    # horizontal_fences: 4 rows x 5 cols (edges above/below each cell);
    # vertical_fences:  3 rows x 6 cols (edges left/right of each cell).
    r, c = empties[0]
    h = [list(row) for row in fy.horizontal_fences]
    v = [list(row) for row in fy.vertical_fences]
    h[r][c] = True          # top edge of (r, c)
    h[r + 1][c] = True      # bottom edge of (r, c)
    v[r][c] = True          # left edge of (r, c)
    v[r][c + 1] = True      # right edge of (r, c)
    hf = tuple(tuple(row) for row in h)
    vf = tuple(tuple(row) for row in v)
    new_fy = fast_replace(
        fy,
        horizontal_fences=hf,
        vertical_fences=vf,
        pastures=compute_pastures_from_arrays(fy.grid, hf, vf),
    )
    assert (r, c) in enclosed_cells(new_fy)  # the cell is now a pasture
    p = fast_replace(cs.players[cp], farmyard=new_fy)
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    # Now only 3 cells are EMPTY-and-unfenced -> prereq fails.
    assert not prereq_met(spec, cs, cp)


# ---------------------------------------------------------------------------
# Sheep / cattle ladders (banded, independent, additive)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "sheep,expected",
    [(0, 0), (1, 2), (2, 2), (3, 3), (4, 4), (10, 4)],
)
def test_sheep_ladder(sheep, expected):
    from agricola.cards.milking_parlor import _sheep_food
    assert _sheep_food(sheep) == expected


@pytest.mark.parametrize(
    "cattle,expected",
    [(0, 0), (1, 2), (2, 3), (3, 4), (10, 4)],
)
def test_cattle_ladder(cattle, expected):
    from agricola.cards.milking_parlor import _cattle_food
    assert _cattle_food(cattle) == expected


# ---------------------------------------------------------------------------
# playable_minors gates on prereq + cost (real legality path)
# ---------------------------------------------------------------------------

def test_playable_only_when_prereq_and_cost_met():
    # Holds the card, has 2 wood, 13 unused -> playable.
    cs, cp = _state(cp_minors=frozenset({"milking_parlor"}), cp_res=Resources(wood=2))
    assert playable_minors(cs, cp) == ["milking_parlor"]
    # No wood -> cost unaffordable.
    cs, cp = _state(cp_minors=frozenset({"milking_parlor"}), cp_res=Resources(wood=1))
    assert playable_minors(cs, cp) == []
    # Prereq unmet (only 3 unused) -> not playable even with the wood.
    cs, cp = _state(cp_minors=frozenset({"milking_parlor"}), cp_res=Resources(wood=2))
    cs = _fill_to_n_unused(cs, cp, 3)
    assert playable_minors(cs, cp) == []


# ---------------------------------------------------------------------------
# On-play food grant via a real engine flow
# ---------------------------------------------------------------------------

def _play_and_food_delta(*, sheep=0, cattle=0):
    cs, cp = _state(
        cp_minors=frozenset({"milking_parlor"}),
        cp_res=Resources(wood=2),
        animals=Animals(sheep=sheep, cattle=cattle),
    )
    food0 = cs.players[cp].resources.food
    cs = _push_minor(cs, cp)
    assert legal_actions(cs) == [sole_play_minor(cs, "milking_parlor")]
    cs = step(cs, sole_play_minor(cs, "milking_parlor"))
    p = cs.players[cp]
    # Kept (not passing), wood spent.
    assert "milking_parlor" in p.minor_improvements
    assert p.resources.wood == 0
    return p.resources.food - food0


def test_play_grants_food_sheep_only():
    assert _play_and_food_delta(sheep=4) == 4
    assert _play_and_food_delta(sheep=1) == 2


def test_play_grants_food_cattle_only():
    assert _play_and_food_delta(cattle=2) == 3
    assert _play_and_food_delta(cattle=3) == 4


def test_play_grants_food_additive():
    # sheep>=3 -> 3 food ; cattle>=1 -> 2 food ; total 5.
    assert _play_and_food_delta(sheep=3, cattle=1) == 5
    # sheep>=4 -> 4 ; cattle>=3 -> 4 ; total 8 (max).
    assert _play_and_food_delta(sheep=4, cattle=3) == 8


def test_play_grants_no_food_without_qualifying_animals():
    assert _play_and_food_delta(sheep=0, cattle=0) == 0
