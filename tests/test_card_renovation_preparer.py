"""Tests for Renovation Preparer (occupation, D123).

Card text: "For each new wood/clay room you build, you get 2 clay/2 stone."

Slash-correlation: each new WOOD room built pays 2 clay, each new CLAY room
built pays 2 stone, stone rooms pay nothing. The card rides the
`after_build_rooms` automatic hook, which fires ONCE per build-rooms action at
the host's Proceed work-complete flip (ruling 60's deferred after-flip) and
reads the whole action's room count off the `PendingBuildRooms` frame's
`num_built`. Each test drives the real Farm Expansion build-rooms flow so the
firing-point wiring is exercised end-to-end.
"""
import agricola.cards.renovation_preparer  # noqa: F401  -- registers the card (not in cards/__init__ yet)

from agricola.actions import (
    ChooseSubAction,
    CommitBuildRoom,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.renovation_preparer import CARD_ID
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import CellType, HouseMaterial
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from tests.factories import (
    with_current_player,
    with_house,
    with_resources,
    with_space,
)
from tests.test_utils import run_actions

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
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


def _expansion_setup(material, *, idx=0, occ=True, **resources):
    """Card-mode state with farm_expansion revealed and the given house material."""
    cs = _card_state()
    cs = with_house(cs, idx, material)
    cs = with_resources(cs, idx, **resources)
    cs = with_space(cs, "farm_expansion", revealed=True)
    if occ:
        cs = _own_occ(cs, 0, CARD_ID)
    return cs


_ONE_ROOM_FLOW = [
    PlaceWorker(space="farm_expansion"),
    ChooseSubAction(name="build_rooms"),
    CommitBuildRoom(row=0, col=0),
    Proceed(),    # flip PendingBuildRooms to after -> after_build_rooms fires
    Stop(),       # pop PendingBuildRooms
    Proceed(),
    Stop(),
]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_renovation_preparer_registered():
    assert CARD_ID in OCCUPATIONS
    after_cards = {e.card_id for e in AUTO_EFFECTS.get("after_build_rooms", ())}
    assert CARD_ID in after_cards


# ---------------------------------------------------------------------------
# One new WOOD room -> +2 clay (and no stone)
# ---------------------------------------------------------------------------

def test_wood_room_pays_2_clay():
    # Wood house: a room costs 5 wood + 2 reed.
    cs = _expansion_setup(HouseMaterial.WOOD, wood=5, reed=2)
    clay0 = cs.players[0].resources.clay
    stone0 = cs.players[0].resources.stone
    cs = run_actions(cs, _ONE_ROOM_FLOW)
    assert cs.players[0].farmyard.grid[0][0].cell_type == CellType.ROOM
    assert cs.players[0].resources.clay == clay0 + 2
    assert cs.players[0].resources.stone == stone0


# ---------------------------------------------------------------------------
# Two wood rooms in ONE action -> +4 clay, paid in ONE payout at the Proceed flip
# ---------------------------------------------------------------------------

def test_two_wood_rooms_one_action_single_payout():
    # Enough for two rooms (2 * (5 wood + 2 reed)).
    cs = _expansion_setup(HouseMaterial.WOOD, wood=10, reed=4)
    clay0 = cs.players[0].resources.clay
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
        CommitBuildRoom(row=0, col=0),
    ])
    # Pick the second cell from what is legal after the first commit so
    # adjacency holds for any grid layout.
    next_room = next(a for a in legal_actions(cs) if isinstance(a, CommitBuildRoom))
    cs = run_actions(cs, [next_room])
    # Build Rooms is ONE action: no payout fires between the piece-commits.
    assert cs.players[0].resources.clay == clay0
    cs = run_actions(cs, [
        Proceed(),    # one after_build_rooms for the WHOLE 2-room action
        Stop(),
        Proceed(),
        Stop(),
    ])
    assert cs.players[0].resources.clay == clay0 + 4


# ---------------------------------------------------------------------------
# One new CLAY room (house renovated to clay) -> +2 stone (and no clay gain)
# ---------------------------------------------------------------------------

def test_clay_room_pays_2_stone():
    # Clay house: a room costs 5 clay + 2 reed. The 5 clay is spent on the room,
    # so any clay delta beyond -5 would be a mis-fire of the wood-room branch.
    cs = _expansion_setup(HouseMaterial.CLAY, clay=5, reed=2)
    stone0 = cs.players[0].resources.stone
    cs = run_actions(cs, _ONE_ROOM_FLOW)
    assert cs.players[0].farmyard.grid[0][0].cell_type == CellType.ROOM
    assert cs.players[0].resources.stone == stone0 + 2
    assert cs.players[0].resources.clay == 0   # 5 - 5 spent, no clay reward


# ---------------------------------------------------------------------------
# A stone-house room pays NOTHING (outside both printed pairs)
# ---------------------------------------------------------------------------

def test_stone_room_pays_nothing():
    cs = _expansion_setup(HouseMaterial.STONE, stone=5, reed=2)
    clay0 = cs.players[0].resources.clay
    cs = run_actions(cs, _ONE_ROOM_FLOW)
    assert cs.players[0].farmyard.grid[0][0].cell_type == CellType.ROOM
    assert cs.players[0].resources.stone == 0   # 5 - 5 spent, no stone reward
    assert cs.players[0].resources.clay == clay0


# ---------------------------------------------------------------------------
# The OPPONENT's build pays nothing (owner-only auto)
# ---------------------------------------------------------------------------

def test_opponent_build_pays_nothing():
    cs = _card_state()
    cs = _own_occ(cs, 0, CARD_ID)              # player 0 owns the card
    cs = with_house(cs, 1, HouseMaterial.WOOD)
    cs = with_resources(cs, 1, wood=5, reed=2)
    cs = with_space(cs, "farm_expansion", revealed=True)
    cs = with_current_player(cs, 1)            # player 1 builds
    clay_p0 = cs.players[0].resources.clay
    clay_p1 = cs.players[1].resources.clay
    cs = run_actions(cs, _ONE_ROOM_FLOW)
    assert cs.players[1].farmyard.grid[0][0].cell_type == CellType.ROOM
    assert cs.players[0].resources.clay == clay_p0
    assert cs.players[1].resources.clay == clay_p1


# ---------------------------------------------------------------------------
# In hand but not played -> inert
# ---------------------------------------------------------------------------

def test_hand_only_is_inert():
    cs = _expansion_setup(HouseMaterial.WOOD, wood=5, reed=2, occ=False)
    p0 = cs.players[0]
    p0 = fast_replace(p0, hand_occupations=frozenset({CARD_ID}))
    cs = fast_replace(cs, players=(p0, cs.players[1]))
    clay0 = cs.players[0].resources.clay
    cs = run_actions(cs, _ONE_ROOM_FLOW)
    assert cs.players[0].resources.clay == clay0   # unplayed card pays nothing
