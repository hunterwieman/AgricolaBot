import agricola.cards.field_spade  # noqa: F401  (registers the card)

"""Tests for Field Spade (minor improvement, Ephipparius E79).

Card text: "Each time after you sow in at least 1 field, you get 1 stone."

An ``after_sow`` automatic effect granting a flat +1 stone once per completed sow
(every sow plants >=1 field). Crop-agnostic — unlike Garden Hoe it fires on a
grain-only sow too. Covers: registration; the grant via a real Grain Utilization
sow; that a grain-only sow fires it (crop-agnostic); a fresh independent sow
re-fires it ("each time"); and the not-owned no-op.
"""
from agricola.actions import ChooseSubAction, CommitSow, PlaceWorker
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell, get_space, with_space
from tests.factories import with_current_player, with_resources

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("field_spade",) + tuple(f"m{i}" for i in range(20)),
)


def _state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return with_current_player(s, 0)


def _own(state, idx=0):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, minor_improvements=p.minor_improvements | {"field_spade"})
        if i == idx else state.players[i] for i in range(2)))


def _reveal(state, space_id):
    sp = fast_replace(get_space(state.board, space_id), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, space_id, sp))


def _with_empty_fields(state, idx, cells):
    p = state.players[idx]
    grid = [[c for c in row] for row in p.farmyard.grid]
    for (r, c) in cells:
        grid[r][c] = Cell(cell_type=CellType.FIELD)
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    return fast_replace(state, players=tuple(
        fast_replace(p, farmyard=fy) if i == idx else state.players[i] for i in range(2)))


def _sow_grain(state, space="grain_utilization"):
    """Place at `space`, choose sow, and commit a 1-grain sow into one field."""
    state = _reveal(state, space)
    state = step(state, PlaceWorker(space=space))
    state = step(state, ChooseSubAction(name="sow"))
    sow = next(a for a in legal_actions(state)
               if isinstance(a, CommitSow) and a.grain == 1 and a.veg == 0)
    return step(state, sow)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert "field_spade" in MINORS
    assert MINORS["field_spade"].cost == Cost(resources=Resources(wood=1))
    asow = {e.card_id for e in AUTO_EFFECTS.get("after_sow", [])}
    assert "field_spade" in asow


# ---------------------------------------------------------------------------
# +1 stone after a real (grain) sow — crop-agnostic
# ---------------------------------------------------------------------------

def test_grants_one_stone_after_grain_sow():
    s = _own(_state())
    s = _with_empty_fields(s, 0, [(1, 0)])
    s = with_resources(s, 0, grain=1, stone=0)
    s = _sow_grain(s)
    # after_sow fired: +1 stone; and a real sow ran (the field is grain-sown).
    assert s.players[0].resources.stone == 1
    assert s.players[0].farmyard.grid[1][0].grain > 0


def test_grants_on_cultivation_sow_too():
    # Fires on a Cultivation sow as well (a different sow host) — with no
    # once-per-game/round latch registered, the auto re-fires on every sow.
    s = _own(_state())
    s = _with_empty_fields(s, 0, [(1, 0)])
    s = with_resources(s, 0, grain=1, stone=0)
    s = _sow_grain(s, "cultivation")
    assert s.players[0].resources.stone == 1


def test_not_owned_no_stone():
    s = _state()
    s = _with_empty_fields(s, 0, [(1, 0)])
    s = with_resources(s, 0, grain=1, stone=0)
    s = _sow_grain(s)
    assert s.players[0].resources.stone == 0
