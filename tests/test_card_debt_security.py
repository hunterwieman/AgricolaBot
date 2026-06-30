"""Debt Security (minor improvement, A31; Artifex).

Card text: "During scoring, you get 1 bonus point for each major improvement you
have, up to the number of your unused farmyard spaces."

Scoring minor: the bonus is min(n_majors_owned, n_unused_farmyard_spaces). Both
quantities are derived at scoring time — majors from
state.board.major_improvement_owners, unused via the engine's exact rule
(cell_type == EMPTY AND not enclosed by fences).
"""
import agricola.cards.debt_security  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.specs import MINORS
from agricola.engine import step
from agricola.pasture import Pasture
from agricola.replace import fast_replace
from agricola.scoring import score
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell, get_space, with_space
from agricola.constants import CellType
from tests.factories import with_grid, with_majors, with_resources
from tests.test_utils import sole_play_minor

CARD_ID = "debt_security"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_minor_with_scoring():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost.resources.food == 2
    assert spec.passing_left is False
    # The scoring term is registered (otherwise the bonus below would be 0).
    from agricola.scoring import SCORING_TERMS
    assert CARD_ID in {card_id for card_id, _ in SCORING_TERMS}


def _own_minor(state, idx, card_id):
    p = fast_replace(state.players[idx],
                     minor_improvements=state.players[idx].minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Scoring: min(majors, unused)
# ---------------------------------------------------------------------------

def test_bonus_is_capped_by_majors_when_majors_fewer():
    # Fresh farmyard: 2 rooms occupied, the other 13 cells are EMPTY/unenclosed
    # -> 13 unused spaces. Own 2 majors -> bonus = min(2, 13) = 2.
    s = setup(0)
    s = with_majors(s, owner_by_idx={0: 0, 2: 0})   # Fireplace + Cooking Hearth to P0
    base, _ = score(s, 0)
    s1 = _own_minor(s, 0, CARD_ID)
    t1, bd1 = score(s1, 0)
    assert bd1.card_points == 2
    assert t1 == base + 2


def test_bonus_is_capped_by_unused_when_unused_fewer():
    # Own 3 majors, but fill the farmyard so only 1 cell is unused -> min(3, 1) = 1.
    s = setup(0)
    s = with_majors(s, owner_by_idx={0: 0, 2: 0, 5: 0})   # 3 majors to P0
    # Fill 12 of the 13 empty cells with field tiles, leaving exactly 1 unused.
    empties = [(r, c) for r in range(3) for c in range(5)
               if s.players[0].farmyard.grid[r][c].cell_type is CellType.EMPTY]
    assert len(empties) == 13
    overrides = {rc: Cell(cell_type=CellType.FIELD) for rc in empties[:12]}
    s = with_grid(s, 0, overrides)
    s = _own_minor(s, 0, CARD_ID)
    _t, bd = score(s, 0)
    assert bd.card_points == 1


def test_zero_majors_gives_zero():
    s = setup(0)                                     # no majors owned
    s = _own_minor(s, 0, CARD_ID)
    _t, bd = score(s, 0)
    assert bd.card_points == 0


def test_zero_unused_gives_zero():
    # Own a major but leave no unused space: fill every empty cell.
    s = setup(0)
    s = with_majors(s, owner_by_idx={0: 0})
    empties = {(r, c): Cell(cell_type=CellType.FIELD)
               for r in range(3) for c in range(5)
               if s.players[0].farmyard.grid[r][c].cell_type is CellType.EMPTY}
    s = with_grid(s, 0, empties)
    s = _own_minor(s, 0, CARD_ID)
    _t, bd = score(s, 0)
    assert bd.card_points == 0


def test_fenced_empty_pasture_cell_is_not_unused():
    # The engine subtlety: a fenced-but-empty pasture cell reads cell_type==EMPTY
    # but is a USED space, so it must NOT count toward the cap. Compare a farm with
    # a 2-cell empty pasture against the same farm without it.
    s = setup(0)
    s = with_majors(s, owner_by_idx={0: 0})          # 1 major
    # Leave only the two pasture cells as the candidate-unused cells: fill the
    # other 11 empty cells.
    grid = s.players[0].farmyard.grid
    empties = [(r, c) for r in range(3) for c in range(5)
               if grid[r][c].cell_type is CellType.EMPTY]
    pasture_cells = empties[:2]
    fill = {rc: Cell(cell_type=CellType.FIELD) for rc in empties[2:]}
    s = with_grid(s, 0, fill)

    # Without a pasture: the 2 cells are EMPTY + unenclosed -> 2 unused -> bonus
    # min(1, 2) = 1.
    s_no_past = _own_minor(s, 0, CARD_ID)
    _t0, bd0 = score(s_no_past, 0)
    assert bd0.card_points == 1

    # Now fence those 2 cells into an (empty) pasture: they become USED ->
    # 0 unused -> bonus min(1, 0) = 0.
    fy = s.players[0].farmyard
    fy = fast_replace(fy, pastures=(Pasture(
        cells=frozenset(pasture_cells), num_stables=0, capacity=4),))
    p = fast_replace(s.players[0], farmyard=fy)
    s_past = fast_replace(s, players=tuple(
        p if i == 0 else s.players[i] for i in range(2)))
    s_past = _own_minor(s_past, 0, CARD_ID)
    _t1, bd1 = score(s_past, 0)
    assert bd1.card_points == 0


# ---------------------------------------------------------------------------
# Real engine play: pay 2 food, play the minor, then it scores.
# ---------------------------------------------------------------------------

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def test_play_via_engine_and_score():
    cs, env = setup_env(5, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = with_resources(cs, cp, food=2)
    cs = with_majors(cs, owner_by_idx={0: cp, 2: cp})    # 2 majors for the player
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD_ID}))
    cs = fast_replace(cs, players=tuple(
        p if i == cp else cs.players[i] for i in range(2)))

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, CARD_ID))

    # Cost paid; card kept (not passing).
    assert cs.players[cp].resources.food == 0
    assert CARD_ID in cs.players[cp].minor_improvements

    # It now contributes its bonus at scoring: min(2 majors, many unused) = 2.
    _t, bd = score(cs, cp)
    assert bd.card_points >= 2
