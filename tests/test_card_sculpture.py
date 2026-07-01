"""Tests for Sculpture (minor improvement, D37; Consul Dirigens Expansion).

Card text: "You can only play this card if there are more complete rounds left to
play than you have unused farmyard spaces."
Cost: 1 Stone. VPs: 2. Not passing. No on-play effect.

A printed-VP minor (Category 1) whose only bespoke logic is its play prerequisite:
a STRICT comparison `(14 - round_number) > unused_farmyard_spaces`, where an unused
space is an EMPTY cell that is NOT enclosed by fences (a fenced-but-empty pasture
cell counts as USED). The 2 VPs are the printed yellow circle, auto-summed at
scoring time, so there is no derived scoring term.

The module import below is what registers the card (it is not in cards/__init__.py).
"""
import agricola.cards.sculpture  # noqa: F401

from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.sculpture import (
    CARD_ID,
    _complete_rounds_left,
    _unused_farmyard_spaces,
)
from agricola.constants import CellType
from agricola.pasture import compute_pastures_from_arrays
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import SCORING_TERMS
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


def _set_round(state, round_number):
    return fast_replace(state, round_number=round_number)


def _fill_all_but(state, idx, keep_empty):
    """Make every farmyard cell a ROOM except the `keep_empty` set of coords.

    Used to control the unused-space count: after this, exactly `len(keep_empty)`
    cells are EMPTY and unenclosed (= unused)."""
    p = state.players[idx]
    grid = p.farmyard.grid
    new_grid = tuple(
        tuple(
            grid[r][c] if (r, c) in keep_empty else Cell(cell_type=CellType.ROOM)
            for c in range(5)
        )
        for r in range(3)
    )
    fy = fast_replace(p.farmyard, grid=new_grid)
    p = fast_replace(p, farmyard=fy)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _enclose_cell(state, idx, cell):
    """Fence (cell) into its own 1x1 pasture: set all 4 surrounding edges and
    recompute the pasture cache. The cell stays EMPTY (cell_type unchanged) but
    becomes enclosed."""
    p = state.players[idx]
    fy = p.farmyard
    r, c = cell
    h = [list(row) for row in fy.horizontal_fences]   # shape (4, 5)
    v = [list(row) for row in fy.vertical_fences]      # shape (3, 6)
    h[r][c] = True          # top edge of the cell
    h[r + 1][c] = True      # bottom edge
    v[r][c] = True          # left edge
    v[r][c + 1] = True      # right edge
    h_t = tuple(tuple(row) for row in h)
    v_t = tuple(tuple(row) for row in v)
    new_pastures = compute_pastures_from_arrays(fy.grid, h_t, v_t)
    fy = fast_replace(fy, horizontal_fences=h_t, vertical_fences=v_t,
                      pastures=new_pastures)
    p = fast_replace(p, farmyard=fy)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_minor():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(stone=1))
    assert spec.vps == 2
    assert spec.passing_left is False
    assert spec.prereq is not None


def test_no_derived_scoring_term():
    # The 2 VPs are the printed circle (auto-summed); there is no bespoke
    # register_scoring term for this card.
    assert CARD_ID not in {cid for cid, _fn in SCORING_TERMS}


# ---------------------------------------------------------------------------
# Helper unit checks
# ---------------------------------------------------------------------------

def test_complete_rounds_left():
    s = _card_state()
    assert _complete_rounds_left(_set_round(s, 1)) == 13
    assert _complete_rounds_left(_set_round(s, 10)) == 4
    assert _complete_rounds_left(_set_round(s, 14)) == 0


def test_unused_counts_empty_unenclosed_only():
    # Setup farm: 2 rooms at (1,0),(2,0) → 13 empty unenclosed = 13 unused.
    s = _card_state()
    assert _unused_farmyard_spaces(s, 0) == 13


def test_non_empty_cells_are_used():
    # Leave exactly 4 cells empty; the rest become ROOM → 4 unused.
    s = _card_state()
    keep = {(0, 0), (0, 1), (0, 2), (0, 3)}
    s = _fill_all_but(s, 0, keep)
    assert _unused_farmyard_spaces(s, 0) == 4


def test_fenced_empty_pasture_cell_counts_as_used():
    # Leave 3 cells empty; fence one of them into a 1x1 pasture. The fenced cell
    # is EMPTY but enclosed → it is USED, so unused drops from 3 to 2.
    s = _card_state()
    keep = {(0, 0), (0, 1), (0, 2)}
    s = _fill_all_but(s, 0, keep)
    assert _unused_farmyard_spaces(s, 0) == 3
    s = _enclose_cell(s, 0, (0, 0))
    # Sanity: the fenced cell is still EMPTY, not a pasture CellType.
    assert s.players[0].farmyard.grid[0][0].cell_type is CellType.EMPTY
    assert (0, 0) in {c for p in s.players[0].farmyard.pastures for c in p.cells}
    assert _unused_farmyard_spaces(s, 0) == 2


# ---------------------------------------------------------------------------
# The prerequisite (strict >)
# ---------------------------------------------------------------------------

def test_prereq_strict_greater_than():
    spec = MINORS[CARD_ID]
    s = _card_state()
    # Control: 2 unused spaces, vary the round.
    s2 = _fill_all_but(s, 0, {(0, 0), (0, 1)})
    assert _unused_farmyard_spaces(s2, 0) == 2

    # rounds_left == unused → NOT playable (strict, not >=).
    # 14 - round_number == 2  →  round_number == 12.
    equal = _set_round(s2, 12)
    assert _complete_rounds_left(equal) == 2
    assert not prereq_met(spec, equal, 0)

    # rounds_left > unused → playable.  14 - 11 == 3 > 2.
    more = _set_round(s2, 11)
    assert _complete_rounds_left(more) == 3
    assert prereq_met(spec, more, 0)

    # rounds_left < unused → NOT playable.  14 - 13 == 1 < 2.
    fewer = _set_round(s2, 13)
    assert _complete_rounds_left(fewer) == 1
    assert not prereq_met(spec, fewer, 0)


def test_prereq_zero_unused_always_playable_with_rounds_left():
    # A full farm (0 unused) is playable in any round that has >=1 complete round
    # left, but not in round 14 (0 left, 0 > 0 is False).
    spec = MINORS[CARD_ID]
    s = _fill_all_but(_card_state(), 0, set())   # every cell a ROOM
    assert _unused_farmyard_spaces(s, 0) == 0
    assert prereq_met(spec, _set_round(s, 13), 0)     # 1 > 0
    assert not prereq_met(spec, _set_round(s, 14), 0)  # 0 > 0 is False


def test_prereq_is_per_player():
    # Player 0's farm should not affect player 1's prereq read.
    spec = MINORS[CARD_ID]
    s = _set_round(_card_state(), 5)   # 9 complete rounds left
    # P0 fills its farm (0 unused); P1 keeps the default 13 unused.
    s = _fill_all_but(s, 0, set())
    assert prereq_met(spec, s, 0)              # 9 > 0
    assert not prereq_met(spec, s, 1)          # 9 > 13 is False


# ---------------------------------------------------------------------------
# Scoring: 2 VPs flow through the minor's printed vps
# ---------------------------------------------------------------------------

def test_vps_two_in_scoring():
    from agricola.scoring import score
    base = _card_state()
    base = fast_replace(base, current_player=0)
    p = base.players[0]
    owned = fast_replace(base, players=tuple(
        fast_replace(p, minor_improvements=p.minor_improvements | {CARD_ID})
        if i == 0 else base.players[i] for i in range(2)))
    total_base, _ = score(base, 0)
    total_owned, _ = score(owned, 0)
    assert total_owned == total_base + 2


# ---------------------------------------------------------------------------
# Family game: byte-identical (the card is never owned / registered into play)
# ---------------------------------------------------------------------------

def test_family_setup_unaffected():
    # The card is not in any Family pool; setup is untouched and round-14 reads 0
    # rounds left as expected.
    s = setup(0)
    assert _complete_rounds_left(_set_round(s, 14)) == 0
