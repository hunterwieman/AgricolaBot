"""Tests for Pastor (occupation B163): once the owner is the ONLY player living in a
2-room house, they gain 3 wood, 2 clay, 1 reed, 1 stone (once) — via the decision-
boundary one-shot sweep. The starting house is 2 rooms, so both players begin tied;
the grant fires only once the OTHER player leaves 2 rooms while the owner stays."""
import agricola.cards.pastor  # noqa: F401  (registers the card)

from agricola.cards.pastor import CARD_ID, _GRANT
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import BOUNDARY_ONE_SHOTS
from agricola.constants import CellType
from agricola.engine import _advance_until_decision, _fire_boundary_one_shots
from agricola.replace import fast_replace
from agricola.setup import setup
from agricola.state import Cell, GameState

from tests.factories import with_grid


def _own(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | {CARD_ID})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _add_room(state, idx, cell):
    """Add a ROOM cell (default house is rooms at (1,0),(2,0); add a 3rd)."""
    return with_grid(state, idx, {cell: Cell(cell_type=CellType.ROOM)})


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in BOUNDARY_ONE_SHOTS
    assert _GRANT.wood == 3 and _GRANT.clay == 2 and _GRANT.reed == 1 and _GRANT.stone == 1


def test_on_play_is_noop():
    s = setup(0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) == s


# --- The boundary sweep -----------------------------------------------------

def test_no_fire_when_both_have_two_rooms():
    """Both players start with 2 rooms -> the owner is not the ONLY one -> no fire."""
    s = _own(setup(0), 0)
    out = _fire_boundary_one_shots(s)
    assert out.players[0].card_state.get(CARD_ID, 0) == 0
    assert CARD_ID not in out.players[0].fired_once


def test_fires_when_owner_alone_at_two_rooms():
    """Opponent expands to 3 rooms; owner stays at 2 -> owner is alone -> grant."""
    s = _own(setup(0), 0)
    s = _add_room(s, 1, (0, 0))                 # opponent now has 3 rooms
    r0 = s.players[0].resources
    out = _fire_boundary_one_shots(s)
    got = out.players[0].resources
    assert got.wood == r0.wood + 3
    assert got.clay == r0.clay + 2
    assert got.reed == r0.reed + 1
    assert got.stone == r0.stone + 1
    assert CARD_ID in out.players[0].fired_once


def test_no_fire_when_owner_not_at_two_rooms():
    """Owner expands to 3 rooms -> does not live in a 2-room house -> no grant even
    though the opponent (still at 2) makes the owner not 'the only' one anyway."""
    s = _own(setup(0), 0)
    s = _add_room(s, 0, (0, 0))                 # owner now has 3 rooms
    s = _add_room(s, 1, (0, 0))                 # opponent has 3 rooms too
    r0 = s.players[0].resources
    out = _fire_boundary_one_shots(s)
    assert out.players[0].resources == r0       # unchanged
    assert CARD_ID not in out.players[0].fired_once


def test_fires_only_once():
    s = _own(setup(0), 0)
    s = _add_room(s, 1, (0, 0))
    out = _fire_boundary_one_shots(s)
    r_after = out.players[0].resources
    # Condition still holds, but the latch prevents a second grant.
    out2 = _fire_boundary_one_shots(out)
    assert out2.players[0].resources == r_after


def test_unowned_never_fires():
    s = setup(0)
    s = _add_room(s, 1, (0, 0))                 # opponent at 3, but no one owns Pastor
    r0 = s.players[0].resources
    out = _fire_boundary_one_shots(s)
    assert out.players[0].resources == r0


def test_fires_through_advance_until_decision():
    s = _own(setup(0), 0)
    s = _add_room(s, 1, (0, 0))
    r0 = s.players[0].resources
    out = _advance_until_decision(s)
    assert out.players[0].resources.wood == r0.wood + 3
