import agricola.cards.zigzag_harrow  # noqa: F401  -- registers the card

"""Tests for Zigzag Harrow (minor improvement, D1; Dulcinaria Expansion).

Card text: "You can immediately plow 1 field such that it completes a "zigzag"
pattern." Cost 1 Wood; prerequisite "3 Fields in an "L" Shape"; PASSING
(traveling minor — passed to the opponent's hand at play).

USER RULING (2026-07-20): zigzag means a pattern like
{(x,y),(x+1,y),(x+1,y+1),(x+2,y+1)}, {(x,y),(x,y+1),(x+1,y+1),(x+1,y+2)},
{(x,y),(x+1,y-1),(x+1,y),(x+2,y-1)}, or {(x,y),(x-1,y+1),(x,y+1),(x-1,y+2)} —
the four orientations of the S/Z tetromino, translated anywhere on the 3x5
grid. "Completes a zigzag" = the new field plus 3 EXISTING field tiles form
one of the templates; the prereq = 3 field tiles forming a bent tromino (an L
of 3, any orientation). Field TILES only in both checks.

The expected candidate sets below were derived independently of the module's
template tables (brute-force over all 4-cell sets whose bounding box + line
counts give exactly the S/Z tetromino), so a shared template bug cannot
self-validate:
  - fields {(0,1),(1,1),(1,2)}  -> completions exactly {(0,0), (2,2)}
    ((0,0) via template {(x,y),(x,y+1),(x+1,y+1),(x+1,y+2)} at (0,0);
     (2,2) via template {(x,y),(x+1,y),(x+1,y+1),(x+2,y+1)} at (0,1))
  - fields {(0,2),(1,1),(1,2)}  -> completions exactly {(2,1), (0,3)}
    ((2,1) via template {(x,y),(x+1,y-1),(x+1,y),(x+2,y-1)} at (0,2);
     (0,3) via template {(x,y),(x-1,y+1),(x,y+1),(x-1,y+2)} at (1,1))
so between the two layouts all four templates complete.
"""
import json
from pathlib import Path

from agricola.actions import (
    ChooseSubAction,
    CommitPlayMinor,
    CommitPlow,
    PlaceWorker,
    Stop,
)
from agricola.cards.zigzag_harrow import CARD_ID
from agricola.cards.specs import MINORS, PLAY_MINOR_VARIANTS, prereq_met
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import _legal_plow_cells, legal_actions, playable_minors
from agricola.pending import PendingPlayMinor, PendingPlow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell, get_space, with_space

from tests.factories import (
    add_resources,
    with_fields,
    with_grid,
    with_pending_stack,
)

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)

_DATA = Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"
with open(_DATA / "revised_minor_improvements.json") as f:
    _ROW = next(r for r in json.load(f) if r["name"] == "Zigzag Harrow")

# Default starting rooms sit at (1,0) and (2,0); all layouts avoid them.
# An L whose completions are exactly {(0,0), (2,2)} (see module docstring).
_F1 = ((0, 1), (1, 1), (1, 2))
# Its mirror, whose completions are exactly {(2,1), (0,3)}.
_F3 = ((0, 2), (1, 1), (1, 2))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _frame(*, field_cells=_F1, extra_overrides=None, hand=(CARD_ID,), wood=1):
    """A prefabricated state at a PendingPlayMinor frame for the current player,
    holding `hand` + `wood` wood, with `field_cells` plowed (plus any
    `extra_overrides` on the grid). The opponent's hand is cleared so the
    passing assertions are exact."""
    state, _env = setup_env(5, card_pool=_POOL)
    cp = state.current_player
    p = fast_replace(state.players[cp], hand_minors=frozenset(hand))
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(state, players=tuple(
        p if i == cp else opp for i in range(2)))
    state = with_fields(state, cp, field_cells)
    if extra_overrides:
        state = with_grid(state, cp, extra_overrides)
    if wood:
        state = add_resources(state, cp, wood=wood)
    state = with_pending_stack(state, (
        PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return state, cp


def _plays(state):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]


def _variants_offered(state):
    return {a.variant for a in _plays(state)}


def _commit_cells(state):
    return {(a.row, a.col) for a in legal_actions(state)
            if isinstance(a, CommitPlow)}


def _n_fields(state, idx):
    g = state.players[idx].farmyard.grid
    return sum(1 for r in range(3) for c in range(5)
               if g[r][c].cell_type is CellType.FIELD)


# ---------------------------------------------------------------------------
# Registration (spec vs the JSON row) — subset/membership checks only
# ---------------------------------------------------------------------------

def test_json_row():
    """Pin the catalog row this module encodes (cost / prereq / text verbatim)."""
    assert _ROW["deck"] == "D" and _ROW["number"] == 1
    assert _ROW["cost"] == "1 Wood"
    assert _ROW["prerequisites"] == '3 Fields in an "L" Shape'
    assert _ROW["passing_left"] == "X"
    assert _ROW["vps"] is None
    assert _ROW["text"] == (
        'You can immediately plow 1 field such that it completes a "zigzag" '
        "pattern.")
    # The module docstring quotes the printed text verbatim (line-wrapped, so
    # compare whitespace-normalized).
    import agricola.cards.zigzag_harrow as mod
    assert _ROW["text"] in " ".join(mod.__doc__.split())


def test_registered_spec():
    assert CARD_ID in MINORS                          # subset check
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.alt_costs == ()
    assert spec.cost_fn is None
    assert spec.min_occupations == 0
    assert spec.max_occupations is None
    assert spec.prereq is not None                    # the L-shape check
    assert spec.vps == 0
    assert spec.passing_left is True                  # traveling minor
    assert CARD_ID in PLAY_MINOR_VARIANTS             # subset check


# ---------------------------------------------------------------------------
# Prerequisite: 3 field tiles forming an L (bent tromino), any orientation
# ---------------------------------------------------------------------------

def test_prereq_rejects_straight_line_and_scattered():
    spec = MINORS[CARD_ID]
    row_i, cp = _frame(field_cells=((0, 0), (0, 1), (0, 2)))
    assert not prereq_met(spec, row_i, cp)            # I-tromino (row): no L
    col_i, cp = _frame(field_cells=((0, 1), (1, 1), (2, 1)))
    assert not prereq_met(spec, col_i, cp)            # I-tromino (column): no L
    scattered, cp = _frame(field_cells=((0, 0), (0, 2), (2, 4)))
    assert not prereq_met(spec, scattered, cp)        # disconnected: no L
    four_line, cp = _frame(field_cells=((0, 0), (0, 1), (0, 2), (0, 3)))
    assert not prereq_met(spec, four_line, cp)        # 4 in a line: still no L


def test_prereq_accepts_all_four_l_orientations():
    spec = MINORS[CARD_ID]
    for cells in [
        ((0, 1), (0, 2), (1, 1)),                     # corner NW
        ((0, 1), (0, 2), (1, 2)),                     # corner NE
        ((0, 1), (1, 1), (1, 2)),                     # corner SW
        ((0, 2), (1, 1), (1, 2)),                     # corner SE
    ]:
        state, cp = _frame(field_cells=cells)
        assert prereq_met(spec, state, cp), cells


def test_prereq_is_an_existence_check():
    """Extra fields don't hurt: 4 fields of which 3 form an L passes."""
    spec = MINORS[CARD_ID]
    state, cp = _frame(field_cells=((0, 1), (0, 2), (0, 3), (1, 3)))
    assert prereq_met(spec, state, cp)


def test_prereq_gates_the_real_frame():
    """I-tromino -> not offered (wood in hand, so the prereq is the only failing
    gate); an L -> offered."""
    state, cp = _frame(field_cells=((0, 0), (0, 1), (0, 2)))
    assert CARD_ID not in playable_minors(state, cp)
    assert not _plays(state)
    state, cp = _frame(field_cells=_F1)
    assert CARD_ID in playable_minors(state, cp)
    assert _plays(state)


# ---------------------------------------------------------------------------
# The wide on-play choice: "plow" (when a completion exists) + always "skip"
# ---------------------------------------------------------------------------

def test_both_variants_offered_when_a_completion_exists():
    state, _cp = _frame()
    assert _variants_offered(state) == {"plow", "skip"}


def test_variant_payments_are_the_printed_cost():
    """Both routes pay exactly the printed 1 wood (zero variant surcharge)."""
    state, _cp = _frame()
    plays = _plays(state)
    assert len(plays) == 2
    for a in plays:
        assert a.payment == Resources(wood=1)


def test_only_skip_when_no_completing_cell():
    """Prereq met (an L exists) and legal plow targets exist, but NO cell
    completes a zigzag -> only "skip" is offered (never a dead-end).

    Fields {(0,0),(0,1),(1,1)}: the only zigzag completion would be (1,2)
    (template {(x,y),(x,y+1),(x+1,y+1),(x+1,y+2)} at (0,0)); a ROOM there
    removes it, while (0,2) and (2,1) stay ordinary legal plow cells."""
    state, cp = _frame(field_cells=((0, 0), (0, 1), (1, 1)),
                       extra_overrides={(1, 2): Cell(cell_type=CellType.ROOM)})
    assert prereq_met(MINORS[CARD_ID], state, cp)
    legal = set(_legal_plow_cells(state.players[cp]))
    assert {(0, 2), (2, 1)} <= legal                  # plow targets DO exist
    assert _variants_offered(state) == {"skip"}


# ---------------------------------------------------------------------------
# The offered CommitPlow cells are EXACTLY the zigzag-completing cells
# ---------------------------------------------------------------------------

def test_commit_set_is_exactly_the_completing_cells():
    """Fields _F1 = {(0,1),(1,1),(1,2)}: the ordinary legal plow cells are
    {(0,0),(0,2),(1,3),(2,1),(2,2)}, of which exactly (0,0) and (2,2) complete
    a zigzag (independently derived — module docstring)."""
    state, cp = _frame(field_cells=_F1)
    assert set(_legal_plow_cells(state.players[cp])) == {
        (0, 0), (0, 2), (1, 3), (2, 1), (2, 2)}
    (plow,) = [a for a in _plays(state) if a.variant == "plow"]
    state = step(state, plow)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingPlow)
    assert top.initiated_by_id == "card:zigzag_harrow"
    assert top.max_plows == 1                         # "plow 1 field"
    assert set(top.allowed_cells) == {(0, 0), (2, 2)}
    assert _commit_cells(state) == {(0, 0), (2, 2)}   # exact: no (0,2)/(1,3)/(2,1)
    # The plow is mandatory once "plow" is chosen (no Stop before the commit).
    assert not any(isinstance(a, Stop) for a in legal_actions(state))


def test_commit_set_mirror_layout():
    """Fields _F3 = {(0,2),(1,1),(1,2)}: exactly (2,1) and (0,3) complete
    (the other two templates — module docstring)."""
    state, cp = _frame(field_cells=_F3)
    assert {(0, 1), (1, 3), (2, 2)} <= set(_legal_plow_cells(state.players[cp]))
    (plow,) = [a for a in _plays(state) if a.variant == "plow"]
    state = step(state, plow)
    assert _commit_cells(state) == {(2, 1), (0, 3)}   # exact


def test_each_template_completes():
    """Each of the four ruling templates is the completing shape in some case:
    _F1 offers (0,0) [{(x,y),(x,y+1),(x+1,y+1),(x+1,y+2)}] and (2,2)
    [{(x,y),(x+1,y),(x+1,y+1),(x+2,y+1)}]; _F3 offers (2,1)
    [{(x,y),(x+1,y-1),(x+1,y),(x+2,y-1)}] and (0,3)
    [{(x,y),(x-1,y+1),(x,y+1),(x-1,y+2)}]. Commit one of each pair; the other
    is covered by the exact-set assertions above."""
    for fields, cell, expect_fields in [
        (_F1, (2, 2), {(0, 1), (1, 1), (1, 2), (2, 2)}),
        (_F1, (0, 0), {(0, 0), (0, 1), (1, 1), (1, 2)}),
        (_F3, (2, 1), {(0, 2), (1, 1), (1, 2), (2, 1)}),
        (_F3, (0, 3), {(0, 2), (1, 1), (1, 2), (0, 3)}),
    ]:
        state, cp = _frame(field_cells=fields)
        (plow,) = [a for a in _plays(state) if a.variant == "plow"]
        state = step(state, plow)
        assert cell in _commit_cells(state)
        state = step(state, CommitPlow(row=cell[0], col=cell[1]))
        g = state.players[cp].farmyard.grid
        got = {(r, c) for r in range(3) for c in range(5)
               if g[r][c].cell_type is CellType.FIELD}
        assert got == expect_fields                   # the zigzag stands
        assert state.pending_stack[-1].phase == "after"   # single-shot: flipped


# ---------------------------------------------------------------------------
# The skip route is a no-op plow-wise; the card passes either way
# ---------------------------------------------------------------------------

def test_skip_plays_without_plowing_and_passes():
    state, cp = _frame()
    wood_before = state.players[cp].resources.wood
    n_before = _n_fields(state, cp)
    (skip,) = [a for a in _plays(state) if a.variant == "skip"]
    out = step(state, skip)
    assert _n_fields(out, cp) == n_before             # no plow happened
    assert not any(isinstance(f, PendingPlow) for f in out.pending_stack)
    # Traveling minor: to the OPPONENT's hand, never the tableau.
    assert CARD_ID in out.players[1 - cp].hand_minors
    assert CARD_ID not in out.players[cp].hand_minors
    assert CARD_ID not in out.players[cp].minor_improvements
    assert out.players[cp].resources.wood == wood_before - 1   # cost paid


def test_plow_route_passes_before_the_plow_resolves():
    """The card already traveled to the opponent before the granted plow."""
    state, cp = _frame()
    (plow,) = [a for a in _plays(state) if a.variant == "plow"]
    mid = step(state, plow)
    assert isinstance(mid.pending_stack[-1], PendingPlow)
    assert CARD_ID in mid.players[1 - cp].hand_minors
    assert CARD_ID not in mid.players[cp].minor_improvements


# ---------------------------------------------------------------------------
# End-to-end through a real engine flow (major_improvement space, Cards mode)
# ---------------------------------------------------------------------------

def test_end_to_end_via_major_improvement_space():
    """Full flow: place a worker on Major/Minor Improvement, choose play_minor,
    play with the "plow" variant, commit a completing cell, and unwind."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    sp = fast_replace(get_space(cs.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    cs = fast_replace(cs, board=with_space(cs.board, "major_improvement", sp))
    p = fast_replace(cs.players[cp],
                     hand_occupations=frozenset(),
                     hand_minors=frozenset({CARD_ID}))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(
        p if i == cp else opp for i in range(2)))
    cs = with_fields(cs, cp, _F1)                     # an L -> prereq met
    cs = add_resources(cs, cp, wood=1)                # the 1-wood cost

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    (plow,) = [a for a in legal_actions(cs)
               if isinstance(a, CommitPlayMinor) and a.variant == "plow"]
    cs = step(cs, plow)
    assert isinstance(cs.pending_stack[-1], PendingPlow)
    assert _commit_cells(cs) == {(0, 0), (2, 2)}      # exactly the completions
    cs = step(cs, CommitPlow(row=2, col=2))
    # Unwind the nested hosts (each after-phase offers only Stop).
    while cs.pending_stack:
        stops = [a for a in legal_actions(cs) if isinstance(a, Stop)]
        assert stops, "expected a Stop to unwind the host stack"
        cs = step(cs, stops[0])

    g = cs.players[cp].farmyard.grid
    assert g[2][2].cell_type is CellType.FIELD        # the completing plow landed
    assert _n_fields(cs, cp) == 4                     # 3 starting + 1 plowed
    assert CARD_ID in cs.players[1 - cp].hand_minors  # passed to the opponent
    assert CARD_ID not in cs.players[cp].minor_improvements
    assert cs.players[cp].resources.wood == 0         # the 1 wood was paid
