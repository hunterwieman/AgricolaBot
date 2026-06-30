"""Tests for Rustic (occupation, B111).

Card text: "For each clay room you build, you get 2 food and 1 bonus point. (this
does not apply to stone rooms and renovated wood rooms.)"

Rustic rides the build_rooms before/after host hooks: `before_build_rooms`
snapshots the room count, `after_build_rooms` (gated on a clay house) pays 2 food
per room built this session and banks 1 bonus point per room into the CardStore,
read back by a scoring term. Each test drives the real Farm Expansion build-rooms
flow so the firing-point wiring is exercised end-to-end.
"""
import agricola.cards.rustic  # noqa: F401  -- registers the card (not in cards/__init__ yet)

from agricola.actions import (
    ChooseSubAction,
    CommitBuildRoom,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.rustic import _VP_KEY, CARD_ID
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import CellType, HouseMaterial
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.scoring import SCORING_TERMS
from agricola.setup import CardPool, setup_env
from tests.factories import (
    with_current_player,
    with_house,
    with_resources,
    with_space,
)
from tests.test_utils import run_actions

_POOL = CardPool(
    occupations=("rustic",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = with_current_player(cs, 0)
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _num_rooms(state, idx):
    g = state.players[idx].farmyard.grid
    return sum(1 for r in range(3) for c in range(5)
               if g[r][c].cell_type == CellType.ROOM)


def _vp(state, idx):
    return state.players[idx].card_state.get(_VP_KEY, 0)


def _score(state, idx):
    """The Rustic scoring term's contribution (SCORING_TERMS is a list of pairs)."""
    return sum(fn(state, idx) for cid, fn in SCORING_TERMS if cid == CARD_ID)


def _expansion_setup(material, *, idx=0, occ=True, **resources):
    """Card-mode state with farm_expansion revealed and the given house material."""
    cs = _card_state()
    cs = with_house(cs, idx, material)
    cs = with_resources(cs, idx, **resources)
    cs = with_space(cs, "farm_expansion", revealed=True)
    if occ:
        cs = _own_occ(cs, idx, CARD_ID)
    return cs


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_rustic_registered():
    assert CARD_ID in OCCUPATIONS
    assert any(cid == CARD_ID for cid, _fn in SCORING_TERMS)
    # before_build_rooms snapshot + after_build_rooms grant are both registered.
    before_cards = {e.card_id for e in AUTO_EFFECTS.get("before_build_rooms", ())}
    after_cards = {e.card_id for e in AUTO_EFFECTS.get("after_build_rooms", ())}
    assert CARD_ID in before_cards
    assert CARD_ID in after_cards


# ---------------------------------------------------------------------------
# A single clay room: +2 food, +1 banked point
# ---------------------------------------------------------------------------

def test_rustic_one_clay_room():
    # Clay house: a room costs 5 clay + 2 reed. Build one room via Farm Expansion.
    cs = _expansion_setup(HouseMaterial.CLAY, clay=5, reed=2)
    food0 = cs.players[0].resources.food
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
        CommitBuildRoom(row=0, col=0),
        Proceed(),    # flip PendingBuildRooms to after -> after_build_rooms fires
        Stop(),       # pop PendingBuildRooms
        Proceed(),
        Stop(),
    ])
    assert cs.players[0].farmyard.grid[0][0].cell_type == CellType.ROOM
    assert cs.players[0].resources.food == food0 + 2   # +2 food for the one clay room
    assert _vp(cs, 0) == 1                              # +1 bonus point banked
    assert _score(cs, 0) == 1                           # reflected by the scoring term


# ---------------------------------------------------------------------------
# Two clay rooms in ONE build-rooms session: +4 food, +2 banked points
# ---------------------------------------------------------------------------

def test_rustic_two_clay_rooms_one_session():
    # Enough clay/reed for two rooms (2 * (5 clay + 2 reed)).
    cs = _expansion_setup(HouseMaterial.CLAY, clay=10, reed=4)
    food0 = cs.players[0].resources.food
    rooms0 = _num_rooms(cs, 0)
    # Build the first room, then a second in the SAME session (build-rooms is
    # multi-shot via Farm Expansion's max_builds=None). Pick the second cell from
    # what is legal after the first commit so adjacency holds for any grid layout.
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
        CommitBuildRoom(row=0, col=0),
    ])
    next_room = next(a for a in legal_actions(cs) if isinstance(a, CommitBuildRoom))
    cs = run_actions(cs, [
        next_room,
        Proceed(),    # one after_build_rooms for the WHOLE 2-room session
        Stop(),
        Proceed(),
        Stop(),
    ])
    assert _num_rooms(cs, 0) == rooms0 + 2
    # Fired ONCE for the session but pays PER ROOM: 2 rooms -> +4 food, +2 points.
    assert cs.players[0].resources.food == food0 + 4
    assert _vp(cs, 0) == 2
    assert _score(cs, 0) == 2


# ---------------------------------------------------------------------------
# Stone rooms do NOT pay (the text's parenthetical)
# ---------------------------------------------------------------------------

def test_rustic_no_payout_for_stone_room():
    # Stone house: a room costs 5 stone + 2 reed. Not a clay room -> no payout.
    cs = _expansion_setup(HouseMaterial.STONE, stone=5, reed=2)
    food0 = cs.players[0].resources.food
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
        CommitBuildRoom(row=0, col=0),
        Proceed(),
        Stop(),
        Proceed(),
        Stop(),
    ])
    assert cs.players[0].farmyard.grid[0][0].cell_type == CellType.ROOM
    assert cs.players[0].resources.food == food0   # no food
    assert _vp(cs, 0) == 0                          # no banked points
    assert _score(cs, 0) == 0


# ---------------------------------------------------------------------------
# Wood rooms do NOT pay either (a wood-house room is not a clay room; the
# "renovated wood rooms" exclusion is the same idea read from the build side)
# ---------------------------------------------------------------------------

def test_rustic_no_payout_for_wood_room():
    cs = _expansion_setup(HouseMaterial.WOOD, wood=5, reed=2)
    food0 = cs.players[0].resources.food
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
        CommitBuildRoom(row=0, col=0),
        Proceed(),
        Stop(),
        Proceed(),
        Stop(),
    ])
    assert cs.players[0].resources.food == food0
    assert _vp(cs, 0) == 0


# ---------------------------------------------------------------------------
# Without the occupation, no card effect fires (control)
# ---------------------------------------------------------------------------

def test_rustic_inert_without_occupation():
    cs = _expansion_setup(HouseMaterial.CLAY, clay=5, reed=2, occ=False)
    food0 = cs.players[0].resources.food
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
        CommitBuildRoom(row=0, col=0),
        Proceed(),
        Stop(),
        Proceed(),
        Stop(),
    ])
    assert cs.players[0].resources.food == food0   # no card -> no payout
    assert _vp(cs, 0) == 0


# ---------------------------------------------------------------------------
# Banking accumulates across two separate clay-room sessions
# ---------------------------------------------------------------------------

def test_rustic_banks_across_two_sessions():
    cs = _expansion_setup(HouseMaterial.CLAY, clay=10, reed=4)

    # First session: build one room at (0,0).
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
        CommitBuildRoom(row=0, col=0),
        Proceed(),
        Stop(),
        Proceed(),
        Stop(),
    ])
    assert _vp(cs, 0) == 1

    # Free the worker so farm_expansion is placeable again, simulating a later turn.
    cs = with_space(cs, "farm_expansion", revealed=True, workers=(0, 0))
    cs = with_current_player(cs, 0)

    # Second session: build another room (pick a legal cell after the first build).
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
    ])
    nxt = next(a for a in legal_actions(cs) if isinstance(a, CommitBuildRoom))
    cs = run_actions(cs, [
        nxt,
        Proceed(),
        Stop(),
        Proceed(),
        Stop(),
    ])
    # Banked points accumulated across BOTH sessions.
    assert _vp(cs, 0) == 2
    assert _score(cs, 0) == 2
