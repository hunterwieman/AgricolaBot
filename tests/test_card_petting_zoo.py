import agricola.cards.petting_zoo  # noqa: F401

"""Tests for Petting Zoo (minor improvement, E11; Ephipparius Expansion).

Card text (verbatim): "As long as you have a pasture orthogonally adjacent to
your house, you can keep animals of any type on this card, up to the number of
rooms in your house."
Cost 1 Wood; no prerequisite; no printed VP.

Ruled MIXED-type (user ruling 2026-07-20): the card contributes `num_rooms`
FLEXIBLE slots (1 animal each, any type, mixable) via `register_flexible_slots`,
gated on some pasture cell being orthogonally adjacent to some ROOM cell. A
pasture is not a `CellType` (empty fenced cells read EMPTY), so pasture cells come
from `enclosed_cells` (the fence-derived decomposition), never from the grid.

The starting farm has rooms at (1,0) and (2,0) (2 rooms, wood house) and no
pastures.
"""
from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.capacity_mods import FLEXIBLE_SLOT_CARDS, extra_flexible_slots
from agricola.cards.petting_zoo import CARD_ID, _slots
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import CellType
from agricola.engine import step
from agricola.helpers import accommodates, extract_slots
from agricola.pasture import compute_pastures_from_arrays
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell, get_space, with_space
from tests.factories import with_resources

from scripts.profile_states import _add_pasture


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _hand_minor(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, hand_minors=p.hand_minors | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _add_rooms(state, idx, cells):
    """Set the given cells to ROOM, recomputing pastures from the new grid so the
    call is order-independent (rooms don't affect pasture geometry)."""
    p = state.players[idx]
    fy = p.farmyard
    grid = [list(row) for row in fy.grid]
    for (r, c) in cells:
        grid[r][c] = Cell(cell_type=CellType.ROOM)
    new_grid = tuple(tuple(row) for row in grid)
    new_fy = fast_replace(fy, grid=new_grid, pastures=compute_pastures_from_arrays(
        new_grid, fy.horizontal_fences, fy.vertical_fences))
    p = fast_replace(p, farmyard=new_fy)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registration / spec
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.vps == 0
    assert spec.passing_left is False
    assert spec.prereq is None                       # no prerequisite
    assert prereq_met(spec, setup(0), 0)
    assert any(cid == CARD_ID for cid, _fn in FLEXIBLE_SLOT_CARDS)


# ---------------------------------------------------------------------------
# The condition: some pasture cell orthogonally adjacent to some room cell
# ---------------------------------------------------------------------------

def test_no_pasture_gives_no_slots():
    """Bare starting farm (no pastures at all): 0 extra slots, and extract_slots
    is unchanged whether or not the card is owned."""
    s = setup(0)
    assert _slots(s.players[0]) == 0
    base = extract_slots(s, s.players[0])
    owned = extract_slots(s, _own_minor(s, 0).players[0])
    assert owned == base                              # num_flexible unchanged
    assert extra_flexible_slots(_own_minor(s, 0).players[0]) == 0


def test_diagonal_pasture_does_not_qualify():
    """A pasture at (0,1) is only DIAGONALLY adjacent to room (1,0) — its
    orthogonal neighbours (0,0)/(0,2)/(1,1) are all non-rooms — so it does not
    satisfy the condition and grants no slots."""
    s = _add_pasture(setup(0), 0, [(0, 1)])          # diagonal to room (1,0)
    p = s.players[0]
    from agricola.helpers import enclosed_cells
    assert enclosed_cells(p.farmyard) == frozenset({(0, 1)})   # the pasture exists
    assert _slots(p) == 0
    owned = _own_minor(s, 0).players[0]
    assert extra_flexible_slots(owned) == 0
    assert extract_slots(s, owned) == extract_slots(s, p)  # unchanged


def test_orthogonal_pasture_qualifies():
    """A pasture at (0,0) shares an edge with room (1,0): the card grants
    num_rooms (=2) flexible slots, added to extract_slots' num_flexible."""
    s = _add_pasture(setup(0), 0, [(0, 0)])          # orthogonal to room (1,0)
    p = s.players[0]
    assert _slots(p) == 2                             # 2 starting rooms
    base_caps, base_flex = extract_slots(s, p)
    owned = _own_minor(s, 0).players[0]
    assert extra_flexible_slots(owned) == 2
    caps, flex = extract_slots(s, owned)
    assert caps == base_caps                          # pasture capacities unchanged
    assert flex == base_flex + 2                      # +num_rooms flexible slots
    # The other (non-owner) player is unaffected.
    assert extract_slots(s, _own_minor(s, 0).players[1]) == extract_slots(s, s.players[1])


def test_pasture_touching_second_room_also_qualifies():
    """A pasture at (2,1) shares an edge with room (2,0) — the condition is
    'any pasture cell adjacent to any room cell', so this qualifies too."""
    s = _add_pasture(setup(0), 0, [(2, 1)])          # orthogonal to room (2,0)
    assert _slots(s.players[0]) == 2


# ---------------------------------------------------------------------------
# Mixed types actually housable (the ruling: any-type, mixable)
# ---------------------------------------------------------------------------

def test_mixed_types_housable():
    """3 rooms + a qualifying 1x1 pasture (cap 2). Fill the pasture with 2 sheep;
    then 1 sheep + 1 boar + 1 cattle (three DIFFERENT types) must go on flexible
    slots. Only the owner (pet + 3 card slots = 4 flexible) fits them; a
    single-type bin never could, which is the whole point of the mixed ruling."""
    s = _add_rooms(setup(0), 0, [(0, 0)])            # rooms now (0,0),(1,0),(2,0) = 3
    s = _add_pasture(s, 0, [(1, 1)])                 # (1,1) orthogonal to room (1,0)
    p = s.players[0]
    assert _slots(p) == 3
    owner = _own_minor(s, 0).players[0]
    # 3 sheep + 1 boar + 1 cattle: pasture holds 2 sheep; the overflow of
    # (1 sheep, 1 boar, 1 cattle) — all different types — needs 3 flexible slots.
    assert not accommodates(s, p, 3, 1, 1)              # non-owner: pet(1) only -> no
    assert accommodates(s, owner, 3, 1, 1)             # owner: pet + 3 card slots -> yes


# ---------------------------------------------------------------------------
# Count tracks the room count (build/renovate-independent)
# ---------------------------------------------------------------------------

def test_count_tracks_room_count():
    """With the condition met, the slot count equals the number of ROOM cells —
    verified by directly constructing farms with 2, 3, and 4 rooms."""
    base = _add_pasture(setup(0), 0, [(0, 0)])       # pasture adjacent to room (1,0)
    assert _slots(base.players[0]) == 2              # starting 2 rooms

    three = _add_rooms(base, 0, [(0, 1)])            # + a 3rd room
    assert _slots(three.players[0]) == 3
    assert extra_flexible_slots(_own_minor(three, 0).players[0]) == 3

    four = _add_rooms(three, 0, [(1, 2)])            # + a 4th room
    assert _slots(four.players[0]) == 4
    assert extra_flexible_slots(_own_minor(four, 0).players[0]) == 4


# ---------------------------------------------------------------------------
# Ownership gating — a card in HAND contributes nothing
# ---------------------------------------------------------------------------

def test_card_in_hand_contributes_nothing():
    """Held in hand (not yet played), the card grants no slots even with a
    qualifying pasture — only a played card is owned."""
    s = _add_pasture(setup(0), 0, [(0, 0)])          # qualifying pasture
    held = _hand_minor(s, 0).players[0]
    assert extra_flexible_slots(held) == 0
    assert extract_slots(s, held) == extract_slots(s, s.players[0])


# ---------------------------------------------------------------------------
# End-to-end play through a real flow (paying the 1 wood)
# ---------------------------------------------------------------------------

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def test_played_via_engine_pays_wood():
    """Drive the actual play-minor flow in CARDS mode (PlaceWorker -> improvement
    -> play_minor -> CommitPlayMinor): the card enters the tableau, the 1-wood
    cost is paid, and its flexible-slot effect goes live."""
    from tests.test_utils import sole_play_minor

    cs, _env = setup_env(0, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = with_resources(cs, cp, wood=1)              # afford the 1-wood cost
    # A qualifying pasture so the played card's effect is observable.
    cs = _add_pasture(cs, cp, [(0, 0)])
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD_ID}))
    cs = fast_replace(cs, players=tuple(
        p if i == cp else cs.players[i] for i in range(2)))
    wood_before = cs.players[cp].resources.wood

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, CARD_ID))

    assert CARD_ID in cs.players[cp].minor_improvements
    assert cs.players[cp].resources.wood == wood_before - 1
    # Effect live: the played card now grants num_rooms (=2) flexible slots.
    assert extra_flexible_slots(cs.players[cp]) == 2
