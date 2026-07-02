"""Tests for Roughcaster (occupation, A110; Base Revised; players 1+).

Card text: "Each time you build at least 1 clay room or renovate your house from
clay to stone, you also get 3 food."

The subtle clause is the renovate one. After a renovate applies, the house is the
NEW material (STONE for both a clay->stone renovate and a Conservator wood->stone
renovate), so the post-renovate `house_material` cannot distinguish them. The card
grants only "from clay to stone", so the FROM material is snapshotted BEFORE the
renovate applies (a `before_renovate` automatic writes it to CardStore) and the
`after_renovate` clause grants iff that snapshot was CLAY. The load-bearing test is
therefore the wood->stone case (owning Conservator, occupation A87, which makes
wood->stone a legal renovate target): it must grant NOTHING even though the house
ends STONE.

Each test drives the real House Redevelopment / Farm Expansion flow that fires the
hook, so the firing-point wiring is exercised end-to-end.
"""
from __future__ import annotations

import agricola.cards.roughcaster  # noqa: F401  (registers the card)
import agricola.cards.conservator  # noqa: F401  (wood->stone renovate target)

from agricola.actions import (
    ChooseSubAction,
    CommitBuildRoom,
    CommitRenovate,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import CellType, HouseMaterial
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from tests.factories import with_house, with_resources, with_space
from tests.test_utils import run_actions, sole_renovate

CARD_ID = "roughcaster"

_POOL = CardPool(
    occupations=(CARD_ID, "conservator") + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = fast_replace(cs, current_player=0)
    # Drop both hands so deterministic plays come only from what a test grants.
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _renovate_setup(material, *, idx=0, own=(CARD_ID,), **resources):
    """A card-mode state with house_redevelopment revealed, the given house, the
    listed occupations owned, and the given resources."""
    cs = _card_state()
    cs = with_house(cs, idx, material)
    cs = with_resources(cs, idx, **resources)
    cs = with_space(cs, "house_redevelopment", revealed=True)
    for cid in own:
        cs = _own_occ(cs, idx, cid)
    return cs


def _renovate_to(target):
    """A `run_actions` thunk selecting the unique legal `CommitRenovate` whose
    `to_material` is `target`. Needed when Conservator makes two targets legal
    (clay and stone from a wood house), where `sole_renovate` would ambiguate."""
    def _pick(state):
        opts = [a for a in legal_actions(state)
                if isinstance(a, CommitRenovate) and a.to_material == target]
        assert len(opts) == 1, f"expected one CommitRenovate to {target}, got {opts!r}"
        return opts[0]
    return _pick


def _drive_renovate(state, commit):
    """Drive the real House Redevelopment renovate flow to a turn-complete state.
    `commit` is the CommitRenovate (or a run_actions thunk producing one)."""
    return run_actions(state, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        commit,      # applies the renovate
        Stop(),      # pop PendingRenovate after-phase (after_renovate fired here)
        Proceed(),   # flip the host (house_redevelopment) to its after-phase
        Stop(),      # pop the host → turn complete
    ])


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    for event in ("before_renovate", "after_renovate", "after_build_rooms"):
        ids = {e.card_id for e in AUTO_EFFECTS.get(event, [])}
        assert CARD_ID in ids, f"roughcaster missing from {event}"
    # All clauses are mandatory autos → not in the declinable TRIGGERS list.
    from agricola.cards.triggers import TRIGGERS
    declinable = {t.card_id for lst in TRIGGERS.values() for t in lst}
    assert CARD_ID not in declinable


# ---------------------------------------------------------------------------
# Renovate clause: grant iff FROM == CLAY (the snapshot's whole point)
# ---------------------------------------------------------------------------

def test_food_on_clay_to_stone_renovate():
    # Clay house, 2 rooms → renovate to stone costs 2 stone + 1 reed. FROM = CLAY,
    # so Roughcaster fires: +3 food.
    cs = _renovate_setup(HouseMaterial.CLAY, stone=2, reed=1)
    food0 = cs.players[0].resources.food
    cs = _drive_renovate(cs, sole_renovate)
    assert cs.pending_stack == ()
    assert cs.players[0].house_material == HouseMaterial.STONE
    assert cs.players[0].resources.food == food0 + 3   # Roughcaster fired


def test_no_food_on_conservator_wood_to_stone_renovate():
    # THE load-bearing case. Own Conservator (wood->stone legal) + Roughcaster, start
    # in a WOOD house, renovate DIRECTLY wood->stone. The house ends STONE, but the
    # FROM material was WOOD, not CLAY → Roughcaster must grant NOTHING.
    # Stone-tier cost for 2 rooms: 2 stone + 1 reed.
    cs = _renovate_setup(HouseMaterial.WOOD, own=(CARD_ID, "conservator"), stone=2, reed=1)
    food0 = cs.players[0].resources.food
    cs = _drive_renovate(cs, _renovate_to(HouseMaterial.STONE))
    assert cs.pending_stack == ()
    assert cs.players[0].house_material == HouseMaterial.STONE
    assert cs.players[0].resources.food == food0     # FROM was WOOD → NO fire


def test_no_food_on_wood_to_clay_renovate():
    # Wood->clay renovate: FROM = WOOD, not clay->stone → no fire.
    cs = _renovate_setup(HouseMaterial.WOOD, clay=2, reed=1)
    food0 = cs.players[0].resources.food
    cs = _drive_renovate(cs, sole_renovate)
    assert cs.players[0].house_material == HouseMaterial.CLAY
    assert cs.players[0].resources.food == food0     # no fire


def test_unowned_renovate_grants_nothing():
    # A player who has NOT played Roughcaster gets no food on a clay->stone renovate.
    cs = _renovate_setup(HouseMaterial.CLAY, own=(), stone=2, reed=1)
    food0 = cs.players[0].resources.food
    cs = _drive_renovate(cs, sole_renovate)
    assert cs.players[0].house_material == HouseMaterial.STONE
    assert cs.players[0].resources.food == food0     # not owned → nothing


# ---------------------------------------------------------------------------
# Build-clay-room clause (unchanged by the fix)
# ---------------------------------------------------------------------------

def test_food_on_clay_room_build():
    # Build a room in a CLAY house via Farm Expansion → a clay room → +3 food fired
    # once at the build-rooms Proceed flip (the after_build_rooms boundary).
    cs = _card_state()
    cs = with_house(cs, 0, HouseMaterial.CLAY)
    cs = with_resources(cs, 0, clay=5, reed=2)   # clay-house room costs 5 clay + 2 reed
    cs = with_space(cs, "farm_expansion", revealed=True)
    cs = _own_occ(cs, 0, CARD_ID)
    food0 = cs.players[0].resources.food
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
        CommitBuildRoom(row=0, col=0),
        Proceed(),    # flip PendingBuildRooms to after (after_build_rooms fires here)
        Stop(),       # pop PendingBuildRooms
        Proceed(),
        Stop(),
    ])
    assert cs.players[0].farmyard.grid[0][0].cell_type == CellType.ROOM
    assert cs.players[0].resources.food == food0 + 3   # Roughcaster fired ONCE


def test_no_food_on_wood_room_build():
    # A wood-house room is not a clay room → no fire.
    cs = _card_state()
    cs = with_resources(cs, 0, wood=5, reed=2)
    cs = with_space(cs, "farm_expansion", revealed=True)
    cs = _own_occ(cs, 0, CARD_ID)
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
    assert cs.players[0].resources.food == food0   # no fire
