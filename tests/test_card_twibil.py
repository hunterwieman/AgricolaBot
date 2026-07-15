"""Tests for Twibil (minor improvement, E49; Ephipparius Expansion).

Card text: "Each time after any player (including you) builds at least 1 wood
room, you get 1 food."

An `any_player=True` automatic effect on the `after_build_rooms` event: it fires
for its OWNER whenever EITHER player builds >= 1 wood room (owner routing lives in
apply_auto_effects). "wood room" is read off the BUILDER's house material (all a
player's rooms share `house_material`); the builder during a worker placement is
`state.current_player`, and the owner is the `idx` handed to the effect fns. The
grant is a flat +1 food.

Each test drives the REAL Farm Expansion build-rooms flow (the roughcaster
build-hook pattern), so the firing-point wiring is exercised end-to-end. The
load-bearing case is the OPPONENT build (the any_player routing): the owner gains
food on a room the opponent built.
"""
from __future__ import annotations

import agricola.cards.twibil  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction,
    CommitBuildRoom,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import CellType, HouseMaterial
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_house, with_resources, with_space
from tests.test_utils import run_actions

CARD_ID = "twibil"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# --- Helpers ----------------------------------------------------------------

def _card_state(cp=0, seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = fast_replace(cs, current_player=cp)
    # Drop both hands so nothing but the test's grants is in play.
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _own_minor(state, idx):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, minor_improvements=p.minor_improvements | {CARD_ID}) if i == idx
        else state.players[i] for i in range(2)))


def _build_one_room(cs):
    """Drive Farm Expansion -> build one room at (0,0) (adjacent to the starting
    room at (1,0)) -> turn complete. after_build_rooms fires at the Proceed flip."""
    return run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
        CommitBuildRoom(row=0, col=0),
        Proceed(),    # flip PendingBuildRooms to after (after_build_rooms fires here)
        Stop(),       # pop PendingBuildRooms
        Proceed(),    # flip the host
        Stop(),       # pop the host -> turn complete
    ])


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(stone=1))   # cost: 1 stone
    assert spec.vps == 1
    entries = AUTO_EFFECTS.get("after_build_rooms", ())
    assert any(e.card_id == CARD_ID and e.any_player for e in entries)


# --- The fire, through the real build-rooms flow -----------------------------

def test_owner_builds_wood_room_gets_food():
    cs = _card_state(cp=0)
    cs = with_house(cs, 0, HouseMaterial.WOOD)
    cs = with_resources(cs, 0, wood=5, reed=2)   # wood-house room cost; food 0
    cs = with_space(cs, "farm_expansion", revealed=True)
    cs = _own_minor(cs, 0)
    food0 = cs.players[0].resources.food
    cs = _build_one_room(cs)
    assert cs.players[0].farmyard.grid[0][0].cell_type == CellType.ROOM
    assert cs.players[0].resources.food == food0 + 1   # Twibil fired


def test_opponent_builds_wood_room_owner_gets_food():
    """THE load-bearing any_player case: player 1 builds the wood room, and the
    OWNER (player 0) — not the builder — gets the food."""
    cs = _card_state(cp=1)                        # player 1 is the builder
    cs = with_house(cs, 1, HouseMaterial.WOOD)
    cs = with_resources(cs, 1, wood=5, reed=2)     # builder's build resources; food 0
    cs = with_resources(cs, 0, food=3)             # owner's marker food
    cs = with_space(cs, "farm_expansion", revealed=True)
    cs = _own_minor(cs, 0)                          # OWNER is player 0
    cs = _build_one_room(cs)
    assert cs.players[1].farmyard.grid[0][0].cell_type == CellType.ROOM
    assert cs.players[0].resources.food == 3 + 1    # owner gained
    assert cs.players[1].resources.food == 0        # builder (non-owner) did not


def test_clay_room_build_no_food():
    """A clay-house room is not a WOOD room -> no fire."""
    cs = _card_state(cp=0)
    cs = with_house(cs, 0, HouseMaterial.CLAY)
    cs = with_resources(cs, 0, clay=5, reed=2)     # clay-house room cost
    cs = with_space(cs, "farm_expansion", revealed=True)
    cs = _own_minor(cs, 0)
    food0 = cs.players[0].resources.food
    cs = _build_one_room(cs)
    assert cs.players[0].farmyard.grid[0][0].cell_type == CellType.ROOM
    assert cs.players[0].resources.food == food0   # no fire (clay room)


def test_unowned_no_food():
    cs = _card_state(cp=0)
    cs = with_house(cs, 0, HouseMaterial.WOOD)
    cs = with_resources(cs, 0, wood=5, reed=2)
    cs = with_space(cs, "farm_expansion", revealed=True)
    # NOT owning Twibil
    food0 = cs.players[0].resources.food
    cs = _build_one_room(cs)
    assert cs.players[0].resources.food == food0   # not owned -> nothing
