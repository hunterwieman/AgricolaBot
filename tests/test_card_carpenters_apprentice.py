import agricola.cards.carpenters_apprentice  # noqa: F401
"""Tests for Carpenter's Apprentice (occupation, deck C #88, players 1+).

Card text (verbatim): "Wood rooms cost you 2 woods less. Your 3rd and 4th stable
each cost you 1 wood less. Your 13th to 15th fence each cost you nothing."

Three passive cost clauses (ruling 74, 2026-07-21 — see the card module docstring):
a -2 wood room reduction gated on the house material being WOOD; a -1 wood stable
reduction under CURRENT-count semantics (`helpers.stables_built` is 2 or 3 at cost
time — the priced stable is the 3rd or 4th); and the ordinal free-fence source
(pieces with cumulative board ordinals 13-15 cost no wood; they still draw supply
PIECES). Rooms/stables drive the real Farm Expansion flow; fences drive the real
Fencing flow END-TO-END in CARDS mode (the deferred-tally accrue + Proceed settle).
"""
import agricola.cards.frame_builder  # noqa: F401  (clay->wood conversion — the wood-room gate test)

from agricola.actions import (
    ChooseSubAction,
    CommitBuildPasture,
    CommitBuildRoom,
    CommitBuildStable,
    CommitChooseCost,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.carpenters_apprentice import CARD_ID
from agricola.cards.cost_mods import FREE_FENCE_ORDINALS, REDUCTIONS
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import CellType, GameMode, HouseMaterial
from agricola.engine import step
from agricola.helpers import fences_built, stables_built
from agricola.legality import legal_actions
from agricola.pending import PendingBuildFences, PendingBuildRooms, PendingChooseCost
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import Cell
from tests.factories import (
    with_current_player,
    with_grid,
    with_house,
    with_resources,
    with_space,
)
from tests.test_fencing import _fencing_setup, _with_initial_pasture

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_1x4_TOP = [(0, 1), (0, 2), (0, 3), (0, 4)]     # 10 fence edges
_2x1_RIGHT = frozenset({(1, 4), (2, 4)})        # 6-edge perimeter, 1 shared -> 5 new


def _fe_state(*, own=True, material=HouseMaterial.WOOD, extra_occs=(), **resources):
    """A Farm Expansion state: player 0 to move, given house material + resources,
    optionally owning Carpenter's Apprentice (played tableau — only a played card
    modifies costs)."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_house(state, 0, material)
    state = with_resources(state, 0, **resources)
    state = with_space(state, "farm_expansion", revealed=True)
    occs = (frozenset({CARD_ID}) if own else frozenset()) | frozenset(extra_occs)
    p0 = fast_replace(state.players[0], occupations=occs)
    return fast_replace(state, players=(p0, state.players[1]))


def _drive_to_build_rooms(state):
    state = step(state, PlaceWorker(space="farm_expansion"))
    state = step(state, ChooseSubAction(name="build_rooms"))
    rooms = [a for a in legal_actions(state) if isinstance(a, CommitBuildRoom)]
    assert rooms, "expected a legal room cell"
    return state, rooms[0]


def _drive_to_build_stables(state):
    state = step(state, PlaceWorker(space="farm_expansion"))
    return step(state, ChooseSubAction(name="build_stables"))


def _cards_fence_state(*, wood, own=True, pre_pastures=()):
    """A CARDS-mode fencing state: Fencing revealed, player 0 to move with `wood`,
    optionally owning Carpenter's Apprentice, with the given pre-built pastures
    (each a cell list; placed fence pieces decrement `fences_in_supply`)."""
    state = _fencing_setup(wood=wood)
    state = fast_replace(state, mode=GameMode.CARDS)
    for cells in pre_pastures:
        state = _with_initial_pasture(state, 0, cells)
    if own:
        p = state.players[0]
        p = fast_replace(p, occupations=p.occupations | {CARD_ID})
        state = fast_replace(
            state, players=tuple(p if i == 0 else state.players[i] for i in range(2)))
    return state


def _wood(state, idx=0):
    return state.players[idx].resources.wood


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    assert any(cid == CARD_ID for cid, _fn in REDUCTIONS.get("build_room", ()))
    assert any(cid == CARD_ID for cid, _fn in REDUCTIONS.get("build_stable", ()))
    assert CARD_ID in FREE_FENCE_ORDINALS
    s = setup(seed=0)
    assert FREE_FENCE_ORDINALS[CARD_ID](s, 0) == frozenset({13, 14, 15})
    # Passive cost card — no on-play effect.
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) is s


# ---------------------------------------------------------------------------
# Clause 1 — wood rooms cost 2 wood less
# ---------------------------------------------------------------------------

def test_wood_room_costs_2_wood_less():
    # Wood house room = 5 wood + 2 reed; with the card -> 3 wood + 2 reed,
    # a singleton frontier -> debited inline (no PendingChooseCost).
    state = _fe_state(material=HouseMaterial.WOOD, wood=5, reed=2)
    state, room = _drive_to_build_rooms(state)
    state = step(state, room)
    assert isinstance(state.pending_stack[-1], PendingBuildRooms)
    assert state.players[0].resources == Resources(wood=2)   # paid 3 wood + 2 reed


def test_clay_house_room_no_discount():
    # After renovating to clay, a room is a CLAY room (5 clay + 2 reed) — the
    # card gives nothing (its clause covers WOOD rooms only).
    state = _fe_state(material=HouseMaterial.CLAY, clay=5, reed=2)
    state, room = _drive_to_build_rooms(state)
    state = step(state, room)
    assert isinstance(state.pending_stack[-1], PendingBuildRooms)
    assert state.players[0].resources == Resources()         # paid full 5 clay + 2 reed


def test_clay_room_wood_bearing_payment_not_discounted():
    # The gate is the HOUSE MATERIAL, not wood in the payment: Frame Builder turns
    # the clay room's 5c+2r into a 3c+1w+2r variant. Carpenter's Apprentice must
    # NOT shave that variant's wood (the room is still a clay room) — the frontier
    # keeps both undiscounted payments.
    state = _fe_state(material=HouseMaterial.CLAY, extra_occs=("frame_builder",),
                      clay=5, reed=2, wood=1)
    state, room = _drive_to_build_rooms(state)
    state = step(state, room)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingChooseCost)
    options = {a.payment for a in legal_actions(state) if isinstance(a, CommitChooseCost)}
    assert options == {
        Resources(clay=5, reed=2),
        Resources(clay=3, reed=2, wood=1),
    }


def test_non_owner_room_full_price():
    state = _fe_state(own=False, material=HouseMaterial.WOOD, wood=5, reed=2)
    state, room = _drive_to_build_rooms(state)
    state = step(state, room)
    assert state.players[0].resources == Resources()         # paid full 5 wood + 2 reed


# ---------------------------------------------------------------------------
# Clause 2 — the 3rd and 4th stable cost 1 wood less (current-count semantics)
# ---------------------------------------------------------------------------

def test_four_stables_one_action_cost_2_2_1_1():
    # One Farm Expansion action, four stables from a fresh farm (base 2 wood each):
    # the count advances between per-stable commits, so the 1st/2nd cost 2 wood
    # and the 3rd/4th cost 1 wood.
    state = _fe_state(wood=6)
    state = _drive_to_build_stables(state)
    for cell, wood_after in (((0, 1), 4), ((0, 2), 2), ((0, 3), 1), ((0, 4), 0)):
        state = step(state, CommitBuildStable(row=cell[0], col=cell[1]))
        assert _wood(state) == wood_after
    assert stables_built(state.players[0].farmyard) == 4


def test_second_and_third_stable_in_one_action():
    # With 1 stable already on the farm, ONE Farm Expansion action building two
    # stables prices the 2nd at 2 wood (no discount) and the 3rd at 1 wood —
    # the per-stable frontier is resolved pre-placement, and the current-count
    # ordinal advances between the two commits.
    state = _fe_state(wood=3)
    state = with_grid(state, 0, {(2, 4): Cell(cell_type=CellType.STABLE)})
    assert stables_built(state.players[0].farmyard) == 1
    state = _drive_to_build_stables(state)
    state = step(state, CommitBuildStable(row=0, col=1))     # the 2nd stable: 2 wood
    assert _wood(state) == 1
    state = step(state, CommitBuildStable(row=0, col=2))     # the 3rd stable: 1 wood
    assert _wood(state) == 0
    assert stables_built(state.players[0].farmyard) == 3


def test_non_owner_stables_full_price():
    state = _fe_state(own=False, wood=8)
    state = _drive_to_build_stables(state)
    for i, cell in enumerate([(0, 1), (0, 2), (0, 3), (0, 4)]):
        state = step(state, CommitBuildStable(row=cell[0], col=cell[1]))
        assert _wood(state) == 8 - 2 * (i + 1)               # every stable: full 2 wood


# ---------------------------------------------------------------------------
# Clause 3 — the 13th-15th fence pieces cost nothing (CARDS mode, end-to-end)
# ---------------------------------------------------------------------------

def test_fence_settle_pieces_13_to_15_free():
    # 10 fences already on the board (a 1x4 pasture). A 5-new-edge commit spans
    # ordinals 11-15: pieces 11-12 are paid, 13-15 free -> the Proceed settle
    # debits exactly 2 wood, and all 5 pieces still draw from the supply pile.
    state = _cards_fence_state(wood=2, pre_pastures=(_1x4_TOP,))
    assert fences_built(state.players[0].farmyard) == 10
    assert state.players[0].fences_in_supply == 5
    state = step(state, PlaceWorker(space="fencing"))
    state = step(state, ChooseSubAction(name="build_fences"))
    state = step(state, CommitBuildPasture(cells=_2x1_RIGHT))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildFences)
    assert top.accrued_cost == Resources(wood=2)             # 5 edges, 3 ordinal-free
    assert _wood(state) == 2                                 # deferred — no debit yet
    assert state.players[0].fences_in_supply == 0            # free pieces still draw supply
    assert fences_built(state.players[0].farmyard) == 15
    state = step(state, Proceed())                           # the whole-action settle
    assert _wood(state) == 0                                 # paid exactly 2 wood
    state = step(state, Stop())                              # pop PendingBuildFences
    state = step(state, Stop())                              # pop the space host
    assert state.pending_stack == ()


def test_fence_settle_non_owner_pays_all_5():
    state = _cards_fence_state(wood=5, own=False, pre_pastures=(_1x4_TOP,))
    state = step(state, PlaceWorker(space="fencing"))
    state = step(state, ChooseSubAction(name="build_fences"))
    state = step(state, CommitBuildPasture(cells=_2x1_RIGHT))
    state = step(state, Proceed())
    assert _wood(state) == 0                                 # full 5 wood
    assert state.players[0].fences_in_supply == 0


# ---------------------------------------------------------------------------
# Placement-time anticipation (legality) — the free ordinals ENABLE a broke build
# ---------------------------------------------------------------------------

def test_broke_player_with_12_built_can_place_on_fencing():
    # 12 fences built (three separate 1x1 pastures), 0 wood: the remaining 3
    # pieces are ordinals 13-15 — all free — so Fencing is placeable.
    state = _cards_fence_state(
        wood=0, pre_pastures=([(0, 1)], [(0, 3)], [(2, 2)]))
    assert fences_built(state.players[0].farmyard) == 12
    assert PlaceWorker(space="fencing") in legal_actions(state)


def test_broke_player_with_10_built_cannot_place_on_fencing():
    # 10 built, 0 wood: any commit's first paid piece is ordinal 11 or 12 — not
    # free — so nothing is affordable and Fencing is NOT placeable.
    state = _cards_fence_state(wood=0, pre_pastures=(_1x4_TOP,))
    assert PlaceWorker(space="fencing") not in legal_actions(state)
    # Control: 1 wood affords a 1-new-edge subdivision -> placeable (shows the
    # 0-wood refusal above is the affordability gate, not geometry).
    control = _cards_fence_state(wood=1, pre_pastures=(_1x4_TOP,))
    assert PlaceWorker(space="fencing") in legal_actions(control)


def test_broke_non_owner_with_12_built_cannot_place_on_fencing():
    state = _cards_fence_state(
        wood=0, own=False, pre_pastures=([(0, 1)], [(0, 3)], [(2, 2)]))
    assert PlaceWorker(space="fencing") not in legal_actions(state)
